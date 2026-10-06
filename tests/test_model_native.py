import asyncio
import importlib
import json

import httpx
import pytest

from ralf_agent import AgentSpec, LocalEngine, SQLiteStore, ToolRegistry, ToolSpec
from ralf_agent.errors import ProviderError, ValidationError

from .test_model_chat import Frames


def api():
    return importlib.import_module("ralf_agent.model_native")


TOOL = {
    "type": "function",
    "function": {"name": "lookup", "description": "Look up", "parameters": {"type": "object"}},
}
HISTORY = [
    {"role": "system", "content": "System"},
    {"role": "system", "content": "References"},
    {"role": "user", "content": "q"},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "a",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"id":1}'},
            },
            {
                "id": "b",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"id":2}'},
            },
        ],
    },
    {"role": "tool", "tool_call_id": "a", "content": '{"found":1}'},
    {"role": "tool", "tool_call_id": "b", "content": '{"found":2}'},
]


def test_anthropic_native_text_tools_history_generation_and_cached_usage():
    captured = []

    def reply(request):
        captured.append((request, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "role": "assistant",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "Check"},
                    {"type": "tool_use", "id": "c", "name": "lookup", "input": {"id": 3}},
                ],
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 5,
                    "output_tokens": 4,
                },
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            provider = api().AnthropicProvider(
                "fixture", api_key="secret", client=client, temperature=0.2, stop=["END"]
            )
            result = await provider.complete(HISTORY, [TOOL])
            assert result.tool_calls[0].arguments == {"id": 3}
            assert result.tool_calls[0].call_id == "c"
            assert result.usage == {"input_tokens": 35, "output_tokens": 4}
            assert "secret" not in json.dumps(provider.identity)

    asyncio.run(run())
    request, body = captured[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert (
        request.headers["x-api-key"] == "secret"
        and request.headers["anthropic-version"] == "2023-06-01"
    )
    assert body["system"] == "System\n\nReferences"
    assert body["temperature"] == 0.2 and body["stop_sequences"] == ["END"]
    assert body["messages"][-1] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": '{"found":1}'},
            {"type": "tool_result", "tool_use_id": "b", "content": '{"found":2}'},
        ],
    }
    assert body["tools"] == [
        {"name": "lookup", "description": "Look up", "input_schema": {"type": "object"}}
    ]


def native_sse(items):
    return "".join(
        "event: " + item["type"] + "\ndata: " + json.dumps(item) + "\n\n" for item in items
    ).encode()


def anthropic_events():
    return [
        {
            "type": "message_start",
            "message": {"role": "assistant", "usage": {"input_tokens": 3, "output_tokens": 0}},
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "中文"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "a", "name": "lookup", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"id":'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": "1}"},
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 4},
        },
        {"type": "message_stop"},
    ]


def test_anthropic_stream_reassembles_complete_tools_before_returning():
    body = Frames(native_sse(anthropic_events()))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
        ) as client:
            provider = api().AnthropicProvider(
                "fixture", api_key="dummy", client=client, stream=True
            )
            result = await provider.complete([{"role": "user", "content": "q"}], [TOOL])
            assert result.output == "中文" and result.tool_calls[0].arguments == {"id": 1}
            assert result.usage == {"input_tokens": 3, "output_tokens": 4}

    asyncio.run(run())
    assert body.closed


@pytest.mark.parametrize(
    "mutation", ["missing_stop", "unclosed_block", "length", "error", "bad_json"]
)
def test_anthropic_bad_stream_refuses_partial_result(mutation):
    items = anthropic_events()
    if mutation == "missing_stop":
        items.pop()
    if mutation == "unclosed_block":
        items.pop(7)
    if mutation == "length":
        items[-2]["delta"]["stop_reason"] = "max_tokens"
    if mutation == "error":
        items.append({"type": "error", "error": {"message": "SECRET"}})
    if mutation == "bad_json":
        items[6]["delta"]["partial_json"] = "bad}"
    body = Frames(native_sse(items))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
        ) as client:
            provider = api().AnthropicProvider(
                "fixture", api_key="dummy", client=client, stream=True
            )
            with pytest.raises(ProviderError) as failure:
                await provider.complete([{"role": "user", "content": "q"}], [])
            assert "SECRET" not in str(failure.value)

    asyncio.run(run())
    assert body.closed


