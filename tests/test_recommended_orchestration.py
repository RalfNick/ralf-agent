import asyncio
import json

import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    ModelResponse,
    Runtime,
    RuntimeBuilder,
    recommended_profile,
)
from ralf_agent.errors import ValidationError
from ralf_agent.types import submission_request


@pytest.mark.parametrize("kind,count", [("plan-and-execute", 2), ("team", 3)])
def test_default_orchestration_is_immutable_and_reconnectable(tmp_path, kind, count):
    from ralf_agent import recommended_harness

    harness = recommended_harness(kind)
    definition = harness.definition
    assert len(definition.members) == count
    if kind == "team":
        assert definition.strategy == "supervisor"
        assert definition.strategy_config == {"supervisor": "synthesizer"}
    else:
        assert definition.planner == "rule"
    profile = recommended_profile(kind)
    builder = RuntimeBuilder(base_dir=tmp_path)

    async def run():
        ref = None
        for _ in range(2):
            async with Runtime(
                builder.build(profile, tmp_path / "runs.sqlite"), owned=True
            ) as runtime:
                handle = await runtime.submit(harness, "task", command_id="s")
                if ref is not None:
                    assert handle.ref == ref
                ref = handle.ref
                done = await handle.wait(wait_timeout=5)
                assert done.snapshot.state == "succeeded", done.snapshot.error

    asyncio.run(run())


def test_custom_orchestration_keeps_original_specs_and_binding_paths():
    from ralf_agent import (
        AgentBindingDescriptor,
        BindingSelection,
        BoundDefinition,
        TeamSpec,
        recommended_harness,
    )

    a = AgentSpec("reader", "Read", output_schema={"type": "object"})
    members = {"worker": a, "final": AgentSpec("final", "Combine")}
    bindings = {
        "team/members/worker": AgentBindingDescriptor(provider=BindingSelection.ref("reader", "1"))
    }
    harness = recommended_harness("team", members, name="custom", agent_bindings=bindings)
    expected = BoundDefinition(
        TeamSpec("custom", members, strategy="supervisor", strategy_config={"supervisor": "final"}),
        bindings,
    )
    assert submission_request(harness.definition, "task") == submission_request(expected, "task")
    a.output_schema["type"] = "string"
    assert harness.definition.definition.members["worker"]["output_schema"]["type"] == "object"


def test_dynamic_dag_and_explicit_model_planner_are_original_declarations():
    from ralf_agent import recommended_harness

    definition = recommended_harness("plan-and-execute", plan_mode="dag").definition
    assert definition.planner == "dag-rule" and definition.plan_mode == "dag"
    assert recommended_harness("plan-and-execute", planner="model").definition.planner == "model"


@pytest.mark.parametrize(
    "kind,options",
    [
        ("unknown", {}),
        ("team", {"members": {}}),
        ("team", {"typo": 1}),
        ("plan-and-execute", {"max_concurrency": True}),
    ],
)
def test_invalid_orchestration_does_not_silently_change_defaults(kind, options):
    from ralf_agent import recommended_harness

    with pytest.raises(ValidationError):
        recommended_harness(kind, **options)


@pytest.mark.parametrize("replace_members", [False, True])
@pytest.mark.parametrize(
    "version,options,linked",
    [
        ("1", {}, False),
        ("2", {}, True),
        ("2", {"planner": "rule"}, False),
        ("2", {"plan_mode": "flat"}, False),
        ("2", {"plan_mode": "dag"}, True),
        ("2", {"planner": "dag-rule", "plan_mode": "dag"}, True),
    ],
)
def test_versioned_plan_consumes_evidence_and_reconnects_without_new_calls(
    tmp_path, replace_members, version, options, linked
):
    from ralf_agent import recommended_harness

    task = {"question": "Calculate the inventory value from the ledger"}
    evidence = {"units": 7, "unit_price": 6, "source": "inventory-ledger"}
    answer = {"total": 42, "source": "inventory-ledger"}
    inputs = []

    class InventoryProvider:
        identity = {"kind": "inventory-evidence-fixture", "version": "1"}

        async def complete(self, messages, tools):
            incoming = json.loads(messages[1]["content"])
            inputs.append(incoming)
            instructions = messages[0]["content"]
            if instructions.startswith(("Analyze the task", "Read inventory")):
                return ModelResponse(output=evidence)
            if incoming == evidence:
                return ModelResponse(output=answer)
            return ModelResponse(output={"error": "The writer did not receive ledger evidence"})

    members = (
        {
            "lookup": AgentSpec("lookup", "Read inventory ledger evidence"),
            "answer": AgentSpec("answer", "Calculate the value from supplied evidence"),
        }
        if replace_members
        else None
    )
    harness = recommended_harness("plan-and-execute", members, version=version, **options)
    registry = ComponentRegistry()
    registry.register("provider", "inventory", lambda c, ctx: InventoryProvider())
    profile = recommended_profile(
        "plan-and-execute", provider={"adapter": "inventory"}, version=version
    )
    builder = RuntimeBuilder(registry, base_dir=tmp_path)

    async def exercise():
        ref = None
        for _ in range(2):
            async with Runtime(
                await builder.abuild(profile, tmp_path / "runs.sqlite"), owned=True
            ) as runtime:
                handle = await runtime.submit(harness, task, command_id="inventory-one")
                done = await handle.wait(wait_timeout=5)
                assert done.snapshot.state == "succeeded", done.snapshot.error
                assert done.snapshot.result == (
                    answer if linked else {"error": "The writer did not receive ledger evidence"}
                )
                if ref is not None:
                    assert handle.ref == ref
                ref = handle.ref
                assert inputs == (
                    [task, evidence]
                    if linked
                    else [{"task": task, "prior": []}, {"task": task, "prior": []}]
                )

    asyncio.run(exercise())
