import asyncio
import os
import uuid

import pytest

from relf_agent import AgentSpec, ModelResponse, Scope, ToolCall, ToolRegistry

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_actual_temporal_middleware_approval_restart_and_resumed_events():
    async def run():
        from temporalio.client import Client, WorkflowHistory

        from relf_agent import (
            MiddlewareProvider,
            MiddlewareToolExecutor,
            NoopMiddleware,
            PythonToolExecutor,
            RunEventSubscription,
            TemporalEngine,
            TemporalRuntime,
            build_temporal_worker,
            replay_temporal_history,
        )

        calls = []

        class Provider:
            identity = {"kind": "temporal-observable-fixture", "version": "1"}

            async def complete(self, messages, tools):
                if any(m["role"] == "tool" for m in messages):
                    return ModelResponse("done")
                return ModelResponse(tool_calls=(ToolCall("read", {"value": 7}, "call"),))

        tools = ToolRegistry()

        @tools.tool(effect="read_only", requires_approval=True)
        def read(value: int):
            calls.append(value)
            return {"value": value}

        runtime = TemporalRuntime(
            providers={"default": MiddlewareProvider(Provider(), [NoopMiddleware()])},
            tools=tools,
            tool_executor=MiddlewareToolExecutor(PythonToolExecutor(tools), [NoopMiddleware()]),
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "observable-" + uuid.uuid4().hex
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=runtime.manifest,
            scope=Scope("observable", queue),
            drive_timeout=20,
        )
        async with build_temporal_worker(client, task_queue=queue, runtime=runtime):
            handle = await engine.submit(
                AgentSpec("a", "Read7", ("read",)), "q", command_id="first"
            )
            paused = await engine.drive(handle.run_id)
            assert paused.state == "waiting_approval" and calls == []
            observed = [
                row
                async for row in RunEventSubscription(
                    engine, handle.run_id, follow=False, page_size=2
                )
            ]
            cursor = observed[-1].cursor
        async with build_temporal_worker(client, task_queue=queue, runtime=runtime):
            pending = paused.pending[0]
            receipt = await engine.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            assert (
                await engine.approve(
                    handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
                )
                == receipt
            )
            assert (await engine.drive(handle.run_id)).state == "succeeded" and calls == [7]
            remaining = [
                row
                async for row in RunEventSubscription(
                    engine, handle.run_id, after=cursor, page_size=2
                )
            ]
            assert remaining and remaining[0].event.seq == cursor.after + 1
            assert [row.event for row in remaining] == await engine.events(
                handle.run_id, after=cursor.after
            )
            history = await client.get_workflow_handle(handle.run_id).fetch_history()
            await replay_temporal_history(
                WorkflowHistory.from_json(handle.run_id, history.to_json())
            )

    asyncio.run(run())
