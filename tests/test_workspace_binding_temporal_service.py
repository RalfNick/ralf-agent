"""Required real Worker restart and native/composite Workspace root selection."""

import asyncio
import os
import uuid

import pytest

from relf_agent import (
    ComponentRegistry,
    FileSystemWorkspace,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
    ToolPolicy,
    ToolRegistry,
    WorkspaceToolSource,
    register_tool_source,
)
from relf_agent.temporal import replay_temporal_history

from .test_workspace_binding_execution import Reader, definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_actual_fixed_workspace_member_roots_approval_restart_and_history(tmp_path, kind):
    for name in ("alpha", "beta"):
        path = tmp_path / name
        path.mkdir()
        (path / "note").write_text(name)
    observed = []

    class Tracked(FileSystemWorkspace):
        def read_text(self, scope, path, *, max_bytes=1048576):
            result = super().read_text(scope, path, max_bytes=max_bytes)
            observed.append(result["text"])
            return result

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "workspace-bindings-" + uuid.uuid4().hex
        scope = Scope("workspace-tests", queue)
        factories = ComponentRegistry()
        factories.register("provider", "reader", lambda c, ctx: Reader())

        async def tools(config, context):
            registry = ToolRegistry()
            for name in ("alpha", "beta"):
                port = context.own(Tracked(tmp_path / name, version="1", scopes=[context.scope]))
                source = context.own_async(WorkspaceToolSource(port, version="1"))
                await register_tool_source(
                    registry,
                    source,
                    prefix=name + "_",
                    policies={
                        "workspace_read_text": ToolPolicy(
                            "1", effect="read_only", requires_approval=True
                        )
                    },
                )
            from relf_agent import ToolSpec

            registry.register(
                ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "ok"
            )
            return registry

        factories.register_async("tools", "roots", tools)
        profile = TemporalProfile(
            "roots",
            "1",
            {"default": {"adapter": "reader"}},
            {"tools": {"adapter": "roots"}},
            binding_components=[
                {
                    "role": "workspace",
                    "component_id": name,
                    "version": "1",
                    "component": {
                        "adapter": "registered-tools",
                        "config": {"names": [name + "_workspace_read_text"]},
                    },
                }
                for name in ("alpha", "beta")
            ],
        )
        first = None
        for stage in range(3):
            assembly = await TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
            try:
                await assembly.start_worker(client, task_queue=queue)
                engine = assembly.create_engine(client, task_queue=queue, activity_timeout=5)
                handle = await engine.submit(definition(kind), "read", command_id="same", budget=64)
                if first is None:
                    first = handle
                    waiting = await engine.drive(handle.run_id, wait_seconds=20)
                    assert waiting.state == "waiting_approval" and observed == [], waiting
                else:
                    assert handle == first
                    deadline = asyncio.get_running_loop().time() + 60
                    approved = set()
                    while asyncio.get_running_loop().time() < deadline:
                        done = await engine.drive(handle.run_id, wait_seconds=20)
                        if done.state != "waiting_approval":
                            break
                        for item in done.pending:
                            target = item.get("run_id", handle.run_id)
                            key = target, item["action_id"]
                            if key in approved:
                                continue
                            receipt = await engine.approve(
                                target,
                                item["action_id"],
                                item["digest"],
                                command_id="approve-" + item["action_id"],
                            )
                            assert (
                                await engine.approve(
                                    target,
                                    item["action_id"],
                                    item["digest"],
                                    command_id="approve-" + item["action_id"],
                                )
                                == receipt
                            )
                            approved.add(key)
                        await asyncio.sleep(0.05)
                    assert done.state == "succeeded", done
                    if kind == "graph":
                        assert (
                            done.result["alpha"]["text"] == "alpha"
                            and done.result["beta"]["text"] == "beta"
                        )
                    else:
                        assert done.result["text"] == ("alpha" if kind == "agent" else "beta")
                    await replay_temporal_history(
                        await client.get_workflow_handle(handle.run_id).fetch_history()
                    )
            finally:
                await assembly.aclose(wait_timeout=30)
            if stage == 1:
                for name in ("alpha", "beta"):
                    (tmp_path / name / "note").write_text("changed after accepted result")
        assert sorted(observed) == (["alpha"] if kind == "agent" else ["alpha", "beta"])

    asyncio.run(run())
