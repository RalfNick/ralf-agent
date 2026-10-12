"""Required actual PostgreSQL effects, Worker restart and Source2 History."""

import asyncio
import os
import sqlite3
import uuid

import pytest

import ralf_agent as r
from ralf_agent.temporal import replay_temporal_history

from .test_workspace_write_configuration import Writer
from .test_workspace_write_execution import definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS") or not os.getenv("RALF_TEST_POSTGRES_DSN"),
    reason="requires actual owned Temporal and PostgreSQL EffectJournal",
)


@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_actual_workspace_write_members_approval_restart_once_and_history(tmp_path, kind):
    for name in ("alpha", "beta"):
        (tmp_path / name).mkdir()
    observed = []

    class Tracked(r.FileSystemWritableWorkspace):
        def write_text(self, scope, path, text, *, expected_version, effect_key):
            receipt = super().write_text(
                scope, path, text, expected_version=expected_version, effect_key=effect_key
            )
            observed.append((self._root, receipt["effect_key"]))
            return receipt

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "workspace-write-" + uuid.uuid4().hex
        scope = r.Scope("workspace-write-tests", queue)
        factories = r.ComponentRegistry()
        factories.register("provider", "writer", lambda c, ctx: Writer())

        async def tools(config, context):
            registry = r.ToolRegistry()
            for name in ("alpha", "beta"):
                port = context.own(Tracked(tmp_path / name, version="1", scopes=[context.scope]))
                source = context.own_async(r.WritableWorkspaceToolSource(port, version="1"))
                await r.register_tool_source(
                    registry,
                    source,
                    prefix=name + "_",
                    policies={
                        "workspace_write_text": r.ToolPolicy(
                            "1",
                            effect="idempotent_write",
                            effect_key_argument="effect_key",
                            reconciler=source.reconcile,
                        )
                    },
                )
            registry.register(
                r.ToolSpec("business", "Business", {"type": "object"}), lambda a, c: "ok"
            )
            return registry

        factories.register_async("tools", "roots", tools)
        profile = r.TemporalProfile(
            "roots",
            "1",
            {"default": {"adapter": "writer"}},
            {
                "tools": {"adapter": "roots"},
                "effect_journal": {
                    "adapter": "postgres",
                    "config": {
                        "dsn_env": "RALF_TEST_POSTGRES_DSN",
                        "backend_id": "workspace-writes",
                        "initialize": True,
                    },
                },
            },
            binding_components=[
                {
                    "role": "workspace",
                    "component_id": name,
                    "version": "1",
                    "component": {
                        "adapter": "registered-tools",
                        "config": {"names": [name + "_workspace_write_text"]},
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
                handle = await engine.submit(
                    definition(kind), "write", command_id="same", budget=64
                )
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
                    if stage == 1:
                        saved = done.result
                    else:
                        assert done.result == saved
                    await replay_temporal_history(
                        await client.get_workflow_handle(handle.run_id).fetch_history()
                    )
            finally:
                await assembly.aclose(wait_timeout=30)
            if stage == 1:
                for name in ("alpha", "beta"):
                    if (tmp_path / name / "note").exists():
                        (tmp_path / name / "note").write_text("later external content")
        expected = ["alpha"] if kind == "agent" else ["alpha", "beta"]
        assert sorted(os.path.basename(path) for path, _ in observed) == expected
        for name in ("alpha", "beta"):
            with sqlite3.connect(tmp_path / name / ".ralf/workspace-writes/journal.sqlite") as conn:
                assert conn.execute(
                    "SELECT count(*) FROM workspace_write_effects WHERE receipt IS NOT NULL"
                ).fetchone()[0] == (1 if name in expected else 0)
            if name in expected:
                assert (tmp_path / name / "note").read_text() == "later external content"

    asyncio.run(run())
