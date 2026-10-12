"""Model evidence cannot silently change owner, decision, or signed arguments."""

import copy
from dataclasses import asdict, fields
from importlib import import_module

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.harness import DecisionProposal
from ralf_agent.model_evidence import snapshot_model_response
from ralf_agent.types import ModelResponse, ToolCall, digest


def api():
    return import_module("ralf_agent.model_continuation")


def received():
    result = {
        "output": "thinking done",
        "tool_calls": [
            {"name": "read", "arguments": {"n": 2}, "call_id": "one"},
            {"name": "read", "arguments": {"n": 4}, "call_id": "two"},
        ],
        "usage": {"input_tokens": 2, "output_tokens": 1},
    }
    result["continuation"] = {
        "protocol": "fixture-functions-1",
        "owner_digest": "a" * 64,
        "decision_digest": digest({"output": result["output"], "tool_calls": result["tool_calls"]}),
        "data": {"content": [{"signature": "原始🙂"}]},
    }
    return result


def proposal(value):
    return DecisionProposal(value["output"], tuple(ToolCall(**c) for c in value["tool_calls"]))


def test_continuation_detaches_input_and_export_and_remains_asdict_json_compatible():
    original = received()["continuation"]
    value = api().ModelContinuation(**original)
    original["data"]["content"][0]["signature"] = "caller change"
    exported = value.to_dict()
    exported["data"]["content"].append({"signature": "export change"})
    assert asdict(value)["data"] == {"content": [{"signature": "原始🙂"}]}
    response = api().ContinuedModelResponse(
        output="ok", continuation=value, usage={"output_tokens": 1}
    )
    assert [field.name for field in fields(ModelResponse)] == ["output", "tool_calls", "usage"]
    assert snapshot_model_response(response)["continuation"]["data"] == {
        "content": [{"signature": "原始🙂"}]
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"protocol": ""},
        {"protocol": "x" * 129},
        {"protocol": 1},
        {"owner_digest": "A" * 64},
        {"owner_digest": "a" * 63},
        {"decision_digest": "not-a-digest"},
        {"data": []},
        {"data": {"x": float("nan")}},
        {"data": {"x": object()}},
        {"data": {"x": "🙂" * 33000}},
    ],
)
def test_continuation_rejects_non_json_invalid_identity_or_oversized_utf8(changes):
    with pytest.raises(ValidationError):
        api().ModelContinuation(**{**received()["continuation"], **changes})


def test_plain_response_codec_and_message_keep_legacy_shape():
    plain = ModelResponse("done", (ToolCall("read", {"n": 2}, "one"),), None)
    encoded = snapshot_model_response(plain)
    assert encoded == {
        "output": "done",
        "tool_calls": [{"name": "read", "arguments": {"n": 2}, "call_id": "one"}],
        "usage": None,
    }
    assert type(api().decode_received_response(encoded)) is ModelResponse
    assert api().validate_continuation(encoded, proposal(encoded), None, enabled=False) is None
    assert api().assistant_message(
        "done", [{"tool": "read", "arguments": {"n": 2}, "call_id": "one"}]
    ) == {
        "role": "assistant",
        "content": "done",
        "tool_calls": [
            {"id": "one", "type": "function", "function": {"name": "read", "arguments": '{"n":2}'}}
        ],
    }


def test_decode_and_validation_preserve_original_continuation_and_detach_evidence():
    value = received()
    identity = {"protocol": "fixture-functions-1", "owner_digest": "a" * 64}
    decoded = api().decode_received_response(value)
    assert isinstance(decoded, api().ContinuedModelResponse)
    validated = api().validate_continuation(value, proposal(value), identity, enabled=True)
    assert validated == value["continuation"]
    value["continuation"]["data"]["content"].clear()
    assert validated["data"] == {"content": [{"signature": "原始🙂"}]}
    assert decoded.continuation.data == {"content": [{"signature": "原始🙂"}]}


