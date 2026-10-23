import asyncio
import os
import uuid

import pytest

from relf_agent import AgentSpec, ModelResponse, Runtime, Scope, ToolRegistry
from relf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from relf_agent.temporal_activities import TemporalRuntime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_session_conversation_and_turn_replay_on_actual_service():
    async def run():
        from temporalio.client import Client

        class Provider:
            identity = {"kind": "session-service", "version": "1"}

            async def complete(self, messages, tools):
                assert messages[1]["content"] in {"question", "follow up"}
                if messages[1]["content"] == "follow up":
                    assert "question" in str(messages[2:]) and "answer" in str(messages[2:])
                return ModelResponse(output="answer")

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "sessions-" + uuid.uuid4().hex
        execution = TemporalRuntime(
            providers={"default": Provider()}, tools=ToolRegistry(), enable_sessions=True
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.manifest,
            scope=Scope("session-tests", queue),
        )
        runtime = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                session = await runtime.open_session(
                    AgentSpec("answer", "Answer"), queue, command_id="open-" + queue
                )
                first = await session.submit("question", command_id="turn-" + queue)
                assert (await first.wait(wait_timeout=20)).snapshot.state == "succeeded"
                for _ in range(100):
                    if not (await session.status()).busy:
                        break
                    await asyncio.sleep(0.05)
                assert not (await session.status()).busy
                replay = await session.submit("question", command_id="turn-" + queue)
                assert replay.turn == first.turn
                second = await session.submit("follow up", command_id="second-" + queue)
                assert second.turn.turn_seq == 2
                assert (await second.wait(wait_timeout=20)).snapshot.state == "succeeded"
                assert [t.turn_seq for t in await session.turns()] == [1, 2]
                from relf_agent.temporal_session_state import workflow_id

                await replay_temporal_history(
                    await client.get_workflow_handle(workflow_id(session.ref.key)).fetch_history()
                )
        finally:
            await runtime.aclose()
            await engine.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("graph", [False, True])
def test_approval_busy_receipt_alias_reconnect_and_idle_rebind(graph):
    async def run():
        from temporalio.client import Client

        from relf_agent import GraphNode, GraphWorkflowSpec, ToolCall, ToolSpec
        from relf_agent.errors import SessionBindingMismatch, SessionBusy

        class ApprovalProvider:
            identity = {"kind": "session-approval", "version": "1"}

            async def complete(self, messages, tools):
                if tools and not any(m["role"] == "tool" for m in messages):
                    return ModelResponse(tool_calls=[ToolCall("lookup", {}, "lookup")])
                return ModelResponse(output="done")

        calls = []

        async def lookup(arguments, context):
            calls.append(context.effect_key)
            return {"found": True}

        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "lookup", "lookup", {"type": "object"}, requires_approval=True, effect="read_only"
            ),
            lookup,
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "session-approval-" + uuid.uuid4().hex
        execution = TemporalRuntime(
            providers={"default": ApprovalProvider()}, tools=tools, enable_sessions=True
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("session-approval", queue),
        )
        host = Runtime.from_temporal(engine)
        agent = AgentSpec("answer", "Answer", ("lookup",))
        definition = GraphWorkflowSpec("g", [GraphNode("a", agent=agent)]) if graph else agent
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(definition, "chat", command_id="open")
                first = await entry.submit("question", command_id="turn")
                assert (await first.wait(wait_timeout=20)).snapshot.state == "waiting_approval"
                with pytest.raises(SessionBusy) as busy:
                    await entry.submit("later", command_id="busy")
                refused = busy.value.receipt
                assert not calls and (await entry.status()).busy
                await host.aclose()
                alias = os.environ["RALF_TEST_TEMPORAL_ADDRESS"].replace("127.0.0.1", "localhost")
                reconnected = await Client.connect(alias)
                other = TemporalEngine(
                    reconnected, task_queue=queue, release=engine.release, scope=engine.scope
                )
                host = Runtime.from_temporal(other)
                attached = await host.aattach_session(entry.ref)
                run = await host.aattach(first.ref)
                item = (await run.pending())[0]
                owner = await host.aattach(type(first.ref).from_dict(item["ref"]))
                receipt = await owner.approve(item["action_id"], item["digest"], command_id="yes")
                assert (
                    await owner.approve(item["action_id"], item["digest"], command_id="yes")
                    == receipt
                )
                assert (
                    await run.wait(wait_timeout=20, terminal_only=True)
                ).snapshot.state == "succeeded"
                for _ in range(200):
                    if not (await attached.status()).busy:
                        break
                    await asyncio.sleep(0.05)
                assert not (await attached.status()).busy and len(calls) == 1
                with pytest.raises(SessionBusy) as repeated:
                    await attached.submit("later", command_id="busy")
                assert repeated.value.receipt == refused
                rebound = await attached.rebind(
                    AgentSpec("new", "New binding"),
                    expected_binding_revision=1,
                    command_id="rebind",
                )
                assert rebound.ref.binding_revision == 2
                assert (await attached.submit("question", command_id="turn")).turn == first.turn
                with pytest.raises(SessionBindingMismatch):
                    await attached.submit("new", command_id="stale")
                assert (await rebound.diagnostics())["error"] is None
                await other.aclose()
        finally:
            await host.aclose()
            await engine.aclose()

    asyncio.run(run())
