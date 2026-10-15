"""One deployment acceptance owns Coding index, close and quota across scopes."""

import copy
from dataclasses import asdict

import pytest

from ralf_agent import ToolSpec
from ralf_agent.errors import CapacityExceeded, DefinitionMismatch, ValidationError
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_state import TemporalCommandRegistryState
from ralf_agent.temporal_tool_execution import notification_identity
from ralf_agent.types import digest
from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY, setup


def registry():
    return TemporalCommandRegistryState(
        admission_policy=POLICY.identity, namespace=NAMESPACE, admission_protocol=3
    )


def coding_request():
    from ralf_agent.temporal_deployment_protocol import CODING_SOURCE_FILES
    from tests.test_temporal_coding_configuration import manifest

    _, request = setup()
    envelope = request["root_admission"]["submission"]
    release = envelope["manifest"]
    native = manifest()
    release.update(native)
    release["tools"] = {
        name: {
            **asdict(ToolSpec(name, name, {"type": "object"}, config=value["config"])),
            "implementation_digest": "c" * 64,
        }
        for name, value in native["tools"].items()
    }
    release["tool_execution_protocol"] = {
        "version": 1,
        "owner": {"kind": "original-test-owner", "version": "1"},
        "implementation": {name: "d" * 64 for name in ("execute", "wait", "aclose")},
        "notifications": notification_identity(),
    }
    release["deployment_admission_protocol"].update(
        version=3, implementation={name: "e" * 64 for name in CODING_SOURCE_FILES}
    )
    request["root_admission"]["manifest_digest"] = digest(release)
    return request


def scoped(request, **fields):
    return {
        **{k: copy.deepcopy(request[k]) for k in ("scope", "admission_policy", "namespace")},
        "manifest_digest": request["root_admission"]["manifest_digest"],
        **fields,
    }


def candidate_query(request):
    return scoped(request, kind="coding_composition_candidates")


def admission_query(request):
    return scoped(
        request,
        kind="coding_composition_admission",
        command_id=request["command_id"],
        run_id=request["target"],
        request_digest=request["payload_digest"],
    )


def test_registry_three_serves_ordinary_two_without_another_quota():
    state = registry()
    _, first = setup()
    receipt = state.reserve(first)
    assert receipt["target"] == first["target"]
    assert state.coding_candidates(candidate_query(first)) == []
    second = copy.deepcopy(first)
    second["scope"]["principal"] = "second"
    second["target"] = root_run_id(POLICY.deployment_id, second["scope"], second["command_id"])
    with pytest.raises(CapacityExceeded):
        state.reserve(second)
    assert len(state.deployment.roots) == 1


def test_coding_index_is_atomic_detached_and_exact_first_acceptance():
    state, request = registry(), coding_request()
    receipt = state.reserve(request)
    result = state.coding_candidates(candidate_query(request))
    assert result == [
        {
            "command_id": "one",
            "run_id": request["target"],
            "request_digest": request["payload_digest"],
            "manifest_digest": request["root_admission"]["manifest_digest"],
            "close_requested": False,
            "execution_epoch": None,
            "namespace": None,
        }
    ]
    result[0]["run_id"] = "foreign"
    moved = copy.deepcopy(request)
    moved["root_admission"]["submission"]["task_queue"] = "moved"
    assert state.reserve(moved) == receipt
    assert state.coding_admission(admission_query(request))["admitted"] is True
    assert len(state.deployment.roots) == len(state.deployment.submissions) == 1


def test_close_is_scope_manifest_exact_and_survives_late_original_binding():
    state, request = registry(), coding_request()
    first = state.reserve(request)
    closed = state.close_coding_submissions(scoped(request))
    assert closed["close_requested"] is True
    assert state.reserve(request) == first
    bound = state.bind_coding_submission(
        {k: v for k, v in admission_query(request).items() if k != "kind"}
        | {"execution_epoch": "original-epoch"}
    )
    assert bound["admitted"] is False
    assert bound["execution_epoch"] == "original-epoch"
    assert bound["namespace"] == NAMESPACE
    with pytest.raises(DefinitionMismatch):
        state.bind_coding_submission(
            {k: v for k, v in admission_query(request).items() if k != "kind"}
            | {"execution_epoch": "replacement"}
        )
    fresh = copy.deepcopy(request)
    fresh["command_id"] = "new"
    fresh["target"] = root_run_id(POLICY.deployment_id, fresh["scope"], "new")
    with pytest.raises(DefinitionMismatch):
        state.reserve(fresh)
    assert len(state.deployment.roots) == 1


def test_close_before_acceptance_cannot_be_bypassed_with_a_new_command():
    state, request = registry(), coding_request()
    assert state.close_coding_submissions(scoped(request))["candidates"] == []
    with pytest.raises(DefinitionMismatch):
        state.reserve(request)
    assert not state.deployment.roots and not state.deployment.submissions


def test_foreign_scope_cannot_find_or_bind_an_original_coding_submission():
    state, request = registry(), coding_request()
    state.reserve(request)
    foreign = admission_query(request)
    foreign["scope"]["principal"] = "other"
    with pytest.raises(DefinitionMismatch):
        state.coding_admission(foreign)
    assert state.coding_candidates(candidate_query(request) | {"scope": foreign["scope"]}) == []


def test_registry_two_refuses_coding_three_without_consuming_a_root():
    state, _ = setup()
    with pytest.raises(DefinitionMismatch):
        state.reserve(coding_request())
    assert not state.deployment.roots and not state.deployment.submissions


def test_close_tombstones_are_bounded_without_expiring_an_original_close():
    state = TemporalCommandRegistryState(
        admission_policy=POLICY.identity, namespace=NAMESPACE, admission_protocol=3, capacity=2
    )
    _, ordinary = setup()
    first = scoped(ordinary, manifest_digest="a" * 64)
    second = scoped(ordinary, manifest_digest="b" * 64)
    assert state.close_coding_submissions(first)["close_requested"] is True
    state.close_coding_submissions(second)
    with pytest.raises(ValidationError):
        state.close_coding_submissions(scoped(ordinary, manifest_digest="c" * 64))
    assert state.close_coding_submissions(first)["close_requested"] is True


def test_malformed_submit_is_typed_before_scoped_index_access():
    state = registry()
    _, value = setup()
    value.pop("command_id")
    with pytest.raises(ValidationError):
        state.reserve(value)
    assert not state.deployment.roots
