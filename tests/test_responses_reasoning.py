import asyncio
import importlib
import json

import httpx
import pytest

from relf_agent.errors import ProviderError, ValidationError
from relf_agent.model_continuation import ContinuedModelResponse, assistant_message
from relf_agent.model_responses import OpenAIResponsesProvider
from relf_agent.types import canonical

TOOL = {
    "type": "function",
    "function": {
        "name": "lookup",
        "description": "Read inventory",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}},
    },
}


def provider(**kwargs):
    try:
        cls = importlib.import_module(
            "relf_agent.responses_reasoning"
        ).OpenAIResponsesReasoningProvider
    except ModuleNotFoundError as exc:
        if exc.name != "relf_agent.responses_reasoning":
            raise
        cls = OpenAIResponsesProvider
    return cls("fixture", api_key="fixture-secret", **kwargs)


def reasoning(**changes):
    return {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "opaque-final",
        "status": None,
        **changes,
    }


def message(text="done", *, identifier="msg_1", phase=None):
    value = {
        "id": identifier,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
    }
    if phase is not None:
        value["phase"] = phase
    return value


def call(*, identifier="fc_1", call_id="call_1", arguments=' { "key" : "A" } ', **changes):
    return {
        "id": identifier,
        "type": "function_call",
        "call_id": call_id,
        "name": "lookup",
        "arguments": arguments,
        "status": "completed",
        **changes,
    }


def completed(output=None, **changes):
    return {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": output if output is not None else [reasoning(), message()],
        "usage": {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens_details": {"reasoning_tokens": 5},
        },
        **changes,
    }


def parse(adapter, value):
    try:
        return adapter._parse(json.dumps(value))
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        pytest.fail(f"Completed native reasoning must be accepted: {type(exc).__name__}: {exc}")


def assistant(result):
    calls = [
        {"name": c.name, "arguments": c.arguments, "call_id": c.call_id} for c in result.tool_calls
    ]
    received = {
        "output": result.output,
        "tool_calls": calls,
        "continuation": result.continuation.to_dict(),
    }
    return assistant_message(
        result.output, calls, received=received, continuation=received["continuation"]
    )


def history(adapter):
    return [
        {"role": "system", "content": "Help"},
        {"role": "user", "content": "inventory?"},
        assistant(
            parse(
                adapter,
                completed(
                    [
                        reasoning(),
                        call(),
                        call(identifier="fc_2", call_id="call_2", arguments='{"key":"B"}'),
                    ]
                ),
            )
        ),
        {"role": "tool", "tool_call_id": "call_2", "content": '{"stock":2}'},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"stock":1}'},
        assistant(
            parse(adapter, completed([reasoning(id="rs_final"), message(phase="final_answer")]))
        ),
        {"role": "user", "content": "next turn"},
    ]


def test_encrypted_items_and_exact_argument_strings_round_trip_in_original_order():
    adapter = provider()
    transcript = history(adapter)
    raw = transcript[2]["model_continuation"]["data"]["output"]
    _, body, _, _ = adapter._prepared(transcript, [TOOL])
    assert body["store"] is False
    assert body["include"] == ["reasoning.encrypted_content"]
    assert not {"previous_response_id", "conversation", "background"} & body.keys()
    assert body["input"][2:5] == raw
    assert body["input"][3]["arguments"] == ' { "key" : "A" } '
    assert body["input"][5:7] == [
        {"type": "function_call_output", "call_id": "call_2", "output": '{"stock":2}'},
        {"type": "function_call_output", "call_id": "call_1", "output": '{"stock":1}'},
    ]
    assert body["input"][7]["id"] == "rs_final"
    assert body["input"][8]["phase"] == "final_answer"
    assert body["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Read inventory",
            "parameters": TOOL["function"]["parameters"],
            "strict": False,
        }
    ]


