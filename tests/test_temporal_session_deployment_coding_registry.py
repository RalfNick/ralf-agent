"""Verified Session Turn admission retains the original Coding close authority."""

import copy

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.types import digest
from tests.test_temporal_deployment_session_registry import (
    NAMESPACE,
    POLICY,
    SCOPE,
    deployment_intent,
    root_lookup,
    state,
    verified,
)
from tests.test_temporal_session_deployment_coding_configuration import coding_session_manifest
from tests.test_temporal_session_deployment_dto import origin, seal


def coding_intent_request(registry, *, composition=False):
    value = deployment_intent()
    manifest = coding_session_manifest(composition=composition)
    manifest["deployment_admission_protocol"].update(
        policy=POLICY.identity, registry_id=registry.registry_id
    )
    value["binding"]["manifest"] = copy.deepcopy(manifest)
    value["submission"]["manifest"] = copy.deepcopy(manifest)
    value["session_ref"]["definition_digest"] = digest(value["binding"])
    value["submission"]["request"]["session_turn"]["session_ref"] = copy.deepcopy(
        value["session_ref"]
    )
    seal(value)
    payload = {
        "kind": "submit",
        "scope": SCOPE,
        "command_id": value["session_command_id"],
        "session_ref": value["session_ref"],
        "input": value["submission"]["request"]["input"],
        "budget": value["submission"]["request"]["budget"],
    }
    registry.reserve(
        {
            "scope": SCOPE,
            "admission_policy": POLICY.identity,
            "namespace": NAMESPACE,
            "command_id": value["session_command_id"],
            "kind": "session_submit",
            "target": value["coordinator_id"],
            "payload_digest": digest(payload),
            "session_submission": {
                "version": 1,
                "session_key": value["session_ref"]["key"],
                "payload": payload,
                "logical_payload": payload,
                "binding": value["binding"],
            },
        }
    )
    return value, {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "command_id": value["run_command_id"],
        "kind": "submit",
        "target": value["run_id"],
        "payload_digest": digest(value["submission"]["request"]),
        "root_admission": {
            "version": 4,
            "manifest_digest": digest(manifest),
            "submission": value["submission"],
            "session_origin": origin(value),
        },
    }


def query(request, *, kind="coding_composition_admission"):
    return {
        **{
            key: copy.deepcopy(request[key])
            for key in ("scope", "admission_policy", "namespace", "command_id")
        },
        "kind": kind,
        "run_id": request["target"],
        "request_digest": request["payload_digest"],
        "manifest_digest": request["root_admission"]["manifest_digest"],
    }


def close_request(request):
    return {
        **{key: copy.deepcopy(request[key]) for key in ("scope", "admission_policy", "namespace")},
        "manifest_digest": request["root_admission"]["manifest_digest"],
    }


@pytest.mark.parametrize("composition", [False, True])
def test_verified_session_coding_root_uses_original_index_and_first_envelope(composition):
    registry = state()
    intent, request = coding_intent_request(registry, composition=composition)
    registry.prepare_session_root(request, intent)
    receipt = registry.commit_session_root(request, intent, verified(intent, request))
    assert len(registry.roots) == len(registry.coding_index) == 1
    assert registry.coding_admission(query(request))["admitted"] is True
    assert registry.deployment_session_root(root_lookup(request))["intent"] == intent
    assert receipt["submission"] == intent["submission"]
    assert registry.commit_session_root(request, intent, verified(intent, request)) == receipt
    assert (
        len(
            registry.coding_candidates(
                {**close_request(request), "kind": "coding_composition_candidates"}
            )
        )
        == 1
    )


@pytest.mark.parametrize("close_after_prepare", [False, True])
def test_original_coding_close_prevents_verified_session_root_commit(close_after_prepare):
    registry = state()
    intent, request = coding_intent_request(registry)
    if close_after_prepare:
        registry.prepare_session_root(request, intent)
    registry.close_coding_submissions(close_request(request))
    with pytest.raises(DefinitionMismatch, match="closed"):
        registry.commit_session_root(request, intent, verified(intent, request))
    assert not registry.roots and not registry.submissions and not registry.coding_index


def test_original_coding_close_retains_existing_session_claim_and_disallows_new_permission():
    registry = state()
    intent, request = coding_intent_request(registry)
    receipt = registry.commit_session_root(request, intent, verified(intent, request))
    result = registry.close_coding_submissions(close_request(request))
    assert len(result["candidates"]) == 1
    assert registry.coding_admission(query(request))["admitted"] is False
    assert registry.commit_session_root(request, intent, verified(intent, request)) == receipt


def test_coding_admission_query_rechecks_original_session_intent_before_exposing_candidate():
    registry = state()
    intent, request = coding_intent_request(registry)
    registry.commit_session_root(request, intent, verified(intent, request))
    key = digest([SCOPE, intent["run_command_id"]])
    registry.session_roots[key]["intent"]["binding"]["task_queue"] = "changed-original"
    with pytest.raises(DefinitionMismatch):
        registry.coding_admission(query(request))


def test_coding_close_also_blocks_fresh_zero_root_session_command():
    _, request = coding_intent_request(state())
    registry = state()
    registry.close_coding_submissions(close_request(request))
    with pytest.raises(DefinitionMismatch, match="closed"):
        coding_intent_request(registry)
    assert not registry.commands and not registry.roots and not registry.coding_index
