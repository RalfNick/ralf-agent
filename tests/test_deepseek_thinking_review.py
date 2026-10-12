"""Independent review regressions for native name and history identity boundaries."""

import asyncio
import json

import httpx
import pytest

from ralf_agent import (
    AgentSpec,
    CompleteModelHistory,
    DeepSeekThinkingProvider,
    LocalEngine,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
)
from ralf_agent.errors import ValidationError


def _sdk_tool_loop(
    tmp_path,
    length,
    stream,
    *,
    call_id="call-1",
    expected_state="succeeded",
    expected_effects=("read",),
):
    name = "a" * length
    requests, effects = [], []
    tools = ToolRegistry()

    def lookup(arguments, context):
        effects.append("read")
        return {"ok": True}

    tools.register(ToolSpec(name, "Read one record", {"type": "object", "properties": {}}), lookup)

    def reply(request):
        body = json.loads(request.content)
        requests.append(body)
        called = any(message["role"] == "tool" for message in body["messages"])
        call = {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": " {} "},
        }
        message = {
            "role": "assistant",
            "content": "done" if called else None,
            "reasoning_content": "opaque reasoning",
        }
        reason = "stop" if called else "tool_calls"
        if not called:
            message["tool_calls"] = [call]
        if not stream:
            return httpx.Response(
                200,
                json={"choices": [{"index": 0, "message": message, "finish_reason": reason}]},
            )
        delta = dict(message)
        if not called:
            delta["tool_calls"] = [{"index": 0, **call}]
        frames = [
            {"choices": [{"index": 0, "delta": delta}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
        ]
        wire = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames)
        return httpx.Response(200, content=wire + "data: [DONE]\n\n")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            provider = DeepSeekThinkingProvider(
                "fixture", api_key="fixture", client=client, stream=stream
            )
            with LocalEngine(
                SQLiteStore(tmp_path / "review.sqlite"),
                providers={"default": provider},
                tools=tools,
                model_continuation=True,
                model_history=CompleteModelHistory(),
            ) as engine:
                handle = engine.submit(
                    AgentSpec("review", "Read the record.", tools=(name,)), "q", command_id="review"
                )
                result = await engine.drive(handle.run_id)
                assert result.state == expected_state, result
                if expected_state == "succeeded":
                    assert result.result == "done"
                else:
                    record = engine.store.run(handle.run_id)
                    assert not any(action["kind"] == "tool" for action in record["actions"])
                    assert record["error"] == {"code": "provider_error"}
                    assert len(record["actions"]) == 1
                    model = record["actions"][0]
                    assert model["kind"] == "model" and model["status"] == "outcome_unknown"
                    assert "received_response" not in model
                    assert len(model["attempts"]) == 1
                    assert model["attempts"][0]["status"] == "unknown"
                    budget = engine.store.budget(handle.run_id)
                    assert budget["held"] == 1 and budget["spent"] == 0
                    assert len(requests) == 1
                    assert engine.status(handle.run_id).state == "waiting_reconciliation"
                    assert (
                        engine.diagnostics(handle.run_id).snapshot.state == "waiting_reconciliation"
                    )
                    assert engine.store.run(handle.run_id)["actions"] == record["actions"]
                    assert len(requests) == 1
                    # The Provider never retries. A new explicit drive retains
                    # the host's pre-existing model-attempt retry semantics.
                    repeated = await engine.drive(handle.run_id)
                    assert repeated.state == "waiting_reconciliation"
                    retried = engine.store.run(handle.run_id)
                    assert len(retried["actions"]) == 1
                    actual = retried["actions"][0]
                    assert actual["id"] == model["id"]
                    assert actual["kind"] == "model" and actual["status"] == "outcome_unknown"
                    assert actual["attempts"][:1] == model["attempts"]
                    assert len(actual["attempts"]) == 2
                    assert actual["attempts"][1]["status"] == "unknown"
                    assert "received_response" not in actual
                    assert retried["error"] == {"code": "provider_error"}
                    assert engine.store.budget(handle.run_id) == {**budget, "held": 2}
                    assert len(requests) == 2 and requests[0] == requests[1]
        assert effects == list(expected_effects)
        if expected_state == "waiting_reconciliation":
            assert len(requests) == 2
            return
        assert len(requests) == 2
        assistant = next(m for m in requests[1]["messages"] if m["role"] == "assistant")
        assert assistant["tool_calls"][0]["function"]["name"] == name
        assert assistant["tool_calls"][0]["function"]["arguments"] == " {} "
        assert assistant["reasoning_content"] == "opaque reasoning"

    asyncio.run(run())


@pytest.mark.parametrize("length", [65, 128])
@pytest.mark.parametrize("stream", [False, True])
def test_review_documented_function_names_complete_the_sdk_tool_loop(tmp_path, length, stream):
    _sdk_tool_loop(tmp_path, length, stream)


@pytest.mark.parametrize("length", [1024, 1025])
@pytest.mark.parametrize("stream", [False, True])
def test_review_unrepresentable_tool_ids_fail_before_any_tool_effect(tmp_path, length, stream):
    _sdk_tool_loop(
        tmp_path,
        6,
        stream,
        call_id="c" * length,
        expected_state="succeeded" if length == 1024 else "waiting_reconciliation",
        expected_effects=("read",) if length == 1024 else (),
    )


def test_review_function_names_above_documented_limit_fail_before_io():
    provider = DeepSeekThinkingProvider("fixture", api_key="fixture")
    tool = {
        "type": "function",
        "function": {"name": "a" * 129, "parameters": {"type": "object"}},
    }
    with pytest.raises(ValidationError):
        provider.validate_request([{"role": "user", "content": "q"}], [tool])
