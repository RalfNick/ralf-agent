import asyncio
import copy
import json

import httpx
import pytest

from relf_agent.errors import ProviderError, ValidationError
from relf_agent.model_continuation import ContinuedModelResponse
from relf_agent.model_protocol import ModelCapabilities

from .test_deepseek_thinking import TOOL, USAGE, assistant, provider


def frame(delta, finish=None, usage=None):
    return {
        "id": "stream-fixture",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "fixture",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish, "logprobs": None}],
        "usage": usage,
    }


def stream_bytes(frames, *, done=True):
    chunks = ["data: " + json.dumps(item) + "\n\n" for item in frames]
    if done:
        chunks.append("data: [DONE]\n\n")
    return "".join(chunks).encode()


def final_frames():
    return [
        frame({"role": "assistant", "reasoning_content": "private "}),
        frame({"reasoning_content": "reasoning"}),
        frame({"content": "done"}),
        frame({"role": None, "content": ""}, "stop", USAGE),
    ]


def tool_frames():
    return [
        frame({"role": "assistant", "reasoning_content": "private "}),
        frame({"reasoning_content": "reasoning", "content": "Checking "}),
        frame(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "a",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": ' { "key" : '},
                    },
                    {
                        "index": 1,
                        "id": "b",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"key":'},
                    },
                ]
            }
        ),
        frame(
            {
                "content": "inventory",
                "tool_calls": [
                    {"index": 1, "function": {"arguments": '"B"}'}},
                    {"index": 0, "function": {"arguments": '"A" } '}},
                ],
            }
        ),
        frame({}, "tool_calls"),
        {"choices": [], "usage": USAGE},
    ]


@pytest.mark.parametrize("tools", [False, True])
def test_sse_accumulates_native_reasoning_without_exposing_it_as_text(tools):
    bodies = []

    def reply(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=stream_bytes(tool_frames() if tools else final_frames()),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            adapter = provider(client=client)
            events = [
                event
                async for event in adapter.stream(
                    [{"role": "user", "content": "q"}], [TOOL] if tools else []
                )
            ]
            assert [e.kind for e in events] == (
                ["text", "text", "response"] if tools else ["text", "response"]
            )
            assert "".join(e.text for e in events) == ("Checking inventory" if tools else "done")
            result = events[-1].response
            assert isinstance(result, ContinuedModelResponse)
            assert result.usage == {"input_tokens": 3, "output_tokens": 4}
            message = result.continuation.data["message"]
            assert message["reasoning_content"] == "private reasoning"
            assert message["role"] == "assistant"
            if tools:
                assert message["tool_calls"] == [
                    {
                        "id": "a",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": ' { "key" : "A" } '},
                    },
                    {
                        "id": "b",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"key":"B"}'},
                    },
                ]
                transcript = [
                    {"role": "user", "content": "q"},
                    assistant(result),
                    {"role": "tool", "tool_call_id": "a", "content": "one"},
                    {"role": "tool", "tool_call_id": "b", "content": "two"},
                ]
                _, body, _, _ = adapter._prepared(transcript, [TOOL])
                assert body["messages"][1] == message
            assert bodies[0]["stream"] is True
            assert bodies[0]["stream_options"] == {"include_usage": True}
            assert bodies[0]["thinking"] == {"type": "enabled"}

    asyncio.run(run())


