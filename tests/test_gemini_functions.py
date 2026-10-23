import asyncio
import copy
import importlib
import json

import httpx
import pytest

from relf_agent.errors import ProviderError, ValidationError
from relf_agent.types import canonical, digest


def provider(**kwargs):
    module = importlib.import_module("relf_agent.gemini_functions")
    return module.GeminiFunctionProvider("fixture", api_key="dummy", **kwargs)


TOOL = {
    "type": "function",
    "function": {
        "name": "lookup",
        "description": "Read inventory",
        "parameters": {
            "type": "object",
            "$defs": {"key": {"type": "string", "minLength": 1}},
            "properties": {"key": {"$ref": "#/$defs/key"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    },
}


def candidate(parts, **extra):
    return {
        "candidates": [
            {"content": {"role": "model", "parts": copy.deepcopy(parts)}, "finishReason": "STOP"}
        ],
        **extra,
    }


SIGNED_PARTS = [
    {"text": "private reasoning", "thought": True, "thoughtSignature": "c2VjcmV0"},
    {"text": "Checking "},
    {
        "functionCall": {"name": "lookup", "args": {"key": "A"}, "id": "native-a"},
        "thoughtSignature": "c2lnbmF0dXJl",
    },
    {"text": "inventory"},
    {"functionCall": {"name": "lookup", "args": {"key": "B"}, "id": "native-b"}},
]


def assistant(result):
    return {
        "role": "assistant",
        "content": result.output,
        "tool_calls": [
            {
                "id": call.call_id,
                "type": "function",
                "function": {"name": call.name, "arguments": canonical(call.arguments)},
            }
            for call in result.tool_calls
        ],
        "model_continuation": result.continuation.to_dict(),
    }


def test_signed_parallel_calls_preserve_native_parts_and_json_schema():
    bodies = []

    def reply(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=candidate(
                SIGNED_PARTS,
                usageMetadata={
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 4,
                    "thoughtsTokenCount": 5,
                },
            ),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            adapter = provider(client=client, temperature=0.2, seed=8)
            result = await adapter.complete([{"role": "user", "content": "inventory?"}], [TOOL])
            assert result.output == "Checking inventory"
            assert [(x.name, x.arguments, x.call_id) for x in result.tool_calls] == [
                ("lookup", {"key": "A"}, "native-a"),
                ("lookup", {"key": "B"}, "native-b"),
            ]
            assert result.usage == {"input_tokens": 3, "output_tokens": 9}
            data = result.continuation.to_dict()
            assert data["data"] == {
                "content": {"role": "model", "parts": SIGNED_PARTS},
                "call_ids": ["native-a", "native-b"],
            }
            assert data["owner_digest"] == digest(adapter.identity)
            assert data["decision_digest"] == digest(
                {
                    "output": "Checking inventory",
                    "tool_calls": [
                        {"name": "lookup", "arguments": {"key": "A"}, "call_id": "native-a"},
                        {"name": "lookup", "arguments": {"key": "B"}, "call_id": "native-b"},
                    ],
                }
            )
            data["data"]["content"]["parts"].clear()
            assert len(result.continuation.to_dict()["data"]["content"]["parts"]) == 5

    asyncio.run(run())
    assert bodies[0]["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "lookup",
                    "description": "Read inventory",
                    "parametersJsonSchema": TOOL["function"]["parameters"],
                }
            ]
        }
    ]
    assert bodies[0]["generationConfig"] == {"maxOutputTokens": 1024, "temperature": 0.2, "seed": 8}


def test_native_history_echoes_original_ids_and_preserves_parallel_receipt_order():
    adapter = provider()
    result = adapter._parse(json.dumps(candidate(SIGNED_PARTS)))
    history = [
        {"role": "system", "content": "safe"},
        {"role": "user", "content": "q"},
        assistant(result),
        {"role": "tool", "tool_call_id": "native-b", "content": '{"stock":2}'},
        {"role": "tool", "tool_call_id": "native-a", "content": "[1,2]"},
    ]
    _, body, _, _ = adapter._prepared(history, [TOOL])
    assert body["contents"][1] == {"role": "model", "parts": SIGNED_PARTS}
    assert body["contents"][2] == {
        "role": "user",
        "parts": [
            {"functionResponse": {"name": "lookup", "id": "native-b", "response": {"stock": 2}}},
            {
                "functionResponse": {
                    "name": "lookup",
                    "id": "native-a",
                    "response": {"result": [1, 2]},
                }
            },
        ],
    }
    assert body["systemInstruction"] == {"parts": [{"text": "safe"}]}


def test_missing_native_id_has_stable_host_id_but_never_forges_api_id():
    adapter = provider()
    raw = json.dumps(candidate([{"functionCall": {"name": "lookup", "args": {"key": "A"}}}]))
    a, b = adapter._parse(raw), adapter._parse(raw)
    assert a.tool_calls[0].call_id == b.tool_calls[0].call_id
    assert isinstance(a.tool_calls[0].call_id, str) and a.tool_calls[0].call_id
    _, body, _, _ = adapter._prepared(
        [
            {"role": "user", "content": "q"},
            assistant(a),
            {"role": "tool", "tool_call_id": a.tool_calls[0].call_id, "content": "true"},
        ],
        [TOOL],
    )
    assert body["contents"][-1]["parts"] == [
        {"functionResponse": {"name": "lookup", "response": {"result": True}}}
    ]


def test_complete_no_argument_function_accepts_omitted_optional_args():
    result = provider()._parse(json.dumps(candidate([{"functionCall": {"name": "ping"}}])))
    assert result.tool_calls[0].arguments == {}


@pytest.mark.parametrize(
    "part",
    [
        {"functionCall": {"name": "lookup", "args": []}},
        {"functionCall": {"name": "lookup", "args": None}},
        {"functionCall": {"name": "lookup", "args": {}, "id": ""}},
        {"functionCall": {"name": "bad.name", "args": {}}},
        {"functionCall": {"name": "a" * 129, "args": {}}},
        {"functionCall": {"name": "lookup", "args": {}, "partialArgs": []}},
        {"functionCall": {"name": "lookup", "args": {}}, "text": "mixed"},
        {"inlineData": {"data": "YQ==", "mimeType": "text/plain"}},
        {"executableCode": {"code": "pass"}},
        {"functionResponse": {"name": "lookup", "response": {}}},
        {"text": "x", "thought": "true"},
        {"text": "x", "thoughtSignature": 1},
        {"thoughtSignature": "c2ln"},
        {},
    ],
)
def test_unsupported_parts_cannot_be_completed_model_decisions(part):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=candidate([part]))
            )
        ) as client:
            with pytest.raises(ProviderError):
                await provider(client=client).complete([{"role": "user", "content": "q"}], [TOOL])

    asyncio.run(run())


