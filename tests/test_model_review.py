"""Independent protocol boundary regressions found during the dev9 review."""

import asyncio
import json

import httpx
import pytest

from ralf_agent.errors import ProviderError, ValidationError
from ralf_agent.model_native import AnthropicProvider, GeminiProvider
from ralf_agent.providers import DeepSeekChatProvider, OpenAIChatProvider


class ReviewFrames(httpx.AsyncByteStream):
    def __init__(self, frames):
        self.frames = frames
        self.closed = False

    async def __aiter__(self):
        for frame in self.frames:
            yield frame

    async def aclose(self):
        self.closed = True


def review_sse(items):
    return [
        ("data: " + (item if isinstance(item, str) else json.dumps(item)) + "\n\n").encode()
        for item in items
    ]


def anthropic_tool_items(partial):
    items = [
        {"type": "message_start", "message": {"role": "assistant"}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "call", "name": "lookup", "input": {}},
        },
    ]
    items.append(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": partial},
        }
    )
    items.extend(
        [
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
            {"type": "message_stop"},
        ]
    )
    return items


def test_anthropic_stream_rejects_empty_json_fragments_after_tool_start():
    frames = ReviewFrames(review_sse(anthropic_tool_items("")))
    events = []

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=frames))
        ) as client:
            provider = AnthropicProvider("fixture", api_key="dummy", client=client)
            with pytest.raises(ProviderError):
                async for event in provider.stream([{"role": "user", "content": "q"}], []):
                    events.append(event)

    asyncio.run(run())
    assert frames.closed
    assert not any(event.kind == "response" for event in events)


def test_anthropic_stream_accepts_complete_empty_object_arguments():
    frames = ReviewFrames(review_sse(anthropic_tool_items("{}")))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=frames))
        ) as client:
            provider = AnthropicProvider("fixture", api_key="dummy", client=client, stream=True)
            result = await provider.complete([{"role": "user", "content": "q"}], [])
            assert result.tool_calls[0].arguments == {}

    asyncio.run(run())
    assert frames.closed


def test_chat_sse_error_event_cannot_publish_tool_proposals():
    items = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call",
                                "function": {"name": "lookup", "arguments": "{}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        "[DONE]",
    ]
    frames = review_sse(items)
    frames.insert(1, b'event: error\ndata: {"choices": []}\n\n')
    body = ReviewFrames(frames)
    events = []

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
        ) as client:
            provider = OpenAIChatProvider("fixture", api_key="dummy", client=client)
            with pytest.raises(ProviderError):
                async for event in provider.stream([{"role": "user", "content": "q"}], []):
                    events.append(event)

    asyncio.run(run())
    assert body.closed
    assert not any(event.kind == "response" for event in events)


@pytest.mark.parametrize(
    "provider_type,payload,streaming",
    [
        (OpenAIChatProvider, {"choices": [[]]}, True),
        (
            GeminiProvider,
            {"candidates": [{"content": [], "finishReason": "STOP"}]},
            False,
        ),
        (
            GeminiProvider,
            {"candidates": [{"content": [], "finishReason": "STOP"}]},
            True,
        ),
        (
            AnthropicProvider,
            {"type": "message_delta", "delta": []},
            True,
        ),
    ],
)
def test_malformed_nested_response_shapes_raise_provider_error(provider_type, payload, streaming):
    if streaming:
        items = [payload]
        if provider_type is AnthropicProvider:
            items.insert(0, {"type": "message_start", "message": {"role": "assistant"}})
        frames = ReviewFrames(review_sse(items))

    def reply(request):
        if streaming:
            return httpx.Response(200, stream=frames)
        return httpx.Response(200, json=payload)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            provider = provider_type("fixture", api_key="dummy", client=client, stream=streaming)
            with pytest.raises(ProviderError):
                await provider.complete([{"role": "user", "content": "q"}], [])

    asyncio.run(run())
    if streaming:
        assert frames.closed


@pytest.mark.parametrize("provider_type", [AnthropicProvider, GeminiProvider])
def test_native_history_rejects_named_speakers_that_cannot_be_represented(provider_type):
    requests = []
    messages = [
        {"role": "user", "name": "alice", "content": "Choose A"},
        {"role": "user", "name": "bob", "content": "Choose B"},
    ]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json={})
            )
        ) as client:
            provider = provider_type("fixture", api_key="dummy", client=client)
            with pytest.raises(ValidationError):
                provider.validate_request(messages, [])

    asyncio.run(run())
    assert not requests


def test_deepseek_non_thinking_preset_rejects_opaque_thinking_history():
    provider = DeepSeekChatProvider("fixture", api_key="dummy")
    with pytest.raises(ValidationError):
        provider.validate_request(
            [{"role": "assistant", "content": "answer", "reasoning_content": "opaque thought"}],
            [],
        )