def test_commentary_is_retained_but_excluded_from_final_json_output():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    adapter = provider(output_schema=schema)
    raw = [
        reasoning(),
        message("working", identifier="msg_comment", phase="commentary"),
        message('{"ok":true}', phase="final_answer"),
    ]
    result = parse(adapter, completed(raw))
    assert isinstance(result, ContinuedModelResponse)
    assert result.output == '{"ok":true}'
    assert result.continuation.data == {"output": raw}
    raw[0]["encrypted_content"] = "mutated"
    assert result.continuation.data["output"][0]["encrypted_content"] == "opaque-final"
    tools = parse(
        provider(), completed([reasoning(), message("working", phase="commentary"), call()])
    )
    assert tools.output is None and tools.tool_calls[0].arguments == {"key": "A"}


@pytest.mark.parametrize("status", [None, "completed", "absent"])
def test_reasoning_optional_status_is_preserved_without_normalizing_wire_evidence(status):
    item = reasoning(status=status)
    if status == "absent":
        item.pop("status")
    result = parse(provider(), completed([item, message()]))
    assert result.continuation.data["output"][0] == item
    assert result.usage == {"input_tokens": 11, "output_tokens": 7}


@pytest.mark.parametrize(
    "changes",
    [{"async": False}, {"caller": None}, {"caller": {"type": "direct"}}, {"namespace": None}],
)
def test_neutral_function_metadata_is_preserved(changes):
    item = call(**changes)
    result = parse(provider(), completed([reasoning(), item]))
    assert result.continuation.data["output"][1] == item


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_encryption",
        "null_encryption",
        "blank_encryption",
        "missing_summary",
        "bad_summary",
        "reasoning_incomplete",
        "reasoning_content",
        "duplicate_item_id",
        "duplicate_call_id",
        "bad_name",
        "long_name",
        "long_call_id",
        "blank_call_id",
        "array_args",
        "duplicate_args",
        "nan_args",
        "commentary_only",
        "phase",
        "refusal",
        "annotations",
        "media",
        "extra",
        "async",
        "caller",
        "namespace",
        "message_incomplete",
        "incomplete",
        "failed",
        "error",
        "empty",
    ],
)
def test_unusable_native_output_cannot_become_a_decision(mutation):
    raw = [reasoning(), message(), call()]
    value = completed(raw)
    if mutation == "missing_encryption":
        raw[0].pop("encrypted_content")
    elif mutation == "null_encryption":
        raw[0]["encrypted_content"] = None
    elif mutation == "blank_encryption":
        raw[0]["encrypted_content"] = "  "
    elif mutation == "missing_summary":
        raw[0].pop("summary")
    elif mutation == "bad_summary":
        raw[0]["summary"] = [{"type": "text", "text": "guess"}]
    elif mutation == "reasoning_incomplete":
        raw[0]["status"] = "incomplete"
    elif mutation == "reasoning_content":
        raw[0]["content"] = [{"type": "input_text", "text": "guess"}]
    elif mutation == "duplicate_item_id":
        raw[2]["id"] = raw[0]["id"]
    elif mutation == "duplicate_call_id":
        raw.append(call(identifier="fc_2"))
    elif mutation == "bad_name":
        raw[2]["name"] = "look.up"
    elif mutation == "long_name":
        raw[2]["name"] = "a" * 65
    elif mutation == "long_call_id":
        raw[2]["call_id"] = "a" * 1025
    elif mutation == "blank_call_id":
        raw[2]["call_id"] = " "
    elif mutation in {"array_args", "duplicate_args", "nan_args"}:
        raw[2]["arguments"] = {
            "array_args": "[]",
            "duplicate_args": '{"key":1,"key":2}',
            "nan_args": '{"key":NaN}',
        }[mutation]
    elif mutation == "commentary_only":
        value["output"] = [reasoning(), message("working", phase="commentary")]
    elif mutation == "phase":
        raw[1]["phase"] = "unknown"
    elif mutation == "refusal":
        raw[1]["content"] = [{"type": "refusal", "refusal": "secret"}]
    elif mutation == "annotations":
        raw[1]["content"][0]["annotations"] = [{"type": "url_citation"}]
    elif mutation == "media":
        raw.append({"type": "web_search_call", "id": "web"})
    elif mutation == "extra":
        raw[0]["secret"] = "unsupported"
    elif mutation == "async":
        raw[2]["async"] = True
    elif mutation == "caller":
        raw[2]["caller"] = {"type": "program", "caller_id": "p"}
    elif mutation == "namespace":
        raw[2]["namespace"] = "remote"
    elif mutation == "message_incomplete":
        raw[1]["status"] = "in_progress"
    elif mutation in {"incomplete", "failed"}:
        value["status"] = mutation
    elif mutation == "error":
        value["error"] = {"message": "secret"}
    else:
        value["output"] = [reasoning(), message(" ")]
    with pytest.raises((ValueError, KeyError, ValidationError)):
        provider()._parse(json.dumps(value))