@pytest.mark.parametrize(
    "change", ["duplicate_id", "blocked", "max_tokens", "role", "empty", "bad_usage"]
)
def test_incomplete_or_ambiguous_responses_fail_closed(change):
    value = candidate(SIGNED_PARTS)
    if change == "duplicate_id":
        value["candidates"][0]["content"]["parts"][-1]["functionCall"]["id"] = "native-a"
    elif change == "blocked":
        value["promptFeedback"] = {"blockReason": "SAFETY"}
    elif change == "max_tokens":
        value["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif change == "role":
        value["candidates"][0]["content"]["role"] = "user"
    elif change == "empty":
        value["candidates"][0]["content"]["parts"] = [{"text": "private", "thought": True}]
    else:
        value["usageMetadata"] = {"promptTokenCount": True, "candidatesTokenCount": 1}
    with pytest.raises((ValueError, ValidationError)):
        provider()._parse(json.dumps(value))


@pytest.mark.parametrize(
    "mutation",
    [
        "owner",
        "digest",
        "call",
        "part",
        "call_ids",
        "orphan",
        "duplicate_result",
        "missing_result",
        "interrupted_group",
        "bad_result",
        "unknown_message",
        "unknown_call",
        "unknown_function",
        "continuation_role",
    ],
)
def test_unrepresentable_history_is_rejected_before_http(mutation):
    adapter = provider()
    result = adapter._parse(json.dumps(candidate(SIGNED_PARTS)))
    history = [
        {"role": "user", "content": "q"},
        assistant(result),
        {"role": "tool", "tool_call_id": "native-a", "content": '{"stock":1}'},
        {"role": "tool", "tool_call_id": "native-b", "content": '{"stock":2}'},
    ]
    if mutation in {"owner", "digest"}:
        history[1]["model_continuation"][
            "owner_digest" if mutation == "owner" else "decision_digest"
        ] = "0" * 64
    elif mutation == "call":
        history[1]["tool_calls"][0]["function"]["arguments"] = '{"key":"CHANGED"}'
    elif mutation == "part":
        history[1]["model_continuation"]["data"]["content"]["parts"][1]["text"] = "changed"
    elif mutation == "call_ids":
        history[1]["model_continuation"]["data"]["call_ids"] = ["native-a"]
    elif mutation == "orphan":
        history[2]["tool_call_id"] = "other"
    elif mutation == "duplicate_result":
        history[3]["tool_call_id"] = "native-a"
    elif mutation == "missing_result":
        history.pop()
    elif mutation == "interrupted_group":
        history.insert(3, {"role": "user", "content": "next turn"})
    elif mutation == "bad_result":
        history[2]["content"] = '{"stock":NaN}'
    elif mutation == "unknown_message":
        history[1]["thinking"] = "lost"
    elif mutation == "unknown_call":
        history[1]["tool_calls"][0]["extra"] = True
    elif mutation == "unknown_function":
        history[1]["tool_calls"][0]["function"]["extra"] = True
    elif mutation == "continuation_role":
        history[1]["role"] = "user"
    with pytest.raises(ValidationError):
        adapter.validate_request(history, [TOOL])


def test_standard_unsigned_history_and_final_signed_content_can_continue():
    adapter = provider()
    history = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "host",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"key":"A"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "host", "content": '{"stock":1}'},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "next"},
    ]
    _, body, _, _ = adapter._prepared(history, [TOOL])
    assert body["contents"][1] == {
        "role": "model",
        "parts": [{"functionCall": {"name": "lookup", "args": {"key": "A"}}}],
    }
    assert "id" not in body["contents"][2]["parts"][0]["functionResponse"]
    final = adapter._parse(json.dumps(candidate([{"text": "done", "thoughtSignature": "c2ln"}])))
    final_message = assistant(final)
    final_message.pop("tool_calls")
    _, body, _, _ = adapter._prepared(
        [{"role": "user", "content": "q"}, final_message, {"role": "user", "content": "next"}], []
    )
    assert body["contents"][1] == {
        "role": "model",
        "parts": [{"text": "done", "thoughtSignature": "c2ln"}],
    }


