"""Explicit adapter factories and resource ownership for the local runtime."""

import asyncio
import inspect
import json
import os
from dataclasses import asdict
from pathlib import Path
from types import MappingProxyType

from .context import ContextAssembler
from .engine import LocalEngine
from .errors import RalfError, ValidationError
from .executors import PythonToolExecutor
from .harness import NativeHarness
from .memory import InMemoryMemory, SQLiteMemory
from .model_native import AnthropicProvider, GeminiProvider
from .model_protocol import ModelCapabilities
from .model_responses import OpenAIResponsesProvider
from .ports import is_async_callable, validate_engine
from .ports import is_sync_callable as _synchronous
from .providers import DeepSeekChatProvider, OpenAIChatProvider
from .recall import FixedRecallPlanner, MemoryRecallPolicy, RecallQuery
from .retrieval import KnowledgeContext, LexicalRetriever, SQLiteKnowledgeStore
from .runtime_config import COMPONENT_KINDS, RuntimeProfile
from .runtime_lifecycle import BuildContext, RuntimeInstance
from .storage import SQLiteStore
from .tools import ToolRegistry
from .types import ModelResponse, Scope, canonical


def _completed(value, label):
    if inspect.isawaitable(value) or inspect.isgenerator(value) or inspect.isasyncgen(value):
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError(f"{label} must finish synchronously")
    return value


def _close_complete(value, label):
    if _completed(value, label) is not None:
        raise ValidationError(f"{label} must return None after completion")


def _fields(config, allowed):
    if set(config) - set(allowed):
        raise ValidationError("Unknown adapter configuration fields")


class RuntimeBuildError(ValidationError):
    """Construction failed; cleanup can be retried through the retained handle."""

    def __init__(self, cleanup):
        super().__init__("Runtime component construction failed")
        self.cleanup = cleanup


class EchoProvider:
    def __init__(self, label):
        self.label = label

    @property
    def identity(self):
        return {"kind": "offline-echo", "version": "1", "label": self.label}

    async def complete(self, messages, tools):
        return ModelResponse(
            output={"echo": messages[1]["content"], "label": self.label},
            usage={"input_tokens": 0, "output_tokens": 0, "source": "offline-echo"},
        )


def _echo_config(config):
    _fields(config, {"label"})
    if not isinstance(config.get("label", "offline"), str):
        raise ValidationError("Echo label must be a string")


def _chat_config(config):
    _model_options(config, OpenAIChatProvider, "OPENAI_API_KEY")


def _chat(config, context):
    return _model(config, OpenAIChatProvider, "OPENAI_API_KEY")


def _model_options(config, provider_type, key_env):
    allowed = {
        "model",
        "base_url",
        "api_key_env",
        "max_output_tokens",
        "timeout",
        "temperature",
        "top_p",
        "stop",
        "stream",
        "capabilities",
    }
    if provider_type in {OpenAIChatProvider, GeminiProvider}:
        allowed.add("seed")
    if provider_type is OpenAIChatProvider:
        allowed.add("token_parameter")
    if provider_type in {OpenAIChatProvider, DeepSeekChatProvider, OpenAIResponsesProvider}:
        allowed.add("json_mode")
    if provider_type is OpenAIResponsesProvider:
        allowed.discard("stop")
        allowed.update({"output_schema", "schema_name", "reasoning_effort"})
    if provider_type is AnthropicProvider:
        allowed.add("api_version")
    _fields(config, allowed)
    if not isinstance(config.get("model"), str) or not config["model"].strip():
        raise ValidationError("Model adapter requires model")
    if config["model"] == "YOUR_MODEL":
        raise ValidationError("Replace YOUR_MODEL in runtime.toml with an explicit model name")
    name = config.get("api_key_env", key_env)
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("api_key_env must name an environment variable")
    options = {key: value for key, value in config.items() if key != "api_key_env"}
    if "capabilities" in options:
        values = options["capabilities"]
        if not isinstance(values, dict) or set(values) - {"text", "tools", "streaming"}:
            raise ValidationError("Invalid model capability configuration")
        options["capabilities"] = ModelCapabilities(**{**asdict(provider_type.supported), **values})
    provider_type(api_key="configuration-validation", **options)
    return name, options


def _model(config, provider_type, key_env):
    name, options = _model_options(config, provider_type, key_env)
    key = os.environ.get(name)
    if not key:
        raise ValidationError("Configured model credential environment variable is unavailable")
    return provider_type(api_key=key, **options)


