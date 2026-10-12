import asyncio
import copy
import importlib
import json

import httpx
import pytest

from ralf_agent.errors import ProviderError, ValidationError
from ralf_agent.model_continuation import ContinuedModelResponse, assistant_message
from ralf_agent.providers import DeepSeekChatProvider
from ralf_agent.types import digest


def provider(**kwargs):
    module = importlib.import_module("ralf_agent.deepseek_thinking")
    return module.DeepSeekThinkingProvider("fixture", api_key="dummy", **kwargs)


TOOL = {
    "type": "function",
    "function": {
        "name": "lookup",
        "description": "Read inventory",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "limit": {"type": "integer", "default": 1}},
            "required": ["key"],
        },
    },
}
CALL_MESSAGE = {
    "role": "assistant",
    "content": "Checking inventory",
    "reasoning_content": "private reasoning",
    "tool_calls": [
        {
            "id": "a",
            "type": "function",
            "function": {"name": "lookup", "arguments": ' { "key" : "A" } '},
        },
        {"id": "b", "type": "function", "function": {"name": "lookup", "arguments": '{"key":"B"}'}},
    ],
}
FINAL_MESSAGE = {"role": "assistant", "content": "done", "reasoning_content": "final reasoning"}
USAGE = {
    "prompt_tokens": 3,
    "completion_tokens": 4,
    "total_tokens": 7,
    "prompt_cache_hit_tokens": 1,
    "prompt_cache_miss_tokens": 2,
    "prompt_tokens_details": {"cached_tokens": 1},
    "completion_tokens_details": {"reasoning_tokens": 2},
}


def completion(message=FINAL_MESSAGE, *, reason=None, usage=USAGE):
    return {
        "id": "completion-fixture",
        "object": "chat.completion",
        "model": "fixture",
        "created": 1,
        "choices": [
            {
                "index": 0,
                "message": copy.deepcopy(message),
                "finish_reason": reason or ("tool_calls" if message.get("tool_calls") else "stop"),
                "logprobs": None,
            }
        ],
        "usage": copy.deepcopy(usage),
    }


def assistant(result):
    proposals = [
        {"name": c.name, "arguments": c.arguments, "call_id": c.call_id} for c in result.tool_calls
    ]
    received = {
        "output": result.output,
        "tool_calls": proposals,
        "continuation": result.continuation.to_dict(),
    }
    return assistant_message(
        result.output, proposals, received=received, continuation=received["continuation"]
    )


def history(adapter):
    calls = adapter._parse(json.dumps(completion(CALL_MESSAGE)))
    final = adapter._parse(json.dumps(completion()))
    return [
        {"role": "system", "content": "Help"},
        {"role": "user", "content": "inventory?"},
        assistant(calls),
        {"role": "tool", "tool_call_id": "b", "content": '{"stock":2}'},
        {"role": "tool", "tool_call_id": "a", "content": '{"stock":1}'},
        assistant(final),
        {"role": "user", "content": "next turn"},
    ]


def test_new_adapter_is_required_for_reasoning_tool_responses():
    assert importlib.util.find_spec("ralf_agent.deepseek_thinking") is not None
    with pytest.raises(ValueError, match="reasoning"):
        DeepSeekChatProvider("fixture", api_key="dummy")._parse(
            json.dumps(completion(CALL_MESSAGE))
        )


def test_native_tool_response_and_original_argument_strings_survive_pipeline():
    bodies = []

    def reply(request):
        bodies.append(json.loads(request.content))
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer dummy"
        return httpx.Response(200, json=completion(CALL_MESSAGE))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            adapter = provider(client=client, reasoning_effort="max", top_p=0.95, stop="END")
            result = await adapter.complete([{"role": "user", "content": "inventory?"}], [TOOL])
            assert isinstance(result, ContinuedModelResponse)
            assert result.output == "Checking inventory"
            assert [(c.name, c.arguments, c.call_id) for c in result.tool_calls] == [
                ("lookup", {"key": "A"}, "a"),
                ("lookup", {"key": "B"}, "b"),
            ]
            assert result.usage == {"input_tokens": 3, "output_tokens": 4}
            evidence = result.continuation.to_dict()
            assert evidence["protocol"] == "deepseek-thinking-v1"
            assert evidence["owner_digest"] == digest(adapter.identity)
            assert evidence["decision_digest"] == digest(
                {
                    "output": "Checking inventory",
                    "tool_calls": [
                        {"name": "lookup", "arguments": {"key": "A"}, "call_id": "a"},
                        {"name": "lookup", "arguments": {"key": "B"}, "call_id": "b"},
                    ],
                }
            )
            assert evidence["data"] == {"message": CALL_MESSAGE}
            transcript = [
                {"role": "user", "content": "inventory?"},
                assistant(result),
                {"role": "tool", "tool_call_id": "a", "content": "in stock"},
                {"role": "tool", "tool_call_id": "b", "content": "sold out"},
            ]
            _, body, _, _ = adapter._prepared(transcript, [TOOL])
            assert body["messages"][1] == CALL_MESSAGE
            assert body["messages"][2:] == transcript[2:]
            assert body["tools"] == [TOOL]
            assert body["thinking"] == {"type": "enabled"}
            assert body["reasoning_effort"] == "max"
            assert body["top_p"] == 0.95
            assert body["stop"] == ["END"]
            assert "temperature" not in body and "seed" not in body
            assert bodies[0]["max_tokens"] == 1024

    asyncio.run(run())


