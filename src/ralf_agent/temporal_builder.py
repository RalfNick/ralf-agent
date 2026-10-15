"""Explicit Temporal component factories; no Local execution authority is created."""

import asyncio
import math
from pathlib import Path
from types import MappingProxyType

from .binding_catalog import BindingCatalog
from .errors import CloseIncomplete, RalfError, ValidationError
from .ports import is_async_callable
from .runtime_builder import (
    _BINDING_FACTORY_KINDS,
    ComponentRegistry,
    RuntimeBuildError,
    _completed,
    validate_continuation_declarations,
)
from .runtime_config import component_declaration
from .runtime_lifecycle import BuildContext
from .temporal_activities import TemporalRuntime
from .temporal_assembly_lifecycle import TemporalRuntimeAssembly
from .temporal_profile import TemporalProfile, TemporalProfileCatalog
from .temporal_session_topology import CompositeSessionTopology
from .tools import ThreadExecutionTracker, ToolRegistry, current_thread_tracker
from .types import Scope


class _ConstructionCleanup:
    def __init__(self, context):
        self._context = context
        self._threads = ThreadExecutionTracker()
        self._tasks = []
        self._aclosing = False

    async def execute(self, operation):
        async def invoke():
            token = current_thread_tracker.set(self._threads)
            try:
                return await operation()
            finally:
                current_thread_tracker.reset(token)

        task = asyncio.create_task(invoke())
        self._tasks.append(task)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancel cooperative construction, retain any explicit bridge work.
            task.cancel()
            await asyncio.sleep(0)
            raise

    async def aclose(self, *, wait_timeout=30):
        self._context._check_cleanup_origin()
        if self._aclosing:
            raise ValidationError("Temporal construction cleanup is already closing")
        self._aclosing = True
        try:
            await self.wait(wait_timeout=wait_timeout)
            await self._context.cleanup_async()
        finally:
            self._aclosing = False

    async def wait(self, *, wait_timeout=30):
        if (
            type(wait_timeout) not in (int, float)
            or not math.isfinite(wait_timeout)
            or wait_timeout < 0
        ):
            raise ValidationError("Construction close timeout must be finite and nonnegative")
        pending = [task for task in self._tasks if not task.done()]
        if pending:
            _, pending = await asyncio.wait(pending, timeout=wait_timeout)
            if pending:
                raise CloseIncomplete("Actual component construction remains owned")
        if self._threads.has_active:
            try:
                await asyncio.wait_for(self._threads.drain(), wait_timeout)
            except TimeoutError:
                raise CloseIncomplete("Actual construction bridge remains owned") from None


def _paths(declaration, kind, data_path):
    if kind == "memory_store" and (
        declaration["adapter"] == "indexed-recall-async"
        or (
            declaration["adapter"] == "semantic-recall-async" and "backend" in declaration["config"]
        )
    ):
        declaration["config"]["backend"] = _paths(
            component_declaration(declaration["config"].get("backend", {"adapter": "sqlite"})),
            kind,
            data_path,
        )
    if kind == "stage_policy" and declaration["adapter"] in {
        "sourced-memory",
        "sourced-memory-async",
    }:
        if "memory" not in declaration["config"]:
            raise ValidationError("Temporal memory stages require an explicit Memory target")
        declaration["config"]["memory"] = _paths(
            component_declaration(declaration["config"]["memory"]), "memory_store", data_path
        )
    if declaration["adapter"] in {"session-resource", "facts-resource", "knowledge-resource"}:
        declaration["config"]["backend"] = _paths(
            component_declaration(declaration["config"]["backend"]), kind, data_path
        )
    elif kind in {"session_store", "memory_store"} and declaration["adapter"] == "sqlite":
        if "path" not in declaration["config"]:
            if data_path is None:
                raise ValidationError("Temporal SQLite Memory requires an explicit data path")
            declaration["config"]["path"] = str(data_path) + "." + kind + ".sqlite"
    return declaration


