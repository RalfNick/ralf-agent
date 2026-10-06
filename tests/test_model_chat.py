import asyncio
import importlib
import json
from contextlib import aclosing

import httpx
import pytest

from ralf_agent import AgentSpec, LocalEngine, SQLiteStore, ToolRegistry, ToolSpec
from ralf_agent.errors import ProviderError, ValidationError
from ralf_agent.providers import OpenAIChatProvider


class Frames(httpx.AsyncByteStream):
    def __init__(self, contents):
        self.contents = contents
        self.closed = False

    async def __aiter__(self):
        for start in range(0, len(self.contents), 7):
            yield self.contents[start : start + 7]

    async def aclose(self):
        self.closed = True


def sse(items):
    return (
        ": keepalive\n\n"
        + "".join(
            "data: "
            + (item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))
            + "\n\n"
            for item in items
        )
    ).encode()


def chunk(delta=None, *, finish=None, usage=None):
    result = {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
    if usage is not None:
        result["usage"] = usage
    return result


def test_default_chat_identity_stays_exact_and_new_configuration_is_detached():
    provider = OpenAIChatProvider("fixture", api_key="dummy")
    assert provider.identity == {
        "kind": "openai-chat-completions",
        "version": "1",
        "model": "fixture",
        "base_url": "https://api.openai.com/v1",
        "max_output_tokens": 1024,
        "token_parameter": "max_completion_tokens",
        "timeout": 60,
    }
    assert provider.capabilities.tools and provider.capabilities.streaming
    provider = OpenAIChatProvider(
        "fixture", api_key="dummy", temperature=0.2, top_p=0.9, stop=["END"], seed=42, stream=True
    )
    snapshot = provider.identity
    assert snapshot["generation"] == {"temperature": 0.2, "top_p": 0.9, "stop": ["END"], "seed": 42}
    assert snapshot["stream"] is True
    snapshot["generation"]["stop"].append("changed")
    assert provider.identity["generation"]["stop"] == ["END"]


def test_chat_generation_configuration_matches_actual_request():
    captured = []

    def reply(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            provider = OpenAIChatProvider(
                "fixture",
                api_key="dummy",
                client=client,
                temperature=0.1,
                top_p=0.8,
                stop="END",
                seed=0,
            )
            assert (await provider.complete([{"role": "user", "content": "q"}], [])).output == "ok"

    asyncio.run(run())
    assert len(captured) == 1
    assert {key: captured[0][key] for key in ["temperature", "top_p", "stop", "seed"]} == {
        "temperature": 0.1,
        "top_p": 0.8,
        "stop": ["END"],
        "seed": 0,
    }


@pytest.mark.parametrize(
    "options",
    [
        {"temperature": True},
        {"temperature": -1},
        {"temperature": float("nan")},
        {"top_p": 2},
        {"seed": True},
        {"stop": [""]},
        {"stop": []},
        {"stream": "true"},
    ],
)
def test_invalid_generation_options_fail_before_http(options):
    with pytest.raises(ValidationError):
        OpenAIChatProvider("fixture", api_key="dummy", **options)


@pytest.mark.parametrize("mode", ["stream", "complete"])
def test_stream_collects_unicode_and_fragmented_parallel_tool_calls_then_usage(mode):
    body = Frames(
        sse(
            [
                chunk({"role": "assistant", "content": "查询"}),
                chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "a",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"id":'},
                            },
                            {
                                "index": 1,
                                "id": "b",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"id":2}'},
                            },
                        ]
                    }
                ),
                chunk({"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}),
                chunk(finish="tool_calls"),
                {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 4}},
                "[DONE]",
            ]
        )
    )
    requests = []

    async def run():
        def reply(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            provider = OpenAIChatProvider("fixture", api_key="dummy", client=client, stream=True)
            if mode == "stream":
                events = [
                    event async for event in provider.stream([{"role": "user", "content": "q"}], [])
                ]
                assert [event.text for event in events if event.kind == "text"] == ["查询"]
                assert [event.kind for event in events].count("response") == 1
                result = events[-1].response
            else:
                result = await provider.complete([{"role": "user", "content": "q"}], [])
            assert [call.arguments for call in result.tool_calls] == [{"id": 1}, {"id": 2}]
            assert [call.call_id for call in result.tool_calls] == ["a", "b"]
            assert result.usage == {"input_tokens": 7, "output_tokens": 4}

    asyncio.run(run())
    assert body.closed and len(requests) == 1
    assert requests[0]["stream"] is True and requests[0]["stream_options"] == {
        "include_usage": True
    }


@pytest.mark.parametrize(
    "items",
    [
        [chunk({"content": "partial"})],
        [chunk({"content": "partial"}, finish="length"), "[DONE]"],
        [chunk({"content": "partial"}, finish="stop")],
        [chunk({"content": "partial"}, finish="stop"), "[DONE]", {"error": {"message": "SECRET"}}],
        [chunk({"content": "partial"}), {"error": {"message": "SECRET"}}],
        ["not JSON", "[DONE]"],
        [
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "a",
                            "function": {"name": "lookup", "arguments": '{"x":NaN}'},
                        }
                    ]
                },
                finish="tool_calls",
            ),
            "[DONE]",
        ],
        [
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "a",
                            "function": {"name": "lookup", "arguments": '{"x":1,"x":2}'},
                        }
                    ]
                },
                finish="tool_calls",
            ),
            "[DONE]",
        ],
        [
            chunk(
                {"content": "ok"},
                finish="stop",
                usage={"prompt_tokens": True, "completion_tokens": 1},
            ),
            "[DONE]",
        ],
    ],
)
def test_invalid_or_unfinished_stream_has_no_final_response_and_closes_connection(items):
    body = Frames(sse(items))
    events = []

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
        ) as client:
            provider = OpenAIChatProvider("fixture", api_key="dummy", client=client)
            with pytest.raises(ProviderError) as failure:
                async for event in provider.stream([{"role": "user", "content": "q"}], []):
                    events.append(event)
            assert "SECRET" not in str(failure.value)

    asyncio.run(run())
    assert body.closed and not [event for event in events if event.kind == "response"]


def test_early_stream_consumer_close_closes_response_but_keeps_injected_client_open():
    body = Frames(
        sse([chunk({"content": "first"}), chunk({"content": "last"}, finish="stop"), "[DONE]"])
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
        ) as client:
            provider = OpenAIChatProvider("fixture", api_key="dummy", client=client)
            async with aclosing(provider.stream([{"role": "user", "content": "q"}], [])) as stream:
                assert (await anext(stream)).text == "first"
            assert body.closed and not client.is_closed

    asyncio.run(run())


def test_capability_refusal_precedes_model_action_reservation(tmp_path):
    api = importlib.import_module("ralf_agent.providers")
    requests = []

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json={})
            )
        ) as client:
            provider = OpenAIChatProvider(
                "fixture",
                api_key="dummy",
                client=client,
                capabilities=api.ModelCapabilities(tools=False),
            )
            tools = ToolRegistry()
            tools.register(ToolSpec("lookup", "Lookup", {"type": "object"}), lambda args, ctx: {})
            with LocalEngine(
                SQLiteStore(tmp_path / "capabilities.sqlite"),
                providers={"default": provider},
                tools=tools,
            ) as engine:
                handle = engine.submit(AgentSpec("a", "Answer", ("lookup",)), "q", command_id="s")
                result = await engine.drive(handle.run_id)
                assert result.state == "failed" and not result.actions
                budget = engine.store.budget(handle.run_id)
                assert budget["spent"] == budget["held"] == 0

    asyncio.run(run())
    assert not requests
