"""Behavior regressions from the dev12 framework capability review."""

import asyncio
import json
import warnings
from contextlib import asynccontextmanager, closing, contextmanager
from types import SimpleNamespace

import pytest

from relf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryMemory,
    Literal,
    LocalEngine,
    ProfiledEngine,
    RuntimeCatalog,
    RuntimeProfile,
    Scope,
    SQLiteMemory,
    SQLiteRunReader,
    SQLiteStore,
    ToolRegistry,
)
from relf_agent.errors import CoordinatorBusy, ValidationError
from relf_agent.runtime_builder import EchoProvider


def deferred_operation(operation, form):
    async def asynchronous():
        operation()

    def generator():
        operation()
        yield

    @contextmanager
    def context():
        operation()
        yield

    @asynccontextmanager
    async def async_context():
        operation()
        yield

    class AsyncCallable:
        async def __call__(self):
            operation()

    class Awaitable:
        def __await__(self):
            operation()
            yield

    return {
        "async": asynchronous,
        "generator": generator,
        "contextmanager": context,
        "asynccontextmanager": async_context,
        "returned-coroutine": lambda: asynchronous(),
        "async-callable": AsyncCallable(),
        "awaitable": Awaitable,
        "false": lambda: False,
    }[form]


INVALID_COMPLETIONS = (
    "async",
    "generator",
    "contextmanager",
    "asynccontextmanager",
    "returned-coroutine",
    "async-callable",
    "awaitable",
    "false",
)


def local(store, **options):
    return LocalEngine(store, providers={}, tools=ToolRegistry(), **options)


def assert_owned(path):
    with SQLiteStore(path) as contender:
        lease = contender.create_coordinator()
        try:
            with pytest.raises(CoordinatorBusy):
                lease.acquire()
        finally:
            lease.release()


@pytest.mark.parametrize("form", INVALID_COMPLETIONS)
def test_incomplete_acquire_cannot_construct_an_execution_owner(tmp_path, form):
    path = tmp_path / "acquire.sqlite"
    store = SQLiteStore(path)
    actual = store.create_coordinator()
    lease = SimpleNamespace(
        acquire=deferred_operation(actual.acquire, form), release=actual.release
    )
    runtime = None
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        try:
            with pytest.raises(ValidationError):
                runtime = local(store, coordinator=lease)
            with local(SQLiteStore(path)):
                pass
        finally:
            if runtime is not None:
                runtime.close()
            actual.release()
            store.close()
        assert not captured


def profiled(path):
    catalog = RuntimeCatalog()
    catalog.register(
        RuntimeProfile("review", "1", {"default": {"adapter": "offline-echo"}}), default=True
    )
    return ProfiledEngine(catalog, path)


INVALID_SESSIONS = [123, False, "", " \t", {"session": "123"}]


@pytest.mark.parametrize("session_id", INVALID_SESSIONS)
@pytest.mark.parametrize("assembly", ["native", "profiled"])
def test_invalid_session_cannot_accept_or_consume_a_submit_command(tmp_path, assembly, session_id):
    path = tmp_path / "submission.sqlite"
    runtime = (
        LocalEngine(
            SQLiteStore(path), providers={"default": EchoProvider("review")}, tools=ToolRegistry()
        )
        if assembly == "native"
        else profiled(path)
    )
    with runtime:
        with pytest.raises(ValidationError, match="Session ID"):
            runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", session_id=session_id)
        handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", session_id="123")
        assert runtime.status(handle.run_id).state == "queued"
        assert (
            runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", session_id="123")
            == handle
        )


@pytest.mark.parametrize("assembly", ["native", "profiled"])
def test_valid_session_names_and_automatic_session_keep_receipt_and_history(tmp_path, assembly):
    path = tmp_path / "valid-sessions.sqlite"
    if assembly == "native":
        runtime = LocalEngine(
            SQLiteStore(path), providers={"default": EchoProvider("review")}, tools=ToolRegistry()
        )
    else:
        runtime = profiled(path)
    with runtime:
        spec = AgentSpec("a", "Answer")
        automatic = runtime.submit(spec, "q", command_id="automatic")
        named = runtime.submit(spec, "q", command_id="named", session_id=" 123 ")
        assert asyncio.run(runtime.drive(automatic.run_id)).state == "succeeded"
        assert asyncio.run(runtime.drive(named.run_id)).state == "succeeded"
        assert runtime.submit(spec, "q", command_id="automatic") == automatic
        assert runtime.submit(spec, "q", command_id="named", session_id=" 123 ") == named
    with closing(SQLiteMemory(path)) as memory:
        assert memory.read(Scope(), automatic.run_id)[0] == 1
        assert memory.read(Scope(), " 123 ")[0] == 1
        assert memory.read(Scope(), "123") == (0, [])


