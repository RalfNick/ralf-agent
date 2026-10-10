import asyncio
import copy
from dataclasses import asdict

import pytest

from ralf_agent import InMemoryArtifactStore
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.types import canonical


def api():
    from ralf_agent import OverlapReferenceSelector, RelevantDataContext

    return OverlapReferenceSelector, RelevantDataContext


def history():
    return [
        {"role": "system", "content": "Answer"},
        {"role": "user", "content": "preferred language"},
    ]


def refs():
    return [
        {"key": "a", "version": 1, "value": "disk snapshot " * 65},
        {"key": "b", "version": 2, "value": "preferred language zh-CN"},
    ]


def test_relevant_fact_wins_context_pressure_without_changing_source():
    _, Context = api()
    values = refs()
    before = copy.deepcopy(values)
    builder = Context(InMemoryArtifactStore())
    messages, manifest = builder.assemble(history(), values, 800)
    assert "zh-CN" in canonical(messages)
    assert values == before
    assert manifest["reference_selection"]["indices"] == [1, 0]
    assert "disk snapshot" not in canonical(messages)


def test_default_selection_preserves_semantic_knowledge_order_and_recent_session():
    Selector, _ = api()
    values = [
        {"key": "semantic", "value": {"text": "unrelated words"}, "_knowledge": {}},
        {"key": "lexical", "value": {"text": "preferred language"}, "_knowledge": {}},
        *refs(),
        {"session": [{"role": "assistant", "task": "old", "content": "zh-CN"}]},
    ]
    assert Selector().select("preferred language", values) == [4, 3, 0, 1, 2]


@pytest.mark.parametrize("choice", [[0, 0], [True], [-1], [8], "0", None])
def test_custom_selector_cannot_fabricate_or_duplicate_evidence(choice):
    _, Context = api()

    class Select:
        identity = {"kind": "invalid-fixture", "version": "1"}

        def select(self, task, references):
            return choice

    builder = Context(InMemoryArtifactStore(), selector=Select())
    with pytest.raises(ValidationError):
        builder.assemble(history(), refs(), 2000)


def test_selector_cannot_modify_detached_candidates_or_return_lazy_result():
    _, Context = api()

    class Mutates:
        identity = {"kind": "mutates-fixture", "version": "1"}

        def select(self, task, references):
            references[0]["value"] = "invented"
            return [0]

    original = refs()
    with pytest.raises(ValidationError):
        Context(InMemoryArtifactStore(), selector=Mutates()).assemble(history(), original, 2000)
    assert original == refs()

    class Lazy:
        identity = {"kind": "lazy-fixture", "version": "1"}

        def select(self, task, references):
            yield 0

    with pytest.raises(ValidationError):
        Context(InMemoryArtifactStore(), selector=Lazy()).assemble(history(), refs(), 2000)


def test_selected_method_and_configuration_cannot_drift():
    Selector, Context = api()
    selector = Selector()
    builder = Context(InMemoryArtifactStore(), selector=selector)
    selector.select = lambda task, refs: [0]
    with pytest.raises(DefinitionMismatch):
        builder.assemble(history(), refs(), 2000)


def test_summary_consumption_uses_saved_selection_without_reselecting():
    _, Context = api()

    class Select:
        identity = {"kind": "calls-fixture", "version": "1"}

        def __init__(self):
            self.calls = 0

        def select(self, task, references):
            self.calls += 1
            return [1]

    selector = Select()
    builder = Context(InMemoryArtifactStore(), selector=selector, summary_max_chars=80)
    messages = history() + [
        {"role": "assistant", "content": "old " * 600},
        {"role": "assistant", "content": "recent " * 30},
    ]
    plan = builder.prepare(messages, refs(), 1200)
    assert plan is not None and selector.calls == 1
    summary = builder.excerpt(plan)
    from ralf_agent import ContextSummary

    restored = copy.deepcopy(plan)
    actual, manifest = builder.finish(restored, ContextSummary(**asdict(summary)))
    assert selector.calls == 1 and "zh-CN" in canonical(actual)
    assert "disk snapshot" not in canonical(actual)
    assert manifest["reference_selection"] == plan["fallback"]["manifest"]["reference_selection"]
    broken = copy.deepcopy(plan)
    broken["references"][1]["value"] = "changed"
    with pytest.raises(DefinitionMismatch):
        builder.finish(broken, summary)


@pytest.mark.parametrize("assembly", ["sync", "async"])
def test_relevant_data_factory_uses_owned_storage_and_cleanup(tmp_path, assembly):
    from ralf_agent import RuntimeBuilder, RuntimeProfile

    api()
    profile = RuntimeProfile(
        "recall",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"context_assembler": {"adapter": "relevant-data"}},
    )

    async def run():
        builder = RuntimeBuilder(base_dir=tmp_path)
        value = (
            builder.build(profile, tmp_path / "runs.sqlite")
            if assembly == "sync"
            else await builder.abuild(profile, tmp_path / "runs.sqlite")
        )
        assert (
            value.context.identity["reference_selector"]["identity"]["kind"]
            == "overlap-reference-selector"
        )
        artifacts = value.context.artifacts
        reference = artifacts.put(value.scope, "cleanup", {"result": "kept"})
        await value.aclose()
        with pytest.raises(ValidationError, match="closed"):
            artifacts.get(value.scope, reference)

    asyncio.run(run())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_failed_selector_construction_closes_owned_artifacts(tmp_path, asynchronous):
    from ralf_agent import ComponentRegistry, RuntimeBuilder, RuntimeProfile

    resources = []

    class Artifact(InMemoryArtifactStore):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    def artifacts(config, ctx):
        value = ctx.own(Artifact())
        resources.append(value)
        return value

    registry = ComponentRegistry()
    registry.register("artifact_store", "fixture", artifacts)
    registry.register("reference_selector", "invalid", lambda c, ctx: object())
    profile = RuntimeProfile(
        "bad",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "context_assembler": {
                "adapter": "relevant-data-async" if asynchronous else "relevant-data",
                "config": {"artifacts": {"adapter": "fixture"}, "selector": {"adapter": "invalid"}},
            }
        },
    )

    async def run():
        with pytest.raises(ValidationError):
            builder = RuntimeBuilder(registry, base_dir=tmp_path)
            if asynchronous:
                await builder.abuild(profile, tmp_path / "runs.sqlite")
            else:
                builder.build(profile, tmp_path / "runs.sqlite")
        assert len(resources) == 1 and resources[0].closed

    asyncio.run(run())
