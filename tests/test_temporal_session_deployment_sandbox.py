"""Selected Session lifecycle imports remain fixed during SDK activations."""

import copy
import importlib
import warnings

import pytest


@pytest.mark.parametrize(
    "workflow_module",
    [
        "ralf_agent.temporal_workflow",
        "ralf_agent.temporal_parent_workflow",
        "ralf_agent.temporal_session_workflow",
    ],
)
def test_original_session_lifecycle_has_no_late_sandbox_import(workflow_module):
    from temporalio.worker.workflow_sandbox._importer import Importer
    from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

    from ralf_agent.temporal import _workflow_runner
    from tests.test_temporal_session_deployment_state import (
        advance,
        ended_observation,
        registration,
        session_state,
        submit_session,
    )

    bootstrap = session_state()
    submit_session(bootstrap)
    entry = bootstrap.deployment_turn()
    registered = registration(entry, "started")
    entry.adopt_registration(registered)
    body, ack = ended_observation(entry, advance(entry))
    accepted = {
        "scope": bootstrap.scope,
        "namespace_id": bootstrap.namespace_id,
        "session_namespace": None,
        "session_id": "chat",
        "command_id": "open",
        **copy.deepcopy(bootstrap.binding),
    }
    command = {
        "kind": "submit",
        "scope": bootstrap.scope,
        "command_id": "session-submit-1",
        "session_ref": bootstrap.ref.to_dict(),
        "input": {"task": [1, 2]},
        "budget": 7,
    }
    importlib.import_module(workflow_module)
    context = RestrictionContext()
    importer = Importer(_workflow_runner().restrictions, context)
    with importer.applied():
        importlib.import_module(workflow_module)
        state_api = importlib.import_module("ralf_agent.temporal_session_state")
        context.is_runtime = True
        context.in_activation = True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                selected = state_api.TemporalSessionState(
                    accepted, deployment_context=bootstrap.deployment_context
                )
                receipt = selected.command(command)
                assert receipt["outcome"]["turn"]["turn_seq"] == 1
                original = selected.deployment_turn()
                original.adopt_registration(registered)
                original.begin_call(ack["identity"])
                original.end_call(
                    {
                        **{key: value for key, value in ack.items() if key != "recorded"},
                        "body_result": body,
                    }
                )
                proof = original.validate_observation(body, ack)
                assert proof["snapshot"]["result"] == "answer"
        finally:
            context.in_activation = False
            context.is_runtime = False


@pytest.mark.parametrize(
    "composition", [False, True], ids=["native6-binding22", "composition7-binding23"]
)
def test_coding_session_activation_has_no_late_pure_validation_import(monkeypatch, composition):
    from types import SimpleNamespace

    from temporalio import workflow
    from temporalio.worker.workflow_sandbox._importer import Importer
    from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

    from ralf_agent.temporal import _workflow_runner
    from tests.test_temporal_deployment_session_registry import state as registry_state
    from tests.test_temporal_session_deployment_coding_registry import coding_intent_request

    intent, _ = coding_intent_request(registry_state(), composition=composition)
    key = intent["session_ref"]["key"]
    binding = copy.deepcopy(intent["binding"])
    accepted = {
        "scope": intent["scope"],
        "namespace_id": intent["namespace"]["id"],
        "session_namespace": key["namespace"],
        "session_id": key["session_id"],
        "command_id": "open",
        **binding,
    }
    actual = SimpleNamespace(
        namespace=intent["namespace"]["name"],
        workflow_id=intent["coordinator_id"],
        run_id=intent["coordinator_execution_epoch"],
        first_execution_run_id=intent["coordinator_execution_epoch"],
        original_execution_run_id=intent["coordinator_execution_epoch"],
        parent=None,
        task_queue=binding["task_queue"],
    )
    monkeypatch.setattr(workflow, "info", lambda: actual)
    module_name = "ralf_agent.temporal_session_workflow"
    importlib.import_module(module_name)
    context = RestrictionContext()
    importer = Importer(_workflow_runner().restrictions, context)
    with importer.applied():
        product = importlib.import_module(module_name)
        context.is_runtime = True
        context.in_activation = True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                instance = product.TemporalSessionWorkflow(accepted)
                receipt = instance.state.command(
                    {
                        "kind": "submit",
                        "scope": intent["scope"],
                        "command_id": intent["session_command_id"],
                        "session_ref": instance.state.ref.to_dict(),
                        "input": intent["submission"]["request"]["input"],
                        "budget": intent["submission"]["request"]["budget"],
                    }
                )
                assert receipt["outcome"]["turn"]["turn_seq"] == 1
                original = instance.state.deployment_turn().intent
                assert original["binding"]["manifest"] == binding["manifest"]
                assert original["submission"]["manifest"]["binding_protocol"] == (
                    23 if composition else 22
                )
                assert (
                    original["submission"]["manifest"]["coding_execution_protocol"]["version"] == 6
                )
                if composition:
                    assert (
                        original["submission"]["manifest"]["coding_composition_protocol"]["version"]
                        == 7
                    )
        finally:
            context.in_activation = False
            context.is_runtime = False