@pytest.mark.parametrize("change", ["output", "name", "arguments", "call_id", "order", "drop"])
def test_harness_cannot_change_signed_original_decision(change):
    value = received()
    altered = copy.deepcopy(value)
    if change == "output":
        altered["output"] = "different"
    elif change == "order":
        altered["tool_calls"].reverse()
    elif change == "drop":
        altered["tool_calls"].pop()
    else:
        altered["tool_calls"][0][change] = {"n": 3} if change == "arguments" else "changed"
    with pytest.raises(ValidationError):
        api().validate_continuation(
            value,
            proposal(altered),
            {"protocol": "fixture-functions-1", "owner_digest": "a" * 64},
            enabled=True,
        )


@pytest.mark.parametrize(
    "change", ["disabled", "missing-owner", "owner", "protocol", "digest", "extra-field"]
)
def test_continuation_requires_opt_in_matching_provider_and_decision(change):
    value = received()
    identity = {"protocol": "fixture-functions-1", "owner_digest": "a" * 64}
    if change in {"owner", "protocol"}:
        identity[change if change == "protocol" else "owner_digest"] = (
            "other" if change == "protocol" else "b" * 64
        )
    elif change == "missing-owner":
        identity = None
    elif change == "digest":
        value["continuation"]["decision_digest"] = "b" * 64
    elif change == "extra-field":
        value["continuation"]["secret"] = True
    with pytest.raises(ValidationError):
        api().validate_continuation(value, proposal(value), identity, enabled=change != "disabled")


def test_signed_assistant_uses_raw_parameters_and_real_action_ids_after_typed_defaults():
    value = received()
    result = api().assistant_message(
        value["output"],
        [
            {"tool": "read", "arguments": {"n": 2, "flag": True}, "call_id": "one"},
            {"tool": "read", "arguments": {"n": 4, "flag": True}, "call_id": "two"},
        ],
        received=value,
        continuation=value["continuation"],
    )
    assert result["tool_calls"][0]["function"]["arguments"] == '{"n":2}'
    assert result["tool_calls"][1]["id"] == "two"
    assert result["model_continuation"] == value["continuation"]
    result["model_continuation"]["data"].clear()
    assert value["continuation"]["data"]


@pytest.mark.parametrize(
    "identity",
    [{}, {"protocol": "p"}, {"protocol": "p", "owner_digest": "a" * 64, "extra": 1}, [], True],
)
def test_provider_declaration_rejects_invalid_shape(identity):
    class Provider:
        continuation_identity = identity

    with pytest.raises(ValidationError):
        api().provider_continuation_identity(Provider())


def test_provider_declaration_is_optional_detached_and_strictly_synchronous():
    class Plain:
        pass

    class Provider:
        continuation_identity = {"protocol": "p", "owner_digest": "a" * 64}

    assert api().provider_continuation_identity(Plain()) is None
    value = api().provider_continuation_identity(Provider())
    value["protocol"] = "changed"
    assert Provider.continuation_identity["protocol"] == "p"


def test_stream_response_owns_a_plain_json_continuation_copy():
    from ralf_agent.model_protocol import ModelStreamEvent

    value = received()
    response = api().decode_received_response(value)
    event = ModelStreamEvent("response", response=response)
    response.continuation.data.clear()
    assert event.response.continuation.data == {"content": [{"signature": "原始🙂"}]}


def test_coroutine_identity_is_rejected_and_closed_without_running_it():
    async def identity():
        raise AssertionError("Declaration must never execute")

    lazy = identity()

    class Provider:
        continuation_identity = lazy

    try:
        with pytest.raises(ValidationError):
            api().provider_continuation_identity(Provider())
        assert lazy.cr_frame is None
    finally:
        lazy.close()


@pytest.mark.parametrize("value", [None, [], {"continuation": None}])
def test_invalid_received_evidence_has_a_domain_validation_error(value):
    with pytest.raises(ValidationError):
        api().decode_received_response(value)
    with pytest.raises(ValidationError):
        api().validate_continuation(value, DecisionProposal(output="ok"), None, enabled=True)
