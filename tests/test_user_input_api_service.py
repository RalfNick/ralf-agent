"""An A2A child reply wakes its original managed root, preserving host ownership."""

import asyncio

import httpx
import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    ModelResponse,
    ProfiledEngine,
    RuntimeBuilder,
    RuntimeCatalog,
    RuntimeProfile,
    Scope,
    TeamSpec,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from ralf_agent.a2a import A2AClient
from ralf_agent.errors import CoordinatorBusy, DefinitionMismatch
from ralf_agent.handoff import SQLiteInbox
from ralf_agent.service_lifecycle import LocalA2AService
from ralf_agent.storage import SQLiteStore
from ralf_agent.task_controls import TaskControlBridge
from ralf_agent.user_input import register_user_input


class Provider:
    identity = {"kind": "service-input-fixture", "version": "1"}

    async def complete(self, messages, tools):
        if any(message["role"] == "tool" for message in messages):
            return ModelResponse(output="confirmed")
        return ModelResponse(tool_calls=(ToolCall("request_input", {"prompt": "Continue?"}),))


def profiled_engine(path, *, provider_calls=None):
    registry = ComponentRegistry()

    def provider(config, context):
        if provider_calls is not None:
            provider_calls.append(True)
        return Provider()

    registry.register("provider", "question-fixture", provider)
    catalog = RuntimeCatalog()
    catalog.register(
        RuntimeProfile(
            "questions",
            "1",
            {"default": {"adapter": "question-fixture"}},
            {
                "user_input_policies": {
                    "adapter": "configured",
                    "config": {
                        "policies": {"ask": {}},
                        "tools": {"request_input": {"policy": "ask"}},
                    },
                }
            },
        ),
        default=True,
    )
    return ProfiledEngine(catalog, path, builder=RuntimeBuilder(registry))


def test_profiled_input_discovery_preflight_is_stable_and_constructs_no_resources(tmp_path):
    path, calls = tmp_path / "not-created.sqlite", []
    engine = profiled_engine(path, provider_calls=calls)
    try:
        controls = TaskControlBridge(engine, Scope())
        controls.require_input_discovery(composite=True)
        controls.verify()
        assert not path.exists() and calls == [] and engine._active is None
        engine.reader.diagnostics = lambda run_id: None
        with pytest.raises(DefinitionMismatch, match="registration"):
            controls.verify()
        assert not path.exists() and calls == []
    finally:
        engine.close()


def test_public_completion_close_retains_actual_drive_cleanup_and_lease(tmp_path):
    async def run():
        cleanup_entered, release = asyncio.Event(), asyncio.Event()
        cancels = []

        class CompleteProvider:
            identity = {"kind": "service-completion-cleanup-fixture", "version": "1"}

            async def complete(self, messages, tools):
                return ModelResponse(output="completed")

        class CleanupEngine(LocalEngine):
            async def drive(self, run_id):
                result = await super().drive(run_id)
                cleanup_entered.set()
                await release.wait()
                return result

            def cancel(self, run_id, *, command_id):
                cancels.append(run_id)
                return super().cancel(run_id, command_id=command_id)

        path = tmp_path / "cleanup.sqlite"
        engine = CleanupEngine(
            SQLiteStore(path), providers={"default": CompleteProvider()}, tools=ToolRegistry()
        )
        inbox = SQLiteInbox(tmp_path / "cleanup-inbox.sqlite")

        async def authenticate(headers):
            return Scope()

        service = LocalA2AService(
            engine=engine,
            inbox=inbox,
            spec=AgentSpec("a", "Complete"),
            authenticate=authenticate,
            url="http://test/rpc",
            enable_user_input=True,
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service)) as http:
                client = A2AClient("http://test/rpc", client=http)
                root = (await client.send_message("start", "Complete"))["id"]
                await asyncio.wait_for(cleanup_entered.wait(), 1)
                assert (await client.get_task(root))["status"]["state"] == "completed"
                closing = asyncio.create_task(service.aclose())
                await asyncio.sleep(0.01)
                assert not closing.done() and cancels == []
                with SQLiteStore(path) as contender:
                    with pytest.raises(CoordinatorBusy):
                        contender.create_coordinator().acquire()
                closing.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await closing
                assert not service.closed
                release.set()
                await service.aclose()
                assert service.closed
                with LocalEngine(SQLiteStore(path), providers={}, tools=ToolRegistry()):
                    pass
        finally:
            release.set()
            await service.aclose()

    asyncio.run(run())


