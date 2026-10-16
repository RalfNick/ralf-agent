"""One original scoped mechanical identity, with repeatable recovery hints."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope, TemporalRuntime
from ralf_agent.errors import IdempotencyConflict, RalfError
from ralf_agent.temporal import TemporalEngine
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow, workflow
from ralf_agent.temporal_state import TemporalCommandRegistryState
from ralf_agent.types import digest, submission_request
from tests.test_temporal_engine import Provider, registry
from tests.test_temporal_scoped_reservation import SCOPE, request


def hint(state, target="original-run"):
    return state.scoped_drive_command({"scope": SCOPE, "target": target})


def test_full_scoped_registry_protects_one_original_drive_and_cancel_without_eviction():
    state = TemporalCommandRegistryState(SCOPE, capacity=1)
    state.reserve(request())
    before = copy.deepcopy(vars(state))
    selected = hint(state)
    assert vars(state) == before
    wake = request("drive", selected["command_id"])
    first = state.reserve(wake)
    for _ in range(5):
        assert state.reserve(wake) == first and hint(state) == selected
    state.reserve(request("cancel", "stop"))
    assert len(state.identities) == 3
    for other in (
        request("drive", "arbitrary"),
        request("drive", "foreign", "unsubmitted"),
        {**wake, "command_id": "extra", "payload_digest": "a" * 64},
        request("submit", "new"),
    ):
        before = copy.deepcopy(vars(state))
        with pytest.raises(RalfError):
            state.reserve(other)
        assert vars(state) == before


def test_original_collision_is_preserved_and_hint_remains_scope_bound():
    state = TemporalCommandRegistryState(SCOPE, capacity=2)
    state.reserve(request())
    canonical = "drive:" + digest([SCOPE, "original-run"])
    old = state.reserve(request("cancel", canonical))
    selected = hint(state)
    assert selected["command_id"] != canonical
    with pytest.raises(IdempotencyConflict):
        state.reserve(request("drive", canonical))
    state.reserve(request("drive", selected["command_id"]))
    assert hint(state) == selected and state.reserve(request("cancel", canonical)) == old
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        state.scoped_drive_command({"scope": {**SCOPE, "principal": "other"}, "target": "x"})
    assert vars(state) == before


@pytest.mark.parametrize("patched", [False, True])
def test_default_parent_repeated_wake_retries_recovery_only_with_history_patch(
    monkeypatch, patched
):
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    manifest = runtime.orchestration_release
    definition = GraphWorkflowSpec("g", [GraphNode("a", agent=AgentSpec("a", "answer"))])
    state = TemporalParentState(
        "parent", SCOPE, "submit", submission_request(definition, "task"), manifest
    )
    node = object.__new__(TemporalParentWorkflow)
    node.state, node.wake_revision = state, 0
    forced = []
    node._deployment_force_child_reads = lambda: forced.append(True)
    patches = []
    monkeypatch.setattr(workflow, "patched", lambda value: patches.append(value) or patched)
    payload = {"command_id": "wake", "payload": {"kind": "drive", "scope": SCOPE}}

    async def run():
        first = await node.command(payload)
        before = state.memory_recovery_revision
        state.state = "cancelling"
        assert await node.command(payload) == first
        assert state.memory_recovery_revision == before + int(
            patched and manifest["kernel"] == "temporal-3"
        )
        assert state.state == "cancelling" and len(forced) == 1 + int(patched)
        assert node.wake_revision == 2

    asyncio.run(run())
    assert patches == ["ralf-scoped-parent-repeat-drive-v1"]


@pytest.mark.parametrize("legacy", [False, True])
def test_sdk_uses_authority_selected_drive_identity_or_preserves_legacy_behavior(legacy):
    state = TemporalCommandRegistryState(SCOPE, capacity=1)
    state.reserve(request())
    calls = []

    class Handle:
        async def query(self, name, value):
            assert name == "view" and value["kind"] == "scoped_drive_command"
            if legacy:
                return {"scope": SCOPE, "capacity": 4096, "accepted_commands": 1}
            return hint(state, value["target"])

    class Engine(TemporalEngine):
        def __init__(self):
            self.scope, self._release, self.drive_timeout = Scope(**SCOPE), {}, 0
            self.client = SimpleNamespace(
                namespace="default", get_workflow_handle=lambda _: Handle()
            )
            self._registry, self._closed = None, False

        async def _command(self, run_id, kind, command_id, **values):
            calls.append(command_id)
            if not legacy:
                state.reserve(request(kind, command_id, run_id))

        async def diagnostics(self, run_id):
            return SimpleNamespace(
                snapshot=SimpleNamespace(state="waiting_approval"),
                workflow={"reconciliation_pending": False, "evidence_ack_pending": False},
            )

    async def run():
        engine = Engine()
        for _ in range(3):
            await engine.drive("original-run", wait_seconds=0)

    asyncio.run(run())
    assert len(set(calls)) == (3 if legacy else 1)
    if not legacy:
        assert len(state.identities) == 2


@pytest.mark.parametrize("fault", ["extra", "scope", "target", "id", "version", "unknown"])
def test_bad_drive_suggestion_never_becomes_a_command(fault):
    from ralf_agent.temporal_scoped_reservation import drive_command

    class Handle:
        async def query(self, *args):
            value = {
                "version": 1,
                "scope": copy.deepcopy(SCOPE),
                "target": "original-run",
                "command_id": "drive:" + "a" * 64,
            }
            if fault == "extra":
                value["extra"] = True
            elif fault == "scope":
                value["scope"]["principal"] = "other"
            elif fault == "target":
                value["target"] = "other"
            elif fault == "id":
                value["command_id"] = "unbounded-business-command"
            elif fault == "version":
                value["version"] = True
            elif fault == "unknown":
                value = None
            return value

    async def run():
        engine = SimpleNamespace(scope=Scope(**SCOPE), _registry=Handle(), _closed=False)
        with pytest.raises(RalfError):
            await drive_command(engine, "original-run")

    asyncio.run(run())


def test_repeated_parent_wake_recovers_same_unknown_root_save_after_two_failures(monkeypatch):
    from tests.test_temporal_parent_session import apply_save, parent, prepare_read

    state, session, store = parent()
    prepare_read(state, session, store)
    state.accept_selection({"calls": [], "done": True, "result": "answer"})
    aggregate = copy.deepcopy(state.root_aggregate)
    node = object.__new__(TemporalParentWorkflow)
    node.state, node.wake_revision = state, 0
    node._deployment_force_child_reads = lambda: None
    monkeypatch.setattr(workflow, "patched", lambda _: True)
    payload = {"command_id": "same-wake", "payload": {"kind": "drive", "scope": state.scope}}

    async def run():
        for _ in range(2):
            action, _ = state.next_session_operation()
            state.accept_session(
                action["id"],
                {"ok": False, "code": "temporary-inspection-failure", "dispatched": False},
            )
            assert state.state != "succeeded" and not state.quiescent
            await node.command(payload)
        for _ in range(4):
            apply_save(state, store)
        assert state.state == "succeeded" and state.quiescent
        assert state.root_aggregate == aggregate
        assert store.read(Scope(), session.key.storage_key)[0] == 1
        assert len([r for r in state.receipts.values() if r["kind"] == "drive"]) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "target,closed", [("original-run", True), (None, False), ("", False), (42, False)]
)
def test_drive_rejects_closed_or_invalid_target_before_registry_io(target, closed):
    class Client:
        def get_workflow_handle(self, *args):
            pytest.fail("closed or malformed controls must not perform I/O")

    async def run():
        engine = object.__new__(TemporalEngine)
        engine.scope, engine._release = Scope(**SCOPE), {}
        engine.client, engine._registry, engine._closed = Client(), None, False
        if closed:
            await engine.aclose()
        with pytest.raises(RalfError) as rejected:
            await engine.drive(target, wait_seconds=0)
        assert rejected.value.code == "validation_error"

    asyncio.run(run())


def test_failed_success_wait_still_discovers_actual_abandoned_child_tree():
    from temporalio.api.history.v1 import HistoryEvent

    from tests.test_temporal_scoped_capacity_service import discover_owned_descendants

    def started(child):
        event = HistoryEvent()
        event.start_child_workflow_execution_initiated_event_attributes.workflow_id = child
        return event

    histories = {"root": [started("child")], "child": [started("grandchild")], "grandchild": []}

    class Client:
        def get_workflow_handle(self, target):
            async def fetch_history():
                return SimpleNamespace(events=histories[target])

            return SimpleNamespace(fetch_history=fetch_history)

    async def run():
        owned = {"root"}  # The body's wait failed before recording its child.
        await discover_owned_descendants(Client(), owned)
        assert owned == {"root", "child", "grandchild"}

    asyncio.run(run())


@pytest.mark.parametrize("missing", [False, True])
def test_empty_scope_drive_preserves_not_found_and_other_sdk_errors(missing):
    from temporalio.service import RPCError, RPCStatusCode

    from ralf_agent.errors import NotFound

    original = RPCError(
        "original SDK failure",
        RPCStatusCode.NOT_FOUND if missing else RPCStatusCode.UNAVAILABLE,
        b"",
    )

    class Handle:
        async def query(self, *args):
            raise original

        async def signal(self, *args):
            pytest.fail("missing or unavailable Registry must not trigger a write")

        async def execute_update(self, *args):
            pytest.fail("unknown Registry outcome must not switch transport")

    async def run():
        engine = object.__new__(TemporalEngine)
        engine.scope, engine._release, engine._closed = Scope(**SCOPE), {}, False
        engine._registry = None
        engine.client = SimpleNamespace(get_workflow_handle=lambda _: Handle())
        with pytest.raises(NotFound if missing else RPCError) as rejected:
            await engine.drive("missing-run", wait_seconds=0)
        if not missing:
            assert rejected.value is original

    asyncio.run(run())
