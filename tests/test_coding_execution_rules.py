"""Pure native permission rules shared by the original execution authorities."""

import copy

import pytest

from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch
from ralf_agent.types import digest


def intent():
    runner = {"kind": "fixture", "version": 1}
    request = {"dispatch": {"arguments": {"task": "fix"}}, "release_digest": "r"}
    state = {"request": request, "grants": {}, "pending_stop": False, "fenced": True}
    environment = {
        "expected_generation": digest({"dispatch": request["dispatch"], "runner": runner})[:32]
    }
    binding = {
        "request": request,
        "dispatch": request["dispatch"],
        "runner": runner,
        "environment": environment,
    }
    return state, runner, binding


def test_original_prepare_is_granted_once_and_duplicate_has_no_permission():
    from ralf_agent.coding_execution_rules import grant

    state, runner, binding = intent()
    first = grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, binding)
    assert first["execute"] and state["pending_stop"] and not state["fenced"]
    assert not grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, binding)[
        "execute"
    ]
    assert state["grants"]["prepare"]["execute"] is False
    first["binding"].clear()
    assert state["grants"]["prepare"]["binding"] == binding


def test_original_namespace_cannot_be_replaced():
    from ralf_agent.coding_execution_rules import grant

    state, runner, binding = intent()
    changed = copy.deepcopy(binding)
    changed["environment"]["expected_generation"] = "different"
    with pytest.raises(DefinitionMismatch):
        grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, changed)
    assert not state["grants"]


def test_read_only_configuration_permission_cannot_be_downgraded():
    from ralf_agent.coding_execution_rules import grant

    state, runner, binding = intent()
    runner["configuration_readonly"] = True
    binding["environment"]["expected_generation"] = digest(
        {"dispatch": state["request"]["dispatch"], "runner": runner}
    )[:32]
    with pytest.raises(DefinitionMismatch, match="configuration"):
        grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, binding)
    assert not state["grants"]
    binding["environment"]["configuration_readonly"] = True
    assert grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, binding)["execute"]


def test_fence_blocks_new_native_submission_but_accepts_same_stop_receipt():
    from ralf_agent.coding_execution_rules import adopt, grant

    state, runner, binding = intent()
    grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, binding)
    stop = {
        "identity": binding["environment"],
        "generation": binding["environment"]["expected_generation"],
        "container_id": "a" * 64,
        "fenced": True,
        "stopped": True,
        "retired": True,
        "container_present": False,
        "running": False,
    }
    adopt(state, runner, "stop", stop)
    assert state["fenced"] and not state["pending_stop"]
    adopt(state, runner, "stop", stop)
    with pytest.raises(AuthorizationDenied):
        grant(state, {"arguments": {"task": "fix"}}, runner, "prepare", {}, binding)
