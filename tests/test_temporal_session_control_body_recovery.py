"""Encoded control bodies retain original semantic end ACK and recovery authority."""

import base64
import copy
import zlib

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_session_deployment_state import TemporalSessionDeploymentState
from ralf_agent.types import canonical, digest
from tests.test_temporal_deployment_session_registry import POLICY
from tests.test_temporal_deployment_session_registry import state as registry_state
from tests.test_temporal_session_deployment_coding_registry import coding_intent_request
from tests.test_temporal_session_deployment_dto import call, seal
from tests.test_temporal_session_deployment_state import advance, registration


def packed(body):
    raw = canonical(body).encode()
    return {
        "_ralf_session_control_body": {
            "version": 1,
            "encoding": "zlib-json-base64",
            "raw_size": len(raw),
            "digest": digest(body),
            "data": base64.b64encode(zlib.compress(raw)).decode(),
        }
    }


def original(*, begin=True):
    intent, _ = coding_intent_request(registry_state())
    manifest = intent["binding"]["manifest"]
    description = manifest["tools"]["plain"]["description"]
    manifest["tools"]["plain"]["description"] = description + "x" * (
        1_044_000 - len(canonical(manifest).encode())
    )
    intent["submission"]["manifest"] = copy.deepcopy(manifest)
    intent["session_ref"]["definition_digest"] = digest(intent["binding"])
    intent["submission"]["request"]["session_turn"]["session_ref"] = copy.deepcopy(
        intent["session_ref"]
    )
    seal(intent)
    entry = TemporalSessionDeploymentState(intent, deployment_id=POLICY.deployment_id)
    entry.adopt_registration(registration(entry, "started"))
    identity = call(entry.intent)
    identity["request_digest"] = digest(entry.control_request("observe"))
    if begin:
        entry.begin_call(identity)
    body = {
        "ok": True,
        "result": {
            "advance": advance(entry),
            "registry_execution_epoch": entry.registry_execution_epoch,
            "execution_epoch": entry.start["execution_epoch"],
        },
    }
    assert len(canonical(body).encode()) > 2 * 1024 * 1024
    return entry, identity, body


def end_payload(identity, body, wire):
    return {
        "identity": copy.deepcopy(identity),
        "body_result": wire,
        "body_result_digest": digest(body),
        "body_stopped": True,
    }


def test_large_original_body_end_ack_survives_duplicate_and_cold_recovery():
    entry, identity, body = original()
    # First prove the same large body satisfies the unchanged semantic validator.
    raw_entry = copy.deepcopy(entry)
    expected_ack = raw_entry.end_call(end_payload(identity, body, body))
    wire = packed(body)
    assert len(canonical(wire).encode()) < 512 * 1024
    ack = entry.end_call(end_payload(identity, body, wire))
    assert ack == expected_ack
    assert ack["body_result_digest"] == digest(body)
    assert entry.end_call(end_payload(identity, body, wire)) == ack
    assert entry.call_ended(ack, body) is True
    recovered = copy.deepcopy(entry)
    result = recovered.recovered_result()
    assert result == {"body": body, "ack": ack}
    assert (
        recovered.validate_observation(result["body"], result["ack"])["snapshot"]["state"]
        == "succeeded"
    )
    result["body"]["result"]["advance"]["run_proof"]["scope"]["workspace"] = "external"
    assert recovered.recovered_result() == {"body": body, "ack": ack}
    recovered.consume_result(body)
    assert recovered.recovered_result() is None
    assert entry.recovered_result() == {"body": body, "ack": ack}


def test_workflow_response_decodes_body_before_original_ack_and_observation_validation():
    from ralf_agent.temporal_session_workflow import TemporalSessionWorkflow

    entry, identity, body = original()
    ack = entry.end_call(end_payload(identity, body, body))
    instance = TemporalSessionWorkflow.__new__(TemporalSessionWorkflow)
    decoded = instance._deployment_response(entry, {**packed(body), "call_end": ack})
    assert decoded == body
    assert entry.validate_observation(decoded, ack)["snapshot"]["state"] == "succeeded"


def test_workflow_original_small_error_body_keeps_its_code_unencoded():
    from ralf_agent.temporal_session_workflow import TemporalSessionWorkflow

    entry, identity, _ = original()
    body = {"ok": False, "code": "definition_mismatch"}
    ack = entry.end_call(end_payload(identity, body, body))
    instance = TemporalSessionWorkflow.__new__(TemporalSessionWorkflow)
    assert instance._deployment_response(entry, {**body, "call_end": ack}) is None
    assert entry.start["last_error"] == {"code": "definition_mismatch"}


