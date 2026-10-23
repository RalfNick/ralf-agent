import asyncio
from types import SimpleNamespace

import pytest

from relf_agent import AgentSpec, Scope
from relf_agent.errors import IdempotencyConflict
from relf_agent.temporal_session_client import TemporalSessionClient
from relf_agent.temporal_session_state import TemporalSessionState, workflow_id
from relf_agent.types import digest
from tests.test_temporal_sessions import session


class Transport:
    def __init__(self, release):
        self.states, self.registered = {}, {}
        self.scope, self.release = Scope(), release
        self.task_queue, self.activity_timeout = "queue", 10
        self.client = self
        self.namespace = "default"
        self.service_client = SimpleNamespace(
            config=SimpleNamespace(target_host="session.test:7233")
        )
        self.on_guard = None
        self.started = []

    async def _guard(self, kind, command, target, payload):
        identity = digest([kind, target, payload])
        if command in self.registered and self.registered[command] != identity:
            raise IdempotencyConflict("Different original command")
        self.registered[command] = identity
        if self.on_guard:
            self.on_guard()

    async def start_workflow(self, name, value, **options):
        self.started.append(options["id"])
        if options["id"] in self.states:
            from temporalio.exceptions import WorkflowAlreadyStartedError

            raise WorkflowAlreadyStartedError(options["id"], name)
        self.states[options["id"]] = TemporalSessionState(value)

    def _handle(self, target):
        async def describe():
            from temporalio.service import RPCError, RPCStatusCode

            if target not in self.states:
                raise RPCError("Session not found", RPCStatusCode.NOT_FOUND, b"")
            return SimpleNamespace()

        async def update(name, value):
            if name == "start_receipt":
                self.states[target].mark_started()
                return {"run_id": value["run_id"], "started": True}
            return self.states[target].command(value)

        return SimpleNamespace(execute_update=update, describe=describe)


def test_conflicting_open_does_not_create_or_pin_session():
    async def run():
        _, runtime = session()
        engine = Transport(runtime.manifest)
        engine.registered["used"] = "another-run"
        client = TemporalSessionClient(engine, "namespace-uuid")
        with pytest.raises(IdempotencyConflict):
            await client.open(AgentSpec("answer", "Failed binding"), "chat", command_id="used")
        assert engine.states == {}
        receipt = await client.open(
            AgentSpec("answer", "Correct binding"), "chat", command_id="new"
        )
        assert receipt.apply_state == "applied"
        assert len(engine.states) == 1

    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["definition", "command"])
def test_invalid_open_is_refused_before_registry_and_workflow_creation(invalid):
    from relf_agent import GraphNode, GraphWorkflowSpec
    from relf_agent.errors import ValidationError

    async def run():
        _, runtime = session()
        engine = Transport(runtime.manifest)
        client = TemporalSessionClient(engine, "namespace-uuid")
        spec = AgentSpec("answer", "Answer")
        definition = (
            GraphWorkflowSpec("graph", [GraphNode("a", agent=spec)])
            if invalid == "definition"
            else spec
        )
        command = "x" * 1025 if invalid == "command" else "open"
        with pytest.raises(ValidationError):
            await client.open(definition, "chat", command_id=command)
        assert not engine.started and not engine.states and not engine.registered

    asyncio.run(run())


def test_existing_open_replays_original_receipt_after_old_provider_is_unavailable():
    async def run():
        _, runtime = session()
        engine = Transport(runtime.manifest)
        client = TemporalSessionClient(engine, "namespace-uuid")
        spec = AgentSpec("answer", "Answer")
        first = await client.open(spec, "chat", command_id="open")
        engine.release = {**engine.release, "providers": {"renamed": {"kind": "new"}}}
        replay = await client.open(spec, "chat", command_id="open")
        assert replay == first and len(engine.states) == 1
        assert (
            next(iter(engine.states.values())).binding["manifest"]["providers"]
            == runtime.manifest["providers"]
        )

    asyncio.run(run())


def test_cancelled_submit_keeps_frozen_intent_owned_until_runtime_detach(monkeypatch):
    from relf_agent import Runtime
    from relf_agent.temporal import TemporalEngine
    from relf_agent.temporal_state import TemporalRunState
    from relf_agent.types import RunDiagnostics, RunSnapshot

    async def run():
        _, execution = session()
        transport = Transport(execution.manifest)
        engine = TemporalEngine(transport, task_queue="queue", release=execution.manifest)
        engine._guard, engine._handle = transport._guard, transport._handle

        async def diagnostics(run_id):
            state = next(s for s in transport.states.values() if s.active["run_id"] == run_id)
            intent = state.active
            proof = TemporalRunState(
                run_id, state.scope, intent["command_id"], intent["request"], intent["manifest"]
            ).diagnostics()
            return RunDiagnostics(**{**proof, "snapshot": RunSnapshot(**proof["snapshot"])})

        engine.diagnostics = diagnostics
        entered, release = asyncio.Event(), asyncio.Event()
        release.set()

        async def namespace_id(client):
            entered.set()
            await release.wait()
            return "namespace-uuid"

        monkeypatch.setattr("relf_agent.temporal_session_activities.namespace_id", namespace_id)
        runtime = Runtime.from_temporal(engine)
        entry = await runtime.open_session(AgentSpec("answer", "Answer"), "chat", command_id="open")
        entered.clear()
        release.clear()
        value = {"task": "original"}
        observer = asyncio.create_task(entry.submit(value, command_id="turn"))
        await entered.wait()
        value["task"] = "changed"
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        closing = asyncio.create_task(runtime.aclose())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await closing
        state = next(iter(transport.states.values()))
        assert state.active["request"]["input"] == {"task": "original"}
        assert state.snapshot()["busy"]
        assert state.started_runs == {state.active["run_id"]}
        assert not engine._closed  # Borrowed backend stays available.
        await engine.aclose()

    asyncio.run(run())


def test_registered_and_accepted_payload_remain_identical_across_await():
    async def run():
        state, runtime = session()
        engine = Transport(runtime.manifest)
        engine.states[workflow_id(state.key)] = state
        client = TemporalSessionClient(engine, "namespace-uuid")
        value = {"task": "original"}
        payload = {
            "kind": "submit",
            "scope": state.scope,
            "command_id": "turn",
            "session_ref": state.ref.to_dict(),
            "input": value,
            "budget": 8,
        }
        engine.on_guard = lambda: value.update(task="changed")
        first = await client.command(state.key, payload)
        assert state.active["request"]["input"] == {"task": "original"}
        engine.on_guard = None
        payload["input"] = {"task": "original"}
        replay = await client.command(state.key, payload)
        assert replay == first

    asyncio.run(run())