def _policy(config, context):
    _fields(config, {"facts", "session", "max_pages"})
    values = dict(config)
    for name in ("facts", "session"):
        if name in values:
            if not isinstance(values[name], dict):
                raise ValidationError("Recall query config must be an object")
            values[name] = RecallQuery(**values[name])
    return MemoryRecallPolicy(**values)


def _sqlite_memory(config, context):
    _fields(config, {"path"})
    return (
        context.own(SQLiteMemory(context.path(config["path"])))
        if "path" in config
        else SQLiteMemory(context.store)
    )


def _sqlite_memory_config(config):
    _fields(config, {"path"})
    if "path" in config and (type(config["path"]) is not str or not config["path"].strip()):
        raise ValidationError("Resource path must be a non-empty string")


def _lexical_config(config):
    from .retrieval import RetrievalQuery, _chunk_config, _text

    _fields(config, {"path", "namespace", "limit", "max_chars", "chunk_size", "overlap"})
    _chunk_config(config.get("chunk_size", 1000), config.get("overlap", 100))
    _text(config.get("namespace", "default"), "Knowledge namespace")
    if "path" in config:
        _text(config["path"], "Knowledge path")
    RetrievalQuery("", config.get("limit", 5), config.get("max_chars", 8000))


def _lexical(config, context):
    _fields(config, {"path", "namespace", "limit", "max_chars", "chunk_size", "overlap"})
    path = (
        context.path(config["path"]) if "path" in config else context.db_path + ".knowledge.sqlite"
    )
    store = context.own(
        SQLiteKnowledgeStore(
            path, chunk_size=config.get("chunk_size", 1000), overlap=config.get("overlap", 100)
        )
    )
    return KnowledgeContext(
        LexicalRetriever(store),
        namespace=config.get("namespace", "default"),
        limit=config.get("limit", 5),
        max_chars=config.get("max_chars", 8000),
    )


def _tool_names_config(config):
    from .binding_catalog import component_identity

    _fields(config, {"names"})
    component_identity("tool_set", config.get("names", []))


def _tool_names(config, context):
    _tool_names_config(config)
    return tuple(config.get("names", []))


_BINDING_FACTORY_KINDS = {
    "provider": "provider",
    "decision_policy": "harness",
    "context": "context_assembler",
    "session": "session_store",
    "facts": "memory_store",
    "knowledge": "knowledge",
    "tool_set": "tool_set",
    "verifier": "verifier",
    "limits": "limits",
    "stage_policy": "stage_policy",
    "workspace": "workspace",
    "skills": "skills",
}


