"""Invocation-local Session snapshots retain fresh mutation checks without double hashing."""

import asyncio
import copy
import sys

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_session_deployment_verification import SessionControlValidation
from ralf_agent.types import canonical, digest
from tests.test_temporal_session_deployment_control import Client, Runtime, fixture
from tests.test_temporal_session_deployment_dto import seal


def original(*, numeric_keys=False):
    deployment, wire, info = fixture()
    if numeric_keys:
        wire["intent"]["submission"]["request"]["input"] = {2: "two", 10: "ten"}
        seal(wire["intent"])
    client = Client(wire)
    runtime = Runtime(copy.deepcopy(wire["intent"]["binding"]["manifest"]))
    proof = SessionControlValidation(runtime, client, wire, info, deployment_id=deployment)
    return proof, wire


@pytest.mark.parametrize("full", [False, True])
def test_each_check_hashes_shared_complete_wire_once_and_remains_fresh(full):
    proof, _ = original()
    calls = []
    previous = sys.getprofile()

    def observe(frame, event, _result):
        if (
            event == "call"
            and frame.f_code is digest.__code__
            and frame.f_back.f_code is SessionControlValidation._check.__code__
        ):
            calls.append(frame.f_locals["value"])

    sys.setprofile(observe)
    try:
        proof._check(full=full)
        proof._check(full=full)
    finally:
        sys.setprofile(previous)
    assert len(calls) == 2
    assert all(value is proof.value for value in calls)
    proof.intent["submission"]["request"]["input"]["task"][0] = True
    with pytest.raises(DefinitionMismatch):
        proof._check(full=full)


@pytest.mark.parametrize("target", ["intent", "embedded"])
@pytest.mark.parametrize("replacement", [True, 1.0])
def test_shared_snapshot_rejects_equal_python_bool_int_and_float_changes(target, replacement):
    proof, _ = original()
    selected = proof.intent if target == "intent" else proof.value["intent"]
    assert type(selected["turn_seq"]) is int
    selected["turn_seq"] = replacement
    with pytest.raises(DefinitionMismatch):
        proof._check(full=False)


@pytest.mark.parametrize("target", ["intent", "embedded"])
def test_shared_snapshot_rejects_equal_detached_pointer_replacement(target):
    proof, _ = original()
    if target == "intent":
        proof.intent = copy.deepcopy(proof.intent)
    else:
        proof.value["intent"] = copy.deepcopy(proof.value["intent"])
    with pytest.raises(DefinitionMismatch):
        proof._check(full=False)


@pytest.mark.parametrize("flag", [None, 0, 1, "true"])
def test_snapshot_sharing_flag_requires_exact_bool(flag):
    proof, _ = original()
    proof._shared_intent = flag
    with pytest.raises(DefinitionMismatch):
        proof._check(full=False)


def test_numeric_key_constructor_preserves_distinct_original_canonical_snapshots():
    proof, _ = original(numeric_keys=True)
    assert proof._shared_intent is False
    assert canonical(proof.value["intent"]) != canonical(proof.intent)
    assert set(proof.value["intent"]["submission"]["request"]["input"]) == {2, 10}
    assert set(proof.intent["submission"]["request"]["input"]) == {"2", "10"}
    proof._check()


@pytest.mark.parametrize("target", ["intent", "embedded"])
def test_numeric_key_snapshot_mutation_is_rejected_on_both_independent_copies(target):
    proof, _ = original(numeric_keys=True)
    if target == "intent":
        proof.intent["submission"]["request"]["input"]["2"] = "changed"
    else:
        proof.value["intent"]["submission"]["request"]["input"][2] = "changed"
    with pytest.raises(DefinitionMismatch):
        proof._check(full=False)


def test_shared_snapshot_remains_detached_from_original_input_and_validated_output():
    proof, wire = original()
    wire["intent"]["submission"]["request"]["input"]["task"].append("external")
    proof._check()
    result = asyncio.run(proof.validate())
    result["intent"]["submission"]["request"]["input"]["task"].append("returned")
    assert proof.intent["submission"]["request"]["input"]["task"] == [1, 2]
    proof._check()
