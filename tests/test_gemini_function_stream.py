import asyncio
import copy
import json

import httpx
import pytest

from relf_agent import AgentSpec, LocalEngine, SQLiteStore, ToolRegistry, ToolSpec
from relf_agent.errors import ProviderError

from .test_gemini_functions import SIGNED_PARTS, TOOL, assistant, candidate, provider
from .test_model_chat import Frames


def frames(items):
    return "".join("data: " + json.dumps(item) + "\n\n" for item in items).encode()


def chunks():
    return [
        {"candidates": [{"content": {"role": "model", "parts": [SIGNED_PARTS[0]]}}]},
        {"candidates": [{"content": {"role": "model", "parts": SIGNED_PARTS[1:3]}}]},
        {
            "candidates": [
                {"content": {"role": "model", "parts": SIGNED_PARTS[3:]}, "finishReason": "STOP"}
            ]
        },
        {"usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 5}},
    ]


def test_stream_preserves_signed_part_boundaries_and_hides_thoughts_until_complete():
    stream = Frames(frames(chunks()))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            adapter = provider(client=client)
            events = [
                event async for event in adapter.stream([{"role": "user", "content": "q"}], [TOOL])
            ]
            assert [event.text for event in events if event.kind == "text"] == [
                "Checking ",
                "inventory",
            ]
            assert [event.kind for event in events] == ["text", "text", "response"]
            completed = events[-1].response
            assert completed.output == "Checking inventory"
            assert completed.usage == {"input_tokens": 3, "output_tokens": 5}
            assert completed.continuation.to_dict()["data"]["content"] == {
                "role": "model",
                "parts": SIGNED_PARTS,
            }
            assert [call.call_id for call in completed.tool_calls] == ["native-a", "native-b"]

    asyncio.run(run())
    assert stream.closed


def test_separate_stop_frame_then_usage_only_is_complete():
    items = chunks()
    items[2]["candidates"][0].pop("finishReason")
    items.insert(3, {"candidates": [{"finishReason": "STOP"}]})
    stream = Frames(frames(items))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            result = await provider(client=client, stream=True).complete(
                [{"role": "user", "content": "q"}], [TOOL]
            )
            assert result.output == "Checking inventory" and len(result.tool_calls) == 2
            assert result.usage == {"input_tokens": 3, "output_tokens": 5}

    asyncio.run(run())
    assert stream.closed


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_stop",
        "late_content",
        "duplicate_stop",
        "different_stop",
        "length",
        "duplicate_id",
        "argument_fragment",
        "wrong_index",
        "error",
        "blocked",
        "bad_usage",
        "bad_usage_after_finish",
        "empty",
        "event_error",
        "truncated_frame",
    ],
)
def test_stream_failure_never_returns_partial_tool_decision(mutation):
    items = copy.deepcopy(chunks())
    if mutation == "missing_stop":
        items[2]["candidates"][0].pop("finishReason")
    elif mutation == "late_content":
        items.append({"candidates": [{"content": {"parts": [{"text": "late"}]}}]})
    elif mutation in {"duplicate_stop", "different_stop"}:
        items.append(
            {
                "candidates": [
                    {"finishReason": "STOP" if mutation == "duplicate_stop" else "MAX_TOKENS"}
                ]
            }
        )
    elif mutation == "length":
        items[2]["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif mutation == "duplicate_id":
        items[2]["candidates"][0]["content"]["parts"][-1]["functionCall"]["id"] = "native-a"
    elif mutation == "argument_fragment":
        items[1]["candidates"][0]["content"]["parts"][-1]["functionCall"] = {
            "name": "lookup",
            "partialArgs": '{"key":',
        }
    elif mutation == "wrong_index":
        items[1]["candidates"][0]["index"] = 1
    elif mutation == "error":
        items.append({"error": {"message": "PRIVATE"}})
    elif mutation == "blocked":
        items.append(
            {
                "promptFeedback": {"blockReason": "SAFETY"},
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 5},
            }
        )
    elif mutation == "bad_usage":
        items[0]["usageMetadata"] = {"promptTokenCount": True, "candidatesTokenCount": 5}
    elif mutation == "bad_usage_after_finish":
        items[3]["usageMetadata"]["candidatesTokenCount"] = -1
    elif mutation == "empty":
        items = [{"candidates": [{"finishReason": "STOP"}]}]
    payload = frames(items)
    if mutation == "event_error":
        payload = b"event: error\n" + payload
    elif mutation == "truncated_frame":
        payload = payload[:-1]
    stream = Frames(payload)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            observed = []
            with pytest.raises(ProviderError) as failure:
                async for event in provider(client=client).stream(
                    [{"role": "user", "content": "q"}], [TOOL]
                ):
                    observed.append(event)
            assert not any(event.kind == "response" for event in observed)
            assert "PRIVATE" not in str(failure.value)

    asyncio.run(run())
    assert stream.closed


def test_closing_consumer_after_visible_delta_releases_stream_without_decision():
    stream = Frames(frames(chunks()))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            generator = provider(client=client).stream([{"role": "user", "content": "q"}], [TOOL])
            assert (await anext(generator)).text == "Checking "
            await generator.aclose()
            assert not client.is_closed

    asyncio.run(run())
    assert stream.closed


