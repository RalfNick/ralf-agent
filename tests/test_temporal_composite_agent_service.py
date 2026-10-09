"""Opt-in real Service/Workers; no paid model or remote data dependencies."""

import asyncio
import os
import sqlite3
import uuid

import pytest

import ralf_agent as r
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime

from .temporal_agent_fixture import Provider
from .temporal_composite_agent_fixture import definitions

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def resources(database):
    async def lookup(arguments, context):
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS calls (effect_key TEXT PRIMARY KEY,n INTEGER)"
            )
            connection.execute(
                "INSERT INTO calls VALUES (?,1) ON CONFLICT(effect_key) DO UPDATE SET n=n+1",
                (context.effect_key,),
            )
        return {"found": True}

    tools = r.ToolRegistry()
    tools.register(
        r.ToolSpec(
            "lookup", "Lookup", {"type": "object"}, requires_approval=True, effect="read_only"
        ),
        lookup,
    )
    return TemporalRuntime(providers={"default": Provider()}, tools=tools)


def definition(kind):
    if kind == "parallel":
        return r.GraphWorkflowSpec(
            "parallel",
            [
                r.GraphNode(name, agent=r.AgentSpec(name, "Answer", ("lookup",)))
                for name in ("a", "b")
            ],
            max_concurrency=2,
        )
    return definitions()[kind]


@pytest.mark.parametrize("kind", ["graph", "parallel", "team", "dynamic", "plan", "nested"])
def test_actual_composite_facade_original_child_approval_reconnect_and_history(tmp_path, kind):
    async def scenario():
        from temporalio.client import Client

        database = tmp_path / "calls.sqlite"
        execution = resources(database)
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "composite-agent-" + uuid.uuid4().hex
        scope = r.Scope("composite-agent-tests", queue)
        raw = TemporalEngine(
            client, task_queue=queue, release=execution.orchestration_release, scope=scope
        )
        worker = build_temporal_worker(client, task_queue=queue, runtime=execution)
        async with worker:
            async with r.Runtime.from_temporal(raw, owned=True) as runtime:
                run = await runtime.create_agent(definition(kind)).submit(
                    "q", command_id="s", budget=64
                )
                assert (await run.wait(wait_timeout=20)).snapshot.state == "waiting_approval"
                ref, original = run.ref, run.receipt
                assert not database.exists()
            changed = TemporalEngine(
                client,
                task_queue="unavailable",
                release={
                    **execution.orchestration_release,
                    "providers": {"moved": {"kind": "other", "version": "2"}},
                },
                scope=scope,
            )
            async with r.Runtime.from_temporal(changed) as runtime:
                restored = await runtime.aattach(r.RunRef.from_dict(ref.to_dict()))
                assert (
                    await runtime.create_agent(definition(kind)).submit(
                        "q", command_id="s", budget=64
                    )
                ).receipt == original
                owners = set()
                for _ in range(40):
                    for item in await restored.pending():
                        owner = await runtime.aattach(r.RunRef.from_dict(item["ref"]))
                        assert owner.ref.run_id != ref.run_id
                        owners.add(owner.ref.run_id)
                        receipt = await owner.approve(
                            item["action_id"],
                            item["digest"],
                            command_id="approve:" + owner.ref.run_id,
                        )
                        assert (
                            await owner.approve(
                                item["action_id"],
                                item["digest"],
                                command_id="approve:" + owner.ref.run_id,
                            )
                            == receipt
                        )
                    observed = await restored.wait(wait_timeout=0.5, terminal_only=True)
                    if observed.snapshot.state == "succeeded":
                        break
                assert observed.snapshot.state == "succeeded"
                expected = (
                    {"a": "done", "b": "done"}
                    if kind == "parallel"
                    else ({"a": "done"} if kind in {"graph", "nested"} else "done")
                )
                assert observed.snapshot.result == expected
                deadline = asyncio.get_running_loop().time() + 10
                while (await restored.diagnostics()).budget["reserved"]:
                    assert asyncio.get_running_loop().time() < deadline
                    await asyncio.sleep(0.05)
                assert (await restored.diagnostics()).budget["unknown"] == 0
                with sqlite3.connect(database) as connection:
                    assert connection.execute("SELECT n FROM calls").fetchall() == [(1,)] * (
                        2 if kind == "parallel" else 1
                    )
                assert len(owners) == (2 if kind == "parallel" else 1)
                assert await restored.pending() == []
            # Replay every accepted child and root with actual recorded Activities.
            todo, seen = [ref.run_id], set()
            while todo:
                run_id = todo.pop()
                if run_id in seen:
                    continue
                seen.add(run_id)
                info = await changed.diagnostics(run_id)
                todo.extend(c["run_id"] for c in info.workflow.get("children", []))
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["graph", "team", "nested"])
def test_actual_root_cancel_propagates_and_releases_undispatched_approval_capacity(tmp_path, kind):
    async def scenario():
        from temporalio.client import Client

        database = tmp_path / "calls.sqlite"
        execution = resources(database)
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "cancel-composite-" + uuid.uuid4().hex
        raw = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=r.Scope("composite-agent-tests", queue),
        )
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            async with r.Runtime.from_temporal(raw) as runtime:
                run = await runtime.create_agent(definition(kind)).submit(
                    "q", command_id="s", budget=64
                )
                assert (await run.wait(wait_timeout=20)).snapshot.state == "waiting_approval"
                receipt = await run.cancel(command_id="stop")
                assert await run.cancel(command_id="stop") == receipt
                assert (await run.wait(wait_timeout=1)).snapshot.state == "cancelled"
                deadline = asyncio.get_running_loop().time() + 20
                while not (await run.diagnostics()).workflow["quiescent"]:
                    assert asyncio.get_running_loop().time() < deadline, (
                        "actual children did not settle"
                    )
                    await asyncio.sleep(0.1)
                assert await run.pending() == [] and not database.exists()
                assert (await run.diagnostics()).budget["reserved"] == 0
                await replay_temporal_history(
                    await client.get_workflow_handle(run.ref.run_id).fetch_history()
                )

    asyncio.run(scenario())