async def reached(engine, run_id, state):
    async with asyncio.timeout(2):
        while engine.status(run_id).state != state:  # noqa: ASYNC110 -- authoritative polling has no Event
            await asyncio.sleep(0.01)


async def parked(service, engine, run_id, state):
    async with asyncio.timeout(2):
        while engine.status(run_id).state != state or service._active:  # noqa: ASYNC110 -- no lifecycle Event
            await asyncio.sleep(0.01)


async def task_reached(client, run_id, state):
    async with asyncio.timeout(2):
        while True:
            task = await client.get_task(run_id)
            if task["metadata"]["ralf"]["state"] == state:
                return task
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("blocked_control", ["approval", "unknown"])
def test_applied_child_input_wakes_paused_root_without_resolving_sibling_control(
    tmp_path, blocked_control
):
    async def run():
        model_calls, tool_calls = [], []

        class MixedProvider:
            identity = {"kind": "mixed-service-input-fixture", "version": "1"}

            async def complete(self, messages, tools):
                model_calls.append(messages)
                if not tools or any(message["role"] == "tool" for message in messages):
                    return ModelResponse(output="confirmed")
                name = tools[0]["function"]["name"]
                return ModelResponse(
                    tool_calls=(
                        ToolCall(name, {"prompt": "Continue?"} if name == "request_input" else {}),
                    )
                )

        def blocked(arguments, context):
            tool_calls.append(context.action_id)
            if blocked_control == "unknown":
                raise RuntimeError("Original write response was lost")
            return "approved"

        tools = ToolRegistry()
        register_user_input(tools)
        tools.register(
            ToolSpec(
                "blocked",
                "Independent controlled operation",
                {"type": "object"},
                requires_approval=blocked_control == "approval",
                effect="unqueryable_write",
            ),
            blocked,
        )
        path = tmp_path / "mixed.sqlite"
        engine = LocalEngine(SQLiteStore(path), tools=tools, providers={"default": MixedProvider()})
        inbox = SQLiteInbox(tmp_path / "inbox.sqlite")

        async def authenticate(headers):
            return Scope()

        service = LocalA2AService(
            engine=engine,
            inbox=inbox,
            spec=TeamSpec(
                "team",
                {
                    "ask": AgentSpec("ask", "Ask", ("request_input",)),
                    "blocked": AgentSpec("blocked", "Operate", ("blocked",)),
                    "finish": AgentSpec("finish", "Summarize"),
                },
                strategy="supervisor",
                strategy_config={"supervisor": "finish"},
                max_concurrency=2,
            ),
            authenticate=authenticate,
            url="http://test/rpc",
            enable_user_input=True,
        )
        pause = "waiting_approval" if blocked_control == "approval" else "waiting_reconciliation"
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service)) as http:
                client = A2AClient("http://test/rpc", client=http)
                root = (await client.send_message("start", "question"))["id"]
                await parked(service, engine, root, pause)
                public_root = await client.get_task(root)
                question = next(
                    item
                    for item in public_root["metadata"]["ralf"]["pending"]
                    if item["kind"] == "input"
                )
                asking = question["ownerTaskId"]
                assert asking == question["owner"]["run_id"] != root
                children = engine.diagnostics(root).workflow["children"]
                sibling = next(
                    child["run_id"] for child in children if child["member"] == "blocked"
                )
                before_sibling = engine.status(sibling)
                before_models = len(model_calls)
                before_tools = len(tool_calls)
                rejected = await client.send_input(
                    asking,
                    question["pending_id"],
                    question["target_digest"],
                    {},
                    command_id="invalid-answer",
                )
                assert rejected["metadata"]["ralf"]["inputReceipt"]["apply_state"] == "rejected"
                await asyncio.sleep(0)
                assert not service._active and engine.status(asking).state == "waiting_input"
                assert len(model_calls) == before_models and len(tool_calls) == before_tools
                response = await client.send_input(
                    asking,
                    question["pending_id"],
                    question["target_digest"],
                    "yes",
                    command_id="answer",
                )
                assert response["metadata"]["ralf"]["inputReceipt"]["apply_state"] == "applied"
                await reached(engine, asking, "succeeded")
                await parked(service, engine, root, pause)
                assert engine.status(asking).result == "confirmed"
                after_sibling = engine.status(sibling)
                assert after_sibling.state == before_sibling.state == pause
                assert after_sibling.pending == before_sibling.pending
                assert after_sibling.actions == before_sibling.actions
                assert len(model_calls) == before_models + 1
                assert len(tool_calls) == before_tools == (blocked_control == "unknown")
                assert len(engine.diagnostics(root).workflow["children"]) == 2
                assert not service.errors
                # A standalone paused-root wake remains inert.
                await service.wakeup(Scope(), root)
                assert not service._active and len(model_calls) == before_models + 1
        finally:
            await service.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["agent", "team", "graph", "parallel-graph", "nested"])