@pytest.mark.parametrize("streaming", [False, True])
def test_real_local_engine_signed_parallel_function_loop(tmp_path, streaming):
    bodies = []
    responses = [candidate(SIGNED_PARTS), candidate([{"text": "done", "thoughtSignature": "c2ln"}])]

    def reply(request):
        bodies.append(json.loads(request.content))
        result = responses.pop(0)
        return (
            httpx.Response(200, stream=Frames(frames([result])))
            if streaming
            else httpx.Response(200, json=result)
        )

    async def run():
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "lookup",
                "Read inventory",
                {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
            ),
            lambda args, ctx: {"stock": 1 if args["key"] == "A" else 2},
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            engine = LocalEngine(
                SQLiteStore(tmp_path / "engine.sqlite3"),
                providers={"default": provider(client=client, stream=streaming)},
                tools=registry,
                model_continuation=True,
            )
            try:
                handle = engine.submit(
                    AgentSpec("inventory", "Read inventory", ("lookup",)), "q", command_id="first"
                )
                result = await engine.drive(handle.run_id)
                assert result.state == "succeeded" and result.result == "done"
                assert len([action for action in result.actions if action["kind"] == "tool"]) == 2
            finally:
                engine.close()

    asyncio.run(run())
    assert bodies[1]["contents"][1] == {"role": "model", "parts": SIGNED_PARTS}
    assert bodies[1]["contents"][2] == {
        "role": "user",
        "parts": [
            {"functionResponse": {"name": "lookup", "id": "native-a", "response": {"stock": 1}}},
            {"functionResponse": {"name": "lookup", "id": "native-b", "response": {"stock": 2}}},
        ],
    }


def test_task_cancellation_closes_network_stream_without_a_decision():
    class BlockingFrames(httpx.AsyncByteStream):
        def __init__(self):
            self.blocked, self.release = asyncio.Event(), asyncio.Event()
            self.closed = False

        async def __aiter__(self):
            yield frames(chunks()[:2])
            self.blocked.set()
            await self.release.wait()
            yield frames(chunks()[2:])

        async def aclose(self):
            self.closed = True

    async def run():
        body = BlockingFrames()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
        ) as client:
            task = asyncio.create_task(
                provider(client=client, stream=True).complete(
                    [{"role": "user", "content": "q"}], [TOOL]
                )
            )
            await body.blocked.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert body.closed and not client.is_closed

    asyncio.run(run())


def test_multistep_native_and_synthetic_calls_form_distinct_complete_groups():
    adapter = provider()
    a = adapter._parse(
        json.dumps(
            candidate([{"functionCall": {"name": "lookup", "args": {"key": "A"}, "id": "native"}}])
        )
    )
    b = adapter._parse(
        json.dumps(candidate([{"functionCall": {"name": "lookup", "args": {"key": "B"}}}]))
    )
    _, body, _, _ = adapter._prepared(
        [
            {"role": "user", "content": "q"},
            assistant(a),
            {"role": "tool", "tool_call_id": "native", "content": '{"stock":1}'},
            assistant(b),
            {"role": "tool", "tool_call_id": b.tool_calls[0].call_id, "content": '{"stock":2}'},
        ],
        [TOOL],
    )
    assert body["contents"][-3]["parts"][0]["functionResponse"]["id"] == "native"
    assert "id" not in body["contents"][-1]["parts"][0]["functionResponse"]


@pytest.mark.parametrize("streaming", [False, True])
def test_repeated_identical_call_without_native_id_runs_in_separate_steps(tmp_path, streaming):
    bodies, effects = [], []
    raw_call = candidate([{"functionCall": {"name": "lookup", "args": {"key": "A"}}}])
    responses = [raw_call, raw_call, candidate([{"text": "done"}])]

    def reply(request):
        bodies.append(json.loads(request.content))
        result = responses.pop(0)
        return (
            httpx.Response(200, stream=Frames(frames([result])))
            if streaming
            else httpx.Response(200, json=result)
        )

    def lookup(args, ctx):
        effects.append(args["key"])
        return {"stock": len(effects)}

    async def run():
        registry = ToolRegistry()
        registry.register(ToolSpec("lookup", "Read inventory", {"type": "object"}), lookup)
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            with LocalEngine(
                SQLiteStore(tmp_path / "repeat.sqlite3"),
                providers={"default": provider(client=client, stream=streaming)},
                tools=registry,
                model_continuation=True,
            ) as engine:
                handle = engine.submit(
                    AgentSpec("inventory", "Read twice", ("lookup",)), "q", command_id="first"
                )
                result = await engine.drive(handle.run_id)
                assert result.state == "succeeded" and result.result == "done"
                assert len([item for item in result.actions if item["kind"] == "tool"]) == 2

    asyncio.run(run())
    assert effects == ["A", "A"] and len(bodies) == 3
    assert bodies[2]["contents"][2]["parts"] == [
        {"functionResponse": {"name": "lookup", "response": {"stock": 1}}}
    ]
    assert bodies[2]["contents"][4]["parts"] == [
        {"functionResponse": {"name": "lookup", "response": {"stock": 2}}}
    ]
