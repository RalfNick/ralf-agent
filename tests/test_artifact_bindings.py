"""Scoped borrowed Artifact targets with original physical references."""

import asyncio
import threading

import pytest

import relf_agent as r
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, RalfError
from relf_agent.tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker


def resource(backend=None, **kwargs):
    cls = getattr(r, "ArtifactBindingResource", None)
    assert cls is not None, "Missing independent Artifact binding resource"
    return cls(
        r.InMemoryArtifactStore(backend_id="artifacts-test") if backend is None else backend,
        version="1",
        namespaces=("alpha", "beta"),
        default_namespace="alpha",
        **kwargs,
    )


def test_resource_select_is_pure_and_namespace_is_host_authorized():
    class NoIO(r.InMemoryArtifactStore):
        def put(self, *args, **kwargs):
            raise AssertionError("Selection must not access backend")

        def get(self, *args, **kwargs):
            raise AssertionError("Selection must not access backend")

    backend = NoIO(backend_id="pure")
    target = resource(backend)
    first = target.select({}, r.Scope())
    second = target.select({"namespace": "beta"}, r.Scope())
    assert first.resource == {"backend_id": "pure", "namespace": "alpha"}
    assert second.namespace == "beta" and second.backend_id == "pure"
    assert target.identity["backend"]["backend_id"] == "pure"
    with pytest.raises(AuthorizationDenied):
        target.select({"namespace": "foreign"}, r.Scope())
    with pytest.raises(RalfError):
        target.select({"path": "secret"}, r.Scope())
    assert not hasattr(second, "delete") and not hasattr(second, "close")
    backend.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"version": ""},
        {"version": True},
        {"version": "\ud800"},
        {"namespaces": []},
        {"namespaces": ["alpha", "alpha"]},
        {"namespaces": ["bad\x00"]},
        {"namespaces": ["\ud800"]},
        {"namespaces": ["x" * 513]},
        {"namespaces": ["alpha"], "default_namespace": "beta"},
        {"namespaces": tuple(str(i) for i in range(257))},
    ],
)
def test_resource_rejects_nonordinary_or_invalid_host_configuration(kwargs):
    cls = getattr(r, "ArtifactBindingResource", None)
    assert cls is not None
    options = {"version": "1", "namespaces": ["alpha"], "default_namespace": "alpha", **kwargs}
    with pytest.raises(RalfError):
        cls(r.InMemoryArtifactStore(), **options)


def test_view_preserves_original_reference_and_borrows_shared_store():
    backend = r.InMemoryArtifactStore(backend_id="shared")
    target = resource(backend)
    view = target.select({"namespace": "beta"}, r.Scope())

    async def run():
        reference = await view.put(r.Scope(), "beta", {"中文": [1, "value"]})
        assert (
            type(reference) is r.ArtifactReference
            and reference.backend_id == "shared"
            and reference.namespace == "beta"
        )
        assert await view.get(r.Scope(), reference) == {"中文": [1, "value"]}
        assert backend.get(r.Scope(), reference) == {"中文": [1, "value"]}
        assert not hasattr(view, "aclose")

    asyncio.run(run())
    backend.put(r.Scope(), "alpha", "still usable")
    backend.close()


def test_view_checks_scope_namespace_and_raw_reference_before_io():
    backend = r.InMemoryArtifactStore(backend_id="guard")
    target = resource(backend)
    view = target.select({}, r.Scope())
    foreign = backend.put(r.Scope(), "beta", "foreign")

    async def run():
        with pytest.raises(AuthorizationDenied):
            await view.put(r.Scope("foreign", "user"), "alpha", "x")
        with pytest.raises(AuthorizationDenied):
            await view.put(r.Scope(), "beta", "x")
        with pytest.raises(AuthorizationDenied):
            await view.get(r.Scope(), foreign)
        with pytest.raises(RalfError):
            await view.get(r.Scope(), foreign.to_dict())
        accepted = await view.put(r.Scope(), "alpha", "original")
        object.__setattr__(accepted, "to_dict", lambda: foreign.to_dict())
        assert await view.get(r.Scope(), accepted) == "original"

    asyncio.run(run())
    backend.close()


def test_backend_method_change_refuses_before_delegation(monkeypatch):
    backend = r.InMemoryArtifactStore(backend_id="methods")
    target = resource(backend)
    view = target.select({}, r.Scope())

    def changed(*args, **kwargs):
        raise AssertionError("Replaced method was called")

    monkeypatch.setattr(backend, "put", changed)
    with pytest.raises(DefinitionMismatch):
        _ = target.identity

    async def run():
        with pytest.raises(DefinitionMismatch):
            await view.put(r.Scope(), "alpha", "x")

    asyncio.run(run())
    backend.close()


