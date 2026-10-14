"""Deadline activation through completed public Store methods without SQL access."""

import asyncio
import inspect
from contextlib import asynccontextmanager, contextmanager
from types import MethodType, SimpleNamespace

import pytest

from ralf_agent import AgentSpec, InMemoryMemory, LocalEngine, ModelResponse, ToolRegistry
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.governance import LocalExecutionPolicy

from .helpers import ScriptedProvider
from .test_extension_contracts import HostCoordinator, StoreAdapter


class DeadlineStore(StoreAdapter):
    local_deadline_version = 1
    _methods = StoreAdapter._methods | {"prepare_local_deadlines"}

    @property
    def backend_id(self):
        return self._backend.backend_id


def engine(store, provider=None, **options):
    memory = InMemoryMemory(backend_id="deadline-port-memory")
    return LocalEngine(
        store,
        providers={"default": provider or ScriptedProvider([])},
        tools=ToolRegistry(),
        coordinator=HostCoordinator(),
        session_store=memory,
        memory_store=memory,
        **options,
    )


def test_connection_hidden_store_restores_original_deadline_without_model_dispatch(
    tmp_path, monkeypatch
):
    import ralf_agent.local_deadlines as deadlines

    path = tmp_path / "execution.sqlite"
    spec = AgentSpec("agent", "Answer")
    policy = LocalExecutionPolicy(run_timeout_seconds=30)
    provider = ScriptedProvider([ModelResponse(output="must not be called")])
    with engine(DeadlineStore(path), provider, execution_policy=policy) as runtime:
        assert not hasattr(runtime.store, "conn")
        assert not hasattr(runtime.store, "path")
        handle = runtime.submit(spec, "task", command_id="original")
        original = runtime.store.run(handle.run_id)
        deadline = original["local_deadlines"]["run_expires_at"]
    monkeypatch.setattr(deadlines, "time", SimpleNamespace(time=lambda: deadline + 1))
    with engine(DeadlineStore(path), provider, execution_policy=policy) as reopened:
        assert reopened.submit(spec, "task", command_id="original") == handle
        assert reopened.store.run(handle.run_id)["local_deadlines"] == original["local_deadlines"]
        snapshot = asyncio.run(reopened.drive(handle.run_id))
        assert snapshot.state == "cancelled"
        assert snapshot.error["code"] == "deadline_exceeded"
        assert provider.calls == 0
        assert reopened.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}


def test_legacy_proxy_without_optional_capability_preserves_defaults_and_refuses_policy(tmp_path):
    store = StoreAdapter(tmp_path / "legacy.sqlite")
    provider = ScriptedProvider([])
    try:
        with pytest.raises(ValidationError, match="optional deadline Store"):
            engine(store, provider, execution_policy=LocalExecutionPolicy(run_timeout_seconds=1))
        with engine(store, provider) as runtime:
            handle = runtime.submit(AgentSpec("agent", "Answer"), "task", command_id="default")
            assert "local_deadlines" not in runtime.store.run(handle.run_id)
            assert provider.calls == 0
            with pytest.raises(DefinitionMismatch, match="deadline Store"):
                runtime.submit(
                    AgentSpec("agent", "Answer"), "task", command_id="explicit", deadline_at=1
                )
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["coroutine-function", "generator-function", "async-generator"])
def test_registration_refuses_lazy_prepare_methods_before_acquiring_authority(tmp_path, kind):
    entered = []

    async def coroutine(self):
        entered.append(True)

    def generator(self):
        entered.append(True)
        yield None

    async def async_generator(self):
        entered.append(True)
        yield None

    method = {
        "coroutine-function": coroutine,
        "generator-function": generator,
        "async-generator": async_generator,
    }[kind]
    store_type = type("LazyStore", (DeadlineStore,), {"prepare_local_deadlines": method})
    store = store_type(tmp_path / "lazy.sqlite")
    try:
        with pytest.raises(ValidationError, match="completed optional Store"):
            engine(store, execution_policy=LocalExecutionPolicy())
        assert entered == []
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["coroutine", "generator", "context", "async-context"])
def test_sync_prepare_refuses_deferred_returns_without_entering_their_body(tmp_path, kind):
    entered = []

    async def coroutine():
        entered.append(True)

    def generator():
        entered.append(True)
        yield None

    @contextmanager
    def context():
        entered.append(True)
        yield None

    @asynccontextmanager
    async def async_context():
        entered.append(True)
        yield None

    deferred = {
        "coroutine": coroutine,
        "generator": generator,
        "context": context,
        "async-context": async_context,
    }[kind]()

    class DeferredStore(DeadlineStore):
        return_deferred = True

        def prepare_local_deadlines(self):
            self._backend.prepare_local_deadlines()
            return deferred if self.return_deferred else None

    provider = ScriptedProvider([])
    store = DeferredStore(tmp_path / "deferred.sqlite")
    try:
        with engine(store, provider, execution_policy=LocalExecutionPolicy()) as runtime:
            with pytest.raises(ValidationError, match="Local deadline preparation"):
                runtime.submit(AgentSpec("agent", "Answer"), "task", command_id="invalid")
            assert provider.calls == 0
            assert entered == []
            store.return_deferred = False
            handle = runtime.submit(AgentSpec("agent", "Answer"), "task", command_id="invalid")
            assert runtime.status(handle.run_id).state == "queued"
            assert len(runtime.events(handle.run_id)) == 1
        if kind == "coroutine":
            assert inspect.getcoroutinestate(deferred) == inspect.CORO_CLOSED
        elif kind == "generator":
            assert inspect.getgeneratorstate(deferred) == inspect.GEN_CLOSED
    finally:
        if kind in {"coroutine", "generator"}:
            deferred.close()
        elif kind == "context":
            deferred.gen.close()
        else:
            asyncio.run(deferred.gen.aclose())


