"""Native publication uses the execution port, never a required SQL connection."""

import asyncio
import inspect
from contextlib import asynccontextmanager, contextmanager

import pytest

import relf_agent as r
from relf_agent.errors import ValidationError
from tests.test_extension_contracts import HostCoordinator, StoreAdapter
from tests.test_local_session_model_history import FIRST_FINAL, options, spec


class NativeStore(StoreAdapter):
    native_history_version = 1
    _methods = StoreAdapter._methods | {
        "prepare_native_history",
        "native_history_publications",
        "publish_native_history",
    }


@pytest.mark.parametrize("source", ["memory", "external-sqlite"])
def test_connection_free_execution_store_preserves_two_turns_and_original_receipts(
    tmp_path, source
):
    async def scenario():
        requests, queries = [], []
        external = (
            r.SQLiteStore(tmp_path / "session.sqlite") if source == "external-sqlite" else None
        )
        memory = (
            r.SQLiteMemory(external)
            if external is not None
            else r.InMemoryMemory(backend_id="non-sql-execution-native-session")
        )
        try:
            original_id = None
            for index, task in enumerate(("first-task", "second-task")):
                store = NativeStore(tmp_path / "execution.sqlite")
                assert not hasattr(store, "conn")
                with r.LocalEngine(
                    store,
                    coordinator=HostCoordinator(),
                    session_store=memory,
                    memory_store=memory,
                    **options(requests, queries),
                ) as engine:
                    if original_id is not None:
                        previous = store.run(original_id)["native_model_history"]
                        assert (await engine.drive(original_id)).state == "succeeded"
                        assert store.run(original_id)["native_model_history"] == previous
                    handle = engine.submit(
                        spec(), task, session_id="chat", command_id=f"turn-{index}"
                    )
                    assert (await engine.drive(handle.run_id)).state == "succeeded"
                    assert (
                        engine.submit(
                            spec(), task, session_id="chat", command_id=f"turn-{index}"
                        ).run_id
                        == handle.run_id
                    )
                    original_id = handle.run_id
            assert len(requests) == 4
            assert requests[2][4]["content"] == FIRST_FINAL
            assert queries == ["first-task", "first-task", "second-task", "second-task"]
        finally:
            if external is not None:
                external.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("method", "lazy"),
    [
        (method, lazy)
        for lazy in ("async", "generator", "context", "async-context", "no-op")
        for method in (
            "prepare_native_history",
            "native_history_publications",
            "publish_native_history",
        )
        if (method, lazy) != ("native_history_publications", "no-op")
    ],
)
def test_lazy_publication_capability_cannot_confirm_success(tmp_path, method, lazy):
    entered = []

    async def asynchronous(self, *args):
        entered.append(True)
        return None

    def generator(self, *args):
        entered.append(True)
        yield None

    @contextmanager
    def context(self, *args):
        entered.append(True)
        yield None

    @asynccontextmanager
    async def async_context(self, *args):
        entered.append(True)
        yield None

    def no_op(self, *args):
        return None

    replacement = {
        "async": asynchronous,
        "generator": generator,
        "context": context,
        "async-context": async_context,
        "no-op": no_op,
    }[lazy]
    store_type = type("LazyNativeStore", (r.SQLiteStore,), {method: replacement})

    async def scenario():
        requests, queries = [], []
        memory = r.InMemoryMemory(backend_id="lazy-native-publication")
        with r.LocalEngine(
            store_type(tmp_path / "execution.sqlite"),
            session_store=memory,
            **options(requests, queries),
        ) as engine:
            try:
                handle = engine.submit(spec(), "first-task", session_id="chat", command_id="turn")
            except ValidationError:
                assert requests == []
                return
            assert (await engine.drive(handle.run_id)).state == "failed"
            assert engine.store.run(handle.run_id)["state"] != "succeeded"

    asyncio.run(scenario())
    assert entered == []


@pytest.mark.parametrize("kind", ["coroutine", "generator", "context", "async-context"])
def test_sync_publication_port_closes_deferred_return_without_entering_body(tmp_path, kind):
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

    class DeferredPrepare(r.SQLiteStore):
        def prepare_native_history(self):
            return deferred

    requests, queries = [], []
    try:
        with r.LocalEngine(
            DeferredPrepare(tmp_path / "execution.sqlite"),
            session_store=r.InMemoryMemory(),
            **options(requests, queries),
        ) as engine:
            with pytest.raises(ValidationError):
                engine.submit(spec(), "first-task", session_id="chat", command_id="turn")
        assert requests == entered == []
        if kind == "coroutine":
            assert inspect.getcoroutinestate(deferred) == inspect.CORO_CLOSED
        elif kind == "generator":
            assert inspect.getgeneratorstate(deferred) == inspect.GEN_CLOSED
        elif kind == "context":
            assert inspect.getgeneratorstate(deferred.gen) == inspect.GEN_CLOSED
        else:
            assert deferred.gen.ag_frame is None
    finally:
        if kind in {"coroutine", "generator"}:
            deferred.close()
        elif kind == "context":
            deferred.gen.close()
        else:
            asyncio.run(deferred.gen.aclose())