def test_complete_with_stream_enabled_returns_only_finished_continued_response():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=stream_bytes(final_frames()))
            )
        ) as client:
            result = await provider(client=client, stream=True).complete(
                [{"role": "user", "content": "q"}], []
            )
            assert isinstance(result, ContinuedModelResponse)
            assert result.output == "done"
            assert result.continuation.data == {
                "message": {
                    "role": "assistant",
                    "content": "done",
                    "reasoning_content": "private reasoning",
                }
            }

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation",
    [
        "no_done",
        "no_finish",
        "length",
        "no_reasoning",
        "bad_reasoning",
        "private_only",
        "extra_delta",
        "extra_call",
        "extra_function",
        "unknown_role",
        "multiple_choices",
        "bad_index",
        "boolean_index",
        "duplicate_call",
        "sparse_call",
        "late_content",
        "late_finish",
        "bad_usage",
        "error",
        "bad_json",
        "unterminated",
        "after_done",
        "duplicate_arguments",
        "wrong_finish",
        "changed_id",
        "changed_name",
        "duplicate_usage",
    ],
)
def test_invalid_stream_never_yields_a_completed_business_decision(mutation):
    frames = copy.deepcopy(tool_frames())
    done = True
    if mutation == "no_done":
        done = False
    elif mutation == "no_finish":
        frames.pop(4)
    elif mutation in {"length", "wrong_finish"}:
        frames[4]["choices"][0]["finish_reason"] = "length" if mutation == "length" else "stop"
    elif mutation == "no_reasoning":
        frames[0]["choices"][0]["delta"].pop("reasoning_content")
        frames[1]["choices"][0]["delta"].pop("reasoning_content")
    elif mutation == "bad_reasoning":
        frames[0]["choices"][0]["delta"]["reasoning_content"] = {}
    elif mutation == "private_only":
        frames = [frame({"role": "assistant", "reasoning_content": "private"}), frame({}, "stop")]
    elif mutation == "extra_delta":
        frames[1]["choices"][0]["delta"]["audio"] = {"data": "lost"}
    elif mutation == "extra_call":
        frames[2]["choices"][0]["delta"]["tool_calls"][0]["extra"] = True
    elif mutation == "extra_function":
        frames[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["extra"] = True
    elif mutation == "unknown_role":
        frames[0]["choices"][0]["delta"]["role"] = "user"
    elif mutation == "multiple_choices":
        frames[0]["choices"].append(copy.deepcopy(frames[0]["choices"][0]))
    elif mutation in {"bad_index", "boolean_index"}:
        frames[0]["choices"][0]["index"] = 1 if mutation == "bad_index" else False
    elif mutation == "duplicate_call":
        frames[2]["choices"][0]["delta"]["tool_calls"][1]["id"] = "a"
    elif mutation == "sparse_call":
        frames[2]["choices"][0]["delta"]["tool_calls"][1]["index"] = 2
        frames[3]["choices"][0]["delta"]["tool_calls"][0]["index"] = 2
    elif mutation == "late_content":
        frames.append(frame({"content": "late"}))
    elif mutation == "late_finish":
        frames.append(frame({}, "stop"))
    elif mutation == "bad_usage":
        frames[-1]["usage"]["completion_tokens"] = True
    elif mutation == "error":
        frames.append({"error": {"message": "failed"}})
    elif mutation == "duplicate_arguments":
        frames[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] = (
            '{"key":"one","key":'
        )
    elif mutation in {"changed_id", "changed_name"}:
        item = frames[3]["choices"][0]["delta"]["tool_calls"][1]
        if mutation == "changed_id":
            item["id"] = "changed"
        else:
            item["function"]["name"] = "other"
    elif mutation == "duplicate_usage":
        frames.append(
            {"choices": [], "usage": {**USAGE, "completion_tokens": 5, "total_tokens": 8}}
        )
    payload = stream_bytes(frames, done=done)
    if mutation == "bad_json":
        payload = b'data: {"choices":[],"choices":[]}\n\n'
    elif mutation == "unterminated":
        payload = payload[:-1]
    elif mutation == "after_done":
        payload += b"data: [DONE]\n\n"

    async def run():
        events = []
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload))
        ) as client:
            with pytest.raises(ProviderError):
                async for event in provider(client=client).stream(
                    [{"role": "user", "content": "q"}], [TOOL]
                ):
                    events.append(event)
        assert not any(e.kind == "response" for e in events)

    asyncio.run(run())


