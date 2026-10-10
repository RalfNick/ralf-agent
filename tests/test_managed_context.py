import asyncio
import copy
import importlib

import pytest

from ralf_agent import AgentSpec, BudgetedContextAssembler, ContextSummary
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.types import canonical, digest
from tests.test_managed_memory_stage import engine


def pipeline(**kwargs):
    return importlib.import_module("ralf_agent.managed_context").ManagedContextPipeline(**kwargs)


def history():
    return [
        {"role": "system", "content": "Answer"},
        {"role": "user", "content": "Task"},
        {"role": "assistant", "content": "x" * 2000},
        {"role": "assistant", "content": "latest"},
    ]


def test_pure_pipeline_reserves_room_and_never_changes_source():
    context = pipeline(summary_max_chars=128)
    source = history()
    before = copy.deepcopy(source)
    plan = context.prepare(source, [], 700)
    assert plan["coverage"] == [digest([source[2]])]
    assert plan["selected"] == [1]
    messages, manifest = context.finish(plan, ContextSummary("old evidence", plan["coverage"]))
    assert messages[:2] == before[:2] and messages[-1] == before[-1]
    assert "untrusted" in messages[2]["content"] and manifest["summary"]["included"]
    assert source == before and len(canonical(messages)) <= 700
    assert (
        context.assemble(source, [], 700)[0]
        == BudgetedContextAssembler().assemble(source, [], 700)[0]
    )


@pytest.mark.parametrize("mode", ["excerpt", "model"])
def test_no_omission_or_no_room_has_no_preparation(mode):
    context = pipeline(mode=mode, summary_max_chars=128)
    assert context.prepare(history()[:2], [], 700) is None
    source = history()
    source[-1]["content"] = "latest" * 70
    assert context.prepare(source, [], 600) is None


def test_summary_cannot_invent_coverage_or_split_latest_tool_group():
    context = pipeline(summary_max_chars=128)
    source = history()[:-1] + [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "latest-call"}]},
        {"role": "tool", "tool_call_id": "latest-call", "content": "answer"},
    ]
    plan = context.prepare(source, [], 700)
    messages, _ = context.finish(plan, ContextSummary("evidence", plan["coverage"]))
    assert messages[-2:] == source[-2:]
    with pytest.raises(ValidationError):
        context.finish(plan, ContextSummary("invented", [digest("wrong")]))


@pytest.mark.parametrize("timeout", [0, float("nan"), 61, True])
def test_model_timeout_is_finite_bounded(timeout):
    with pytest.raises(ValidationError):
        pipeline(mode="model", timeout=timeout)


def test_policy_methods_are_pinned_and_model_request_is_tool_free():
    context = pipeline(mode="model", provider="summary", summary_max_chars=128)
    plan = context.prepare(history(), [{"secret": "not-summary-input"}], 700)
    request = context.request(plan)
    assert request.tools == [] and "not-summary-input" not in canonical(request.messages)
    assert "context-summary:" in request.messages[0]["content"]
    context.prepare = lambda *args: None
    with pytest.raises(DefinitionMismatch):
        _ = context.identity


def test_default_schema_and_release_do_not_change(tmp_path):
    with engine(tmp_path / "run.sqlite") as local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert "managed_context" not in local.diagnostics(h.run_id).manifest
        assert local.store.conn.execute("SELECT value FROM metadata").fetchone()[0] == "1"


def test_pipeline_admission_pins_provider_and_enables_semantic8(tmp_path):
    context = pipeline(mode="model")
    with engine(tmp_path / "run.sqlite", context_assembler=context) as local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        manifest = local.diagnostics(h.run_id).manifest
        assert manifest["managed_context"]["policy"] == context.identity
        assert manifest["managed_context"]["provider"] == local.providers["default"].identity
        assert local.store.conn.execute("SELECT value FROM metadata").fetchone()[0] == "8"


def test_advanced_pipeline_activates_composite_schema(tmp_path):
    from ralf_agent import GraphNode, GraphWorkflowSpec

    with engine(tmp_path / "run.sqlite", context_assembler=pipeline()) as local:
        h = local.submit(
            GraphWorkflowSpec("g", [GraphNode("a", agent=AgentSpec("a", "Answer"))]),
            "q",
            command_id="s",
        )
        assert local.store.conn.execute("SELECT value FROM metadata").fetchone()[0] == "11"
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"


def test_existing_context_binding_selects_pipeline_per_agent(tmp_path):
    from ralf_agent import (
        AgentBindingDescriptor,
        AgentDefinition,
        BindingCatalog,
        BindingSelection,
        Scope,
    )

    context = pipeline()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("context", "managed", "1", context)
    with engine(tmp_path / "run.sqlite", binding_catalog=catalog) as local:
        h = local.submit(
            AgentDefinition(
                AgentSpec("a", "Answer"),
                AgentBindingDescriptor(context=BindingSelection.ref("managed", "1")),
            ),
            "q",
            command_id="s",
        )
        manifest = local.diagnostics(h.run_id).manifest
        assert manifest["kernel"] == "local-bindings-8"
        assert "managed_context" in manifest["agent_bindings"]["steps"]["agent"]["manifest"]


def test_pipeline_rejects_lazy_preparation_override():
    from ralf_agent import ManagedContextPipeline

    class Lazy(ManagedContextPipeline):
        async def prepare(self, *args):
            return None

    with pytest.raises(ValidationError):
        Lazy()


@pytest.mark.parametrize("mode", ["excerpt", "model"])
def test_temporal_managed_context_is_explicitly_versioned(mode):
    from ralf_agent import ManagedContextPipeline, ToolRegistry
    from ralf_agent.temporal_activities import TemporalRuntime
    from tests.helpers import ScriptedProvider

    runtime = TemporalRuntime(
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
        context_builder=ManagedContextPipeline(mode=mode),
    )
    assert runtime.manifest["kernel"] == "temporal-2"
    assert runtime.manifest["managed_context"]["policy"]["mode"] == mode
