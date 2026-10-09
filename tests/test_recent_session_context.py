"""Optional recall retains recent complete turns without changing stored history."""

import asyncio
import copy

import pytest

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry
from ralf_agent.context import ContextAssembler
from ralf_agent.context_pipeline import BudgetedContextAssembler
from ralf_agent.types import canonical


@pytest.fixture(params=[ContextAssembler, BudgetedContextAssembler])
def builder(request):
    return request.param()


def test_three_runs_recall_recent_session_even_when_all_history_does_not_fit(tmp_path, builder):
    class Echo:
        identity = {"kind": "recent-session-echo", "version": "1"}

        def __init__(self):
            self.requests = []

        async def complete(self, messages, tools):
            self.requests.append(copy.deepcopy(messages))
            return ModelResponse(output=messages[1]["content"])

    async def run():
        provider = Echo()
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
            context_assembler=builder,
        ) as engine:
            for i, value in enumerate(
                ["old-" + "x" * 220, "My current code is 73.", "What is my current code?"]
            ):
                handle = engine.submit(
                    AgentSpec("a", "Answer", max_context_chars=600),
                    value,
                    command_id=str(i),
                    session_id="same",
                )
                assert (await engine.drive(handle.run_id)).state == "succeeded"
            assert "73" in canonical(provider.requests[-1])
            assert "old-" not in canonical(provider.requests[-1])
            assert len(canonical(provider.requests[-1])) <= 600

    asyncio.run(run())


def head():
    return [{"role": "system", "content": "Answer"}, {"role": "user", "content": "Now?"}]


def tool_turn():
    return [
        {"role": "user", "content": "Check"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "c", "function": {"name": "read", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c", "content": "73"},
        {"role": "assistant", "content": "Verified 73"},
    ]


def selected(messages):
    import json

    return json.loads(messages[2]["content"].split("\n", 1)[1])[0]["session"]


def test_whole_recent_tool_turn_is_selected_and_detached(builder):
    history = [
        {"role": "user", "content": "x" * 1000},
        {"role": "assistant", "content": "old"},
    ] + tool_turn()
    references = [{"session": history}]
    before = copy.deepcopy(references)
    messages, manifest = builder.assemble(head(), references, 800)
    assert selected(messages) == tool_turn()
    assert manifest["session_projection"][0]["omitted_messages"] == 2
    messages[2]["content"] = "modified"
    assert references == before


def test_oversized_latest_turn_cannot_be_skipped_to_recall_older_turn(builder):
    references = [
        {
            "session": tool_turn()
            + [{"role": "user", "content": "latest"}, {"role": "assistant", "content": "x" * 1000}]
        }
    ]
    messages, manifest = builder.assemble(head(), references, 800)
    assert messages == head() and manifest["dropped_references"] == 1


@pytest.mark.parametrize(
    "suffix",
    [
        [{"role": "assistant", "tool_calls": [{"id": "dangling"}]}],
        [{"role": "tool", "tool_call_id": "foreign", "content": "unknown"}],
    ],
)
def test_incomplete_recent_tool_evidence_is_not_selected(builder, suffix):
    refs = [
        {
            "session": [
                {"role": "user", "content": "x" * 1000},
                {"role": "assistant", "content": "old"},
            ]
            + tool_turn()
            + suffix
        }
    ]
    messages, _ = builder.assemble(head(), refs, 800)
    assert messages == head()


def test_fitting_references_keep_original_shape_and_order(builder):
    refs = [{"key": "fact", "version": 1, "value": "hi"}, {"session": tool_turn()}]
    messages, manifest = builder.assemble(head(), refs, 2000)
    import json

    assert json.loads(messages[2]["content"].split("\n", 1)[1]) == refs
    assert manifest["dropped_references"] == 0


def test_budgeted_projection_honors_exact_unit_limit():
    refs = [
        {
            "session": [
                {"role": "user", "content": "x" * 1000},
                {"role": "assistant", "content": "old"},
            ]
            + tool_turn()
        }
    ]
    messages, manifest = BudgetedContextAssembler(max_units=800).assemble(head(), refs, 3000)
    assert selected(messages) == tool_turn()
    assert manifest["measurement"]["units"] <= 800
