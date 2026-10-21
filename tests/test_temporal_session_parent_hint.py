"""Session Coordinators receive Session hints, not composition-parent hints."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")
from ralf_agent.errors import DefinitionMismatch  # noqa: E402
from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow  # noqa: E402
from tests.test_temporal_deployment_child_wake import selected_parent  # noqa: E402


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("descendant", [False, True])
def test_session_root_does_not_send_unregistered_composition_hint(
    monkeypatch, native, legacy, descendant
):
    async def scenario():
        value = selected_parent(monkeypatch)
        if native:
            original = value
            value = object.__new__(TemporalRunWorkflow)
            value.__dict__.update(original.__dict__)
        value.state.manifest["deployment_admission_protocol"]["version"] = 4
        value.state.manifest["session_deployment_protocol"] = 1
        value.state.manifest["coding_execution_protocol"] = {}
        assert value._deployment_notifications_selected()
        value.state.deployment_admission.update(
            lineage=[{"parent_run_id": "composition-parent"}] if descendant else [],
            session_origin={
                "coordinator_id": "coordinator",
                "coordinator_execution_epoch": "coordinator-epoch",
            },
        )
        info = workflow.info()
        info.parent = SimpleNamespace(
            namespace=info.namespace,
            workflow_id="composition-parent" if descendant else "coordinator",
            run_id="composition-epoch" if descendant else "coordinator-epoch",
        )
        monkeypatch.setattr(workflow, "info", lambda: info)
        monkeypatch.setattr(
            workflow,
            "patched",
            lambda name: not legacy if name == "ralf-session-root-parent-hint-v1" else True,
        )
        sent = []

        class Receiver:
            async def signal(self, name, payload):
                sent.append((name, payload))

        monkeypatch.setattr(workflow, "get_external_workflow_handle", lambda *a, **kw: Receiver())
        assert await value._notify_deployment_parent()
        assert len(sent) == (1 if descendant or legacy else 0)
        if sent:
            assert sent[0][0] == "deployment_child_wake"
            assert sent[0][1]["parent_run_id"] == info.parent.workflow_id

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["namespace", "workflow_id", "run_id"])
def test_session_root_hint_refuses_changed_original_coordinator(monkeypatch, field):
    async def scenario():
        value = selected_parent(monkeypatch)
        value.state.manifest["deployment_admission_protocol"]["version"] = 4
        value.state.manifest["session_deployment_protocol"] = 1
        value.state.manifest["coding_execution_protocol"] = {}
        assert value._deployment_notifications_selected()
        value.state.deployment_admission.update(
            lineage=[],
            session_origin={
                "coordinator_id": "coordinator",
                "coordinator_execution_epoch": "coordinator-epoch",
            },
        )
        info = workflow.info()
        info.parent = SimpleNamespace(
            namespace=info.namespace, workflow_id="coordinator", run_id="coordinator-epoch"
        )
        setattr(info.parent, field, "foreign")
        monkeypatch.setattr(workflow, "info", lambda: info)

        def forbidden(*args, **kwargs):
            raise AssertionError("A changed original parent must not receive a hint")

        monkeypatch.setattr(workflow, "get_external_workflow_handle", forbidden)
        with pytest.raises(DefinitionMismatch):
            await value._notify_deployment_parent()

    asyncio.run(scenario())


@pytest.mark.parametrize("retry", [False, True])
def test_session_root_discards_only_misrouted_generic_retry_debt(monkeypatch, retry):
    async def scenario():
        value = selected_parent(monkeypatch)
        value.state.manifest["deployment_admission_protocol"]["version"] = 4
        value.state.manifest["session_deployment_protocol"] = 1
        value.state.manifest["coding_execution_protocol"] = {}
        assert value._deployment_notifications_selected()
        value.state.deployment_admission.update(
            lineage=[],
            session_origin={
                "coordinator_id": "coordinator",
                "coordinator_execution_epoch": "coordinator-epoch",
            },
        )
        info = workflow.info()
        info.parent = SimpleNamespace(
            namespace=info.namespace, workflow_id="coordinator", run_id="coordinator-epoch"
        )
        monkeypatch.setattr(workflow, "info", lambda: info)
        value._deployment_parent_pending = {"token": "a" * 64}
        value._deployment_parent_notification_error = {"retryable": retry}
        value._deployment_parent_notification_retry = retry
        value._deployment_parent_notification_attempts = 1
        session_debt = {"change_token": "b" * 64}
        value._session_deployment_pending = session_debt
        value._session_deployment_sent = "c" * 64

        def forbidden(*args, **kwargs):
            raise AssertionError("Do not resend an obsolete, misrouted hint")

        monkeypatch.setattr(workflow, "get_external_workflow_handle", forbidden)
        assert await value._notify_deployment_parent()
        assert value._deployment_parent_pending is None
        assert value._deployment_parent_notification_error is None
        assert value._deployment_parent_notification_retry is False
        assert value._deployment_parent_notification_attempts == 0
        assert value._session_deployment_pending is session_debt
        assert value._session_deployment_sent == "c" * 64

    asyncio.run(scenario())
