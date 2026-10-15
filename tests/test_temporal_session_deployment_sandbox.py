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
