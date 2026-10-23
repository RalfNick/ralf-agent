"""A retired original Turn wakes Session without coupling its notification debt."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent import temporal_deployment_execution_state as admission
from relf_agent import temporal_deployment_release_state as release
from relf_agent import temporal_workflow as product
from relf_agent.temporal_parent_workflow import TemporalParentWorkflow
from relf_agent.temporal_session_deployment_dto import ORIGIN_FIELDS
from relf_agent.temporal_session_workflow import TemporalSessionWorkflow
from relf_agent.temporal_state import TemporalRunState
from tests.test_temporal_session_deployment_dto import reservation
from tests.test_temporal_session_deployment_state import registration, session_state, submit_session


def original(monkeypatch, *, parent=False):
    session = session_state()
    submit_session(session)
    entry = session.deployment_turn()
    entry.adopt_registration(registration(entry, "started"))
    intent = entry.intent
    state = TemporalRunState(
        intent["run_id"],
        intent["scope"],
        intent["run_command_id"],
        intent["submission"]["request"],
        intent["submission"]["manifest"],
        "original-business-epoch",
    )
    origin = {
        name: intent[name]
        for name in ORIGIN_FIELDS
        - {"coordinator_first_execution_epoch", "coordinator_original_execution_epoch"}
    }
    origin.update(
        coordinator_first_execution_epoch=intent["coordinator_execution_epoch"],
        coordinator_original_execution_epoch=intent["coordinator_execution_epoch"],
    )
    metadata = {
        "version": 2,
        "root": reservation(intent)["root_admission"],
        "lineage": [],
        "session_origin": origin,
    }
    admission.initialize(
        state,
        metadata,
        namespace=intent["namespace"]["name"],
        epoch=state.epoch,
        original_epoch=state.epoch,
        parent={
            "namespace": intent["namespace"]["name"],
            "workflow_id": intent["coordinator_id"],
            "run_id": intent["coordinator_execution_epoch"],
        },
    )
    release.initialize(state)
    action, _ = state.next_operation()
    state.accept_model(
        action["id"], {"ok": True, "output": "answer", "tool_calls": [], "usage": {}}
    )
    instance = (TemporalParentWorkflow if parent else product.TemporalRunWorkflow).__new__(
        TemporalParentWorkflow if parent else product.TemporalRunWorkflow
    )
    instance.state, instance.wake_revision = state, 0
    observer = TemporalSessionWorkflow.__new__(TemporalSessionWorkflow)
    observer.state, observer.wake_revision = session, 0
    info = SimpleNamespace(
        workflow_id=state.run_id,
        namespace=intent["namespace"]["name"],
        run_id=state.epoch,
        first_execution_run_id=state.epoch,
        original_execution_run_id=state.epoch,
    )
    monkeypatch.setattr(product.workflow, "info", lambda: info)
    sent = []
    failures = []

    class Handle:
        async def signal(self, name, value):
            sent.append((name, copy.deepcopy(value)))
            if failures:
                raise failures.pop(0)
            observer.wake(value)

    def external(workflow_id, *, run_id=None):
        assert workflow_id == intent["coordinator_id"]
        assert run_id == intent["coordinator_execution_epoch"]
        return Handle()

    monkeypatch.setattr(product.workflow, "get_external_workflow_handle", external)
    return instance, observer, sent, failures


@pytest.mark.parametrize("parent", [False, True])
def test_quiet_observation_before_retirement_gets_new_postretirement_wake(monkeypatch, parent):
    instance, observer, sent, _ = original(monkeypatch, parent=parent)
    asyncio.run(instance._notify_session())
    before = observer.wake_revision
    assert before == 1
    instance.state.deployment_seal = {"proof_digest": "a" * 64}
    instance.state.deployment_retirement = {
        "released": True,
        "certificate": instance.state.deployment_seal,
    }
    asyncio.run(instance._notify_session())
    assert observer.wake_revision == before + 1
    assert sent[0][1]["change_token"] != sent[1][1]["change_token"]
    asyncio.run(instance._notify_session())
    assert len(sent) == 2


def test_failed_signal_keeps_same_pending_token_without_marking_sent_or_reacquiring(monkeypatch):
    instance, observer, sent, failures = original(monkeypatch)
    instance.state.deployment_retirement = {"released": True}
    retirement = copy.deepcopy(instance.state.deployment_retirement)
    failures.append(RuntimeError("original signal reply unavailable"))
    asyncio.run(instance._notify_session())
    assert observer.wake_revision == 0
    assert instance._session_deployment_pending == sent[0][1]
    assert instance._session_deployment_sent is None
    asyncio.run(instance._notify_session())
    assert sent[0] == sent[1]
    assert instance._session_deployment_pending is None
    assert instance._session_deployment_sent == sent[1][1]["change_token"]
    assert instance.state.deployment_retirement == retirement
    asyncio.run(instance._notify_session())
    assert len(sent) == 2


@pytest.mark.parametrize("tool_end_evidence", [False, True])
def test_run_loop_checks_postretirement_notification_before_passive_wait(
    monkeypatch, tool_end_evidence
):
    instance, observer, sent, _ = original(monkeypatch)

    def patched(change_id):
        assert change_id == "ralf-unowned-tool-end-evidence-v1"
        return tool_end_evidence  # Replay without the marker and new History.

    async def admitted(activity_timeout):
        return True

    async def parent():
        return None

    async def retired(activity_timeout):
        instance.state.deployment_retirement = {"released": True}

    async def wait(predicate, **kwargs):
        assert instance.state.deployment_retirement == {"released": True}
        assert len(sent) == 2 and observer.wake_revision == 2
        raise asyncio.CancelledError

    instance._check_deployment_initialization = lambda: None
    instance._ensure_deployment_admission = admitted
    instance._notify_deployment_parent = parent
    instance._ensure_deployment_retirement = retired
    monkeypatch.setattr(product.workflow, "patched", patched)
    monkeypatch.setattr(product.workflow, "wait_condition", wait)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(instance.run({"activity_timeout": 30}))


def test_old_pending_delivery_then_retirement_change_notifies_before_sleep(monkeypatch):
    instance, observer, sent, failures = original(monkeypatch)
    failures.append(RuntimeError("pre-retirement signal unavailable"))
    asyncio.run(instance._notify_session())
    first = sent[0]
    instance.state.deployment_retirement = {"released": True}
    asyncio.run(instance._notify_session())
    assert sent[1] == first
    assert len(sent) == 3
    assert sent[2][1]["change_token"] != first[1]["change_token"]
    assert instance._session_deployment_pending is None
    assert observer.wake_revision == 2
