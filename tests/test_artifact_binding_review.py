"""Independent review reproductions at original public binding boundaries."""

import asyncio
import gc
import types
import warnings
import weakref
from types import SimpleNamespace

import pytest

import ralf_agent as r
from ralf_agent.binding_runtime import AgentBindingResolver
from ralf_agent.errors import DefinitionMismatch, RalfError

from .test_artifact_binding_execution import definition, engine, host
from .test_artifact_binding_lifetime import NativeAsyncArtifacts


@pytest.mark.parametrize("sync_mode", ["thread", "coordinator", "async"])
def test_read_keeps_original_reference_when_delegated_copy_is_mutated(sync_mode):
    class Rewrite(r.InMemoryArtifactStore):
        def get(self, scope, reference, *, max_bytes=None):
            for key, value in self.other.items():
                object.__setattr__(reference, key, value)
            return r.InMemoryArtifactStore.get(self, scope, reference, max_bytes=max_bytes)

    class AsyncRewrite(NativeAsyncArtifacts):
        async def get(self, scope, reference, *, max_bytes=None):
            for key, value in self.other.items():
                object.__setattr__(reference, key, value)
            return await NativeAsyncArtifacts.get(self, scope, reference, max_bytes=max_bytes)

    async def run():
        backend = AsyncRewrite() if sync_mode == "async" else Rewrite(backend_id="alpha")
        resource = r.ArtifactBindingResource(
            backend,
            version="1",
            namespaces=["alpha"],
            default_namespace="alpha",
            sync_mode="thread" if sync_mode == "async" else sync_mode,
        )
        view = resource.select({}, r.Scope())
        first = await view.put(r.Scope(), "alpha", "original")
        backend.other = (await view.put(r.Scope(), "alpha", "replacement")).to_dict()
        original = first.to_dict()
        with pytest.raises(DefinitionMismatch):
            await view.get(r.Scope(), first)
        assert first.to_dict() == original

    asyncio.run(run())


@pytest.mark.parametrize("replace", ["backend", "put", "get"])
def test_equal_custom_store_never_replaces_original_backend_or_receiver(replace):
    class EqualStore(r.InMemoryArtifactStore):
        def __eq__(self, other):
            return isinstance(other, EqualStore)

    a, b = (EqualStore(backend_id="same") for _ in range(2))
    resource = r.ArtifactBindingResource(a, version="1")
    view = resource.select({}, r.Scope())
    if replace == "backend":
        resource._backend = b
    else:
        setattr(a, replace, types.MethodType(getattr(EqualStore, replace), b))
    with pytest.raises(DefinitionMismatch):
        asyncio.run(view.put(r.Scope(), "context-results", "redirected"))
    assert not a._records and not b._records


def test_equal_callable_object_never_replaces_original_operation():
    class EqualOperation:
        def __init__(self, backend):
            self.backend = backend

        def __eq__(self, other):
            return isinstance(other, EqualOperation)

        def __call__(self, *args, **kwargs):
            return r.InMemoryArtifactStore.put(self.backend, *args, **kwargs)

    a, b = (r.InMemoryArtifactStore(backend_id="same") for _ in range(2))
    a.put = EqualOperation(a)
    resource = r.ArtifactBindingResource(a, version="1")
    view = resource.select({}, r.Scope())
    a.put = EqualOperation(b)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(view.put(r.Scope(), "context-results", "redirected"))
    assert not a._records and not b._records


@pytest.mark.parametrize("field", ["namespaces", "scope"])
def test_custom_equality_cannot_change_a_sealed_namespace_or_scope_guard(field):
    class EqualNamespaces(tuple):
        def __contains__(self, value):
            return True

    class EqualText(str):
        def __eq__(self, other):
            return True

        def __ne__(self, other):
            return False

    backend = r.InMemoryArtifactStore(backend_id="sealed")
    resource = r.ArtifactBindingResource(backend, version="1")
    if field == "namespaces":
        resource._namespaces = EqualNamespaces(resource._namespaces)
        with pytest.raises(DefinitionMismatch):
            resource.select({"namespace": "foreign"}, r.Scope())
    else:
        view = resource.select({}, r.Scope())
        view._scope_json = EqualText(view._scope_json)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(view.put(r.Scope("foreign", "other"), "context-results", "x"))
    assert not backend._records


