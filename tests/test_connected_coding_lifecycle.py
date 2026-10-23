"""Connected Local lifecycle uses synthetic sources and a real structural peer."""

import asyncio
import copy
import json
import secrets

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, ToolRegistry
from relf_agent.codex_connected_runner import ConnectedCodexCodingRunner
from relf_agent.delegated_coding import register_coding_tool
from relf_agent.errors import DefinitionMismatch
from relf_agent.runner_journal import RunnerJournal
from relf_agent.storage import SQLiteStore
from tests.helpers import ScriptedProvider
from tests.test_connected_coding_loop import application, assert_no_key_files


class SyntheticCredentials:
    """Borrowed test source; count resolution separately from identity reads."""

    def __init__(self, key, mode="success"):
        self.key = key
        self.mode = mode
        self.generation = "1"
        self.calls = 0
        self.close_calls = 0
        self.connections = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False

    @property
    def identity(self):
        return {
            "kind": "synthetic-coding-credentials",
            "version": "1",
            "generation": self.generation,
        }

    async def resolve(self, connection):
        self.calls += 1
        self.connections.append(copy.deepcopy(connection))
        self.entered.set()
        if self.mode == "error":
            cause = RuntimeError(self.key)
            failure = RuntimeError({"credential": self.key})
            failure.credential = self.key
            raise failure from cause
        if self.mode == "invalid":
            return self.key + "\n"
        if self.mode == "drift":
            self.generation = "2"
        if self.mode == "blocked":
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self.key

    async def aclose(self):
        self.close_calls += 1


def synthetic_key():
    return "synthetic-lifecycle-" + secrets.token_hex(24)


async def approve_original_action(engine):
    handle = engine.submit(
        AgentSpec("connected", "connected", tools=("coding",)), {}, command_id="submit"
    )
    waiting = await engine.drive(handle.run_id)
    assert waiting.state == "waiting_approval"
    pending = waiting.pending[0]
    engine.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="approve")
    return handle.run_id


def coding_action(engine, run_id):
    return next(
        action for action in engine.store.run(run_id)["actions"] if action["kind"] == "tool"
    )


def assert_namespace_retired(tmp_path, runner):
    assert runner.active_operations == 0
    assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}


def assert_no_public_secret(tmp_path, engine, journal, run_id, key, error=None):
    evidence = [engine.store.run(run_id), engine.store.events(run_id)]
    evidence += [row[0] for row in journal.conn.execute("SELECT record FROM runner_effects")]
    if error is not None:
        seen = set()
        while error is not None and id(error) not in seen:
            seen.add(id(error))
            evidence += [str(error), repr(error), vars(error)]
            error = error.__cause__ or error.__context__
    assert key not in repr(evidence)
    assert_no_key_files(tmp_path, key)


@pytest.mark.parametrize("mode", ["error", "invalid"])
def test_source_failures_cannot_leak_exception_chain_or_start_native_business(tmp_path, mode):
    key = synthetic_key()
    source = SyntheticCredentials(key, mode)
    engine, runner, journal = application(tmp_path, source=source)

    async def scenario():
        run_id = await approve_original_action(engine)
        assert source.calls == 0
        result = await engine.drive(run_id)
        assert result.state == "waiting_reconciliation"
        action = coding_action(engine, run_id)
        assert len(action["attempts"]) == 1
        assert action["delegated_execution"]["fenced"] is True
        assert action["delegated_execution"]["pending_stop"] is False
        assert "result_candidate" not in action["delegated_execution"]
        assert source.calls == 1
        assert not (tmp_path / "auth-methods.txt").exists()
        assert not (tmp_path / "native-submissions.jsonl").exists()
        assert_namespace_retired(tmp_path, runner)
        assert_no_public_secret(tmp_path, engine, journal, run_id, key)
        await runner.aclose()
        await runner.aclose()
        assert source.calls == 1
        assert source.close_calls == 0

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()


@pytest.mark.parametrize("stop", ["caller_cancel", "runner_close"])
def test_cancelled_resolution_retires_original_owner_without_auth_or_reread(tmp_path, stop):
    key = synthetic_key()
    source = SyntheticCredentials(key, "blocked")
    engine, runner, journal = application(tmp_path, source=source)

    async def scenario():
        run_id = await approve_original_action(engine)
        driving = asyncio.create_task(engine.drive(run_id))
        async with asyncio.timeout(5):
            await source.entered.wait()
        assert source.calls == 1
        assert not (tmp_path / "auth-methods.txt").exists()
        engine.cancel(run_id, command_id="cancel")
        if stop == "caller_cancel":
            driving.cancel()
        else:
            await runner.aclose(wait_timeout=5)
        with pytest.raises(asyncio.CancelledError) as caught:
            await driving
        # Local drive cancellation preserves an owned underlying tool operation;
        # the original explicit resource close settles its borrowed source.
        await runner.aclose(wait_timeout=5)
        assert source.cancelled is True
        assert_namespace_retired(tmp_path, runner)
        assert not (tmp_path / "auth-methods.txt").exists()
        assert not (tmp_path / "native-submissions.jsonl").exists()
        assert (await engine.drive(run_id)).state == "cancelled"
        action = coding_action(engine, run_id)
        assert len(action["attempts"]) == 1
        assert action["delegated_execution"]["fenced"] is True
        assert "result_candidate" not in action["delegated_execution"]
        assert_no_public_secret(tmp_path, engine, journal, run_id, key, caught.value)
        await runner.aclose()
        assert source.calls == 1
        assert source.close_calls == 0

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()