class ComponentRegistry:
    def __init__(self):
        self._factories = {}
        self.register("tool_set", "names", _tool_names, validator=_tool_names_config)
        self.register(
            "provider",
            "offline-echo",
            lambda c, ctx: EchoProvider(c.get("label", "offline")),
            validator=_echo_config,
        )
        self.register("provider", "chat-completions", _chat, validator=_chat_config)
        for name, provider_type, key_env in [
            ("openai-responses", OpenAIResponsesProvider, "OPENAI_API_KEY"),
            ("deepseek-chat", DeepSeekChatProvider, "DEEPSEEK_API_KEY"),
            ("anthropic-messages", AnthropicProvider, "ANTHROPIC_API_KEY"),
            ("gemini-content", GeminiProvider, "GEMINI_API_KEY"),
        ]:
            # Bind values now, rather than capture the loop's final adapter.
            self.register(
                "provider",
                name,
                lambda c, ctx, cls=provider_type, env=key_env: _model(c, cls, env),
                validator=lambda c, cls=provider_type, env=key_env: (
                    _model_options(c, cls, env) and None
                ),
            )
        self.register(
            "tools", "empty", lambda c, ctx: ToolRegistry(), validator=lambda c: _fields(c, {})
        )
        self.register(
            "context_assembler",
            "default",
            lambda c, ctx: ContextAssembler(**c),
            validator=lambda c: _fields(c, {}),
        )
        from .context_factories import budgeted_context, managed_context

        self.register(
            "context_assembler",
            "budgeted",
            lambda c, ctx: budgeted_context(c),
            validator=lambda c: budgeted_context(c) and None,
        )
        self.register(
            "context_assembler",
            "managed-summary",
            lambda c, ctx: managed_context(c),
            validator=lambda c: managed_context(c) and None,
        )
        self.register(
            "harness", "native", lambda c, ctx: NativeHarness(), validator=lambda c: _fields(c, {})
        )
        from .agent_limits import FixedAgentLimits
        from .completion import SchemaCompletionVerifier, ToolReceiptVerifier

        def fixed_limits(config):
            _fields(config, {"max_decisions", "max_context_chars", "max_tool_actions"})
            return FixedAgentLimits(**config)

        self.register(
            "limits",
            "fixed",
            lambda c, ctx: fixed_limits(c),
            validator=lambda c: fixed_limits(c) and None,
        )

        self.register(
            "verifier",
            "schema",
            lambda c, ctx: SchemaCompletionVerifier(),
            validator=lambda c: _fields(c, {}),
        )

        def receipt_verifier(config):
            _fields(
                config,
                {"tool", "when", "result_schema", "argument_bindings", "on_missing", "feedback"},
            )
            if "tool" not in config:
                raise ValidationError("Tool receipt verification requires a tool")
            return ToolReceiptVerifier(**config)

        self.register(
            "verifier",
            "tool-receipt",
            lambda c, ctx: receipt_verifier(c),
            validator=lambda c: receipt_verifier(c) and None,
        )
        self.register(
            "tool_executor",
            "python",
            lambda c, ctx: PythonToolExecutor(ctx.tools),
            validator=lambda c: _fields(c, {}),
        )
        self.register(
            "recall_policy",
            "bounded-recall",
            _policy,
            validator=lambda c: _policy(c, None) and None,
        )
        self.register(
            "recall_planner",
            "fixed",
            lambda c, ctx: FixedRecallPlanner(_policy(c, ctx)),
            validator=lambda c: _policy(c, None) and None,
        )
        for kind in ("session_store", "memory_store"):
            self.register(kind, "sqlite", _sqlite_memory, validator=_sqlite_memory_config)
            self.register(
                kind,
                "in-memory",
                lambda c, ctx: InMemoryMemory(**c),
                validator=lambda c: (_fields(c, {"backend_id"}) or InMemoryMemory(**c)) and None,
            )
        from .conversation_factories import colocated_conversation, conversation_config

        self.register(
            "conversation_resource",
            "colocated-session",
            colocated_conversation,
            validator=conversation_config,
        )
        self.register("knowledge", "sqlite-lexical", _lexical, validator=_lexical_config)
        from .workflow import IdentityTransform, StaticWorkflowCompiler, StaticWorkflowInterpreter
        from .workflow_scheduler import StaticWorkflowScheduler

        self.register(
            "workflow_compiler",
            "static",
            lambda c, ctx: StaticWorkflowCompiler(),
            validator=lambda c: _fields(c, {}),
        )
        self.register(
            "workflow_interpreter",
            "static",
            lambda c, ctx: StaticWorkflowInterpreter(),
            validator=lambda c: _fields(c, {}),
        )
        self.register(
            "workflow_scheduler",
            "static-ready",
            lambda c, ctx: StaticWorkflowScheduler(),
            validator=lambda c: _fields(c, {}),
        )
        self.register(
            "workflow_transforms",
            "identity",
            lambda c, ctx: {"identity": IdentityTransform()},
            validator=lambda c: _fields(c, {}),
        )
        from .dag_planning import ModelDAGPlanner, RuleDAGPlanner
        from .planning import CompleteVerifier, ModelPlanner, RulePlanner
        from .remote_factories import (
            knowledge_config,
            memory_config,
            postgres_knowledge,
            postgres_memory,
            redis_memory,
        )
        from .teams import RouterTeam, SequentialTeam, SupervisorTeam

        self.register(
            "planners",
            "rule",
            lambda c, ctx: {"rule": RulePlanner(**c)},
            validator=lambda c: (_fields(c, {"members"}) or RulePlanner(**c)) and None,
        )
        self.register(
            "planners",
            "model",
            lambda c, ctx: {"model": ModelPlanner(**c)},
            validator=lambda c: (
                (_fields(c, {"provider", "instructions", "version"}) or ModelPlanner(**c)) and None
            ),
        )
        self.register(
            "plan_verifiers",
            "complete",
            lambda c, ctx: {"complete": CompleteVerifier()},
            validator=lambda c: _fields(c, {}),
        )
        self.register(
            "planners",
            "dag-rule",
            lambda c, ctx: {"dag-rule": RuleDAGPlanner()},
            validator=lambda c: _fields(c, {}),
        )
        self.register(
            "planners",
            "dag-model",
            lambda c, ctx: {"dag-model": ModelDAGPlanner(**c)},
            validator=lambda c: (
                (_fields(c, {"provider", "instructions", "version"}) or ModelDAGPlanner(**c))
                and None
            ),
        )
        self.register(
            "team_strategies",
            "defaults",
            lambda c, ctx: {
                "sequential": SequentialTeam(),
                "router": RouterTeam(),
                "supervisor": SupervisorTeam(),
            },
            validator=lambda c: _fields(c, {}),
        )
        for kind in ("session_store", "memory_store"):
            self.register_async(
                kind, "redis", redis_memory, validator=lambda c: memory_config(c, redis=True)
            )
            self.register_async(kind, "postgres", postgres_memory, validator=memory_config)
        self.register_async(
            "knowledge", "postgres-lexical", postgres_knowledge, validator=knowledge_config
        )

        async def vector_knowledge(config, context):
            return await postgres_knowledge(config, context, vector=True)

        self.register_async(
            "knowledge",
            "postgres-qdrant",
            vector_knowledge,
            validator=lambda c: knowledge_config(c, vector=True),
        )

        from .knowledge_factories import (
            hybrid_config,
            postgres_qdrant_hybrid,
            sqlite_hybrid,
            sqlite_hybrid_http,
        )

        self.register("knowledge", "sqlite-hybrid", sqlite_hybrid, validator=hybrid_config)
        self.register_async(
            "knowledge",
            "sqlite-hybrid-http",
            sqlite_hybrid_http,
            validator=lambda c: hybrid_config(c, http=True),
        )
        self.register_async(
            "knowledge",
            "sqlite-hybrid-rerank-http",
            sqlite_hybrid_http,
            validator=lambda c: hybrid_config(c, rerank_http=True),
        )
        self.register_async(
            "knowledge",
            "postgres-qdrant-hybrid",
            postgres_qdrant_hybrid,
            validator=lambda c: hybrid_config(c, remote=True),
        )

        from .middleware_factories import register_middleware_factories

        register_middleware_factories(self)
        from .managed_memory_factories import register_memory_stages

        register_memory_stages(self)
        from .data_context_factories import register_data_context

        register_data_context(self)
        from .relevant_context_factories import register_relevant_context

        register_relevant_context(self)
        from .query_factories import register_query_knowledge
        from .semantic_memory_factories import register_semantic_memory

        register_query_knowledge(self)
        register_semantic_memory(self)
        from .fact_index_factories import register_fact_index

        register_fact_index(self)
        from .temporal_journal_factories import register_effect_journal

        register_effect_journal(self)
        from .tool_execution_factories import register_tool_execution

        register_tool_execution(self)
        from .cli_tool_factories import register_cli_tools

        register_cli_tools(self)
        from .http_tool_factories import register_http_tools

        register_http_tools(self)
        from .mcp_http_factories import register_mcp_http

        register_mcp_http(self)
        from .workspace_factories import register_workspace_tools

        register_workspace_tools(self)
        from .skill_factories import register_skill_tools

        register_skill_tools(self)

    def register(self, kind, name, factory, *, validator=None):
        self._register(kind, name, factory, validator, asynchronous=False)

    def register_async(self, kind, name, factory, *, validator=None):
        self._register(kind, name, factory, validator, asynchronous=True)

    def _register(self, kind, name, factory, validator, *, asynchronous):
        if (
            kind
            not in COMPONENT_KINDS
            | {
                "provider",
                "tool_set",
                "workspace",
                "skills",
                "artifact_store",
                "reference_selector",
                "embedding_provider",
                "vector_index",
                "fact_index_catalog",
                "effect_journal",
                "tool_execution",
            }
            or not isinstance(name, str)
            or not name.strip()
        ):
            raise ValidationError("Register a known component kind and non-empty adapter name")
        if not (is_async_callable(factory) if asynchronous else _synchronous(factory)):
            raise ValidationError(
                "Async adapter factories must be async"
                if asynchronous
                else "Adapter factories must be synchronous"
            )
        if validator is not None and not _synchronous(validator):
            raise ValidationError("Adapter validators must be synchronous")
        if (kind, name) in self._factories:
            raise ValidationError("An adapter name is already registered")
        self._factories[kind, name] = (factory, validator)

    def prepare(self, kind, declaration):
        if (kind, declaration["adapter"]) in {
            ("session_store", "session-resource"),
            ("conversation_resource", "session-resource"),
            ("memory_store", "facts-resource"),
            ("knowledge", "knowledge-resource"),
        }:
            from .binding_data import (
                FactsBindingResource,
                KnowledgeBindingResource,
                data_namespace_options,
            )
            from .binding_sessions import SessionBindingResource, namespace_options
            from .runtime_config import component_declaration

            resource_type, validate, default = {
                "session_store": (SessionBindingResource, namespace_options, None),
                "conversation_resource": (SessionBindingResource, namespace_options, None),
                "memory_store": (FactsBindingResource, data_namespace_options, "default"),
                "knowledge": (KnowledgeBindingResource, data_namespace_options, "default"),
            }[kind]
            config = declaration.get("config", {})
            _fields(config, {"backend", "namespaces", "default_namespace"})
            if "backend" not in config:
                raise ValidationError("Binding resource requires a backend declaration")
            namespaces = validate(
                config.get("namespaces", [default]), config.get("default_namespace", default)
            )
            default_namespace = config.get("default_namespace", default)
            backend = component_declaration(config["backend"])
            if backend["adapter"] in {"session-resource", "facts-resource", "knowledge-resource"}:
                raise ValidationError("Binding resources cannot wrap another resource")
            factory, options = self.prepare(
                "session_store" if kind == "conversation_resource" else kind, backend
            )
            if is_async_callable(factory):

                async def wrap(config, context):
                    return resource_type(
                        await factory(config, context),
                        namespaces=namespaces,
                        default_namespace=default_namespace,
                    )
            else:

                def wrap(config, context):
                    return resource_type(
                        _completed(factory(config, context), "Session backend factory"),
                        namespaces=namespaces,
                        default_namespace=default_namespace,
                    )

            return wrap, options
        entry = self._factories.get((kind, declaration["adapter"]))
        if entry is None:
            raise ValidationError("Adapter is not explicitly registered")
        factory, validator = entry
        config = json.loads(canonical(declaration["config"]))
        if validator is not None:
            try:
                outcome = _completed(validator(json.loads(canonical(config))), "Adapter validator")
                if outcome is not None:
                    raise ValidationError("Adapter validator must return None")
            except ValidationError:
                raise
            except Exception as exc:
                raise ValidationError("Adapter configuration is invalid") from exc
        return factory, config


