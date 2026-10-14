"""Regressions for actual selected payload and SDK initializer failures."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, DeploymentAdmissionPolicy, Scope
from ralf_agent.types import submission_request
from tests.test_temporal_deployment_dispatch_integration import runtime


def test_selected_legacy_model_payload_gets_scope_and_actual_sdk_identity(monkeypatch):
    pytest.importorskip("temporalio")
    from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow

    selected = runtime(_deployment_admission_policy=DeploymentAdmissionPolicy("worker-only"))
    instance = object.__new__(TemporalRunWorkflow)
    instance.state = SimpleNamespace(
        manifest=selected.manifest,
        scope={"workspace": "w", "principal": "p"},
        run_id="original-run",
        epoch="original-epoch",
    )
    captured = []

    async def execute(name, request, **options):
        captured.append(request)
        return {"ok": True}

    monkeypatch.setattr(workflow, "execute_activity", execute)
    original = {"messages": [{"role": "user", "content": "task"}]}
    assert asyncio.run(instance._execute_activity("model", original)) == {"ok": True}
    assert captured == [{"scope": instance.state.scope, "_deployment_activity_request": original}]
    assert "scope" not in original


def test_invalid_selected_metadata_fails_in_sdk_owned_run_instead_of_initializer(monkeypatch):
    pytest.importorskip("temporalio")
    from temporalio.exceptions import ApplicationError

    from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow

    selected = runtime(_deployment_admission_policy=DeploymentAdmissionPolicy("worker-only"))
    monkeypatch.setattr(
        workflow,
        "info",
        lambda: SimpleNamespace(
            workflow_id="original-run",
            run_id="original-epoch",
            original_execution_run_id="original-epoch",
            namespace="original",
            parent=None,
        ),
    )
    instance = TemporalRunWorkflow(
        {
            "scope": asdict(Scope()),
            "command_id": "first",
            "request": submission_request(AgentSpec("a", "Answer"), "task"),
            "manifest": selected.manifest,
            "activity_timeout": 3,
        }
    )
    with pytest.raises(ApplicationError):
        instance._check_deployment_initialization()
    assert instance.state.state == "failed"
    assert instance.state.error["code"] == "definition_mismatch"
    assert instance.state.event_log[-1]["kind"] == "deployment_initialization_refused"