def test_cold_reconciliation_and_close_never_resolve_credentials_or_repeat_login(tmp_path):
    key = synthetic_key()
    source = SyntheticCredentials(key)
    engine, runner, journal = application(tmp_path, mode="echo", source=source)
    cold_engine = cold_runner = cold_journal = None

    async def initial():
        run_id = await approve_original_action(engine)
        assert (await engine.drive(run_id)).state == "waiting_reconciliation"
        assert source.calls == 1
        assert_namespace_retired(tmp_path, runner)
        await runner.aclose()
        assert source.calls == 1 and source.close_calls == 0
        return run_id

    try:
        run_id = asyncio.run(initial())
        identity = runner.identity
        auth_before = (tmp_path / "auth-methods.txt").read_text()
        assert auth_before.splitlines() == ["account/read", "account/login/start"]
        assert not (tmp_path / "native-submissions.jsonl").exists()
        engine.close()
        journal.close()
        cold_source = SyntheticCredentials(key, "error")
        cold_journal = RunnerJournal(
            str(tmp_path / "native.sqlite"), identity={"fixture": "connected-loop"}
        )
        cold_runner = ConnectedCodexCodingRunner(
            tmp_path / "coding",
            connection=runner._connection,
            credential_source=cold_source,
            journal=cold_journal,
            docker_executable=runner._docker,
            docker_host="unix:///fixture/docker.sock",
            request_timeout=identity["request_timeout"],
        )
        assert cold_runner.identity == identity
        tools = ToolRegistry()
        register_coding_tool(tools, cold_runner)
        cold_engine = LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            tools=tools,
            providers={"default": ScriptedProvider([ModelResponse(output="complete")])},
        )

        async def recover():
            assert (await cold_engine.drive(run_id)).state == "waiting_reconciliation"
            assert (await cold_engine.drive(run_id)).state == "waiting_reconciliation"
            assert cold_source.calls == 0
            assert (tmp_path / "auth-methods.txt").read_text() == auth_before
            assert not (tmp_path / "native-submissions.jsonl").exists()
            assert len(coding_action(cold_engine, run_id)["attempts"]) == 1
            assert_namespace_retired(tmp_path, cold_runner)
            assert_no_public_secret(tmp_path, cold_engine, cold_journal, run_id, key)
            await cold_runner.aclose()
            await cold_runner.aclose()
            assert cold_source.calls == 0
            assert cold_source.close_calls == 0

        asyncio.run(recover())
    finally:
        if cold_journal is not None:
            cold_journal.close()
        if cold_engine is not None:
            cold_engine.close()
        else:
            engine.close()
            journal.close()


def test_source_identity_drift_after_resolution_refuses_auth_and_native_business(tmp_path):
    key = synthetic_key()
    source = SyntheticCredentials(key, "drift")
    engine, runner, journal = application(tmp_path, source=source)

    async def scenario():
        run_id = await approve_original_action(engine)
        try:
            result = await engine.drive(run_id)
            assert result.state == "cancelling"
            with pytest.raises(DefinitionMismatch) as caught:
                _ = runner.identity
            assert source.calls == 1
            assert not (tmp_path / "auth-methods.txt").exists()
            assert not (tmp_path / "native-submissions.jsonl").exists()
            assert_no_public_secret(tmp_path, engine, journal, run_id, key, caught.value)
            assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}
            # The changed source cannot authorize adopting the original stop
            # receipt. Physical retirement has completed, while its owner stays
            # available to retry the receipt after dependency repair.
            assert runner.active_operations == 1
            assert coding_action(engine, run_id)["delegated_execution"]["pending_stop"] is True
        finally:
            # Restore the test source identity so retained receipt ownership can
            # settle through the original Runner, without changing product code.
            source.generation = "1"
            await runner.aclose(wait_timeout=5)
        assert source.calls == 1
        assert source.close_calls == 0
        assert_namespace_retired(tmp_path, runner)

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()


def test_completed_connection_resolves_once_and_close_leaves_source_borrowed(tmp_path):
    key = synthetic_key()
    source = SyntheticCredentials(key)
    engine, runner, journal = application(tmp_path, source=source)

    async def scenario():
        run_id = await approve_original_action(engine)
        assert source.calls == 0
        assert (await engine.drive(run_id)).state == "succeeded"
        assert source.calls == 1
        assert (tmp_path / "auth-methods.txt").read_text().splitlines() == [
            "account/read",
            "account/login/start",
            "account/read",
        ]
        assert [
            json.loads(line)["method"]
            for line in (tmp_path / "native-submissions.jsonl").read_text().splitlines()
        ] == ["thread/start", "turn/start"]
        assert_namespace_retired(tmp_path, runner)
        assert_no_public_secret(tmp_path, engine, journal, run_id, key)
        await runner.aclose()
        await runner.aclose()
        assert source.calls == 1
        assert source.close_calls == 0

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()
