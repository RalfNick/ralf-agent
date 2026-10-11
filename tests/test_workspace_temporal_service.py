"""Required actual Temporal read Actions, approval/restart and saved evidence."""

import asyncio
import json
import os
import uuid

import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    InMemoryWorkspace,
    ModelResponse,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
    ToolCall,
    ToolPolicy,
    ToolRegistry,
    WorkspaceToolSource,
    register_tool_source,
)
from ralf_agent.temporal import replay_temporal_history

from .test_workspace_configuration import config

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class Reader:
    identity = {"kind": "workspace-reader-fixture", "version": "1"}

    async def complete(self, messages, tools):
        evidence = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if evidence:
            return ModelResponse(output=evidence[-1])
        return ModelResponse(
            tool_calls=[ToolCall("workspace_read_text", {"path": "note"}, call_id="read")]
        )


@pytest.mark.parametrize("memory", [False, True])
def test_actual_workspace_approval_restart_retains_snapshot_and_history(tmp_path, memory):
    root = tmp_path / "files"
    root.mkdir()
    leaf = root / "note"
    leaf.write_text("original")
    observed = []

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "workspace-" + uuid.uuid4().hex
        scope = Scope("files", queue)
        registry = ComponentRegistry()
        registry.register("provider", "workspace-reader", lambda config, context: Reader())

        if memory:

            class TrackedMemory(InMemoryWorkspace):
                def read_text(self, scope, path, *, max_bytes=1048576):
                    observed.append(path)
                    return super().read_text(scope, path, max_bytes=max_bytes)

            async def tools(config, context):
                port = context.own(
                    TrackedMemory({"note": "original"}, version="v1", scopes=[context.scope])
                )
                source = context.own_async(WorkspaceToolSource(port, version="v1"))
                tools = ToolRegistry()
                await register_tool_source(
                    tools,
                    source,
                    policies={
                        "workspace_read_text": ToolPolicy(
                            "1", effect="read_only", requires_approval=True
                        )
                    },
                )
                return tools

            registry.register_async("tools", "memory-workspace", tools)
            declaration = {"adapter": "memory-workspace"}
        else:
            declaration = {
                "adapter": "workspace-read",
                "config": config(root, requires_approval=True),
            }
        profile = TemporalProfile(
            "files", "1", {"default": {"adapter": "workspace-reader"}}, {"tools": declaration}
        )
        first = None
        for index in range(3):
            assembly = await TemporalRuntimeBuilder(registry).abuild(profile, scope=scope)
            try:
                await assembly.start_worker(client, task_queue=queue)
                engine = assembly.create_engine(client, task_queue=queue, activity_timeout=5)
                handle = await engine.submit(
                    AgentSpec("reader", "Read the permitted file", tools=("workspace_read_text",)),
                    "read",
                    command_id="same",
                )
                if index == 0:
                    first = handle
                    status = await engine.drive(handle.run_id, wait_seconds=20)
                    assert status.state == "waiting_approval" and not observed, status.error
                    pending = status.pending[0]
                else:
                    assert handle == first
                    if index == 1:
                        receipt = await engine.approve(
                            handle.run_id,
                            pending["action_id"],
                            pending["digest"],
                            command_id="approve",
                        )
                        assert (
                            await engine.approve(
                                handle.run_id,
                                pending["action_id"],
                                pending["digest"],
                                command_id="approve",
                            )
                            == receipt
                        )
                    status = await engine.drive(handle.run_id, wait_seconds=20)
                    assert status.state == "succeeded" and status.result["text"] == "original", (
                        status
                    )
                    await replay_temporal_history(
                        await client.get_workflow_handle(handle.run_id).fetch_history()
                    )
            finally:
                await assembly.aclose(wait_timeout=30)
            if index == 1:
                leaf.write_text("changed after accepted evidence")
        if memory:
            assert observed == ["note"]

    asyncio.run(run())