@pytest.mark.parametrize("mode", ["ref", "disabled"])
def test_custom_equal_prediction_cannot_ignore_explicit_local_selection(tmp_path, mode):
    class Ignored(r.ManagedDataContext):
        def artifact_binding_identity(self, metadata):
            return self.identity

        def bind_artifacts(self, target):
            return self

    catalog, backends, tools, context, observed = host(tmp_path)
    original = Ignored(context.artifacts)
    try:
        with engine(tmp_path / "ignored.sqlite", catalog, tools, original) as runtime:
            with pytest.raises(DefinitionMismatch):
                runtime.submit(definition("agent", mode), "read", command_id="s")
            assert not observed and not original.artifacts._records
            assert runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_custom_prediction_cannot_rewrite_its_selected_target_argument(tmp_path):
    from ralf_agent.artifact_binding_context import predict, realize

    class Redirect(r.ManagedDataContext):
        def artifact_binding_identity(self, metadata):
            metadata.clear()
            metadata.update(self.foreign.identity)
            return predict(self, metadata)

        def bind_artifacts(self, target):
            return realize(self, self.foreign)

    catalog, backends, tools, context, observed = host(tmp_path)
    original = Redirect(context.artifacts)
    foreign = r.InMemoryArtifactStore(backend_id="unregistered")
    original.foreign = r.ArtifactBindingResource(foreign, version="1").select({}, r.Scope())
    try:
        with engine(tmp_path / "redirected.sqlite", catalog, tools, original) as runtime:
            with pytest.raises(DefinitionMismatch):
                runtime.submit(definition("agent"), "read", command_id="s")
            assert not observed and not foreign._records
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()
        foreign.close()


@pytest.mark.parametrize("name", ["artifact_binding_identity", "bind_artifacts"])
def test_local_binding_ports_are_pinned_even_when_replacement_returns_cached_identity(name):
    origin = r.ManagedDataContext(r.InMemoryArtifactStore(backend_id="origin"))
    target = r.ArtifactBindingResource(
        r.InMemoryArtifactStore(backend_id="target"), version="1"
    ).select({}, r.Scope())
    resolver = AgentBindingResolver(SimpleNamespace())
    first = resolver._artifact_context(origin, target)
    original = getattr(origin, name)
    calls = []

    def changed(argument):
        calls.append(name)
        return original(argument)

    setattr(origin, name, changed)
    with pytest.raises(DefinitionMismatch):
        resolver._artifact_context(origin, target)
    assert not calls and first is not None


def test_local_ports_are_pinned_at_engine_assembly_before_first_submission(tmp_path):
    catalog, backends, tools, context, observed = host(tmp_path)
    try:
        with engine(tmp_path / "first.sqlite", catalog, tools, context) as runtime:
            original = context.artifact_binding_identity
            calls = []

            def replacement(metadata):
                calls.append("replacement")
                return original(metadata)

            context.artifact_binding_identity = replacement
            with pytest.raises(DefinitionMismatch):
                runtime.submit(definition("agent"), "read", command_id="s")
            assert not calls and not observed
    finally:
        for backend in backends.values():
            backend.close()
        context.artifacts.close()


def test_local_port_pins_do_not_retain_retired_contexts():
    resolver = AgentBindingResolver(SimpleNamespace())
    target = r.ArtifactBindingResource(
        r.InMemoryArtifactStore(backend_id="target"), version="1"
    ).select({}, r.Scope())
    for _ in range(5):
        origin = r.ManagedDataContext(r.InMemoryArtifactStore(backend_id="origin"))
        selected = resolver._artifact_context(origin, target)
        retired = weakref.ref(origin)
        del selected, origin
        gc.collect()
        assert retired() is None
        assert not resolver._artifact_ports and not resolver._artifact_contexts


@pytest.mark.parametrize("limit", [1, 0, True, 1.5, 1048577])
def test_custom_async_read_cannot_ignore_invalid_or_undersized_limit(limit):
    async def run():
        backend = NativeAsyncArtifacts()
        view = r.ArtifactBindingResource(
            backend, version="1", namespaces=["alpha"], default_namespace="alpha"
        ).select({}, r.Scope())
        reference = await view.put(r.Scope(), "alpha", "content bigger than limit")
        loops = len(backend.loops)
        with pytest.raises(RalfError):
            await view.get(r.Scope(), reference, max_bytes=limit)
        assert len(backend.loops) == loops

    asyncio.run(run())


@pytest.mark.parametrize("sync_mode", ["thread", "coordinator"])
def test_lazy_read_result_is_closed_without_running_or_unawaited_warning(sync_mode):
    class Lazy(r.InMemoryArtifactStore):
        def get(self, *args, **kwargs):
            async def pending():
                self.invoked = True
                return "x"

            return pending()

    backend = Lazy(backend_id="lazy")
    backend.invoked = False
    view = r.ArtifactBindingResource(backend, version="1", sync_mode=sync_mode).select(
        {}, r.Scope()
    )
    reference = backend.put(r.Scope(), "context-results", "x")

    async def run():
        with pytest.raises(RalfError):
            await view.get(r.Scope(), reference)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(run())
        gc.collect()
    assert not backend.invoked
    assert not [warning for warning in caught if "never awaited" in str(warning.message)]