@pytest.mark.parametrize(
    "mutation",
    [
        "owner",
        "protocol",
        "digest",
        "decision",
        "native",
        "envelope",
        "unsigned_calls",
        "unsigned_final",
        "orphan",
        "duplicate_receipt",
        "missing_receipt",
        "interrupted",
        "role",
        "extra",
        "call_extra",
    ],
)
def test_invalid_signed_history_is_rejected_before_http(mutation):
    adapter = provider()
    transcript = history(adapter)
    evidence = transcript[2]["model_continuation"]
    if mutation in {"owner", "protocol", "digest"}:
        evidence[
            {"owner": "owner_digest", "protocol": "protocol", "digest": "decision_digest"}[mutation]
        ] = "foreign" if mutation == "protocol" else "0" * 64
    elif mutation == "decision":
        transcript[2]["tool_calls"][0]["function"]["arguments"] = '{"key":"changed"}'
    elif mutation == "native":
        evidence["data"]["output"][1]["arguments"] = '{"key":"changed"}'
    elif mutation == "envelope":
        evidence["data"]["extra"] = True
    elif mutation == "unsigned_calls":
        transcript[2].pop("model_continuation")
    elif mutation == "unsigned_final":
        transcript[5].pop("model_continuation")
    elif mutation == "orphan":
        transcript[3]["tool_call_id"] = "foreign"
    elif mutation == "duplicate_receipt":
        transcript[4]["tool_call_id"] = "call_2"
    elif mutation == "missing_receipt":
        transcript.pop(4)
    elif mutation == "interrupted":
        transcript.insert(4, {"role": "user", "content": "next"})
    elif mutation == "role":
        transcript[2]["role"] = "user"
    elif mutation == "extra":
        transcript[2]["phase"] = "guessed"
    else:
        transcript[2]["tool_calls"][0]["extra"] = True
    with pytest.raises(ValidationError):
        adapter.validate_request(transcript, [TOOL])


def test_plain_text_history_without_tools_can_enter_explicit_adapter():
    adapter = provider()
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "next"},
    ]
    _, body, _, _ = adapter._prepared(messages, [])
    assert body["input"] == messages
    with pytest.raises(ValidationError):
        adapter.validate_request(messages, [TOOL])


def test_reasoning_options_map_explicitly_and_secrets_stay_out_of_identity():
    try:
        adapter = provider(
            reasoning_effort="max",
            reasoning_context="all_turns",
            reasoning_summary="detailed",
            reasoning_mode="pro",
        )
    except TypeError as exc:
        pytest.fail(f"Explicit reasoning options must be supported: {exc}")
    _, body, _, _ = adapter._prepared([], [])
    assert body["reasoning"] == {
        "effort": "max",
        "context": "all_turns",
        "summary": "detailed",
        "mode": "pro",
    }
    assert adapter.identity["kind"] == "openai-responses-reasoning"
    assert "fixture-secret" not in canonical(adapter.identity)
    assert adapter.continuation_identity["protocol"] == "openai-responses-reasoning-v1"