@pytest.mark.parametrize(
    "mutation", ["duplicate", "name", "unknown", "unknown_function", "description"]
)
def test_invalid_declarations_fail_preflight(mutation):
    tools = [copy.deepcopy(TOOL)]
    if mutation == "duplicate":
        tools.append(copy.deepcopy(TOOL))
    elif mutation == "name":
        tools[0]["function"]["name"] = "not a name"
    elif mutation == "unknown":
        tools[0]["extra"] = "lost"
    elif mutation == "unknown_function":
        tools[0]["function"]["strict"] = True
    else:
        tools[0]["function"]["description"] = 1
    with pytest.raises(ValidationError):
        provider().validate_request([{"role": "user", "content": "q"}], tools)


def test_declaration_names_outside_round_trip_subset_fail_before_io():
    tool = copy.deepcopy(TOOL)
    tool["function"]["name"] = "namespace:lookup.v1-test"
    with pytest.raises(ValidationError):
        provider().validate_request([{"role": "user", "content": "q"}], [tool])


def test_oversized_continuation_is_a_provider_failure_not_a_dto_exception():
    async def run():
        value = candidate([{"text": "done", "thoughtSignature": "A" * 131072}])
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value))
        ) as client:
            with pytest.raises(ProviderError):
                await provider(client=client).complete([{"role": "user", "content": "q"}], [])

    asyncio.run(run())


def test_empty_unsigned_assistant_cannot_be_represented_as_a_completed_turn():
    with pytest.raises(ValidationError):
        provider().validate_request(
            [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": ""},
                {"role": "user", "content": "next"},
            ],
            [],
        )


@pytest.mark.parametrize("continued", [False, True])
def test_whitespace_assistant_does_not_claim_a_completed_turn(continued):
    adapter = provider()
    message = {"role": "assistant", "content": "  "}
    if continued:
        message["model_continuation"] = {
            **adapter.continuation_identity,
            "decision_digest": digest({"output": "  ", "tool_calls": []}),
            "data": {"content": {"role": "model", "parts": [{"text": "  "}]}, "call_ids": []},
        }
    with pytest.raises(ValidationError):
        adapter.validate_request(
            [{"role": "user", "content": "q"}, message, {"role": "user", "content": "next"}], []
        )


def test_history_call_ids_are_scoped_to_complete_receipt_groups():
    adapter = provider()
    result = adapter._parse(
        json.dumps(candidate([{"functionCall": {"name": "lookup", "args": {}, "id": "same"}}]))
    )
    _, body, _, _ = adapter._prepared(
        [
            {"role": "user", "content": "q"},
            assistant(result),
            {"role": "tool", "tool_call_id": "same", "content": '{"stock":1}'},
            assistant(result),
            {"role": "tool", "tool_call_id": "same", "content": '{"stock":2}'},
        ],
        [TOOL],
    )
    assert body["contents"][2]["parts"][0]["functionResponse"]["response"] == {"stock": 1}
    assert body["contents"][4]["parts"][0]["functionResponse"]["response"] == {"stock": 2}


def test_json_duplicates_in_arguments_and_results_never_pass_native_protocol():
    adapter = provider()
    raw = '{"candidates":[{"content":{"parts":[{"functionCall":{"name":"lookup","args":{"key":"A","key":"B"}}}]},"finishReason":"STOP"}]}'
    with pytest.raises(ValueError):
        adapter._parse(raw)
    result = adapter._parse(
        json.dumps(candidate([{"functionCall": {"name": "lookup", "args": {}, "id": "a"}}]))
    )
    with pytest.raises(ValidationError):
        adapter.validate_request(
            [
                {"role": "user", "content": "q"},
                assistant(result),
                {"role": "tool", "tool_call_id": "a", "content": '{"stock":1,"stock":2}'},
            ],
            [TOOL],
        )
