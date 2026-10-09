import asyncio
import copy

import pytest

from ralf_agent import (
    BudgetedContextAssembler,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import ValidationError
from ralf_agent.types import digest

GROUPS = [[{"role": "assistant", "content": "User selected zh-CN; ticket remains unresolved."}]]


class SummaryProvider:
    identity = {"kind": "model-summary-fixture", "version": "1"}

    def __init__(self, output=None):
        self.calls = 0
        self.output = {"text": "Language: zh-CN. Ticket unresolved."} if output is None else output

    async def complete(self, messages, tools):
        self.calls += 1
        assert tools == []
        return ModelResponse(output=self.output, usage={"input_tokens": 25, "output_tokens": 10})


def test_managed_summary_restart_and_host_assigned_coverage(tmp_path):
    from ralf_agent.model_context import FrozenContextSummarizer, ManagedModelSummarizer

    async def run():
        provider = SummaryProvider()
        groups = copy.deepcopy(GROUPS)
        path = tmp_path / "run.sqlite"
        for _ in range(2):
            with LocalEngine(
                SQLiteStore(path), providers={"default": provider}, tools=ToolRegistry()
            ) as engine:
                summary = await ManagedModelSummarizer().summarize(
                    engine, groups, command_id="summary", max_chars=128
                )
                assert summary.summary.group_digests == tuple(digest(g) for g in GROUPS)
                assert engine.status(summary.run_id).state == "succeeded"
                assert engine.diagnostics(summary.run_id).budget["spent"] == 1
                frozen = FrozenContextSummarizer(summary)
                groups[0][0]["content"] = "mutated"
                assert (
                    frozen.summarize(copy.deepcopy(GROUPS), max_chars=128).text
                    == "Language: zh-CN. Ticket unresolved."
                )
                with pytest.raises(ValidationError):
                    frozen.summarize(groups, max_chars=128)
                groups = copy.deepcopy(GROUPS)
        assert provider.calls == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "output",
    [{"text": ""}, {"text": "  "}, {"text": "x" * 129}, {"text": "ok", "group_digests": []}],
)
def test_model_summary_invalid_completion_not_adopted(tmp_path, output):
    from ralf_agent.model_context import ManagedModelSummarizer

    async def run():
        with LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": SummaryProvider(output)},
            tools=ToolRegistry(),
        ) as engine:
            with pytest.raises(ValidationError):
                await ManagedModelSummarizer().summarize(
                    engine, GROUPS, command_id="summary", max_chars=128
                )

    asyncio.run(run())


def test_frozen_summary_is_used_by_pure_budgeted_builder(tmp_path):
    from ralf_agent.model_context import FrozenContextSummarizer, ManagedModelSummarizer

    async def run():
        provider = SummaryProvider()
        # Oversized historical evidence is summarized explicitly before assembly.
        old = [[{"role": "assistant", "content": "x" * 2500}]]
        with LocalEngine(
            SQLiteStore(tmp_path / "run.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
        ) as engine:
            result = await ManagedModelSummarizer().summarize(engine, old, command_id="summary")
            builder = BudgetedContextAssembler(
                summarizer=FrozenContextSummarizer(result), summary_max_chars=128
            )
            history = [
                {"role": "system", "content": "Answer"},
                {"role": "user", "content": "Task"},
                *old[0],
                {"role": "assistant", "content": "newest"},
            ]
            messages, manifest = builder.assemble(history, [], 800)
            assert manifest["summary"]["included"] and manifest["dropped_groups"] == 1
            assert "untrusted" in messages[2]["content"]
            assert messages[-1]["content"] == "newest" and provider.calls == 1

    asyncio.run(run())
