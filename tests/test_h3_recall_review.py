import copy

import pytest

from relf_agent import InMemoryArtifactStore, OverlapReferenceSelector, RelevantDataContext
from relf_agent.types import canonical


def history():
    return [{"role": "system", "content": "Answer"}, {"role": "user", "content": "language"}]


def test_ordinary_fact_key_contributes_to_relevance_under_pressure():
    refs = [
        {"key": "a", "version": 1, "value": "unrelated " * 30},
        {"key": "language", "version": 1, "value": "zh-CN"},
    ]
    assert OverlapReferenceSelector(max_references=1).select("language", refs) == [1]
    messages, _ = RelevantDataContext(InMemoryArtifactStore()).assemble(history(), refs, 520)
    assert "zh-CN" in canonical(messages) and "unrelated" not in canonical(messages)


def test_relevant_fact_competes_with_knowledge_without_reordering_semantic_branch():
    refs = [
        {
            "key": "knowledge:first",
            "version": 1,
            "value": "unrelated knowledge " + "x" * 250,
            "_knowledge": {},
        },
        {"key": "fact", "version": 1, "value": "language zh-CN"},
        {"key": "knowledge:second", "value": "language", "_knowledge": {}},
    ]
    chosen = OverlapReferenceSelector().select("language", refs)
    assert chosen == [1, 0, 2]
    messages, _ = RelevantDataContext(InMemoryArtifactStore()).assemble(history(), refs, 550)
    assert "zh-CN" in canonical(messages)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("phase", ["assembly", "summary-finish"])
def test_session_projection_preserves_originating_task_and_complete_answer(native, phase):
    turn = (
        [{"role": "assistant", "task": "KEEP_REQUEST", "content": "Response " * 150}]
        if native
        else [
            {"role": "user", "content": "KEEP_REQUEST"},
            {"role": "assistant", "content": "Response " * 150},
        ]
    )
    refs = [{"session": turn}]
    original = copy.deepcopy(refs)
    context = RelevantDataContext(InMemoryArtifactStore())
    if phase == "assembly":
        messages, manifest = context.assemble(history(), refs, 5000)
    else:
        source = history() + [
            {"role": "assistant", "content": "old " * 4000},
            {"role": "assistant", "content": "recent"},
        ]
        plan = context.prepare(source, refs, 5000)
        assert plan is not None
        messages, manifest = context.finish(copy.deepcopy(plan), context.excerpt(plan))
    assert refs == original
    assert "KEEP_REQUEST" in canonical(messages) and "Response " * 150 in canonical(messages)
    assert manifest["reference_compression"] == []


def test_oversized_session_keeps_complete_latest_turn_and_projection_evidence():
    turns = [
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "OLD" * 1000},
        {"role": "user", "content": "LATEST_REQUEST"},
        {"role": "assistant", "content": "Response " * 150},
    ]
    messages, manifest = RelevantDataContext(InMemoryArtifactStore()).assemble(
        history(), [{"session": turns}], 1800
    )
    assert "LATEST_REQUEST" in canonical(messages) and "Response " * 150 in canonical(messages)
    assert "old request" not in canonical(messages)
    assert manifest["session_projection"][0]["selected_turns"] == 1


def test_observed_fact_provenance_does_not_dominate_relevance():
    refs = [
        {
            "key": "language-generated-id",
            "value": {
                "trust": "completed-result-observation",
                "value": "weather",
                "run_id": "language",
            },
        },
        {"key": "actual", "value": "language zh-CN"},
    ]
    assert OverlapReferenceSelector(max_references=1).select("language", refs) == [1]
