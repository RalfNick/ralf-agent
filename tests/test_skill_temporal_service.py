"""Required real Workers use original read Actions, approvals and History recovery."""

import asyncio
import json
import os
import uuid

import pytest

import ralf_agent as r
from ralf_agent.temporal import replay_temporal_history

from .test_skill_execution import Reader, definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual owned Temporal Service"
)


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_actual_catalog_members_approval_worker_restart_and_history(tmp_path, kind):
    for name in ("alpha", "beta"):
        root = tmp_path / name
        (root / "help").mkdir(parents=True)
        (root / "help/SKILL.md").write_text(name)
        (root / "skills.json").write_text(
            json.dumps(
                {
                    "version": "1",
                    "skills": [
                        {
                            "name": "help",
                            "description": "Reference",
                            "version": "1",
                            "path": "help/SKILL.md",
                        }
                    ],
                }
            )
        )
    observed = []

    class Tracked(r.FileSystemSkillCatalog):
        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            observed.append(value["skill"]["instructions"])
            return value

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "skill-catalog-" + uuid.uuid4().hex
        scope = r.Scope("skill-tests", queue)
        factories = r.ComponentRegistry()
        factories.register("provider", "reader", lambda c, ctx: Reader())

        async def tools(config, context):
            registry = r.ToolRegistry()
            for name in ("alpha", "beta"):
                catalog = context.own(Tracked(tmp_path / name, version="1", scopes=[context.scope]))
                source = context.own_async(r.SkillToolSource(catalog, version="1"))
                await r.register_tool_source(
                    registry,
                    source,
                    prefix=name + "_",
                    policies={
                        "skill_get": r.ToolPolicy("1", effect="read_only", requires_approval=True)
                    },
                )
            registry.register(
                r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "business"
            )
            return registry

        factories.register_async("tools", "catalogs", tools)
        profile = r.TemporalProfile(
            "catalogs",
            "1",
            {"default": {"adapter": "reader"}},
            {"tools": {"adapter": "catalogs"}},
            binding_components=[
                {
                    "role": "tool_set",
                    "component_id": name,
                    "version": "1",
                    "component": {
                        "adapter": "names",
                        "config": {"names": [name + "_skill_get", "business"]},
                    },
                }
                for name in ("alpha", "beta")
            ],
        )
        first, saved = None, None
        for stage in range(3):
            assembly = await r.TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
            try:
                await assembly.start_worker(client, task_queue=queue)
                engine = assembly.create_engine(client, task_queue=queue, activity_timeout=5)
                handle = await engine.submit(definition(kind), "read", command_id="same", budget=64)
                if stage == 0:
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
                        for pending in done.pending:
                            target = pending.get("run_id", handle.run_id)
                            key = target, pending["action_id"]
                            if key in approved:
                                continue
                            receipt = await engine.approve(
                                target,
                                pending["action_id"],
                                pending["digest"],
                                command_id="approve-" + pending["action_id"],
                            )
                            assert (
                                await engine.approve(
                                    target,
                                    pending["action_id"],
                                    pending["digest"],
                                    command_id="approve-" + pending["action_id"],
                                )
                                == receipt
                            )
                            approved.add(key)
                        await asyncio.sleep(0.05)
                    assert done.state == "succeeded", done
                    if stage == 1:
                        saved = done.result
                    else:
                        assert done.result == saved
                    await replay_temporal_history(
                        await client.get_workflow_handle(handle.run_id).fetch_history()
                    )
            finally:
                await assembly.aclose(wait_timeout=30)
        assert sorted(observed) == (["alpha"] if kind == "agent" else ["alpha", "beta"])

    asyncio.run(run())


def test_actual_explicit_scope_default_factory_restarts_original_read(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "help.md").write_text("Original explicit Scope")
    (root / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {"name": "help", "description": "Reference", "version": "1", "path": "help.md"}
                ],
            }
        )
    )

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "skill-explicit-scope-" + uuid.uuid4().hex
        scope = r.Scope("skill-tests", queue)
        factories = r.ComponentRegistry()
        factories.register("provider", "reader", lambda c, ctx: Reader())
        profile = r.TemporalProfile(
            "explicit",
            "1",
            {"default": {"adapter": "reader"}},
            {
                "tools": {
                    "adapter": "skills-file",
                    "config": {
                        "root": str(root),
                        "version": "1",
                        "scopes": [{"workspace": scope.workspace, "principal": scope.principal}],
                        "requires_approval": True,
                    },
                }
            },
        )
        spec = r.AgentSpec("reader", "Read help", tools=["skill_get"], max_decisions=3)
        first = None
        for stage in range(3):
            assembly = await r.TemporalRuntimeBuilder(factories).abuild(profile, scope=scope)
            try:
                await assembly.start_worker(client, task_queue=queue)
                engine = assembly.create_engine(client, task_queue=queue, activity_timeout=5)
                handle = await engine.submit(spec, "read", command_id="same", budget=16)
                if stage == 0:
                    first = handle
                    status = await engine.drive(handle.run_id, wait_seconds=20)
                    assert status.state == "waiting_approval", status
                else:
                    assert handle == first
                    status = await engine.drive(handle.run_id, wait_seconds=20)
                    if stage == 1:
                        pending = status.pending[0]
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
                    assert status.state == "succeeded", status
                    assert status.result["skill"]["instructions"] == "Original explicit Scope"
                    await replay_temporal_history(
                        await client.get_workflow_handle(handle.run_id).fetch_history()
                    )
            finally:
                await assembly.aclose(wait_timeout=30)

    asyncio.run(run())
