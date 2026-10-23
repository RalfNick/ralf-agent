"""Selectable completion verification, composite isolation and actual business oracle."""

import asyncio

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    TeamSpec,
    ToolRegistry,
    WorkflowSpec,
)
from relf_agent.business_evaluation import evaluate_business, load_business_cases
from relf_agent.completion import SchemaCompletionVerifier, ToolReceiptVerifier
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.runtime_builder import ComponentRegistry, RuntimeBuilder
from relf_agent.runtime_config import RuntimeProfile
from relf_agent.tools import ToolSpec
from relf_agent.types import ToolCall

from .helpers import ScriptedProvider


def engine(path, **kwargs):
    return LocalEngine(
        SQLiteStore(path),
        providers=kwargs.pop(
            "providers", {"default": ScriptedProvider([ModelResponse(output="ok")])}
        ),
        tools=ToolRegistry(),
        **kwargs,
    )


def test_binding_role_ref_disabled_and_inherit_are_explicit(tmp_path):
    catalog = BindingCatalog(scope=Scope())
    catalog.register("verifier", "schema", "1", SchemaCompletionVerifier())
    host = ToolReceiptVerifier("required", on_missing="reject")
    with engine(
        tmp_path / "refs.sqlite",
        binding_catalog=catalog,
        verifier=host,
        providers={"default": ScriptedProvider([ModelResponse(output="ok")] * 3)},
    ) as runtime:
        for n, selection in enumerate(
            [
                BindingSelection.ref("schema", "1"),
                BindingSelection.disabled(),
                BindingSelection.inherit(),
            ]
        ):
            spec = AgentDefinition(AgentSpec("a", "a"), AgentBindingDescriptor(verifier=selection))
            handle = runtime.submit(spec, "q", command_id=str(n))
            done = asyncio.run(runtime.drive(handle.run_id))
            assert done.state == ("failed" if n == 2 else "succeeded")
            manifest = runtime.diagnostics(handle.run_id).manifest
            assert manifest["kernel"] == ("local-bindings-5" if n < 2 else "local-bindings-1")
        assert "verifier" in runtime.binding_capabilities["supported_binding_roles"]
        assert "verifier" not in runtime.binding_capabilities["resource_selector_roles"]


def test_legacy_inherited_none_has_no_new_manifest_fields(tmp_path):
    with engine(tmp_path / "legacy.sqlite") as runtime:
        spec = AgentDefinition(AgentSpec("a", "a"), AgentBindingDescriptor())
        handle = runtime.submit(spec, "q", command_id="s")
        manifest = runtime.diagnostics(handle.run_id).manifest
        entry = manifest["agent_bindings"]["steps"]["agent"]
        assert (
            "verifier" not in entry["resolved"] and "completion_verifier" not in entry["manifest"]
        )
        assert manifest["kernel"] == "local-bindings-1"


def test_missing_catalog_version_and_resource_selectors_refuse_before_dispatch(tmp_path):
    catalog = BindingCatalog(scope=Scope())
    catalog.register("verifier", "schema", "1", SchemaCompletionVerifier())
    with engine(tmp_path / "missing.sqlite", binding_catalog=catalog) as runtime:
        with pytest.raises(DefinitionMismatch):
            runtime.submit(
                AgentDefinition(
                    AgentSpec("a", "a"),
                    AgentBindingDescriptor(verifier=BindingSelection.ref("schema", "2")),
                ),
                "q",
                command_id="missing",
            )
        with pytest.raises(ValidationError):
            runtime.submit(
                AgentDefinition(
                    AgentSpec("a", "a"),
                    AgentBindingDescriptor(
                        verifier=BindingSelection.ref("schema", "1", selector={"namespace": "a"})
                    ),
                ),
                "q",
                command_id="selector",
            )


@pytest.mark.parametrize("kind", ["sequence", "graph", "parallel", "team", "dynamic", "nested"])
def test_selected_verifier_survives_all_local_definition_boundaries(tmp_path, kind):
    catalog = BindingCatalog(scope=Scope())
    catalog.register("verifier", "schema", "1", SchemaCompletionVerifier())
    agent = AgentSpec("a", "a")
    if kind == "sequence":
        definition, path = WorkflowSpec("s", [agent]), "sequence/steps/0"
    elif kind in {"graph", "parallel"}:
        definition, path = (
            GraphWorkflowSpec(
                "g",
                [GraphNode("answer", agent=agent)],
                max_concurrency=2 if kind == "parallel" else 1,
            ),
            "graph/nodes/answer",
        )
    elif kind == "nested":
        definition, path = (
            TeamSpec("t", {"member": WorkflowSpec("s", [agent])}),
            "team/members/member/sequence/steps/0",
        )
    else:
        definition = (TeamSpec if kind == "team" else DynamicWorkflowSpec)("t", {"member": agent})
        path = ("team" if kind == "team" else "dynamic") + "/members/member"
    wrapped = BoundDefinition(
        definition, {path: AgentBindingDescriptor(verifier=BindingSelection.ref("schema", "1"))}
    )
    with engine(
        tmp_path / (kind + ".sqlite"),
        binding_catalog=catalog,
        verifier=ToolReceiptVerifier("missing", on_missing="reject"),
    ) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert runtime.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-5"


