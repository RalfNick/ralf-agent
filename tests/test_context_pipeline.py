import importlib
from contextlib import contextmanager

import pytest

from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.types import canonical, digest


def api():
    return importlib.import_module("relf_agent.context_pipeline")


def history():
    return [
        {"role": "system", "content": "Keep the required policy"},
        {"role": "user", "content": "Diagnose pool errors"},
        {"role": "assistant", "content": "Old evidence " * 400},
        {
            "role": "assistant",
            "tool_calls": [{"id": "old", "function": {"name": "read", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "old", "content": "old diagnosis"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "latest", "function": {"name": "verify", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "latest", "content": "confirmed latest evidence"},
    ]


def test_default_budget_keeps_complete_groups_and_does_not_mutate_history():
    h = history()
    before = digest(h)
    messages, manifest = api().BudgetedContextAssembler().assemble(h, [], 700)
    assert messages[:2] == h[:2] and messages[-2:] == h[-2:]
    assert digest(h) == before and manifest["dropped_groups"] >= 1
    assert manifest["digest"] == digest(messages)
    assert manifest["measurement"] == {
        "units": len(canonical(messages)),
        "unit": "canonical-chars",
        "estimated": False,
    }


def test_explicit_excerpt_summary_is_evidence_with_coverage_not_a_system_instruction():
    a = api()
    builder = a.BudgetedContextAssembler(
        summarizer=a.ExcerptContextSummarizer(), summary_max_chars=500
    )
    h = history()
    messages, manifest = builder.assemble(h, [], 1200)
    assert messages[:2] == h[:2] and messages[-2:] == h[-2:]
    assert (
        messages[2]["role"] == "user" and "untrusted historical evidence" in messages[2]["content"]
    )
    assert manifest["summary"]["included"] is True
    assert manifest["summary"]["group_digests"] == [digest([h[2]])]
    assert len(canonical(messages)) <= 1200


def test_optional_summary_and_memory_never_displace_latest_evidence():
    a = api()
    h = history()
    builder = a.BudgetedContextAssembler(summarizer=a.ExcerptContextSummarizer())
    messages, manifest = builder.assemble(h, [{"key": "big", "value": "x" * 2000}], 430)
    assert messages[:2] == h[:2] and messages[-2:] == h[-2:]
    assert manifest["summary"]["included"] is False and manifest["dropped_references"] == 1


def test_explicit_token_estimator_and_replaceable_exact_counter():
    a = api()
    h = history()[:2]
    h[1]["content"] = "中文" * 100
    messages, manifest = a.BudgetedContextAssembler(
        counter=a.UTF8TokenEstimator(), max_units=500
    ).assemble(h, [], 1000)
    assert (
        manifest["measurement"]["unit"] == "estimated-tokens"
        and manifest["measurement"]["estimated"]
    )
    assert messages == h

    class Exact:
        identity = {"kind": "application-tokenizer", "model": "fixture", "version": "1"}

        def count(self, messages):
            return a.ContextMeasure(len(canonical(messages).encode()), "fixture-tokens", False)

    with pytest.raises(ValidationError):
        a.BudgetedContextAssembler(counter=Exact(), max_units=100).assemble(h, [], 1000)


@pytest.mark.parametrize("value", [True, -1, 1.2, float("nan"), "7"])
def test_measure_rejects_nonfinite_and_noninteger_counts(value):
    with pytest.raises(ValidationError):
        api().ContextMeasure(value, "tokens", True)


@pytest.mark.parametrize("kind", ["dangling", "missing", "duplicate", "unknown", "tool-only"])
def test_invalid_tool_groups_are_rejected(kind):
    h = history()
    if kind == "dangling":
        h.pop()
    elif kind == "missing":
        h.pop(4)
    elif kind == "duplicate":
        h.append(h[-1].copy())
    elif kind == "unknown":
        h[-1]["tool_call_id"] = "foreign"
    else:
        h = h[:2] + h[-1:]
    with pytest.raises(ValidationError):
        api().BudgetedContextAssembler().assemble(h, [], 10000)


@pytest.mark.parametrize("selection", [[], [True], [2, 2], [2, 0], [0], [9], "2"])
def test_budgeter_proposals_cannot_duplicate_reorder_or_omit_latest(selection):
    class Invalid:
        identity = {"kind": "invalid", "version": "1"}

        def select(self, head, groups, **kwargs):
            return selection

    with pytest.raises(ValidationError):
        api().BudgetedContextAssembler(budgeter=Invalid()).assemble(history(), [], 10000)


def test_detached_plugin_inputs_and_changed_identity_are_checked():
    a = api()

    class Mutator:
        identity = {"kind": "mutator", "version": "1"}

        def select(self, head, groups, **kwargs):
            head[0]["content"] = "injected policy"
            groups[-1][0]["tool_calls"] = []
            return [len(groups) - 1]

    h = history()
    messages, _ = a.BudgetedContextAssembler(budgeter=Mutator()).assemble(h, [], 10000)
    assert messages[:2] == h[:2] and messages[-2:] == h[-2:]

    class Changing(a.CanonicalCharacterCounter):
        identity = {"kind": "changing", "version": "1"}

        def count(self, messages):
            self.identity = {"kind": "changing", "version": "2"}
            return super().count(messages)

    with pytest.raises(DefinitionMismatch):
        a.BudgetedContextAssembler(counter=Changing()).assemble(h, [], 10000)


def test_lazy_and_async_counter_returns_are_rejected_without_entering():
    a = api()
    entered = []

    class Lazy:
        identity = {"kind": "lazy", "version": "1"}

        @contextmanager
        def count(self, messages):
            entered.append(True)
            yield a.ContextMeasure(0, "tokens", True)

    with pytest.raises(ValidationError):
        a.BudgetedContextAssembler(counter=Lazy()).assemble(history()[:2], [], 1000)
    assert entered == []

    class Async:
        identity = {"kind": "async", "version": "1"}

        async def count(self, messages):
            return a.ContextMeasure(0, "tokens", True)

    with pytest.raises(ValidationError):
        a.BudgetedContextAssembler(counter=Async())


def test_summary_coverage_cannot_claim_unrelated_evidence():
    a = api()

    class Invalid:
        identity = {"kind": "invented-coverage", "version": "1"}

        def summarize(self, groups, **kwargs):
            return a.ContextSummary("made up", ("0" * 64,))

    with pytest.raises(ValidationError):
        a.BudgetedContextAssembler(summarizer=Invalid()).assemble(history(), [], 1200)


def test_latest_oversize_and_invalid_budgets_fail_instead_of_truncating():
    a = api()
    h = history()
    h[-1]["content"] = "x" * 5000
    with pytest.raises(ValidationError):
        a.BudgetedContextAssembler().assemble(h, [], 1000)
    for kw in [{"max_units": True}, {"max_units": 0}, {"summary_max_chars": 1000000}]:
        with pytest.raises(ValidationError):
            a.BudgetedContextAssembler(**kw)