def test_async_replacement_and_postawait_identity_change_reject_adoption():
    class Remote:
        def __init__(self):
            self.store = r.InMemoryArtifactStore(backend_id="async")
            self.version = "1"

        @property
        def backend_id(self):
            return self.store.backend_id

        @property
        def identity(self):
            return {
                "kind": "async-contract-store",
                "version": self.version,
                "backend_id": self.backend_id,
            }

        async def put(self, scope, namespace, value, *, expires_at=None):
            result = self.store.put(scope, namespace, value, expires_at=expires_at)
            self.version = "moved"
            await asyncio.sleep(0)
            return result

        async def get(self, scope, reference, *, max_bytes=None):
            return self.store.get(scope, reference, max_bytes=max_bytes)

    backend = Remote()
    view = resource(backend).select({}, r.Scope())

    async def run():
        with pytest.raises(DefinitionMismatch):
            await view.put(r.Scope(), "alpha", "x")

    asyncio.run(run())
    backend.store.close()


@pytest.mark.parametrize("lazy", ["coroutine", "wrong-reference", "oversized"])
def test_returned_reference_is_completed_original_and_matches_request(lazy):
    class Bad(r.InMemoryArtifactStore):
        def put(self, scope, namespace, value, *, expires_at=None):
            if lazy == "coroutine":

                async def pending():
                    return None

                return pending()
            if lazy == "oversized":
                return {"too-large": "x" * 1048577}
            return super().put(scope, namespace, "different", expires_at=expires_at)

    backend = Bad(backend_id="bad")
    view = resource(backend).select({}, r.Scope())

    async def run():
        with pytest.raises(RalfError):
            await view.put(r.Scope(), "alpha", "original")

    asyncio.run(run())
    backend.close()


def test_cancelled_sync_write_remains_in_original_actual_thread_tracker():
    class Blocked(r.InMemoryArtifactStore):
        def put(self, *args, **kwargs):
            self.entered.set()
            assert self.release.wait(5)
            return super().put(*args, **kwargs)

    backend = Blocked(backend_id="thread")
    backend.entered = threading.Event()
    backend.release = threading.Event()
    view = resource(backend).select({}, r.Scope())
    tracker = ThreadExecutionTracker()

    async def run():
        token = current_thread_tracker.set(tracker)
        group = current_thread_group.set("original")
        task = asyncio.create_task(view.put(r.Scope(), "alpha", "x"))
        try:
            assert await asyncio.to_thread(backend.entered.wait, 2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert tracker.has_active_for("original")
        finally:
            backend.release.set()
            await tracker.drain("original")
            current_thread_group.reset(group)
            current_thread_tracker.reset(token)
        assert not tracker.has_active

    asyncio.run(run())
    backend.close()


def test_direct_view_constructor_cannot_bypass_host_namespace_allowlist():
    target = resource()
    cls = r.ArtifactView
    with pytest.raises(AuthorizationDenied):
        cls(target, r.Scope(), "foreign")


@pytest.mark.parametrize("field", ["scope", "target", "identity", "check"])
def test_live_view_drift_cannot_expand_selected_resource(field, monkeypatch):
    target = resource()
    view = target.select({}, r.Scope())
    scope = r.Scope()
    if field == "scope":
        scope = r.Scope("foreign", "user")
        view._scope_json = '{"principal":"user","workspace":"foreign"}'
    elif field == "target":
        view._target = resource()
    elif field == "identity":
        view._identity = view._identity.replace('"version":"1"', '"version":"changed"', 1)
    else:
        monkeypatch.setattr(view, "_check", lambda *args: None)

    async def run():
        with pytest.raises(DefinitionMismatch):
            await view.put(scope, "alpha", "x")

    asyncio.run(run())


def test_coordinator_sync_mode_refuses_lazy_without_executing_it():
    class Lazy(r.InMemoryArtifactStore):
        def put(self, *args, **kwargs):
            async def pending():
                self.executed = True
                return None

            return pending()

    backend = Lazy(backend_id="coordinator")
    backend.executed = False
    target = resource(backend, sync_mode="coordinator")
    view = target.select({}, r.Scope())

    async def run():
        with pytest.raises(RalfError):
            await view.put(r.Scope(), "alpha", "x")
        assert backend.executed is False

    asyncio.run(run())
    backend.close()