class RuntimeBuilder:
    def __init__(
        self, registry=None, *, store_factory=SQLiteStore, engine_factory=LocalEngine, base_dir=None
    ):
        self.registry = ComponentRegistry() if registry is None else registry
        self.store_factory, self.engine_factory = store_factory, engine_factory
        self.base_dir = Path.cwd().resolve() if base_dir is None else Path(base_dir).resolve()
        if (
            not isinstance(self.registry, ComponentRegistry)
            or not _synchronous(store_factory)
            or not _synchronous(engine_factory)
        ):
            raise ValidationError(
                "RuntimeBuilder requires an explicit registry and synchronous factories"
            )

    def _prepare(self, profile, db_path, scope):
        if not isinstance(profile, RuntimeProfile):
            raise ValidationError("Build a RuntimeProfile")
        from .query_factories import preflight_query_providers

        preflight_query_providers(profile)
        scope = Scope() if scope is None else scope
        if not isinstance(scope, Scope):
            raise ValidationError("Runtime scope must be supplied by a trusted host")
        providers = {
            name: self.registry.prepare("provider", value)
            for name, value in profile.providers.items()
        }
        components = {
            kind: self.registry.prepare(kind, value) for kind, value in profile.components.items()
        }
        path = str(Path(db_path).resolve())
        bindings = [
            (
                declaration,
                self.registry.prepare(
                    _BINDING_FACTORY_KINDS[declaration["role"]], declaration["component"]
                ),
            )
            for declaration in profile.binding_components or []
        ]
        return scope, path, providers, components, bindings

    def _store(self, path):
        try:
            return _completed(self.store_factory(path), "Execution store factory")
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Execution authority could not be constructed") from exc

    def build(self, profile, db_path, *, scope=None):
        scope, path, providers, components, bindings = self._prepare(profile, db_path, scope)
        if any(
            not _synchronous(factory)
            for factory, _ in [
                *providers.values(),
                *components.values(),
                *(prepared for _, prepared in bindings),
            ]
        ):
            raise ValidationError("Async adapter factories require await RuntimeBuilder.abuild")
        store = self._store(path)
        context, candidate = BuildContext(store, path, scope, self.base_dir), None

        def construct(prepared):
            factory, config = prepared
            return _completed(factory(config, context), "Adapter factory")

        try:
            built_providers = {name: construct(prepared) for name, prepared in providers.items()}
            for provider in built_providers.values():
                LocalEngine._component_identity(provider, ("complete",), False, "Provider")
            context.providers = MappingProxyType(built_providers)
            context.tools = (
                construct(components.pop("tools")) if "tools" in components else ToolRegistry()
            )
            options = {kind: construct(prepared) for kind, prepared in components.items()}
            if profile.binding_components is not None:
                from .binding_catalog import BindingCatalog

                catalog = BindingCatalog(scope=scope)
                for declaration, prepared in bindings:
                    catalog.register(
                        declaration["role"],
                        declaration["component_id"],
                        declaration["version"],
                        construct(prepared),
                    )
                options["binding_catalog"] = catalog
            candidate = _completed(
                self.engine_factory(
                    store,
                    providers=built_providers,
                    tools=context.tools,
                    scope=scope,
                    runtime_profile=profile.identity,
                    **options,
                ),
                "Execution engine factory",
            )
            validate_engine(candidate)
            return RuntimeInstance(candidate, context)
        except Exception as exc:
            # A rejected value without close cannot own execution resources.
            # Close the authority we created instead; actual close-capable
            # engines retain ownership until their close completes.
            owner = candidate if callable(getattr(candidate, "close", None)) else None
            cleanup = RuntimeInstance(owner, context, drain_engine=False)
            try:
                cleanup.close()
            except Exception as cleanup_error:
                raise RuntimeBuildError(cleanup) from cleanup_error
            if isinstance(exc, RalfError):
                raise
            raise RuntimeBuildError(cleanup) from exc

    async def abuild(self, profile, db_path, *, scope=None):
        scope, path, providers, components, bindings = self._prepare(profile, db_path, scope)
        store = self._store(path)
        context = BuildContext(store, path, scope, self.base_dir, allow_async=True)
        candidate = None

        async def construct(prepared):
            factory, config = prepared
            value = (
                await factory(config, context)
                if is_async_callable(factory)
                else factory(config, context)
            )
            return _completed(value, "Adapter factory")

        try:
            built_providers = {
                name: await construct(prepared) for name, prepared in providers.items()
            }
            for provider in built_providers.values():
                LocalEngine._component_identity(provider, ("complete",), False, "Provider")
            context.providers = MappingProxyType(built_providers)
            context.tools = (
                await construct(components.pop("tools"))
                if "tools" in components
                else ToolRegistry()
            )
            options = {kind: await construct(prepared) for kind, prepared in components.items()}
            if profile.binding_components is not None:
                from .binding_catalog import BindingCatalog

                catalog = BindingCatalog(scope=scope)
                for declaration, prepared in bindings:
                    catalog.register(
                        declaration["role"],
                        declaration["component_id"],
                        declaration["version"],
                        await construct(prepared),
                    )
                options["binding_catalog"] = catalog
            candidate = _completed(
                self.engine_factory(
                    store,
                    providers=built_providers,
                    tools=context.tools,
                    scope=scope,
                    runtime_profile=profile.identity,
                    **options,
                ),
                "Execution engine factory",
            )
            validate_engine(candidate)
            return RuntimeInstance(candidate, context)
        except BaseException as exc:
            owner = candidate if callable(getattr(candidate, "close", None)) else None
            # Rejected candidates may not implement a valid drain port. Their
            # synchronous close remains responsible for the authority gate.
            cleanup = RuntimeInstance(owner, context, drain_engine=False)
            try:
                await cleanup.aclose()
            except BaseException as cleanup_error:
                raise RuntimeBuildError(cleanup) from cleanup_error
            if isinstance(exc, (RalfError, asyncio.CancelledError)):
                raise
            if not isinstance(exc, Exception):
                raise
            raise RuntimeBuildError(cleanup) from exc