@pytest.mark.parametrize("session_id", INVALID_SESSIONS)
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
@pytest.mark.parametrize("operation", ["read", "append"])
def test_session_backends_reject_invalid_ids_before_reading_or_writing(
    tmp_path, backend, operation, session_id
):
    memory = InMemoryMemory() if backend == "memory" else SQLiteMemory(tmp_path / "memory.sqlite")
    message = {"role": "assistant", "content": "valid history"}
    try:
        memory.append(Scope(), "123", message, expected_revision=0, message_id="original")
        with pytest.raises(ValidationError, match="Session ID"):
            if operation == "read":
                memory.read(Scope(), session_id)
            else:
                memory.append(
                    Scope(),
                    session_id,
                    {"role": "user", "content": "invalid"},
                    expected_revision=1,
                    message_id="invalid",
                )
        assert memory.read(Scope(), "123") == (1, [message])
    finally:
        memory.close()


def test_invalid_completed_acquire_cleans_up_a_partially_owned_lease(tmp_path):
    path = tmp_path / "partial-acquire.sqlite"
    with SQLiteStore(path) as store:
        actual = store.create_coordinator()

        def incomplete():
            actual.acquire()
            return True

        runtime = None
        try:
            with pytest.raises(ValidationError):
                runtime = local(
                    store, coordinator=SimpleNamespace(acquire=incomplete, release=actual.release)
                )
            with local(SQLiteStore(path)):
                pass
        finally:
            if runtime is not None:
                runtime.close()
            actual.release()


@pytest.mark.parametrize("reuse", ["store", "lease"])
def test_failed_acquire_never_releases_a_reused_coordinator_owner(tmp_path, reuse):
    path = tmp_path / "reused-coordinator.sqlite"
    with LocalEngine(
        SQLiteStore(path), providers={"default": EchoProvider("owner")}, tools=ToolRegistry()
    ) as owner:
        contender_store = owner.store if reuse == "store" else SQLiteStore(path)
        options = {} if reuse == "store" else {"coordinator": owner.coordinator}
        try:
            with pytest.raises(CoordinatorBusy):
                local(contender_store, **options)
            assert_owned(path)
            handle = owner.submit(AgentSpec("a", "Answer"), "q", command_id="owner")
            assert asyncio.run(owner.drive(handle.run_id)).state == "succeeded"
        finally:
            if contender_store is not owner.store:
                contender_store.close()


@pytest.mark.parametrize("form", INVALID_COMPLETIONS)
def test_incomplete_store_close_retains_ownership_and_can_be_retried(tmp_path, form):
    path = tmp_path / "store-close.sqlite"
    store = SQLiteStore(path)
    runtime = local(store)
    close = store.close
    store.close = deferred_operation(close, form)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        try:
            with pytest.raises(ValidationError):
                runtime.close()
            assert store.conn.execute("SELECT 1").fetchone()[0] == 1
            assert_owned(path)
            with pytest.raises(ValidationError):
                runtime.submit(AgentSpec("a", "Answer"), "q", command_id="blocked")
            store.close = close
            runtime.close()
            with local(SQLiteStore(path)):
                pass
        finally:
            store.close = close
            runtime.close()
            close()
            runtime.coordinator.release()
        assert not captured


