import asyncio

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    LocalEngine,
    ModelResponse,
    RelevantDataContext,
    SQLiteArtifactStore,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
    recommended_harness,
)
from tests.test_binding_execution import RecordingProvider, bound_catalog


class Writes:
    identity = {"kind": "h3-write-fixture", "version": "1"}

    async def complete(self, messages, tools):
        if not any(m["role"] == "tool" for m in messages):
            return ModelResponse(tool_calls=[ToolCall("change", {"value": 1}, "write")])
        return ModelResponse(output={"done": True})


@pytest.mark.parametrize(
    "kind,nested",
    [("team", False), ("plan-and-execute", False), ("team", True), ("plan-and-execute", True)],
)
def test_custom_defaults_preserve_selected_agent_approval_and_one_effect_across_restart(
    tmp_path, kind, nested
):
    writes = []
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change",
            "Change",
            {"type": "object"},
            effect="idempotent_write",
            requires_approval=True,
        ),
        lambda args, ctx: writes.append(ctx.effect_key) or {"changed": True},
    )
    worker = AgentSpec("worker", "Change", tools=("change",))
    worker = WorkflowSpec("nested", [worker]) if nested else worker
    path = (
        ("team" if kind == "team" else "dynamic")
        + "/members/worker"
        + ("/sequence/steps/0" if nested else "")
    )
    harness = recommended_harness(
        kind,
        {"worker": worker, "final": AgentSpec("final", "Combine")},
        agent_bindings={
            path: AgentBindingDescriptor(provider=BindingSelection.ref("writer", "1")),
            ("team" if kind == "team" else "dynamic") + "/members/final": AgentBindingDescriptor(
                provider=BindingSelection.ref("final", "1")
            ),
        },
    )
    handle, child, pending = None, None, None
    for round in range(2):
        artifacts = SQLiteArtifactStore(tmp_path / "artifacts.sqlite")
        catalog = bound_catalog()
        catalog.register("provider", "writer", "1", Writes())
        catalog.register("provider", "final", "1", RecordingProvider("final"))
        try:
            with LocalEngine(
                SQLiteStore(tmp_path / "runs.sqlite"),
                providers={"default": RecordingProvider("host")},
                tools=tools,
                binding_catalog=catalog,
                context_assembler=RelevantDataContext(artifacts),
            ) as runtime:
                actual = runtime.submit(harness.definition, "task", command_id="s")
                if handle:
                    assert actual == handle
                handle = actual
                if round == 0:
                    assert asyncio.run(runtime.drive(handle.run_id)).state == "waiting_approval"
                    children = runtime.diagnostics(handle.run_id).workflow["children"]
                    child = children[0]["run_id"]
                    pending = runtime.status(child).pending[0]
                    assert not writes
                else:
                    receipt = runtime.approve(
                        child, pending["action_id"], pending["digest"], command_id="approve"
                    )
                    assert (
                        runtime.approve(
                            child, pending["action_id"], pending["digest"], command_id="approve"
                        )
                        == receipt
                    )
                    done = asyncio.run(runtime.drive(handle.run_id))
                    assert done.state == "succeeded", done.error
                    assert done.result["provider"] == "final"
                    assert len(writes) == 1
        finally:
            artifacts.close()