def test_all_final_assistant_reasoning_is_preserved_across_turns_with_tools():
    adapter = provider()
    transcript = history(adapter)
    _, body, _, _ = adapter._prepared(transcript, [TOOL])
    assert body["messages"] == [
        transcript[0],
        transcript[1],
        CALL_MESSAGE,
        transcript[3],
        transcript[4],
        FINAL_MESSAGE,
        transcript[6],
    ]
    _, no_tools, _, _ = adapter._prepared(transcript, [])
    assert no_tools["messages"][5] == FINAL_MESSAGE
    assert "tools" not in no_tools


@pytest.mark.parametrize(
    "message",
    [
        FINAL_MESSAGE,
        {**FINAL_MESSAGE, "reasoning_content": "", "tool_calls": None},
        {**FINAL_MESSAGE, "reasoning_content": None},
        {**FINAL_MESSAGE, "tool_calls": []},
    ],
)
def test_every_completed_final_response_carries_exact_native_evidence(message):
    adapter = provider()
    result = adapter._parse(json.dumps(completion(message)))
    assert isinstance(result, ContinuedModelResponse)
    assert result.continuation.data == {"message": message}
    assert result.tool_calls == ()
    assert result.output == "done"


def test_text_only_unsigned_history_can_be_used_when_request_has_no_tools():
    adapter = provider()
    transcript = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "next"},
    ]
    _, body, _, _ = adapter._prepared(transcript, [])
    assert body["messages"] == transcript
    with pytest.raises(ValidationError):
        adapter.validate_request(transcript, [TOOL])