@pytest.mark.parametrize(
    "choice",
    [
        {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "partial"}]},
        {"stop_reason": "refusal", "content": [{"type": "text", "text": "no"}]},
        {"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": "hidden"}]},
        {
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "a", "name": "lookup", "input": []}],
        },
    ],
)
def test_anthropic_refuses_unsupported_or_incomplete_response(choice):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"role": "assistant", **choice})
            )
        ) as client:
            with pytest.raises(ProviderError):
                await (
                    api()
                    .AnthropicProvider("fixture", api_key="dummy", client=client)
                    .complete([], [])
                )

    asyncio.run(run())


def gemini_chunk(text, *, reason=None, thoughts=False):
    candidate = {"content": {"role": "model", "parts": [{"text": text, "thought": thoughts}]}}
    if reason is not None:
        candidate["finishReason"] = reason
    return {"candidates": [candidate]}


@pytest.mark.parametrize("streaming", [False, True])
def test_gemini_native_generation_system_text_stream_and_usage(streaming):
    captured = []
    final = gemini_chunk("ok", reason="STOP")
    final["usageMetadata"] = {
        "promptTokenCount": 5,
        "candidatesTokenCount": 2,
        "thoughtsTokenCount": 1,
    }
    if streaming:
        from .test_model_chat import sse

        body = Frames(sse([gemini_chunk("private", thoughts=True), final]))

    def reply(request):
        captured.append((request, json.loads(request.content)))
        return httpx.Response(200, stream=body) if streaming else httpx.Response(200, json=final)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            provider = api().GeminiProvider(
                "fixture",
                api_key="secret",
                client=client,
                stream=streaming,
                temperature=0.2,
                top_p=0.8,
                seed=5,
            )
            result = await provider.complete(HISTORY[:3], [])
            assert result.output == "ok" and result.usage == {"input_tokens": 5, "output_tokens": 3}
            assert not provider.capabilities.tools

    asyncio.run(run())
    request, payload = captured[0]
    assert request.headers["x-goog-api-key"] == "secret" and "secret" not in str(request.url)
    assert payload["systemInstruction"] == {"parts": [{"text": "System\n\nReferences"}]}
    assert payload["generationConfig"] == {
        "maxOutputTokens": 1024,
        "temperature": 0.2,
        "topP": 0.8,
        "seed": 5,
    }
    assert request.url.path.endswith(":streamGenerateContent" if streaming else ":generateContent")
    if streaming:
        assert request.url.params["alt"] == "sse" and body.closed


@pytest.mark.parametrize("messages,tools", [(HISTORY[:3], [TOOL]), (HISTORY, [])])
def test_gemini_tool_capability_is_rejected_before_http(messages, tools):
    captured = []

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: captured.append(request) or httpx.Response(200)
            )
        ) as client:
            provider = api().GeminiProvider("fixture", api_key="dummy", client=client)
            with pytest.raises(ValidationError):
                await provider.complete(messages, tools)

    asyncio.run(run())
    assert not captured


@pytest.mark.parametrize(
    "value",
    [
        gemini_chunk("partial", reason="MAX_TOKENS"),
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {
                                "functionCall": {"name": "lookup", "args": {}},
                                "thoughtSignature": "opaque",
                            }
                        ]
                    },
                }
            ]
        },
    ],
)
def test_gemini_rejects_partial_blocked_or_signed_tool_response(value):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value))
        ) as client:
            with pytest.raises(ProviderError):
                await (
                    api().GeminiProvider("fixture", api_key="dummy", client=client).complete([], [])
                )

    asyncio.run(run())


def test_anthropic_agent_approval_and_tool_round_trip(tmp_path):
    requests, effects = [], []

    def reply(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "role": "assistant",
                    "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "id": "a", "name": "lookup", "input": {}}],
                },
            )
        assert body["messages"][-1]["content"][0]["type"] == "tool_result"
        return httpx.Response(
            200,
            json={
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "done"}],
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            tools = ToolRegistry()
            tools.register(
                ToolSpec("lookup", "Lookup", {"type": "object"}, requires_approval=True),
                lambda args, ctx: effects.append("called") or {"ok": True},
            )
            with LocalEngine(
                SQLiteStore(tmp_path / "native.sqlite"),
                providers={
                    "default": api().AnthropicProvider("fixture", api_key="dummy", client=client)
                },
                tools=tools,
            ) as engine:
                handle = engine.submit(AgentSpec("a", "Answer", ("lookup",)), "q", command_id="s")
                waiting = await engine.drive(handle.run_id)
                assert waiting.state == "waiting_approval" and not effects
                pending = waiting.pending[0]
                engine.approve(
                    handle.run_id, pending["action_id"], pending["digest"], command_id="a"
                )
                assert (await engine.drive(handle.run_id)).result == "done"

    asyncio.run(run())
    assert effects == ["called"] and len(requests) == 2