class TemporalRuntimeBuilder:
    def __init__(self, registry=None, *, base_dir=None):
        self.registry = ComponentRegistry() if registry is None else registry
        if not isinstance(self.registry, ComponentRegistry):
            raise ValidationError("Temporal construction requires an explicit ComponentRegistry")
        self.base_dir = Path.cwd().resolve() if base_dir is None else Path(base_dir).resolve()

    def _prepare(self, profile, *, data_path=None, scope=None, admission_policy=None):
        if not isinstance(profile, TemporalProfile):
            raise ValidationError("Build an immutable TemporalProfile")
        from .admission_factories import host_options

        host_admission = host_options(profile, admission_policy)
        if profile.execution.get("deployment_sessions") and not (
            host_admission or "admission_policy" in profile.components
        ):
            raise ValidationError("Deployment Sessions require an explicit admission policy")
        scope = Scope() if scope is None else scope
        if not isinstance(scope, Scope):
            raise ValidationError("Temporal assembly requires a trusted Scope")
        if data_path is not None:
            path = Path(data_path)
            data_path = (path if path.is_absolute() else self.base_dir / path).resolve()
        from .parent_completion_factories import preflight_parent_completion_providers
        from .query_factories import preflight_query_providers
        from .user_input_factories import preflight_user_input

        preflight_query_providers(profile)
        preflight_parent_completion_providers(profile)
        preflight_user_input(profile)
        from .temporal_coding_factories import preflight_coding_references

        preflight_coding_references(profile)
        validate_continuation_declarations(
            profile, enabled=profile.execution.get("model_continuation", False)
        )
        prepared_providers = {
            name: self.registry.prepare("provider", value)
            for name, value in profile.providers.items()
        }
        prepared_components = {
            kind: self.registry.prepare(kind, _paths(value, kind, data_path))
            for kind, value in profile.components.items()
        }
        if host_admission:
            prepared_components["admission_policy"] = (
                lambda config, context: host_admission["admission_policy"],
                {},
            )
        prepared_bindings = []
        for value in profile.binding_components or []:
            kind = _BINDING_FACTORY_KINDS[value["role"]]
            prepared_bindings.append(
                (value, self.registry.prepare(kind, _paths(value["component"], kind, data_path)))
            )
        return profile, scope, data_path, prepared_providers, prepared_components, prepared_bindings

    async def abuild(self, profile, *, data_path=None, scope=None, admission_policy=None):
        return await self._construct_profile(
            self._prepare(
                profile, data_path=data_path, scope=scope, admission_policy=admission_policy
            )
        )

    async def _construct_profile(self, prepared, *, resource_owner=None):
        profile, scope, data_path, prepared_providers, prepared_components, prepared_bindings = (
            prepared
        )
        context = BuildContext(
            None,
            data_path or self.base_dir / "temporal-data.sqlite",
            scope,
            self.base_dir,
            allow_async=True,
            resource_owner=resource_owner,
        )
        cleanup = _ConstructionCleanup(context)
        context.coding_execution = profile.execution.get("coding_execution", False)
        context.coding_composition = profile.execution.get("coding_composition", False)
        context.effect_journal = None

        async def construct(prepared):
            factory, config = prepared

            async def operation():
                value = (
                    await factory(config, context)
                    if is_async_callable(factory)
                    else factory(config, context)
                )
                return _completed(value, "Temporal component factory")

            return await cleanup.execute(operation)

        try:
            providers = {name: await construct(value) for name, value in prepared_providers.items()}
            context.providers = MappingProxyType(providers)
            original_journal = None
            if context.coding_execution and "effect_journal" in prepared_components:
                original_journal = await construct(prepared_components.pop("effect_journal"))
                context.effect_journal = original_journal
            context.tools = (
                await construct(prepared_components.pop("tools"))
                if "tools" in prepared_components
                else ToolRegistry()
            )
            options = {name: await construct(value) for name, value in prepared_components.items()}
            from .admission_factories import validate_admission_result

            validate_admission_result(options)
            if "execution_policy" in options:
                from .governance import TemporalExecutionPolicy

                if not isinstance(options["execution_policy"], TemporalExecutionPolicy):
                    raise ValidationError(
                        "Declared execution policy factory must return TemporalExecutionPolicy"
                    )
            if original_journal is not None:
                options["effect_journal"] = original_journal
            if profile.binding_components is not None:
                catalog = BindingCatalog(scope=scope)
                for declaration, prepared in prepared_bindings:
                    catalog.register(
                        declaration["role"],
                        declaration["component_id"],
                        declaration["version"],
                        await construct(prepared),
                    )
                options["binding_catalog"] = catalog
            if "memory_store" in options:
                options["facts"] = options.pop("memory_store")
            if "context_assembler" in options:
                options["context_builder"] = options.pop("context_assembler")
            if "effect_journal" in options:
                options["journal"] = options.pop("effect_journal")
            execution = profile.execution
            composite = execution.pop("composite_sessions")
            if execution.get("artifact_bindings") and "binding_catalog" not in options:
                options["binding_catalog"] = BindingCatalog(scope=scope)
            if execution["session_writes"]:
                from .binding_sessions import SessionBindingResource

                sources = ([options["session_store"]] if "session_store" in options else []) + [
                    component
                    for (role, _, _), (component, _) in (
                        options["binding_catalog"]._entries.items()
                        if "binding_catalog" in options
                        else []
                    )
                    if role == "session"
                ]
                initialized = set()
                for source in sources:
                    backend = (
                        source.backend if isinstance(source, SessionBindingResource) else source
                    )
                    if id(backend) in initialized:
                        continue
                    initialized.add(id(backend))
                    initialize = getattr(backend, "initialize_session_identity", None)
                    if initialize is not None:
                        if not is_async_callable(initialize):
                            raise ValidationError("Session identity initialization must be async")

                        async def operation(initialize=initialize):
                            return _completed(await initialize(), "Session identity initialization")

                        await cleanup.execute(operation)
            if composite:
                options["session_topology"] = CompositeSessionTopology()
            runtime = TemporalRuntime(
                providers=providers,
                tools=context.tools,
                runtime_profile=profile.identity,
                **options,
                **execution,
            )
            assembly = TemporalRuntimeAssembly(runtime, context, profile, scope)
            assembly._construction = cleanup
            return assembly
        except BaseException as exc:
            if resource_owner is not None:
                raise RuntimeBuildError(cleanup) from exc
            try:
                await cleanup.aclose(wait_timeout=0)
            except BaseException as cleanup_error:
                raise RuntimeBuildError(cleanup) from cleanup_error
            if isinstance(exc, (RalfError, asyncio.CancelledError)):
                raise
            if not isinstance(exc, Exception):
                raise
            raise RuntimeBuildError(cleanup) from exc

    async def abuild_catalog(self, catalog, *, data_path=None, scope=None, admission_policy=None):
        from .temporal_profile_host import CatalogConstructionCleanup, TemporalProfileHost

        if not isinstance(catalog, TemporalProfileCatalog):
            raise ValidationError("Build an explicit TemporalProfileCatalog")
        profiles = catalog.profiles
        if not 1 <= len(profiles) <= 32:
            raise ValidationError("Temporal Host requires1 to32 explicit Profiles")
        selected = catalog.default_profile.identity
        builder = TemporalRuntimeBuilder(self.registry, base_dir=catalog.base_dir)
        scope = Scope() if scope is None else scope
        prepared = [
            builder._prepare(p, data_path=data_path, scope=scope, admission_policy=admission_policy)
            for p in profiles
        ]
        root = BuildContext(
            None,
            builder.base_dir / "temporal-data.sqlite",
            scope,
            builder.base_dir,
            allow_async=True,
        )
        handles, assemblies = [], []
        cleanup = CatalogConstructionCleanup(root, handles)
        try:
            for value in prepared:
                assembly = await builder._construct_profile(value, resource_owner=root)
                assemblies.append(assembly)
                handles.append(assembly._construction)
            return TemporalProfileHost(assemblies, root, handles, selected, scope)
        except BaseException as exc:
            if isinstance(exc, RuntimeBuildError):
                handles.append(exc.cleanup)
            try:
                await cleanup.aclose(wait_timeout=0)
            except BaseException as close_error:
                raise RuntimeBuildError(cleanup) from close_error
            raise RuntimeBuildError(cleanup) from exc