@pytest.mark.parametrize(
    "method", ["prepare_native_history", "native_history_publications", "publish_native_history"]
)
def test_unknown_publication_port_exception_does_not_leave_run_running(tmp_path, method):
    def broken(self, *args):
        raise RuntimeError("Private backend failure")

    store_type = type("BrokenPublicationStore", (r.SQLiteStore,), {method: broken})

    async def scenario():
        requests, queries = [], []
        with r.LocalEngine(
            store_type(tmp_path / "execution.sqlite"),
            session_store=r.InMemoryMemory(),
            **options(requests, queries),
        ) as engine:
            try:
                handle = engine.submit(spec(), "first-task", session_id="chat", command_id="turn")
            except ValidationError:
                assert requests == []
                return
            assert (await engine.drive(handle.run_id)).state == "failed"
            assert "Private backend failure" not in str(engine.store.run(handle.run_id)["error"])

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "returned", [None, {}, [float("nan")], [{"tuple": ("native",)}], [{}] * 129]
)
def test_publication_lookup_requires_bounded_completed_finite_json_records(tmp_path, returned):
    class InvalidRead(r.SQLiteStore):
        def native_history_publications(self, *args):
            return returned

    async def scenario():
        requests, queries = [], []
        with r.LocalEngine(
            InvalidRead(tmp_path / "execution.sqlite"),
            session_store=r.InMemoryMemory(),
            **options(requests, queries),
        ) as engine:
            handle = engine.submit(spec(), "first-task", session_id="chat", command_id="turn")
            assert (await engine.drive(handle.run_id)).state == "failed"
            assert requests == []

    asyncio.run(scenario())


def test_publication_readback_must_prove_exact_stable_id_and_full_body_in_original_transaction(
    tmp_path,
):
    class ForgedLookup(r.SQLiteStore):
        def native_history_publications(self, *args):
            records = super().native_history_publications(*args)
            if records:
                records[-1]["source_action"] = "forged-adoption"
            return records

    async def scenario():
        requests, queries = [], []
        store = ForgedLookup(tmp_path / "execution.sqlite")
        memory = r.SQLiteMemory(store)
        with r.LocalEngine(store, session_store=memory, **options(requests, queries)) as engine:
            handle = engine.submit(spec(), "first-task", session_id="chat", command_id="turn")
            assert (await engine.drive(handle.run_id)).state == "failed"
            run = store.run(handle.run_id)
            assert (
                store.native_history_publications(
                    engine.scope, run["native_model_history"]["stages"]["agent"]["stream"]
                )
                == []
            )
            record = run["native_model_history"]["episodes"]["agent"]
            receipt = memory.inspect_message(
                engine.scope,
                run["native_model_history"]["stages"]["agent"]["address"],
                record["message_id"],
            )
            assert receipt["receipt"] is None

    asyncio.run(scenario())


def test_invalid_publication_return_with_failing_close_still_refuses_before_business_io(tmp_path):
    entered = []
    closed = []

    class Deferred:
        def __await__(self):
            entered.append(True)
            yield None

        def close(self):
            closed.append(True)
            raise RuntimeError("Cleanup adapter failure")

    class BadPrepare(r.SQLiteStore):
        def prepare_native_history(self):
            return Deferred()

    requests, queries = [], []
    with r.LocalEngine(
        BadPrepare(tmp_path / "execution.sqlite"),
        session_store=r.InMemoryMemory(),
        **options(requests, queries),
    ) as engine:
        with pytest.raises(ValidationError):
            engine.submit(spec(), "first-task", session_id="chat", command_id="turn")
    assert entered == requests == []
    assert closed == [True]


def test_deep_publication_lookup_refuses_with_typed_failure_and_no_model_dispatch(tmp_path):
    nested = []
    for _ in range(2000):
        nested = [nested]

    class DeepRead(r.SQLiteStore):
        def native_history_publications(self, *args):
            return [{"value": nested}]

    async def scenario():
        requests, queries = [], []
        with r.LocalEngine(
            DeepRead(tmp_path / "execution.sqlite"),
            session_store=r.InMemoryMemory(),
            **options(requests, queries),
        ) as engine:
            handle = engine.submit(spec(), "first-task", session_id="chat", command_id="turn")
            assert (await engine.drive(handle.run_id)).state == "failed"
            assert requests == []

    asyncio.run(scenario())