@pytest.mark.parametrize("kind", ["sequence", "graph", "parallel"])
def test_other_node_tool_receipt_does_not_confirm_current_agent(tmp_path, kind):
    writers = ScriptedProvider(
        [
            ModelResponse(tool_calls=[ToolCall("repair", {"ticket": "INC-1"})]),
            ModelResponse(output="written"),
        ]
    )
    checker = ScriptedProvider([ModelResponse(output={"status": "resolved", "ticket": "INC-1"})])
    catalog = BindingCatalog(scope=Scope())
    catalog.register("verifier", "gate", "1", ToolReceiptVerifier("repair", on_missing="reject"))
    tools = ToolRegistry()
    writes = []
    tools.register(
        ToolSpec(
            "repair",
            "repair",
            {"type": "object"},
            effect="idempotent_write",
            requires_approval=True,
        ),
        lambda a, ctx: writes.append(a) or {"applied": True},
    )
    writer = AgentSpec("writer", "Write", ("repair",), provider="writer")
    reader = AgentSpec("reader", "Answer", provider="reader")
    if kind == "sequence":
        raw, prefix, first, second = (
            WorkflowSpec("s", [writer, reader]),
            "sequence/steps/",
            "0",
            "1",
        )
    else:
        raw = GraphWorkflowSpec(
            "g",
            [
                GraphNode("writer", agent=writer),
                GraphNode("reader", agent=reader, depends_on=("writer",)),
            ],
            max_concurrency=2 if kind == "parallel" else 1,
        )
        prefix, first, second = "graph/nodes/", "writer", "reader"
    bound = BoundDefinition(
        raw,
        {
            prefix + first: AgentBindingDescriptor(verifier=BindingSelection.disabled()),
            prefix + second: AgentBindingDescriptor(verifier=BindingSelection.ref("gate", "1")),
        },
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "isolation.sqlite"),
        providers={"writer": writers, "reader": checker},
        tools=tools,
        binding_catalog=catalog,
    ) as runtime:
        handle = runtime.submit(bound, "q", command_id="s")
        pending = asyncio.run(runtime.drive(handle.run_id)).pending[0]
        runtime.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
        )
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "completion_rejected"
        assert writes == [{"ticket": "INC-1"}]
        record = next(
            a["completion_verification"] for a in done.actions if "completion_verification" in a
        )
        assert record["request"]["receipts"] == []


@pytest.mark.parametrize("asynchronous", [False, True])
def test_factory_binding_and_default_component_support_sync_and_async(tmp_path, asynchronous):
    registry = ComponentRegistry()
    if asynchronous:

        async def factory(config, context):
            await asyncio.sleep(0)
            return SchemaCompletionVerifier()

        registry.register_async("verifier", "custom", factory)
    else:
        registry.register("verifier", "custom", lambda c, ctx: SchemaCompletionVerifier())
    profile = RuntimeProfile(
        "p",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={"verifier": {"adapter": "custom"}},
        binding_components=[
            {
                "role": "verifier",
                "component_id": "gate",
                "version": "1",
                "component": {"adapter": "schema"},
            }
        ],
    )
    builder = RuntimeBuilder(registry=registry)

    async def run():
        if asynchronous:
            runtime = await builder.abuild(profile, tmp_path / "factory.sqlite")
        else:
            runtime = builder.build(profile, tmp_path / "factory.sqlite")
        async with runtime:
            handle = runtime.submit(
                AgentDefinition(
                    AgentSpec("a", "a"),
                    AgentBindingDescriptor(verifier=BindingSelection.ref("gate", "1")),
                ),
                "q",
                command_id="s",
            )
            done = await runtime.drive(handle.run_id)
            assert done.state == "succeeded"

    asyncio.run(run())


def test_receipt_rule_profile_rejects_invalid_config_before_database(tmp_path):
    profile = RuntimeProfile(
        "p",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "verifier": {
                "adapter": "tool-receipt",
                "config": {"tool": "repair", "on_missing": "accept"},
            }
        },
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, tmp_path / "invalid.sqlite")
    assert not (tmp_path / "invalid.sqlite").exists()


def test_verifier_disable_cannot_disable_required_schema(tmp_path):
    spec = AgentDefinition(
        AgentSpec("a", "a", output_schema={"type": "integer"}),
        AgentBindingDescriptor(verifier=BindingSelection.disabled()),
    )
    with engine(tmp_path / "schema.sqlite") as runtime:
        handle = runtime.submit(spec, "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "failed"


def test_evaluator_gate_keeps_independent_business_oracle(tmp_path):
    case = load_business_cases()[0]
    expected = case["expected"]
    provider = ScriptedProvider(
        [
            ModelResponse(
                tool_calls=[ToolCall("inspect_ticket", {"ticket_id": expected["ticket_id"]})]
            ),
            ModelResponse(output=expected),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "apply_fix", {"ticket_id": expected["ticket_id"], "fix": expected["fix"]}
                    )
                ]
            ),
            ModelResponse(output=expected),
        ]
    )
    verifier = ToolReceiptVerifier(
        "apply_fix",
        when={
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"const": "resolved"}},
        },
        result_schema={
            "type": "object",
            "required": ["applied"],
            "properties": {"applied": {"const": True}},
        },
        argument_bindings={"ticket_id": "/ticket_id", "fix": "/fix"},
    )
    report = asyncio.run(
        evaluate_business(
            provider,
            cases=[case],
            offline=True,
            completion_verifier=verifier,
            evidence_dir=tmp_path / "evidence",
        )
    )
    assert report["passed"] == 1 and report["calls"] == 4 and report["model_quality"] is None
    assert report["cases"][0]["metrics"]["approval"]
    assert report["cases"][0]["completion_verification"] == {"accept": 1, "reject": 0, "retry": 1}
    assert report["completion_verifier"]["kind"] == verifier.identity["kind"]


def test_cli_offline_receipt_gate_is_explicit(capsys):
    import json

    from relf_agent.business_evaluation_cli import main

    assert main(["--offline", "--receipt-gate"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] == 8 and "completion_verifier" in report
