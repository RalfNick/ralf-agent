import asyncio
import copy
from contextlib import aclosing

import httpx
import pytest

from relf_agent.errors import ProviderError

from .test_responses_provider import frames
from .test_responses_reasoning import call, completed, message, provider, reasoning


def sequence():
    comment = message("working", identifier="msg_comment", phase="commentary")
    final = message("done", phase="final_answer")
    rs = reasoning(
        summary=[{"type": "summary_text", "text": "private summary"}],
        content=[{"type": "reasoning_text", "text": "private reasoning"}],
    )
    output = [rs, comment, final, call()]
    return [
        {"type": "response.created", "response": {"id": "resp_1"}},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                **rs,
                "summary": [],
                "content": [],
                "encrypted_content": "partial",
                "status": "in_progress",
            },
        },
        {
            "type": "response.reasoning_summary_part.added",
            "output_index": 0,
            "summary_index": 0,
            "item_id": "rs_1",
            "part": {"type": "summary_text", "text": ""},
        },
        {
            "type": "response.reasoning_summary_text.delta",
            "output_index": 0,
            "summary_index": 0,
            "item_id": "rs_1",
            "delta": "private summary",
        },
        {
            "type": "response.reasoning_summary_text.done",
            "output_index": 0,
            "summary_index": 0,
            "item_id": "rs_1",
            "text": "private summary",
        },
        {
            "type": "response.reasoning_summary_part.done",
            "output_index": 0,
            "summary_index": 0,
            "item_id": "rs_1",
            "part": rs["summary"][0],
        },
        {
            "type": "response.reasoning_text.delta",
            "output_index": 0,
            "content_index": 0,
            "item_id": "rs_1",
            "delta": "private reasoning",
        },
        {
            "type": "response.reasoning_text.done",
            "output_index": 0,
            "content_index": 0,
            "item_id": "rs_1",
            "text": "private reasoning",
        },
        {"type": "response.output_item.done", "output_index": 0, "item": rs},
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {**comment, "content": [], "status": "in_progress"},
        },
        {
            "type": "response.output_text.delta",
            "output_index": 1,
            "content_index": 0,
            "item_id": "msg_comment",
            "delta": "working",
        },
        {"type": "response.output_item.done", "output_index": 1, "item": comment},
        {
            "type": "response.output_item.added",
            "output_index": 2,
            "item": {**final, "content": [], "status": "in_progress"},
        },
        {
            "type": "response.content_part.added",
            "output_index": 2,
            "content_index": 0,
            "item_id": "msg_1",
            "part": {"type": "output_text", "text": "", "annotations": [], "logprobs": []},
        },
        {
            "type": "response.output_text.delta",
            "output_index": 2,
            "content_index": 0,
            "item_id": "msg_1",
            "delta": "do",
        },
        {
            "type": "response.output_text.delta",
            "output_index": 2,
            "content_index": 0,
            "item_id": "msg_1",
            "delta": "ne",
        },
        {
            "type": "response.output_text.done",
            "output_index": 2,
            "content_index": 0,
            "item_id": "msg_1",
            "text": "done",
        },
        {
            "type": "response.content_part.done",
            "output_index": 2,
            "content_index": 0,
            "item_id": "msg_1",
            "part": final["content"][0],
        },
        {"type": "response.output_item.done", "output_index": 2, "item": final},
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 3,
            "item_id": "fc_1",
            "delta": ' { "key" : "A" } ',
        },
        {
            "type": "response.function_call_arguments.done",
            "output_index": 3,
            "item_id": "fc_1",
            "arguments": ' { "key" : "A" } ',
        },
        {"type": "response.output_item.done", "output_index": 3, "item": output[3]},
        {"type": "response.completed", "response": completed(output)},
    ]


def consume(events):
    async def run():
        transport = frames(events)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=transport))
        ) as client:
            async with aclosing(provider(client=client).stream([], [])) as values:
                try:
                    observed = [event async for event in values]
                except ProviderError as exc:
                    pytest.fail(f"Complete reasoning stream must be accepted: {exc}")
            assert not client.is_closed
        assert transport.closed
        return observed

    return asyncio.run(run())