@pytest.mark.parametrize(
    "mutation",
    [
        "owner",
        "protocol",
        "digest",
        "output",
        "call",
        "native_call",
        "native_output",
        "native_role",
        "native_extra",
        "data_extra",
        "orphan",
        "duplicate_result",
        "missing_result",
        "interrupted_group",
        "unsigned_final",
        "unsigned_calls",
        "unknown_message",
        "unknown_call",
        "unknown_function",
        "continuation_role",
    ],
)
def test_unrepresentable_history_fails_before_io(mutation):
    adapter = provider()
    transcript = history(adapter)
    evidence = transcript[2]["model_continuation"]
    if mutation in {"owner", "protocol", "digest"}:
        evidence[
            {"owner": "owner_digest", "protocol": "protocol", "digest": "decision_digest"}[mutation]
        ] = "other" if mutation == "protocol" else "0" * 64
    elif mutation == "output":
        transcript[2]["content"] = "changed"
    elif mutation == "call":
        transcript[2]["tool_calls"][0]["function"]["arguments"] = '{"key":"changed"}'
    elif mutation == "native_call":
        evidence["data"]["message"]["tool_calls"][0]["function"]["arguments"] = '{"key":"changed"}'
    elif mutation == "native_output":
        evidence["data"]["message"]["content"] = "changed"
    elif mutation == "native_role":
        evidence["data"]["message"]["role"] = "user"
    elif mutation == "native_extra":
        evidence["data"]["message"]["audio"] = {"data": "opaque"}
    elif mutation == "data_extra":
        evidence["data"]["call_ids"] = ["a", "b"]
    elif mutation == "orphan":
        transcript[3]["tool_call_id"] = "other"
    elif mutation == "duplicate_result":
        transcript[4]["tool_call_id"] = "b"
    elif mutation == "missing_result":
        transcript.pop(4)
    elif mutation == "interrupted_group":
        transcript.insert(4, {"role": "user", "content": "next"})
    elif mutation == "unsigned_final":
        transcript[5].pop("model_continuation")
    elif mutation == "unsigned_calls":
        transcript[2].pop("model_continuation")
    elif mutation == "unknown_message":
        transcript[2]["reasoning_content"] = "guessed"
    elif mutation == "unknown_call":
        transcript[2]["tool_calls"][0]["extra"] = True
    elif mutation == "unknown_function":
        transcript[2]["tool_calls"][0]["function"]["extra"] = True
    else:
        transcript[2]["role"] = "user"
    with pytest.raises(ValidationError):
        adapter.validate_request(transcript, [TOOL])


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_reasoning",
        "reasoning_object",
        "missing_role",
        "role",
        "missing_content",
        "content_array",
        "extra",
        "bad_call",
        "bad_function",
        "bad_arguments",
        "duplicate_arguments",
        "duplicate_id",
        "empty",
        "multiple",
        "choice_index",
        "boolean_index",
        "missing_finish",
        "length",
        "filter",
        "refusal",
        "stop_with_calls",
        "tool_finish_without_calls",
        "error",
    ],
)
def test_invalid_or_incomplete_native_decisions_fail_closed(mutation):
    value = completion(CALL_MESSAGE)
    choice = value["choices"][0]
    message = choice["message"]
    if mutation == "missing_reasoning":
        message.pop("reasoning_content")
    elif mutation == "reasoning_object":
        message["reasoning_content"] = {}
    elif mutation == "missing_role":
        message.pop("role")
    elif mutation == "role":
        message["role"] = "user"
    elif mutation == "missing_content":
        message.pop("content")
    elif mutation == "content_array":
        message["content"] = [{"text": "text"}]
    elif mutation in {"extra", "refusal"}:
        message["audio" if mutation == "extra" else "refusal"] = "unsupported"
    elif mutation == "bad_call":
        message["tool_calls"][0]["extra"] = True
    elif mutation == "bad_function":
        message["tool_calls"][0]["function"]["extra"] = True
    elif mutation in {"bad_arguments", "duplicate_arguments"}:
        message["tool_calls"][0]["function"]["arguments"] = (
            "[]" if mutation == "bad_arguments" else '{"key":"A","key":"B"}'
        )
    elif mutation == "duplicate_id":
        message["tool_calls"][1]["id"] = "a"
    elif mutation == "empty":
        choice["message"] = {**FINAL_MESSAGE, "content": "  "}
        choice["finish_reason"] = "stop"
    elif mutation == "multiple":
        value["choices"].append(copy.deepcopy(choice))
    elif mutation in {"choice_index", "boolean_index"}:
        choice["index"] = 1 if mutation == "choice_index" else False
    elif mutation == "missing_finish":
        choice.pop("finish_reason")
    elif mutation in {"length", "filter", "stop_with_calls"}:
        choice["finish_reason"] = {
            "length": "length",
            "filter": "content_filter",
            "stop_with_calls": "stop",
        }[mutation]
    elif mutation == "tool_finish_without_calls":
        choice["message"] = copy.deepcopy(FINAL_MESSAGE)
    else:
        value["error"] = {"message": "failed"}
    with pytest.raises((ValueError, KeyError, ValidationError)):
        provider()._parse(json.dumps(value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_tokens", True),
        ("completion_tokens", -1),
        ("total_tokens", 8),
        ("prompt_cache_hit_tokens", 4),
        ("prompt_cache_miss_tokens", "2"),
        ("prompt_tokens_details", {"cached_tokens": False}),
        ("completion_tokens_details", {"reasoning_tokens": 5}),
        ("other_tokens", 1),
    ],
)
def test_usage_is_validated_without_double_counting_reasoning(field, value):
    usage = {**USAGE, field: value}
    with pytest.raises(ValueError):
        provider()._parse(json.dumps(completion(usage=usage)))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_p": 0},
        {"top_p": 0.949},
        {"top_p": 1.1},
        {"top_p": True},
        {"top_p": float("nan")},
        {"reasoning_effort": "medium"},
        {"reasoning_effort": None},
        {"reasoning_effort": {}},
        {"max_output_tokens": 0},
        {"timeout": -1},
        {"json_mode": 1},
        {"json_mode": True, "stream": True},
    ],
)
def test_invalid_configuration_is_rejected_before_io(kwargs):
    with pytest.raises(ValidationError):
        provider(**kwargs)


@pytest.mark.parametrize(
    "kwargs", [{"temperature": 0.5}, {"seed": 1}, {"presence_penalty": 1}, {"frequency_penalty": 1}]
)
def test_ignored_service_parameters_are_not_exposed(kwargs):
    with pytest.raises(TypeError):
        provider(**kwargs)


def test_model_is_explicit_and_credentials_never_enter_identity(monkeypatch):
    module = importlib.import_module("ralf_agent.deepseek_thinking")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-fixture")
    with pytest.raises(TypeError):
        module.DeepSeekThinkingProvider()
    adapter = module.DeepSeekThinkingProvider("fixture")
    assert adapter.api_key == "env-fixture"
    assert "env-fixture" not in json.dumps(adapter.identity)
    assert adapter.continuation_identity == provider().continuation_identity
    assert adapter.identity["reasoning_effort"] == "high"
    for effort in ("low", "high", "max"):
        _, body, _, _ = provider(reasoning_effort=effort, top_p=1)._prepared(
            [{"role": "user", "content": "q"}], []
        )
        assert body["reasoning_effort"] == effort and body["top_p"] == 1


