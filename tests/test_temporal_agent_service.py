"""Opt-in actual persisted Temporal Service, Worker and History acceptance."""

import asyncio
import os
import sqlite3
import uuid

import pytest

import relf_agent as r
from relf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from relf_agent.temporal_activities import TemporalRuntime

from .temporal_agent_fixture import Provider

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("sequence", [False, True])
def test_actual_remote_agent_approval_detach_reconnect_and_history(tmp_path, sequence):
    async def scenario():
        from temporalio.client import Client

        database = tmp_path / "lookup-audit.sqlite"

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
        worker_runtime = TemporalRuntime(providers={"default": Provider()}, tools=tools)
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "agent-facade-" + uuid.uuid4().hex
        scope = r.Scope("agent-facade-tests", queue)
        raw = TemporalEngine(client, task_queue=queue, release=worker_runtime.manifest, scope=scope)
        worker = build_temporal_worker(client, task_queue=queue, runtime=worker_runtime)
        spec = r.AgentSpec("a", "Answer", ("lookup",))
        definition = (
            r.WorkflowSpec("sequence", [spec, r.AgentSpec("b", "Finish")]) if sequence else spec
        )
        async with worker:
            async with r.Runtime.from_temporal(raw, owned=True) as runtime:
                agent = runtime.create_agent(definition)
                run = await agent.submit("q", command_id="submit")
                assert (await run.wait(wait_timeout=20)).snapshot.state == "waiting_approval"
                ref, original = run.ref, run.receipt
                assert not database.exists()
            assert raw._closed
            # Same service/Scope, moved queue/default release; original History wins.
            changed = TemporalEngine(
                client,
                task_queue="unavailable",
                release={**worker_runtime.manifest, "policy": {"kind": "moved"}},
                scope=scope,
            )
            async with r.Runtime.from_temporal(changed) as runtime:
                restored = await runtime.aattach(r.RunRef.from_dict(ref.to_dict()))
                replay = await runtime.create_agent(definition).submit("q", command_id="submit")
                assert replay.receipt == original and replay.ref == ref
                action = (await restored.pending())[0]
                receipt = await restored.approve(
                    action["action_id"], action["digest"], command_id="approve"
                )
                assert (
                    await restored.approve(
                        action["action_id"], action["digest"], command_id="approve"
                    )
                    == receipt
                )
                assert (await restored.wait(wait_timeout=20)).snapshot.result == "done"
                with sqlite3.connect(database) as connection:
                    assert connection.execute("SELECT n FROM calls").fetchall() == [(1,)]
                assert (await restored.events())[-1].seq > 1
            history = await client.get_workflow_handle(ref.run_id).fetch_history()
            await replay_temporal_history(history)

    asyncio.run(scenario())


def test_actual_remote_observer_cancel_and_client_close_leave_worker_running():
    async def scenario():
        from temporalio.client import Client

        called, release = asyncio.Event(), asyncio.Event()

        class BlockingProvider:
            identity = {"kind": "facade-observer-blocking", "version": "1"}

            async def complete(self, messages, tools):
                called.set()
                await release.wait()
                return r.ModelResponse(output="completed-after-detach")

        worker_runtime = TemporalRuntime(
            providers={"default": BlockingProvider()}, tools=r.ToolRegistry()
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "agent-observer-" + uuid.uuid4().hex
        scope = r.Scope("agent-facade-tests", queue)
        raw = TemporalEngine(client, task_queue=queue, release=worker_runtime.manifest, scope=scope)
        worker = build_temporal_worker(client, task_queue=queue, runtime=worker_runtime)
        async with worker:
            runtime = r.Runtime.from_temporal(raw, owned=True)
            run = await runtime.create_agent(r.AgentSpec("a", "A")).submit("q", command_id="s")
            await asyncio.wait_for(called.wait(), 20)
            try:
                before = await run.events()
                result = await run.wait(wait_timeout=0.02)
                assert result.wait_reason == "observation_timeout"
                observer = asyncio.create_task(run.wait())
                await asyncio.sleep(0.02)
                observer.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await observer
                assert await run.events() == before
                await runtime.aclose(close_timeout=1)
                assert raw._closed and not release.is_set()
                reconnect = TemporalEngine(
                    client, task_queue=queue, release=worker_runtime.manifest, scope=scope
                )
                async with r.Runtime.from_temporal(reconnect) as recovered:
                    attached = await recovered.aattach(run.ref)
                    assert (await attached.status()).state == "running"
                    release.set()
                    assert (
                        await attached.wait(wait_timeout=20)
                    ).snapshot.result == "completed-after-detach"
                await replay_temporal_history(
                    await client.get_workflow_handle(run.ref.run_id).fetch_history()
                )
            finally:
                release.set()
                if runtime.state != "closed":
                    await runtime.aclose()

    asyncio.run(scenario())