@pytest.mark.parametrize("returned", [True, False, 0, "done", {}, []])
def test_prepare_requires_none_and_rolls_back_activation_on_invalid_result(tmp_path, returned):
    class InvalidStore(DeadlineStore):
        return_invalid = True

        def prepare_local_deadlines(self):
            self._backend.prepare_local_deadlines()
            return returned if self.return_invalid else None

    provider = ScriptedProvider([])
    with engine(
        InvalidStore(tmp_path / "invalid.sqlite"), provider, execution_policy=LocalExecutionPolicy()
    ) as runtime:
        with pytest.raises(ValidationError, match="return None"):
            runtime.submit(AgentSpec("agent", "Answer"), "task", command_id="invalid")
        assert provider.calls == 0
        runtime.store.return_invalid = False
        handle = runtime.submit(AgentSpec("agent", "Answer"), "task", command_id="invalid")
        assert runtime.status(handle.run_id).state == "queued"
        assert len(runtime.events(handle.run_id)) == 1


@pytest.mark.parametrize("drift", ["method", "backend", "store"])
def test_original_deadline_store_binding_must_survive_before_resume(tmp_path, drift):
    path = tmp_path / "execution.sqlite"
    provider = ScriptedProvider([ModelResponse(output="must not be called")])
    original = DeadlineStore(path)
    runtime = engine(
        original, provider, execution_policy=LocalExecutionPolicy(run_timeout_seconds=30)
    )
    replacement = None
    backend = original.backend_id
    try:
        handle = runtime.submit(AgentSpec("agent", "Answer"), "task", command_id="original")
        if drift == "method":
            original.prepare_local_deadlines = MethodType(lambda self: None, original)
        elif drift == "backend":
            original._backend.backend_id = "replacement-authority"
        else:
            replacement = DeadlineStore(path)
            runtime.store = replacement
        with pytest.raises(DefinitionMismatch, match="deadline Store"):
            asyncio.run(runtime.drive(handle.run_id))
        assert provider.calls == 0
    finally:
        runtime.store = original
        original._backend.backend_id = backend
        if drift == "method":
            del original.prepare_local_deadlines
        runtime.close()
        if replacement is not None:
            replacement.close()


@pytest.mark.parametrize("drift", ["method", "backend"])
def test_preparation_rechecks_original_store_binding_before_acceptance(tmp_path, drift):
    class MutatingStore(DeadlineStore):
        mutate = True

        def prepare_local_deadlines(self):
            self._backend.prepare_local_deadlines()
            if self.mutate:
                if drift == "method":
                    self.prepare_local_deadlines = MethodType(lambda self: None, self)
                else:
                    self._backend.backend_id = "replacement-during-preparation"

    store = MutatingStore(tmp_path / "mutation.sqlite")
    backend = store.backend_id
    provider = ScriptedProvider([])
    with engine(store, provider, execution_policy=LocalExecutionPolicy()) as runtime:
        try:
            with pytest.raises(DefinitionMismatch, match="deadline Store"):
                runtime.submit(AgentSpec("agent", "Answer"), "task", command_id="original")
            assert provider.calls == 0
        finally:
            store.mutate = False
            store._backend.backend_id = backend
            if drift == "method":
                del store.prepare_local_deadlines
        handle = runtime.submit(AgentSpec("agent", "Answer"), "task", command_id="original")
        assert runtime.status(handle.run_id).state == "queued"
        assert len(runtime.events(handle.run_id)) == 1