def test_json_mode_requires_prompt_and_valid_final_object_and_rejects_streaming():
    adapter = provider(json_mode=True)
    with pytest.raises(ValidationError):
        adapter.validate_request([{"role": "user", "content": "q"}], [])
    _, body, _, _ = adapter._prepared([{"role": "user", "content": "Return JSON"}], [])
    assert body["response_format"] == {"type": "json_object"}
    result = adapter._parse(json.dumps(completion({**FINAL_MESSAGE, "content": '{"ok":true}'})))
    assert (
        result.output == '{"ok":true}'
        and result.continuation.data["message"]["reasoning_content"] == "final reasoning"
    )
    with pytest.raises(ValueError):
        adapter._parse(json.dumps(completion()))
    with pytest.raises(ValidationError):
        adapter._prepared([{"role": "user", "content": "Return JSON"}], [], streaming=True)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "name", "extra", "function_extra", "description"]
)
def test_function_declarations_must_round_trip_supported_text_protocol(mutation):
    tools = [copy.deepcopy(TOOL)]
    if mutation == "duplicate":
        tools.append(copy.deepcopy(TOOL))
    elif mutation == "name":
        tools[0]["function"]["name"] = "not a name"
    elif mutation == "extra":
        tools[0]["extra"] = True
    elif mutation == "function_extra":
        tools[0]["function"]["strict"] = True
    else:
        tools[0]["function"]["description"] = 1
    with pytest.raises(ValidationError):
        provider().validate_request([{"role": "user", "content": "q"}], tools)


def test_oversized_utf8_evidence_is_provider_failure_without_truncation():
    async def run():
        value = completion({**FINAL_MESSAGE, "reasoning_content": "思" * 45000})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value))
        ) as client:
            with pytest.raises(ProviderError):
                await provider(client=client).complete([{"role": "user", "content": "q"}], [])

    asyncio.run(run())


def test_duplicate_response_json_keys_are_not_accepted():
    with pytest.raises(ValueError):
        provider()._parse('{"choices":[],"choices":[]}')


def test_call_ids_are_scoped_to_complete_result_groups():
    adapter = provider()
    result = adapter._parse(
        json.dumps(completion({**CALL_MESSAGE, "tool_calls": CALL_MESSAGE["tool_calls"][:1]}))
    )
    transcript = [
        {"role": "user", "content": "q"},
        assistant(result),
        {"role": "tool", "tool_call_id": "a", "content": "one"},
        assistant(result),
        {"role": "tool", "tool_call_id": "a", "content": "two"},
    ]
    _, body, _, _ = adapter._prepared(transcript, [TOOL])
    assert [body["messages"][i]["content"] for i in (2, 4)] == ["one", "two"]


@pytest.mark.parametrize("count", [256, 257])
def test_native_call_count_is_bounded_by_complete_history_receipt_contract(count):
    message = {
        "role": "assistant",
        "content": None,
        "reasoning_content": "",
        "tool_calls": [
            {
                "id": f"call-{i}",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }
            for i in range(count)
        ],
    }
    adapter = provider()
    if count == 257:
        with pytest.raises(ValueError):
            adapter._parse(json.dumps(completion(message)))
        return
    result = adapter._parse(json.dumps(completion(message)))
    transcript = [
        {"role": "user", "content": "q"},
        assistant(result),
        *[{"role": "tool", "tool_call_id": f"call-{i}", "content": "{}"} for i in range(count)],
    ]
    _, body, _, _ = adapter._prepared(transcript, [TOOL])
    assert body["messages"][1] == message
    assert len(body["messages"]) == 258


def test_large_valid_utf8_reasoning_is_kept_complete_below_existing_evidence_cap():
    message = {**FINAL_MESSAGE, "reasoning_content": "思" * 43000}
    result = provider()._parse(json.dumps(completion(message)))
    assert result.continuation.data == {"message": message}


def test_nullable_tool_reasoning_is_preserved_and_replayed_as_native_null():
    adapter = provider()
    message = {**CALL_MESSAGE, "reasoning_content": None}
    result = adapter._parse(json.dumps(completion(message)))
    assert result.continuation.data == {"message": message}
    transcript = [
        {"role": "user", "content": "q"},
        assistant(result),
        {"role": "tool", "tool_call_id": "a", "content": "one"},
        {"role": "tool", "tool_call_id": "b", "content": "two"},
    ]
    _, body, _, _ = adapter._prepared(transcript, [TOOL])
    assert body["messages"][1] == message
