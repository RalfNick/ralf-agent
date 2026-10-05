import asyncio
import threading
from contextlib import closing

import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.context import ContextAssembler
from ralf_agent.errors import CoordinatorBusy, DefinitionMismatch, ValidationError

from .helpers import ScriptedProvider


class StoreAdapter:
    """An actual SQLite authority behind a port without SQL/connection/path access."""

    _methods = {
        "transaction",
        "command",
        "insert_run",
        "run",
        "save_run",
        "emit",
        "events",
        "create_budget",
        "budget",
        "reserve",
        "mark_unknown",
        "settle",
        "session_owner",
        "unresolved_effect",
        "close",
    }

    def __init__(self, path):
        self._backend = SQLiteStore(path)

    def __getattr__(self, name):
        if name not in self._methods:
            raise AttributeError(name)
        return getattr(self._backend, name)


class HostCoordinator:
    def __init__(self):
        self.owned = False

    def acquire(self):
        self.owned = True

    def release(self):
        self.owned = False


def test_execution_adapter_does_not_need_a_sqlite_connection_or_path(tmp_path):
    store = StoreAdapter(tmp_path / "execution.db")
    lease = HostCoordinator()
    memory = InMemoryMemory(backend_id="host:memory:1")
    with LocalEngine(
        store,
        coordinator=lease,
        session_store=memory,
        memory_store=memory,
        providers={"default": ScriptedProvider([ModelResponse(output="done")])},
        tools=ToolRegistry(),
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s", session_id="shared")
        with pytest.raises(ValidationError):
            runtime.submit(AgentSpec("a", "x"), "other", command_id="other", session_id="shared")
        assert asyncio.run(runtime.drive(run.run_id)).result == "done"
        assert lease.owned
    assert not lease.owned


def test_invalid_custom_provider_is_rejected_before_accepting_a_run(tmp_path):
    class SyncProvider:
        identity = {"kind": "sync-invalid", "version": "1"}

        def complete(self, messages, tools):
            pytest.fail("A configuration error must never dispatch a model call")

    with LocalEngine(
        SQLiteStore(tmp_path / "provider.db"),
        providers={"default": SyncProvider()},
        tools=ToolRegistry(),
    ) as runtime:
        with pytest.raises(ValidationError):
            runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
        assert runtime.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_custom_context_policy_is_used_and_pinned_on_recovery(tmp_path):
    class EvidenceContext(ContextAssembler):
        identity = {"kind": "host-evidence", "version": "1"}

        def assemble(self, history, references, max_chars):
            history = [*history[:2], {"role": "user", "content": "Host-selected evidence"}]
            return super().assemble(history, references, max_chars)

    path = tmp_path / "context.db"
    provider = ScriptedProvider([ModelResponse(output="done")])
    with LocalEngine(
        SQLiteStore(path),
        providers={"default": provider},
        tools=ToolRegistry(),
        context_assembler=EvidenceContext(),
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
    with LocalEngine(
        SQLiteStore(path),
        providers={"default": provider},
        tools=ToolRegistry(),
    ) as runtime:
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(run.run_id))
    with LocalEngine(
        SQLiteStore(path),
        providers={"default": provider},
        tools=ToolRegistry(),
        context_assembler=EvidenceContext(),
    ) as runtime:
        assert asyncio.run(runtime.drive(run.run_id)).state == "succeeded"
        assert provider.messages[0][-1]["content"] == "Host-selected evidence"


def test_async_memory_does_not_block_cancellation_or_other_agents(tmp_path):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()

        class RemoteMemory:
            backend_id = "remote-memory:1"

            async def read(self, scope, session_id):
                started.set()
                await release.wait()
                return 0, []

            async def append(self, *args, **kwargs):
                return 1

            async def facts(self, scope, namespace):
                return []

        remote = RemoteMemory()
        provider = ScriptedProvider([ModelResponse(output="done")])
        with LocalEngine(
            SQLiteStore(tmp_path / "remote.db"),
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=remote,
            memory_store=remote,
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            try:
                await asyncio.wait_for(started.wait(), 1)
                runtime.cancel(run.run_id, command_id="c")
                assert runtime.status(run.run_id).state == "cancelling"
                assert provider.calls == 0
            finally:
                release.set()
                await drive
            assert runtime.status(run.run_id).state == "cancelled"
            assert provider.calls == 0

    asyncio.run(exercise())


def test_memory_backend_failure_is_a_typed_run_failure(tmp_path):
    class UnavailableMemory(InMemoryMemory):
        def facts(self, scope, namespace):
            raise ConnectionError("do not persist backend connection secrets")

    with LocalEngine(
        SQLiteStore(tmp_path / "unavailable.db"),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
        memory_store=UnavailableMemory(),
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "failed"
        assert snapshot.error == {"code": "memory_backend_error"}
        assert runtime.store.budget(run.run_id) == {"limit": 32, "held": 0, "spent": 0}


def test_symlink_database_alias_cannot_acquire_a_second_coordinator(tmp_path):
    path, alias = tmp_path / "actual.db", tmp_path / "alias.db"
    with LocalEngine(SQLiteStore(path), providers={}, tools=ToolRegistry()):
        alias.symlink_to(path)
        with SQLiteStore(alias) as store:
            with pytest.raises(CoordinatorBusy):
                second = LocalEngine(store, providers={}, tools=ToolRegistry())
                second.close()


def test_provider_change_during_async_context_read_never_dispatches(tmp_path):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()

        class RemoteFacts:
            backend_id = "remote:stable"

            async def facts(self, *args):
                started.set()
                await release.wait()
                return []

        provider = ScriptedProvider([ModelResponse(output="wrong definition")])
        with LocalEngine(
            SQLiteStore(tmp_path / "changed.db"),
            providers={"default": provider},
            tools=ToolRegistry(),
            memory_store=RemoteFacts(),
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 1)
            provider.identity = {"kind": "changed-provider", "version": "2"}
            release.set()
            snapshot = await drive
            assert snapshot.state == "failed"
            assert snapshot.error == {"code": "definition_mismatch"}
            assert provider.calls == 0
            assert runtime.store.budget(run.run_id) == {"limit": 32, "held": 0, "spent": 0}

    asyncio.run(exercise())


def test_cancel_during_async_final_read_does_not_start_a_session_write(tmp_path):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()

        class RemoteSession:
            backend_id = "remote:session"

            def __init__(self):
                self.reads = 0
                self.messages = []

            async def read(self, *args):
                self.reads += 1
                if self.reads == 2:
                    started.set()
                    await release.wait()
                return 0, []

            async def append(self, scope, session_id, message, **kwargs):
                self.messages.append(message)
                return 1

        sessions = RemoteSession()
        with LocalEngine(
            SQLiteStore(tmp_path / "final.db"),
            providers={"default": ScriptedProvider([ModelResponse(output="cancelled answer")])},
            tools=ToolRegistry(),
            session_store=sessions,
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s", session_id="shared")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 1)
            runtime.cancel(run.run_id, command_id="c")
            release.set()
            assert (await drive).state == "cancelled"
            assert sessions.messages == []

    asyncio.run(exercise())


def test_threaded_memory_replacement_invalidates_the_pinned_backend(tmp_path):
    from ralf_agent import ThreadedMemoryAdapter

    memory = ThreadedMemoryAdapter(InMemoryMemory(backend_id="remote:first"))
    with LocalEngine(
        SQLiteStore(tmp_path / "replaced.db"),
        providers={"default": ScriptedProvider([ModelResponse(output="wrong memory")])},
        tools=ToolRegistry(),
        memory_store=memory,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
        memory.backend = InMemoryMemory(backend_id="remote:second")
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(run.run_id))


def test_threaded_remote_memory_yields_to_the_coordinator(tmp_path):
    from ralf_agent import ThreadedMemoryAdapter

    async def exercise():
        started, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        class BlockingMemory(InMemoryMemory):
            timed_out = False

            def read(self, *args):
                loop.call_soon_threadsafe(started.set)
                self.timed_out = not release.wait(1)
                return super().read(*args)

        backend = BlockingMemory(backend_id="blocking:remote")
        provider = ScriptedProvider([])
        with LocalEngine(
            SQLiteStore(tmp_path / "threaded.db"),
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=ThreadedMemoryAdapter(backend),
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            try:
                await asyncio.wait_for(started.wait(), 2)
                assert not backend.timed_out
                runtime.cancel(run.run_id, command_id="c")
            finally:
                release.set()
                await drive
            assert runtime.status(run.run_id).state == "cancelled"
            assert provider.calls == 0

    asyncio.run(exercise())


def test_independent_sqlite_memory_backends_cannot_silently_replace_each_other(tmp_path):
    from ralf_agent import SQLiteMemory

    path = tmp_path / "identity.db"
    with closing(SQLiteMemory(":memory:")) as first, closing(SQLiteMemory(":memory:")) as second:
        with LocalEngine(
            SQLiteStore(path),
            providers={"default": ScriptedProvider([])},
            tools=ToolRegistry(),
            memory_store=first,
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
        with LocalEngine(
            SQLiteStore(path),
            providers={"default": ScriptedProvider([ModelResponse(output="wrong")])},
            tools=ToolRegistry(),
            memory_store=second,
        ) as runtime:
            with pytest.raises(DefinitionMismatch):
                asyncio.run(runtime.drive(run.run_id))


@pytest.mark.parametrize("identity", [None, [], {}])
def test_invalid_context_configuration_releases_its_coordinator(tmp_path, identity):
    class InvalidContext(ContextAssembler):
        pass

    context = InvalidContext()
    context.identity = identity
    lease = HostCoordinator()
    with SQLiteStore(tmp_path / "initialization.db") as store:
        with pytest.raises(ValidationError):
            LocalEngine(
                store,
                providers={},
                tools=ToolRegistry(),
                coordinator=lease,
                context_assembler=context,
            )
        assert not lease.owned


def test_caller_cancellation_keeps_async_memory_save_owned_until_it_finishes(tmp_path):
    async def exercise():
        started, release, saved = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class RemoteSession:
            backend_id = "remote:save"
            messages = []

            async def read(self, *args):
                return 0, []

            async def append(self, scope, session_id, message, **kwargs):
                started.set()
                await release.wait()
                self.messages.append(message)
                saved.set()
                return 1

        sessions = RemoteSession()
        with LocalEngine(
            SQLiteStore(tmp_path / "saving.db"),
            providers={"default": ScriptedProvider([ModelResponse(output="done")])},
            tools=ToolRegistry(),
            session_store=sessions,
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 1)
            drive.cancel()
            with pytest.raises(asyncio.CancelledError):
                await drive
            with pytest.raises(ValidationError):
                runtime.close()
            release.set()
            await asyncio.wait_for(saved.wait(), 1)
            assert (await runtime.drive(run.run_id)).state == "cancelled"
            assert len(sessions.messages) == 1

    asyncio.run(exercise())