def test_complete_reasoning_stream_uses_done_encryption_and_hides_commentary():
    observed = consume(sequence())
    assert [event.text for event in observed if event.kind == "text"] == ["do", "ne"]
    result = observed[-1].response
    assert result.output == "done" and result.tool_calls[0].arguments == {"key": "A"}
    assert result.continuation.data["output"][0]["encrypted_content"] == "opaque-final"
    assert result.continuation.data["output"][1]["phase"] == "commentary"


def test_complete_snapshot_without_intermediate_events_is_sufficient():
    observed = consume([{"type": "response.completed", "response": completed()}])
    assert len(observed) == 1 and observed[0].response.output == "done"


def test_unclassified_text_delta_is_not_exposed_until_final_phase_is_known():
    output = [message("working", phase="commentary"), call()]
    observed = consume(
        [
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_1",
                "delta": "working",
            },
            {"type": "response.completed", "response": completed(output)},
        ]
    )
    assert [event.kind for event in observed] == ["response"]
    assert observed[0].response.output is None


@pytest.mark.parametrize("phase,expected", [("commentary", []), ("final_answer", ["working"])])
def test_phase_omitted_from_added_item_is_classified_by_complete_snapshot(phase, expected):
    initial = message("", identifier="msg_1")
    initial.update(status="in_progress", content=[])
    output = [message("working", phase=phase), call()]
    observed = consume(
        [
            {"type": "response.output_item.added", "output_index": 0, "item": initial},
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_1",
                "delta": "working",
            },
            {"type": "response.completed", "response": completed(output)},
        ]
    )
    assert [event.text for event in observed if event.kind == "text"] == expected
    assert observed[-1].response.continuation.data["output"][0]["phase"] == phase


def test_unknown_phase_buffer_preserves_original_text_delta_order():
    final = message("world", identifier="msg_2", phase="final_answer")
    observed = consume(
        [
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_1",
                "delta": "hello ",
            },
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {**final, "content": [], "status": "in_progress"},
            },
            {
                "type": "response.output_text.delta",
                "output_index": 1,
                "content_index": 0,
                "item_id": "msg_2",
                "delta": "world",
            },
            {"type": "response.completed", "response": completed([message("hello "), final])},
        ]
    )
    assert [event.text for event in observed if event.kind == "text"] == ["hello ", "world"]
    assert observed[-1].response.output == "hello world"


def test_partial_response_snapshots_accept_empty_items_and_benign_response_metadata():
    raw = [reasoning(), call()]
    initial = completed(
        [
            reasoning(encrypted_content=None, content=None, status="in_progress"),
            call(arguments="", status="in_progress"),
        ],
        status="in_progress",
        created_at=1,
        model="fixture",
        tools=[],
    )
    observed = consume(
        [
            {"type": "response.created", "response": initial},
            {"type": "response.in_progress", "response": initial},
            {"type": "response.completed", "response": completed(raw)},
        ]
    )
    assert observed[-1].response.tool_calls[0].arguments == {"key": "A"}


def test_documented_delta_obfuscation_is_accepted_without_exposing_padding():
    events = sequence()
    events[14].update(obfuscation="padding", logprobs=[])
    observed = consume(events)
    assert [event.text for event in observed if event.kind == "text"] == ["do", "ne"]