@pytest.mark.parametrize("fault", ["identity-scope", "body-scope", "encoded-digest"])
def test_encoded_end_does_not_weaken_scope_or_mutate_ledger_on_failure(fault):
    entry, identity, body = original()
    if fault == "identity-scope":
        identity["scope"]["workspace"] = "foreign"
    if fault == "body-scope":
        body["result"]["advance"]["run_proof"]["scope"]["workspace"] = "foreign"
    wire = packed(body)
    if fault == "encoded-digest":
        wire["_ralf_session_control_body"]["digest"] = "f" * 64
    before = copy.deepcopy(vars(entry))
    with pytest.raises((DefinitionMismatch, ValidationError)):
        entry.end_call(end_payload(identity, body, wire))
    assert vars(entry) == before


def test_owned_activity_packs_end_update_and_return_wire_with_original_digest_and_id():
    import asyncio
    from types import SimpleNamespace

    from ralf_agent.temporal_session_deployment_control import owned_control_body
    from ralf_agent.temporal_session_deployment_dto import decode_control_body
    from ralf_agent.temporal_session_deployment_verification import SessionControlValidation
    from ralf_agent.temporal_session_state import SESSION_ACTIVITY
    from tests.test_temporal_session_deployment_control import Client, Handle, Runtime

    entry, _, body = original(begin=False)
    updates = []

    class LedgerHandle(Handle):
        async def execute_update(self, name, value, **options):
            if name == "session_deployment_call_start":
                return entry.begin_call(value["identity"])
            assert name == "session_deployment_call_end"
            updates.append((copy.deepcopy(value), copy.deepcopy(options)))
            return entry.end_call(value)

    class LedgerClient(Client):
        def get_workflow_handle(self, workflow_id, *, run_id=None):
            assert workflow_id == self.intent["coordinator_id"]
            return LedgerHandle(self, run_id)

    wire = entry.control_request("observe")
    client = LedgerClient(wire)
    runtime = Runtime(copy.deepcopy(entry.intent["binding"]["manifest"]))
    info = SimpleNamespace(
        workflow_id=entry.intent["coordinator_id"],
        workflow_run_id=entry.intent["coordinator_execution_epoch"],
        workflow_namespace=client.namespace,
        activity_id="producer-observe",
        activity_type=SESSION_ACTIVITY,
        attempt=1,
        task_queue=entry.intent["binding"]["task_queue"],
    )
    validation = SessionControlValidation(
        runtime, client, wire, info, deployment_id=entry.deployment_id
    )

    async def scenario():
        async def operation():
            return copy.deepcopy(body["result"])

        response = await owned_control_body(validation, operation)
        assert await runtime._deployment_execution_owner.wait(wait_timeout=1)
        return response

    response = asyncio.run(scenario())
    assert len(updates) == 1
    ended, options = updates[0]
    manifest = entry.intent["binding"]["manifest"]
    assert set(ended["body_result"]) == {"_ralf_session_control_body"}
    assert decode_control_body(ended["body_result"], manifest) == body
    assert ended["body_result_digest"] == digest(body)
    assert options["id"] == "ralf-session-call-end:" + digest([ended["identity"], body])
    returned_wire = {name: value for name, value in response.items() if name != "call_end"}
    assert set(returned_wire) == {"_ralf_session_control_body"}
    assert decode_control_body(returned_wire, manifest) == body
    assert response["call_end"]["body_result_digest"] == digest(body)
    assert entry.call_ended(response["call_end"], body) is True
    assert entry.recovered_result() == {"body": body, "ack": response["call_end"]}


def test_large_encoded_body_recovery_uses_original_sandbox_activation_restrictions():
    import importlib
    import warnings

    from temporalio.worker.workflow_sandbox._importer import Importer
    from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

    from ralf_agent.temporal import _workflow_runner

    entry, identity, body = original()
    wire = packed(body)
    registered = registration(entry, "started")
    importlib.import_module("ralf_agent.temporal_session_workflow")
    context = RestrictionContext()
    importer = Importer(_workflow_runner().restrictions, context)
    with importer.applied():
        workflow_product = importlib.import_module("ralf_agent.temporal_session_workflow")
        state_product = importlib.import_module("ralf_agent.temporal_session_deployment_state")
        context.is_runtime = context.in_activation = True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                recovered = state_product.TemporalSessionDeploymentState(
                    copy.deepcopy(entry.intent), deployment_id=entry.deployment_id
                )
                recovered.adopt_registration(copy.deepcopy(registered))
                recovered.begin_call(identity)
                ack = recovered.end_call(end_payload(identity, body, wire))
                instance = workflow_product.TemporalSessionWorkflow.__new__(
                    workflow_product.TemporalSessionWorkflow
                )
                decoded = instance._deployment_response(recovered, {**wire, "call_end": ack})
                assert decoded == body
                assert (
                    recovered.validate_observation(decoded, ack)["snapshot"]["state"] == "succeeded"
                )
                assert recovered.recovered_result() == {"body": body, "ack": ack}
        finally:
            context.is_runtime = context.in_activation = False
