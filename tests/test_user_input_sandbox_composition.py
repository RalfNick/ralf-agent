"""Closed Temporal releases compose intrinsic input with original Sandbox grants."""

import asyncio
import copy
from dataclasses import asdict

import pytest

import ralf_agent as r
from ralf_agent.binding_sandbox import validate_sandbox_protocol
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import effective_step, normalize_request
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.temporal_state import TemporalRunState, validate_manifest
from ralf_agent.types import canonical, submission_request
from ralf_agent.user_input import register_user_input
from tests.test_sandbox_bindings import registered as registered
from tests.test_temporal_parent_completion import Gate
from tests.test_temporal_user_input import QuestionProvider, question


def execution(registry, *, input_selected, parent_selected=False, catalog=None):
    if input_selected:
        register_user_input(registry)
    options = {}
    if parent_selected:
        options["parent_completion_policies"] = {"checked": r.ParentCompletionPolicy(Gate())}
    return TemporalRuntime(
        providers={"default": QuestionProvider()},
        tools=registry,
        binding_catalog=catalog,
        **options,
    )


@pytest.mark.parametrize(
    "input_selected,parent_selected,protocol",
    [(True, False, 10), (False, True, 9), (True, True, 10)],
)
def test_selected_input_parent_completion_and_native_sandbox_have_one_fixed_release(
    registered, input_selected, parent_selected, protocol
):
    registry, ports = registered
    runtime = execution(registry, input_selected=input_selected, parent_selected=parent_selected)
    manifest = runtime.manifest
    assert manifest["binding_protocol"] == protocol
    assert manifest["sandbox_binding_protocol"] == 1
    assert manifest["tool_execution_protocol"]["version"] == 1
    assert (manifest.get("user_input_protocol") == 1) is input_selected
    assert (manifest.get("parent_completion_protocol") == 1) is parent_selected
    assert validate_manifest(manifest) == manifest
    assert all(port.calls == [] and not port.closed for port in ports)


@pytest.mark.parametrize("kind", ["agent", "team", "flat", "dag"])
def test_input_wait_preserves_original_selected_member_sandbox_and_tool_set(registered, kind):
    async def run():
        registry, ports = registered
        catalog = r.BindingCatalog(scope=r.Scope())
        catalog.register(
            "sandbox", "a", "1", r.SandboxBindingResource(registry, names=["a_sandbox_run"])
        )
        catalog.register("tool_set", "granted", "1", ["a_sandbox_run", "request_input", "business"])
        runtime = execution(registry, input_selected=True, catalog=catalog)
        descriptor = r.AgentBindingDescriptor(
            sandbox=r.BindingSelection.ref("a", "1"),
            tool_set=r.BindingSelection.ref("granted", "1"),
        )
        agent = r.AgentSpec(
            "ask",
            "Ask the original question",
            tools=("a_sandbox_run", "b_sandbox_run", "request_input", "business"),
        )
        selected = effective_step(asdict(agent), runtime.manifest, descriptor.to_dict())
        assert selected["tools"] == ["a_sandbox_run", "request_input", "business"]
        disabled = effective_step(
            asdict(agent),
            runtime.manifest,
            r.AgentBindingDescriptor(sandbox=r.BindingSelection.disabled()).to_dict(),
        )
        assert disabled["tools"] == ["request_input", "business"]
        scope = asdict(r.Scope())
        if kind == "agent":
            request = normalize_request(
                submission_request(r.AgentDefinition(agent, descriptor), "Choose", budget=4)
            )
            state = TemporalRunState("selected", scope, "submit", request, runtime.manifest)
            parent = None
        else:
            definition = (
                r.TeamSpec("team", {"worker": agent}, child_budget=4)
                if kind == "team"
                else r.DynamicWorkflowSpec(
                    "plan", {"worker": agent}, child_budget=4, plan_mode=kind
                )
            )
            path = "team/members/worker" if kind == "team" else "dynamic/members/worker"
            request = normalize_request(
                submission_request(
                    r.BoundDefinition(definition, {path: descriptor}), "Choose", budget=8
                )
            )
            parent = TemporalParentState(
                "parent", scope, "submit", request, runtime.orchestration_release
            )
            parent.accept_selection(
                r.DAGProposal([r.DAGNode("one", "worker", input=r.Literal("Choose"))]).to_dict()
                if kind == "dag"
                else r.PlanProposal([r.ChildCall("one", "worker", "Choose")]).to_dict()
                if kind == "flat"
                else {
                    "calls": [{"id": "one", "member": "worker", "input": "Choose"}],
                    "done": False,
                }
            )
            call = parent.next_calls()[0]
            state = TemporalRunState(
                call["run_id"], scope, call["command_id"], call["request"], parent.manifest
            )
        assert state.step["tools"] == ["a_sandbox_run", "request_input", "business"]
        item = await question(runtime, state)
        assert item["owner"]["run_id"] == state.run_id
        assert not state.pending_acks
        assert all(
            action["tool"] == "request_input" and action["attempts"] == []
            for action in state.actions
            if action["kind"] == "tool"
        )
        if parent is not None:
            parent.observe(state.run_id, {**state.diagnostics(), "scope": scope})
            assert parent.state == "waiting_input"
            assert parent.snapshot()["pending"][0]["owner"]["run_id"] == state.run_id
        assert all(port.calls == [] and not port.closed for port in ports)

    asyncio.run(run())


def test_unselected_native_sandbox_keeps_original_closed_protocol(registered):
    registry, ports = registered
    first = execution(registry, input_selected=False).manifest
    second = execution(registry, input_selected=False).manifest
    assert first["binding_protocol"] == 4
    assert not any(
        key.startswith("user_input") or key.startswith("parent_completion") for key in first
    )
    assert canonical(first) == canonical(second)
    assert validate_manifest(first) == first
    assert all(port.calls == [] for port in ports)


@pytest.mark.parametrize("protocol", [1, 2, 3, 11, True])
def test_sandbox_refuses_unrelated_old_and_future_binding_protocols(registered, protocol):
    registry, ports = registered
    manifest = copy.deepcopy(execution(registry, input_selected=False).manifest)
    manifest["binding_protocol"] = protocol
    with pytest.raises(DefinitionMismatch):
        validate_sandbox_protocol(manifest)
    assert all(port.calls == [] for port in ports)


@pytest.mark.parametrize("feature", ["input", "parent"])
def test_sandbox_composition_still_requires_exact_selected_joint_protocol(registered, feature):
    registry, ports = registered
    manifest = execution(
        registry, input_selected=feature == "input", parent_selected=feature == "parent"
    ).manifest
    manifest.pop("user_input_protocol" if feature == "input" else "parent_completion_protocol")
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)
    assert all(port.calls == [] for port in ports)