@pytest.mark.parametrize("authority", ["local", "profiled"])
def test_public_root_question_discovery_resumes_original_owner_and_root(tmp_path, kind, authority):
    async def run():
        tools = ToolRegistry()
        register_user_input(tools)
        path = tmp_path / "runs.sqlite"
        engine = (
            LocalEngine(SQLiteStore(path), tools=tools, providers={"default": Provider()})
            if authority == "local"
            else profiled_engine(path)
        )
        inbox = SQLiteInbox(tmp_path / "inbox.sqlite")

        async def authenticate(headers):
            return Scope()

        worker = AgentSpec("worker", "Ask", ("request_input",))
        spec = {
            "agent": worker,
            "team": TeamSpec("team", {"worker": worker}),
            "graph": GraphWorkflowSpec("graph", [GraphNode("ask", agent=worker)]),
            "parallel-graph": GraphWorkflowSpec(
                "parallel", [GraphNode("ask", agent=worker)], max_concurrency=2
            ),
            "nested": TeamSpec("outer", {"inner": TeamSpec("inner", {"worker": worker})}),
        }[kind]
        service = LocalA2AService(
            engine=engine,
            inbox=inbox,
            spec=spec,
            authenticate=authenticate,
            url="http://test/rpc",
            enable_user_input=True,
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service)) as http:
                client = A2AClient("http://test/rpc", client=http)
                submitted = await client.send_message("start", "question")
                root_id = submitted["id"]
                public_root = await task_reached(client, root_id, "waiting_input")
                question = next(
                    item
                    for item in public_root["metadata"]["ralf"]["pending"]
                    if item["kind"] == "input"
                )
                owner_id = question["ownerTaskId"]
                assert owner_id == question["owner"]["run_id"]
                assert (owner_id != root_id) == (kind in {"team", "nested"})
                assert question["prompt"] == "Continue?"
                assert question["reply_schema"]["type"] == "string"
                assert (await client.get_task(owner_id))["status"]["state"] == "input-required"
                await client.send_input(
                    owner_id,
                    question["pending_id"],
                    question["target_digest"],
                    "yes",
                    command_id="reply",
                )
                completed = await task_reached(client, root_id, "succeeded")
                assert completed["status"]["state"] == "completed"
                assert not completed["metadata"]["ralf"].get("pending")
                assert (await client.get_task(owner_id))["status"]["state"] == "completed"
        finally:
            await service.aclose()

    asyncio.run(run())