@pytest.mark.parametrize(
    "field,values",
    [
        ("reasoning_effort", [None, "none", "minimal", "low", "medium", "high", "xhigh", "max"]),
        ("reasoning_context", [None, "auto", "current_turn", "all_turns"]),
        ("reasoning_summary", [None, "auto", "concise", "detailed"]),
        ("reasoning_mode", [None, "standard", "pro"]),
    ],
)
def test_supported_reasoning_options_are_pinned_and_none_is_omitted(field, values):
    for value in values:
        adapter = provider(**{field: value})
        _, body, _, _ = adapter._prepared([], [])
        if value is None:
            assert field not in adapter.identity and field.removeprefix(
                "reasoning_"
            ) not in body.get("reasoning", {})
        else:
            assert (
                adapter.identity[field] == value
                and body["reasoning"][field.removeprefix("reasoning_")] == value
            )


@pytest.mark.parametrize(
    "field", ["reasoning_effort", "reasoning_context", "reasoning_summary", "reasoning_mode"]
)
@pytest.mark.parametrize("value", [[], {}, True, 1, "unsupported"])
def test_invalid_reasoning_configuration_is_a_typed_preflight_error(field, value):
    with pytest.raises(ValidationError):
        provider(**{field: value})


@pytest.mark.parametrize("field", ["temperature", "top_p", "stop", "seed"])
def test_explicit_reasoning_rejects_unsupported_generation_parameters(field):
    with pytest.raises(TypeError):
        provider(**{field: 1})


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_tokens", True),
        ("output_tokens", -1),
        ("total_tokens", 20),
        ("input_tokens_details", {"cached_tokens": 12}),
        ("output_tokens_details", {"reasoning_tokens": 8}),
        ("output_tokens_details", {"reasoning_tokens": False}),
        ("output_tokens_details", {"unknown_tokens": 0}),
    ],
)
def test_usage_breakdown_cannot_exceed_or_disagree_with_totals(field, value):
    response = completed()
    response["usage"][field] = value
    with pytest.raises((ValueError, KeyError, ValidationError)):
        provider()._parse(json.dumps(response))


def test_call_and_utf8_evidence_limits_are_enforced_without_truncating():
    adapter = provider()
    items = [call(identifier=f"fc_{i}", call_id=f"call_{i}", arguments="{}") for i in range(256)]
    result = parse(adapter, completed(items))
    assert len(result.tool_calls) == 256 and len(result.continuation.data["output"]) == 256
    with pytest.raises(ValueError):
        adapter._parse(
            json.dumps(completed(items + [call(identifier="overflow", call_id="overflow")]))
        )
    with pytest.raises(ValidationError):
        adapter._parse(
            json.dumps(completed([reasoning(encrypted_content="密" * 44000), message()]))
        )


def test_http_lifecycle_preserves_borrowed_client_and_does_not_retry_failures():
    async def run():
        requests = []

        def serve(request):
            requests.append(request)
            return httpx.Response(200, json=completed())

        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            result = await provider(client=client).complete([{"role": "user", "content": "q"}], [])
            assert result.output == "done" and not client.is_closed and len(requests) == 1
            assert str(requests[0].url) == "https://api.openai.com/v1/responses"
            assert requests[0].headers["authorization"] == "Bearer fixture-secret"
        attempts = []

        def fail(request):
            attempts.append(request)
            return httpx.Response(500, json={"error": "secret"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(ProviderError) as error:
                await provider(client=client).complete([], [])
            assert len(attempts) == 1 and "secret" not in str(error.value)

    asyncio.run(run())


def test_non_utf8_native_evidence_is_rejected_with_sanitized_provider_error():
    async def run():
        value = completed([reasoning(encrypted_content="\ud800"), message()])
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=json.dumps(value))
            )
        ) as client:
            with pytest.raises(ProviderError):
                await provider(client=client).complete([], [])

    asyncio.run(run())
