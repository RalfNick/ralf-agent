"""An empty queued child keeps its independent first read, without a second hint."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")
from relf_agent.temporal_workflow import workflow  # noqa: E402
from tests.test_temporal_deployment_child_wake import selected_parent  # noqa: E402


def initial(monkeypatch, *, legacy=False, version=4):
    value = selected_parent(monkeypatch)
    value.state.manifest["deployment_admission_protocol"]["version"] = version
    value.state.manifest["coding_execution_protocol"] = {}
    assert value._deployment_notifications_selected()
    value.state.state, value.state.error = "queued", None
    value.state.children = []
    value.state.actions = []
    value.state.receipts = {"submit": {}}
    value.state.command_digests = {"submit": "a" * 64}
    info = workflow.info()
    info.parent = SimpleNamespace(namespace=info.namespace, workflow_id="owner", run_id="epoch")
    monkeypatch.setattr(workflow, "info", lambda: info)
    monkeypatch.setattr(
        workflow,
        "patched",
        lambda name: not legacy if name == "ralf-empty-queued-parent-hint-v1" else True,
    )
    sent = []

    class Receiver:
        async def signal(self, name, payload):
            sent.append((name, payload))

    monkeypatch.setattr(workflow, "get_external_workflow_handle", lambda *a, **kw: Receiver())
    return value, sent


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("version", [3, 4])
def test_only_new_selected4_empty_queued_hint_is_omitted(monkeypatch, legacy, version):
    async def run():
        value, sent = initial(monkeypatch, legacy=legacy, version=version)
        assert await value._notify_deployment_parent()
        skipped = version == 4 and not legacy
        assert len(sent) == (0 if skipped else 1)
        if skipped:
            assert getattr(value, "_deployment_parent_notified", None) is None
            assert getattr(value, "_deployment_parent_pending", None) is None
            # This optimization never adopts a child or clears its initial read.
            call = {"run_id": "initial-child"}
            assert value._deployment_child_is_dirty(call)
            assert value._deployment_child_read_ready(call, 1)
            value._deployment_force_child_reads()
            assert value._deployment_child_is_dirty(call)
            value.state.state = "running"
            value.state.actions.append({"kind": "context"})
            assert await value._notify_deployment_parent()
            assert len(sent) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "field",
    [
        "actions",
        "children",
        "queue",
        "reservations",
        "active_action",
        "remote_uncertain",
        "pending_acks",
        "deferred_acks",
        "reconcile_requests",
        "active_reconciliation",
        "active_evidence_ack",
        "session_stages",
        "pending_session",
        "session_recovery",
        "memory_stages",
        "pending_completion",
        "memory_recovery",
        "memory_recovery_revision",
        "context_read_stages",
        "managed_context_stages",
        "context_artifact_dispatches",
        "context_artifact_receipts",
        "completion_stages",
        "pending_verification",
        "input_requests",
        "planning_input_sources",
        "root_read_request",
        "composition_stop_intent",
        "deployment_seal",
        "deployment_retirement",
        "deployment_admission_error",
    ],
)
def test_queued_obligation_still_notifies(monkeypatch, field):
    async def run():
        value, sent = initial(monkeypatch)
        setattr(value.state, field, [{}])
        assert await value._notify_deployment_parent()
        assert len(sent) == 1

    asyncio.run(run())


@pytest.mark.parametrize("ledger", ["deployment_calls", "tool_executions"])
def test_physical_ledger_without_business_revision_still_notifies(monkeypatch, ledger):
    async def run():
        value, sent = initial(monkeypatch)
        setattr(value.state, ledger, {"call": {"stopped": True, "execution_stopped": True}})
        assert await value._notify_deployment_parent()
        assert len(sent) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "debt", ["pending", "notified", "error", "retry", "attempts", "command", "failure"]
)
def test_queued_notification_debt_or_control_is_not_discarded(monkeypatch, debt):
    async def run():
        value, sent = initial(monkeypatch)
        if debt == "command":
            value.state.receipts["drive"] = {}
            value.state.command_digests["drive"] = "b" * 64
        elif debt == "failure":
            value.state.error = {"code": "unknown"}
        else:
            field = {
                "pending": "_deployment_parent_pending",
                "notified": "_deployment_parent_notified",
                "error": "_deployment_parent_notification_error",
                "retry": "_deployment_parent_notification_retry",
                "attempts": "_deployment_parent_notification_attempts",
            }[debt]
            item = (
                {"token": "b" * 64}
                if debt == "pending"
                else {"retryable": False}
                if debt == "error"
                else "b" * 64
                if debt == "notified"
                else 1
            )
            setattr(value, field, item)
        assert await value._notify_deployment_parent() is (debt != "error")
        assert len(sent) == (0 if debt == "error" else 1)
        if debt == "pending":
            assert sent[0][1]["token"] == "b" * 64

    asyncio.run(run())