@pytest.mark.parametrize(
    "index,extension",
    [
        (14, {"obfuscation": []}),
        (3, {"name": "foreign"}),
        (5, {"caller": {"type": "program"}}),
        (13, {"call_id": "foreign"}),
        (8, {"status": "incomplete"}),
    ],
)
def test_semantic_event_extensions_and_malformed_padding_are_rejected(index, extension):
    async def run():
        events = sequence()
        events[index].update(extension)
        transport = frames(events)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=transport))
        ) as client:
            with pytest.raises(ProviderError):
                async for _ in provider(client=client).stream([], []):
                    pass
        assert transport.closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation",
    [
        "encryption",
        "summary",
        "reasoning_text",
        "arguments",
        "text",
        "phase",
        "item_id",
        "part",
        "duplicate_done",
        "after_done",
        "after_summary_done",
        "after_arguments_done",
        "after_final",
        "missing_final",
        "failed",
        "incomplete",
        "unsupported",
        "bad_index",
        "bad_sequence",
        "wrong_event",
        "missing_encryption",
        "incomplete_summary",
        "wrong_content_kind",
        "added_field",
        "changed_response_id",
        "text_done_after_item",
        "summary_done_after_item",
        "arguments_done_after_item",
        "part_done_after_item",
        "text_done_after_part",
        "text_done_logprobs",
    ],
)
def test_stream_corruption_never_yields_a_completed_response(mutation):
    async def run():
        events = sequence()
        if mutation == "encryption":
            events[8]["item"] = {**events[8]["item"], "encrypted_content": "different"}
        elif mutation == "summary":
            events[3]["delta"] = "different"
        elif mutation == "reasoning_text":
            events[6]["delta"] = "different"
        elif mutation == "arguments":
            events[19]["delta"] = '{"key":"changed"}'
        elif mutation == "text":
            events[14]["delta"] = "changed"
        elif mutation == "phase":
            events[12]["item"]["phase"] = "commentary"
        elif mutation == "item_id":
            events[14]["item_id"] = "changed"
        elif mutation == "part":
            events[17]["part"] = {"type": "output_text", "text": "changed"}
        elif mutation == "duplicate_done":
            events.insert(9, copy.deepcopy(events[8]))
        elif mutation == "after_done":
            events.insert(9, copy.deepcopy(events[6]))
        elif mutation == "after_summary_done":
            events.insert(5, copy.deepcopy(events[3]))
        elif mutation == "after_arguments_done":
            events.insert(21, copy.deepcopy(events[19]))
        elif mutation == "after_final":
            events.append(copy.deepcopy(events[0]))
        elif mutation == "missing_final":
            events.pop()
        elif mutation in {"failed", "incomplete"}:
            events[-1]["type"] = "response." + mutation
        elif mutation == "unsupported":
            events.insert(
                1,
                {"type": "response.web_search_call.completed", "item_id": "web", "output_index": 0},
            )
        elif mutation == "bad_index":
            events[14]["output_index"] = True
        elif mutation == "bad_sequence":
            events[-1]["sequence_number"] = -1
        elif mutation == "wrong_event":
            events[14]["type"] = "response.reasoning_text.delta"
        elif mutation == "missing_encryption":
            events[-1]["response"]["output"][0].pop("encrypted_content")
        elif mutation == "incomplete_summary":
            events[5]["status"] = "incomplete"
        elif mutation == "wrong_content_kind":
            events[13]["part"]["type"] = "reasoning_text"
        elif mutation == "added_field":
            events[1]["item"]["audio"] = {}
        elif mutation == "text_done_after_item":
            observed = events.pop(16)
            events.insert(18, observed)
        elif mutation == "summary_done_after_item":
            observed = events.pop(4)
            events.insert(8, observed)
        elif mutation == "arguments_done_after_item":
            observed = events.pop(20)
            events.insert(21, observed)
        elif mutation == "part_done_after_item":
            observed = events.pop(17)
            events.insert(18, observed)
        elif mutation == "text_done_after_part":
            observed = events.pop(16)
            events.insert(17, observed)
        elif mutation == "text_done_logprobs":
            events[16]["logprobs"] = [{"token": "secret"}]
        else:
            events[-1]["response"]["id"] = "changed"
        transport = frames(events)
        if mutation == "bad_sequence":
            from .test_model_chat import Frames

            transport = Frames(
                b'event: response.completed\ndata: {"type":"response.completed","sequence_number":-1}\n\n'
            )
        observed = []
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=transport))
        ) as client:
            with pytest.raises(ProviderError):
                async for event in provider(client=client).stream([], []):
                    observed.append(event)
        assert all(event.kind != "response" for event in observed)
        assert transport.closed

    asyncio.run(run())


def test_closing_consumer_early_closes_response_without_accepting_a_decision():
    async def run():
        transport = frames(sequence())
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=transport))
        ) as client:
            async with aclosing(provider(client=client).stream([], [])) as values:
                try:
                    first = await anext(values)
                except ProviderError as exc:
                    pytest.fail(f"Native reasoning must stream before cancellation: {exc}")
                assert first.kind == "text" and first.text == "do"
            assert transport.closed and not client.is_closed

    asyncio.run(run())
