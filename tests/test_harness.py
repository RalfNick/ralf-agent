"""Pure Harness policies return detached requests/proposals, never execute effects."""

from dataclasses import FrozenInstanceError
from importlib import import_module

import pytest

from relf_agent import AgentSpec, ModelResponse, ToolCall, ToolRegistry, ToolSpec
from relf_agent.errors import ValidationError


def harness_api():
    return import_module("relf_agent.harness")


def test_native_prepare_preserves_request_without_aliasing_messages_or_tools():
    api = harness_api()
    messages = [{"role": "user", "content": {"task": ["read"]}}]
    tools = [{"type": "function", "function": {"name": "read", "parameters": {}}}]
    request = api.NativeHarness().prepare(AgentSpec("agent", "Read the evidence"), messages, tools)
    assert isinstance(request, api.ModelRequest)
    assert request.messages == messages
    assert request.tools == tools
    messages[0]["content"]["task"].append("caller-change")
    tools[0]["function"]["name"] = "caller-change"
    assert request.messages[0]["content"]["task"] == ["read"]
    assert request.tools[0]["function"]["name"] == "read"
    request.messages[0]["content"]["task"].append("request-change")
    assert messages[0]["content"]["task"] == ["read", "caller-change"]


def test_native_propose_preserves_response_without_aliasing_output_or_calls():
    api = harness_api()
    output = {"evidence": ["observed"]}
    arguments = {"record_id": "R1", "options": {"fields": ["status"]}}
    response = ModelResponse(output=output, tool_calls=(ToolCall("read", arguments, "call-1"),))
    proposal = api.NativeHarness().propose(AgentSpec("agent", "Read the evidence"), response)
    assert isinstance(proposal, api.DecisionProposal)
    assert proposal.output == output
    assert proposal.tool_calls == response.tool_calls
    assert isinstance(proposal.tool_calls, tuple)
    output["evidence"].append("caller-change")
    arguments["options"]["fields"].append("caller-change")
    assert proposal.output == {"evidence": ["observed"]}
    assert proposal.tool_calls[0].arguments["options"]["fields"] == ["status"]
    proposal.tool_calls[0].arguments["options"]["fields"].append("proposal-change")
    assert arguments["options"]["fields"] == ["status", "caller-change"]


def test_custom_harness_changes_messages_and_proposals_without_executing_tools():
    api = harness_api()
    writes = []
    registry = ToolRegistry()
    registry.register(ToolSpec("write", "Write a record", {"type": "object"}), writes.append)

    class ReadOnlyHarness(api.NativeHarness):
        identity = {"kind": "read-only-policy", "version": "1"}

        def prepare(self, spec, messages, tools):
            request = super().prepare(spec, messages, tools)
            return api.ModelRequest(
                [*request.messages, {"role": "system", "content": "Require read-only evidence"}],
                request.tools,
            )

        def propose(self, spec, response):
            return api.DecisionProposal(output={"status": "refused"})

    policy = ReadOnlyHarness()
    spec = AgentSpec("agent", "Inspect", tools=("write",))
    request = policy.prepare(
        spec, [{"role": "user", "content": "write"}], registry.descriptions(spec.tools)
    )
    proposed = policy.propose(spec, ModelResponse(tool_calls=(ToolCall("write", {}),)))
    assert request.messages[-1]["content"] == "Require read-only evidence"
    assert proposed.output == {"status": "refused"}
    assert proposed.tool_calls == ()
    assert writes == []


@pytest.mark.parametrize("field", ["messages", "tools"])
@pytest.mark.parametrize(
    "value", [None, {}, ["invalid"], [{"value": float("nan")}], [{"value": object()}]]
)
def test_model_request_rejects_non_json_or_non_record_sequences(field, value):
    api = harness_api()
    arguments = {"messages": [], "tools": [], field: value}
    with pytest.raises(ValidationError):
        api.ModelRequest(**arguments)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {"value": object()}])
def test_decision_proposal_rejects_non_finite_or_non_json_output(value):
    api = harness_api()
    with pytest.raises(ValidationError):
        api.DecisionProposal(output=value)


@pytest.mark.parametrize(
    "calls",
    [
        None,
        "write",
        ({"name": "write", "arguments": {}},),
        (ToolCall("", {}),),
        (ToolCall("write", []),),
        (ToolCall("write", {"value": float("inf")}),),
    ],
)
def test_decision_proposal_rejects_malformed_tool_calls(calls):
    api = harness_api()
    with pytest.raises(ValidationError):
        api.DecisionProposal(tool_calls=calls)


def test_dtos_are_frozen_and_proposals_leave_completion_validation_to_engine():
    api = harness_api()
    request = api.ModelRequest([], [])
    proposal = api.DecisionProposal()
    assert proposal.output is None
    assert proposal.tool_calls == ()
    assert api.DecisionProposal(output="   ").output == "   "
    with pytest.raises(FrozenInstanceError):
        request.messages = []
    with pytest.raises(FrozenInstanceError):
        proposal.output = "changed"


def test_native_propose_rejects_an_untyped_model_response():
    api = harness_api()
    with pytest.raises(ValidationError):
        api.NativeHarness().propose(AgentSpec("agent", "Inspect"), {"output": "done"})