def test_reasoning_continuation_utf8_limit_applies_to_sse_without_summarizing():
    frames = [
        frame({"role": "assistant", "reasoning_content": "思" * 45000}),
        frame({"content": "done"}, "stop"),
    ]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=stream_bytes(frames))
            )
        ) as client:
            with pytest.raises(ProviderError):
                await provider(client=client, stream=True).complete(
                    [{"role": "user", "content": "q"}], []
                )

    asyncio.run(run())


def test_sse_frame_and_total_response_limits_are_reused(monkeypatch):
    monkeypatch.setattr("relf_agent.model_http.MAX_FRAME_BYTES", 500)
    frames = [
        frame({"role": "assistant", "reasoning_content": "a" * 1000}),
        frame({"content": "done"}, "stop"),
    ]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=stream_bytes(frames))
            )
        ) as client:
            with pytest.raises(ProviderError):
                await provider(client=client, stream=True).complete(
                    [{"role": "user", "content": "q"}], []
                )
        monkeypatch.setattr("relf_agent.model_http.MAX_FRAME_BYTES", 1000000)
        monkeypatch.setattr("relf_agent.model_http.MAX_STREAM_BYTES", 500)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=stream_bytes(frames))
            )
        ) as client:
            with pytest.raises(ProviderError):
                await provider(client=client, stream=True).complete(
                    [{"role": "user", "content": "q"}], []
                )

    asyncio.run(run())


def test_stream_and_tool_capabilities_are_enforced_before_request():
    adapter = provider(capabilities=ModelCapabilities(tools=False, streaming=False))
    with pytest.raises(ValidationError):
        adapter.validate_request([{"role": "user", "content": "q"}], [TOOL])
    with pytest.raises(ValidationError):
        adapter._prepared([{"role": "user", "content": "q"}], [], streaming=True)


@pytest.mark.parametrize("count", [256, 257])
def test_stream_call_count_is_bounded_by_complete_history_receipt_contract(count):
    deltas = [
        {
            "index": i,
            "id": f"call-{i}",
            "type": "function",
            "function": {"name": "lookup", "arguments": "{}"},
        }
        for i in range(count)
    ]
    frames = [
        frame({"role": "assistant", "reasoning_content": "", "tool_calls": deltas}),
        frame({}, "tool_calls"),
    ]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=stream_bytes(frames))
            )
        ) as client:
            adapter = provider(client=client, stream=True)
            if count == 257:
                with pytest.raises(ProviderError):
                    await adapter.complete([{"role": "user", "content": "q"}], [TOOL])
            else:
                result = await adapter.complete([{"role": "user", "content": "q"}], [TOOL])
                assert len(result.tool_calls) == 256
                assert result.continuation.data["message"]["tool_calls"][-1]["id"] == "call-255"

    asyncio.run(run())


@pytest.mark.parametrize("tools", [False, True])
def test_sse_explicit_null_reasoning_is_preserved_without_becoming_text(tools):
    frames = tool_frames() if tools else final_frames()
    for item in frames:
        for choice in item["choices"]:
            if "reasoning_content" in choice["delta"]:
                choice["delta"]["reasoning_content"] = None

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=stream_bytes(frames))
            )
        ) as client:
            adapter = provider(client=client)
            events = [
                event
                async for event in adapter.stream(
                    [{"role": "user", "content": "q"}], [TOOL] if tools else []
                )
            ]
            result = events[-1].response
            assert isinstance(result, ContinuedModelResponse)
            message = result.continuation.data["message"]
            assert "reasoning_content" in message and message["reasoning_content"] is None
            assert "".join(event.text for event in events) == (
                "Checking inventory" if tools else "done"
            )
            transcript = [{"role": "user", "content": "q"}, assistant(result)]
            if tools:
                transcript.extend(
                    [
                        {"role": "tool", "tool_call_id": "a", "content": "one"},
                        {"role": "tool", "tool_call_id": "b", "content": "two"},
                    ]
                )
            _, body, _, _ = adapter._prepared(transcript, [TOOL] if tools else [])
            assert body["messages"][1] == message

    asyncio.run(run())
