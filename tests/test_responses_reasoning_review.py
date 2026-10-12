"""Independent review regressions for observed native Responses evidence."""

import asyncio

import httpx
import pytest

from ralf_agent.errors import ProviderError

from .test_responses_provider import frames
from .test_responses_reasoning import call, completed, provider, reasoning
from .test_responses_reasoning_runtime import wire_response


def assert_stream_rejected(events):
    async def run():
        transport = frames(events)
        observed = []
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=transport))
        ) as client:
            with pytest.raises(ProviderError):
                async for event in provider(client=client).stream([], []):
                    observed.append(event)
        assert not any(event.kind == "response" for event in observed)
        assert transport.closed

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["response.created", "response.in_progress"])
def test_observed_response_snapshot_tool_identity_cannot_change_at_completion(kind):
    observed = completed([reasoning(), call(name="write_inventory")], status="in_progress")
    final = completed([reasoning(), call()])
    assert_stream_rejected(
        [
            {"type": kind, "response": observed},
            {"type": "response.completed", "response": final},
        ]
    )


def test_response_creation_with_failure_evidence_cannot_later_complete():
    assert_stream_rejected(
        [
            {
                "type": "response.created",
                "response": {
                    "id": "resp_1",
                    "status": "failed",
                    "error": {"code": "server_error"},
                    "output": [],
                },
            },
            {"type": "response.completed", "response": completed([reasoning(), call()])},
        ]
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"call_id": "foreign-call"},
        {"name": "write_inventory"},
        {"status": "incomplete"},
        {"caller": {"type": "program", "tool_id": "foreign-program"}},
    ],
)
def test_argument_done_cannot_discard_unsupported_semantic_event_fields(extra):
    assert_stream_rejected(
        [
            {
                "type": "response.function_call_arguments.done",
                "output_index": 1,
                "item_id": "fc_1",
                "arguments": ' { "key" : "A" } ',
                **extra,
            },
            {"type": "response.completed", "response": completed([reasoning(), call()])},
        ]
    )


@pytest.mark.parametrize("stream", [False, True], ids=["json", "sse"])
@pytest.mark.parametrize("nullable", ["reasoning_content", "function_async", "function_status"])
def test_official_neutral_nullable_fields_are_preserved_in_original_output(stream, nullable):
    raw = {
        "reasoning_content": [reasoning(content=None), call()],
        "function_async": [reasoning(), call(**{"async": None})],
        "function_status": [reasoning(), call(status=None)],
    }[nullable]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: wire_response(raw, stream=stream))
        ) as client:
            result = await provider(client=client, stream=stream).complete([], [])
            assert result.continuation.data == {"output": raw}
            assert result.tool_calls[0].name == "lookup"
            assert not client.is_closed

    asyncio.run(run())
