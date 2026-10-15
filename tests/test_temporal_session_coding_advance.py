"""Original Session Advance accepts only the correlated Coding call inventory."""

import copy
import importlib
import warnings

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_deployment_release_state import seal, view
from ralf_agent.temporal_session_deployment_state import TemporalSessionDeploymentState
from ralf_agent.types import digest
from tests.test_temporal_deployment_session_registry import POLICY
from tests.test_temporal_deployment_session_registry import state as registry_state
from tests.test_temporal_session_coding_retirement import environment
from tests.test_temporal_session_deployment_coding_registry import coding_intent_request
from tests.test_temporal_session_deployment_dto import call
from tests.test_temporal_session_deployment_state import advance, registration


def fixture(*, composition=False, fenced=False, ordinary=False):
    _, _, run, _, record, _, _ = environment(
        composition=composition, fenced=fenced, ordinary=ordinary
    )
    if ordinary:
        from tests.test_temporal_session_deployment_execution import original

        intent = original()[0]
    else:
        intent, _ = coding_intent_request(registry_state(), composition=composition)
    entry = TemporalSessionDeploymentState(intent, deployment_id=POLICY.deployment_id)
    registered = registration(entry, "started")
    registered["start"]["execution_epoch"] = run.epoch
    registered["execution_epoch"] = run.epoch
    entry.adopt_registration(registered)
    certificate = seal(run, {"scope": run.scope, "children": []})
    result = advance(entry)
    result["closure"] = view(run)
    result["retirement"] = {
        "root": result["closure"]["deployment"]["admission_receipt"]["root"],
        "certificate": certificate,
        "released": True,
    }
    return entry, result, record, registered


def observe(entry, value):
    identity = call(entry.intent)
    identity["request_digest"] = digest(entry.control_request("observe"))
    entry.begin_call(identity)
    body = {
        "ok": True,
        "result": {
            "advance": value,
            "registry_execution_epoch": entry.registry_execution_epoch,
            "execution_epoch": entry.start["execution_epoch"],
        },
    }
    ack = entry.end_call(
        {
            "identity": identity,
            "body_result": body,
            "body_result_digest": digest(body),
            "body_stopped": True,
        }
    )
    return entry.validate_observation(body, ack)


@pytest.mark.parametrize("composition", [False, True])
@pytest.mark.parametrize("fenced", [False, True])
def test_original_coding_closure_advances_after_positive_retirement(composition, fenced):
    entry, value, _, _ = fixture(composition=composition, fenced=fenced)
    expected = {**value["run_proof"], "descendants": []}
    assert observe(entry, value) == expected
    assert entry.start["phase"] == "started"


@pytest.mark.parametrize(
    "fault",
    ["missing", "extra", "identity", "namespace", "epoch", "present", "unfenced", "unknown"],
)
def test_coding_advance_refuses_malformed_fence_or_unknown_call(fault):
    entry, value, _, _ = fixture(fenced=True)
    record = next(iter(value["closure"]["calls"].values()))
    if fault == "missing":
        record.pop("fence_proof")
    elif fault == "extra":
        record["fence_proof"]["caller_claim"] = True
    elif fault == "identity":
        record["fence_proof"]["identity"]["request_digest"] = "e" * 64
    elif fault == "namespace":
        record["fence_proof"]["namespace"]["id"] = "22222222-2222-4222-8222-222222222222"
    elif fault == "epoch":
        record["fence_proof"]["execution_epoch"] = "replacement"
    elif fault == "present":
        record["fence_proof"]["process_present"] = True
    elif fault == "unfenced":
        record["fence_proof"]["native_fenced"] = False
    else:
        record["stopped"], record["end_proof"] = False, None
    with pytest.raises((DefinitionMismatch, ValidationError)):
        observe(entry, value)


def test_ordinary_four_advance_keeps_original_call_record_shape():
    entry, value, _, _ = fixture(ordinary=True)
    assert observe(entry, value)["snapshot"]["state"] == "succeeded"
    other, damaged, _, _ = fixture(ordinary=True)
    next(iter(damaged["closure"]["calls"].values()))["fence_proof"] = None
    with pytest.raises((DefinitionMismatch, ValidationError)):
        observe(other, damaged)


@pytest.mark.parametrize("composition", [False, True])
def test_coding_advance_uses_only_preloaded_pure_modules_in_activation(composition):
    from temporalio.worker.workflow_sandbox._importer import Importer
    from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

    from ralf_agent.temporal import _workflow_runner

    entry, value, _, registered = fixture(composition=composition)
    importlib.import_module("ralf_agent.temporal_session_workflow")
    context = RestrictionContext()
    importer = Importer(_workflow_runner().restrictions, context)
    with importer.applied():
        importlib.import_module("ralf_agent.temporal_session_workflow")
        product = importlib.import_module("ralf_agent.temporal_session_deployment_state")
        context.is_runtime = context.in_activation = True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                original = product.TemporalSessionDeploymentState(
                    copy.deepcopy(entry.intent), deployment_id=entry.deployment_id
                )
                original.adopt_registration(registered)
                assert observe(original, value)["snapshot"]["state"] == "succeeded"
        finally:
            context.is_runtime = context.in_activation = False
