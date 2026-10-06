import asyncio

import httpx
import pytest

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    ModelCapabilities,
    ModelResponse,
    OpenAIChatProvider,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import ProviderError

from .test_model_chat import Frames, chunk, sse


@pytest.mark.parametrize("calls,reason", [([1], "tool_calls"), ({}, "stop"), ([], "tool_calls")])
def test_malformed_call_collection_or_finish_reason_is_not_a_valid_response(calls, reason):
    async def run():
        value = {
            "choices": [
                {"finish_reason": reason, "message": {"content": "ok", "tool_calls": calls}}
            ]
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value))
        ) as client:
            with pytest.raises(ProviderError):
                await OpenAIChatProvider("fixture", api_key="dummy", client=client).complete([], [])

    asyncio.run(run())


@pytest.mark.parametrize("streaming", [False, True])
def test_reasoning_tool_continuation_is_never_silently_discarded(streaming):
    call = {"id": "a", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
    if streaming:
        body = Frames(
            sse(
                [
                    chunk({"reasoning_content": "opaque state"}),
                    chunk({"tool_calls": [{"index": 0, **call}]}, finish="tool_calls"),
                    "[DONE]",
                ]
            )
        )
    value = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "reasoning_content": "opaque state",
                    "tool_calls": [call],
                },
            }
        ]
    }

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (
                    httpx.Response(200, stream=body)
                    if streaming
                    else httpx.Response(200, json=value)
                )
            )
        ) as client:
            with pytest.raises(ProviderError):
                await OpenAIChatProvider(
                    "fixture", api_key="dummy", client=client, stream=streaming
                ).complete([], [])

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["frame", "total"])
def test_stream_limits_close_response_and_return_no_complete_proposal(monkeypatch, boundary):
    from ralf_agent import model_http

    if boundary == "frame":
        monkeypatch.setattr(model_http, "MAX_FRAME_BYTES", 40)
    else:
        monkeypatch.setattr(model_http, "MAX_STREAM_BYTES", 40)
    body = Frames(sse([chunk({"content": "a" * 100}, finish="stop"), "[DONE]"]))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
        ) as client:
            with pytest.raises(ProviderError):
                await OpenAIChatProvider(
                    "fixture", api_key="dummy", client=client, stream=True
                ).complete([], [])

    asyncio.run(run())
    assert body.closed


def test_stream_cancellation_closes_actual_connection_and_never_proposes_tools(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        class Blocked(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                yield sse(
                    [
                        chunk(
                            {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "a",
                                        "function": {"name": "lookup", "arguments": '{"x":'},
                                    }
                                ]
                            }
                        )
                    ]
                )
                started.set()
                await release.wait()

            async def aclose(self):
                self.closed = True

        body = Blocked()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
        ) as client:
            provider = OpenAIChatProvider("fixture", api_key="dummy", client=client, stream=True)
            with LocalEngine(
                SQLiteStore(tmp_path / "cancel.sqlite"),
                providers={"default": provider},
                tools=ToolRegistry(),
            ) as engine:
                handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="s")
                driving = asyncio.create_task(engine.drive(handle.run_id))
                await asyncio.wait_for(started.wait(), 2)
                # Cancelling a drive waiter leaves its shielded execution alive.
                # This probe cancels the owned execution Tasks, as loop shutdown does.
                victims = [
                    task for task in asyncio.all_tasks() if task is not asyncio.current_task()
                ]
                for task in victims:
                    task.cancel()
                await asyncio.gather(*victims, return_exceptions=True)
                assert driving.done()
                assert body.closed and not client.is_closed
                run_state = engine.store.run(handle.run_id)
                assert all(action["kind"] == "model" for action in run_state["actions"])
                assert "received_response" not in run_state["actions"][0]
                assert engine.store.budget(handle.run_id)["held"] == 1

    asyncio.run(run())


def test_preflight_identity_mutation_prevents_dispatch_and_reservation(tmp_path):
    async def run():
        class Provider:
            changed = False
            calls = 0

            @property
            def identity(self):
                return {"kind": "preflight-fixture", "changed": self.changed}

            def validate_request(self, messages, tools):
                self.changed = True

            async def complete(self, messages, tools):
                self.calls += 1
                return ModelResponse(output="not called")

        provider = Provider()
        with LocalEngine(
            SQLiteStore(tmp_path / "changed.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            result = await engine.drive(handle.run_id)
            assert result.state == "failed" and not result.actions and not provider.calls
            assert engine.store.budget(handle.run_id)["held"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("streaming", [False, True])
def test_disabled_tool_capability_also_rejects_unsolicited_response_proposals(streaming):
    call = {"id": "a", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
    body = Frames(
        sse([chunk({"tool_calls": [{"index": 0, **call}]}, finish="tool_calls"), "[DONE]"])
    )
    value = {
        "choices": [
            {"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [call]}}
        ]
    }

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (
                    httpx.Response(200, stream=body)
                    if streaming
                    else httpx.Response(200, json=value)
                )
            )
        ) as client:
            provider = OpenAIChatProvider(
                "fixture",
                api_key="dummy",
                client=client,
                stream=streaming,
                capabilities=ModelCapabilities(tools=False),
            )
            with pytest.raises(ProviderError):
                await provider.complete([], [])

    asyncio.run(run())
