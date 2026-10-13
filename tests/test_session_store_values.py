import asyncio
import importlib

import pytest

from ralf_agent import AgentSpec, InMemoryMemory, LocalEngine, SQLiteStore, ToolRegistry
from ralf_agent.errors import ValidationError


def api():
    return importlib.import_module("ralf_agent.session_store_values")


@pytest.mark.parametrize(
    "value",
    [
        None,
        [0, []],
        (0,),
        (0, [], None),
        (True, []),
        (0.0, []),
        (-1, []),
        (0, {}),
        (0, None),
        (1, [[]]),
        (1, ["message"]),
        (1, [{"value": float("nan")}]),
    ],
)
def test_read_refuses_malformed_completed_values(value):
    with pytest.raises(ValidationError):
        api().session_read_value(value)


def test_read_detaches_finite_dictionary_messages():
    original = (1, [{"role": "assistant", "content": {"items": ["中文🙂", True, None]}}])
    revision, messages = api().session_read_value(original)
    messages[0]["content"]["items"].append("caller")
    assert revision == 1 and original[1][0]["content"]["items"] == ["中文🙂", True, None]


@pytest.mark.parametrize("value", [None, True, 1.0, 0, -1, 4, [], {}])
def test_append_refuses_noninteger_or_impossible_revision(value):
    with pytest.raises(ValidationError):
        api().session_append_revision(value, 2)


@pytest.mark.parametrize("value", [1, 2, 3])
def test_append_preserves_historical_duplicate_revision(value):
    assert api().session_append_revision(value, 2) == value


def test_lazy_read_and_ack_are_closed_without_entering_them():
    async def deferred():
        pytest.fail("must not enter deferred adapter work")

    read, ack = deferred(), deferred()
    with pytest.raises(ValidationError):
        api().session_read_value(read)
    with pytest.raises(ValidationError):
        api().session_append_revision(ack, 0)
    assert read.cr_frame is ack.cr_frame is None


class NeverProvider:
    identity = {"kind": "session-output-test", "version": "1"}
    calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        pytest.fail("private output validation cannot require a model request")


class MalformedStore:
    backend_id = "malformed-session-output"

    def __init__(self, value=(0, []), ack=1):
        self.value, self.ack, self.append_calls = value, ack, 0

    def read(self, scope, session_id):
        return self.value

    def append(self, *args, **kwargs):
        self.append_calls += 1
        return self.ack


@pytest.mark.parametrize(
    "value",
    [
        (True, []),
        (0.0, []),
        (-1, []),
        [0, []],
        (1, [[]]),
        (0, None),
        (1, [{"content": float("nan")}]),
    ],
)
def test_original_local_consumer_rejects_read_before_adoption(tmp_path, value):
    async def run():
        provider, sessions = NeverProvider(), MalformedStore(value)
        engine = LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=sessions,
        )
        try:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="c")
            recorded = engine.store.run(handle.run_id)
            with pytest.raises(ValidationError):
                await engine._load_references(recorded, engine._agent_step(recorded))
            with pytest.raises(ValidationError):
                await engine._finish_node(handle.run_id, "result")
            assert provider.calls == sessions.append_calls == 0
            assert engine.status(handle.run_id).state != "succeeded"
        finally:
            await engine.wait_for_threads()
            engine.close()

    asyncio.run(run())


@pytest.mark.parametrize("ack", [True, 1.0, None, -1, 9000])
def test_original_local_consumer_cannot_succeed_on_malformed_ack(tmp_path, ack):
    async def run():
        provider, sessions = NeverProvider(), MalformedStore(ack=ack)
        engine = LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=sessions,
        )
        try:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="c")
            with pytest.raises(ValidationError):
                await engine._finish_node(handle.run_id, "result")
            assert provider.calls == 0 and sessions.append_calls == 1
            assert engine.status(handle.run_id).state != "succeeded"
        finally:
            await engine.wait_for_threads()
            engine.close()

    asyncio.run(run())


def test_original_local_replay_accepts_lower_original_revision_and_keeps_manifest(tmp_path):
    async def run():
        sessions, provider = InMemoryMemory(), NeverProvider()
        engine = LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=sessions,
        )
        try:
            handle = engine.submit(AgentSpec("a", "Answer"), "task", command_id="c", session_id="s")
            recorded = engine.store.run(handle.run_id)
            sessions.append(
                engine.scope,
                "s",
                {"role": "assistant", "content": "result", "agent": "a", "task": "task"},
                expected_revision=0,
                message_id=handle.run_id + ":0:result",
            )
            sessions.append(
                engine.scope, "s", {"content": "later"}, expected_revision=1, message_id="later"
            )
            await engine._finish_node(handle.run_id, "result")
            assert engine.status(handle.run_id).state == "succeeded"
            assert sessions.read(engine.scope, "s")[0] == 2 and provider.calls == 0
            assert recorded["manifest"] == engine._manifest(recorded["definition"]["steps"])
        finally:
            await engine.wait_for_threads()
            engine.close()

    asyncio.run(run())