@pytest.mark.parametrize("form", INVALID_COMPLETIONS)
def test_incomplete_release_is_retriable_without_reclosing_storage(tmp_path, form):
    class CountingStore(SQLiteStore):
        closes = 0

        def close(self):
            self.closes += 1
            super().close()

    path = tmp_path / "lease-release.sqlite"
    store = CountingStore(path)
    actual = store.create_coordinator()
    lease = SimpleNamespace(acquire=actual.acquire, release=actual.release)
    runtime = local(store, coordinator=lease)
    lease.release = deferred_operation(actual.release, form)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        try:
            with pytest.raises(ValidationError):
                runtime.close()
            assert_owned(path)
            with pytest.raises(ValidationError):
                runtime.close()
            assert store.closes == 1
            lease.release = actual.release
            runtime.close()
            assert store.closes == 1
            with local(SQLiteStore(path)):
                pass
        finally:
            lease.release = actual.release
            runtime.close()
            actual.release()
            SQLiteStore.close(store)
        assert not captured


@pytest.mark.parametrize("form", ["async", "generator", "async-callable"])
def test_store_declared_async_or_generator_close_is_rejected_before_acquire(tmp_path, form):
    path = tmp_path / "invalid-store.sqlite"
    store = SQLiteStore(path)
    close = store.close
    store.close = deferred_operation(close, form)
    runtime = None
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        try:
            with pytest.raises(ValidationError):
                runtime = local(store)
            with local(SQLiteStore(path)):
                pass
        finally:
            store.close = close
            if runtime is not None:
                runtime.close()
            close()
        assert not captured


@pytest.mark.parametrize("limit", [1, 2])
def test_profiled_and_readonly_diagnostics_retain_detached_workflow_details(tmp_path, limit):
    path = tmp_path / "diagnostics.sqlite"
    spec = GraphWorkflowSpec(
        "agents",
        [
            GraphNode("a", agent=AgentSpec("a", "Answer"), input=Literal("left")),
            GraphNode("b", agent=AgentSpec("b", "Answer"), input=Literal("right")),
        ],
        max_concurrency=limit,
    )
    with profiled(path) as runtime:
        handle = runtime.submit(spec, "q", command_id="s", session_id="parent-session")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"
        details = runtime.diagnostics(handle.run_id)
        assert details.workflow is not None
        assert set(details.workflow["nodes"]) == {"a", "b"}
        assert all(node["state"] == "completed" for node in details.workflow["nodes"].values())
        assert all("execution" not in node for node in details.workflow["nodes"].values())
        if limit == 2:
            assert details.workflow["nodes"]["a"]["session_id"] == "parent-session:node:a"
            assert details.workflow["nodes"]["b"]["session_id"] == "parent-session:node:b"
        details.workflow["nodes"]["a"]["state"] = "modified"
        details.workflow["plan"]["nodes"].clear()
    reader = SQLiteRunReader(path)
    restored = reader.diagnostics(handle.run_id)
    assert restored.workflow["nodes"]["a"]["state"] == "completed"
    assert len(restored.workflow["plan"]["nodes"]) == 2
    with local(SQLiteStore(path)) as native:
        assert native.diagnostics(handle.run_id) == restored


@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize("command", ["run", "resume"])
def test_configured_cli_run_and_resume_report_completed_nodes(tmp_path, capsys, limit, command):
    from relf_agent.cli import main

    path = tmp_path / "cli.sqlite"
    config = tmp_path / "runtime.json"
    declaration = {
        "name": "review",
        "version": "1",
        "providers": {"default": {"adapter": "offline-echo"}},
    }
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default": {"name": "review", "version": "1"},
                "profiles": [declaration],
            }
        )
    )
    spec = GraphWorkflowSpec(
        "graph",
        [
            GraphNode("a", transform="identity", input=Literal(1)),
            GraphNode("b", transform="identity", input=Literal(2)),
        ],
        max_concurrency=limit,
    )
    if command == "run":
        spec_path = tmp_path / "graph.json"
        spec_path.write_text(json.dumps(spec.to_dict()))
        arguments = ["run", "--spec", str(spec_path), "--input", "q", "--command-id", "s"]
    else:
        with profiled(path) as runtime:
            handle = runtime.submit(spec, "q", command_id="s")
        arguments = ["resume", handle.run_id]
    assert main(["--db", str(path), "--config", str(config), "--format", "text", *arguments]) == 0
    output = capsys.readouterr()
    assert not output.err
    assert "State: succeeded" in output.out
    assert "Node: a (completed)" in output.out
    assert "Node: b (completed)" in output.out
