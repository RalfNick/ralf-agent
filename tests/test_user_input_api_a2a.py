"""Explicit wire continuation routes an answer, never ordinary task text."""

import asyncio
from dataclasses import asdict

import httpx
import pytest

from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope, TeamSpec, ToolRegistry
from relf_agent.a2a import A2AApplication, A2AClient, A2ARemoteError
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch
from relf_agent.handoff import SQLiteInbox
from relf_agent.task_controls import TaskControlBridge
from relf_agent.types import CommandReceipt, RunDiagnostics, RunSnapshot
from relf_agent.user_input import UserInputPolicy, make_input_record

from .test_task_controls import Controls


class InputAuthority(Controls):
    def __init__(self):
        self.answers = []

    def status(self, run_id):
        return RunSnapshot(
            run_id, "running" if self.answers else "waiting_input", 1, None, None, (), ()
        )

    def send_input(
        self, run_id, pending_id, target_digest, value, *, command_id, expected_state_revision=None
    ):
        self.answers.append((run_id, pending_id, target_digest, value, command_id))
        return CommandReceipt(command_id, run_id, "send_input")


@pytest.mark.parametrize("invalid_source", ["scope", "parent", "cycle"])
def test_discovery_rejects_foreign_question_or_managed_ownership(invalid_source):
    class Source(Controls):
        def diagnostics(self, run_id):
            request = make_input_record(
                run_id="child",
                release_digest="a" * 64,
                scope={"workspace": "other", "principal": "owner"}
                if invalid_source == "scope"
                else asdict(Scope()),
                source={
                    "kind": "tool",
                    "action_id": "action",
                    "node": 0,
                    "proposal_digest": "b" * 64,
                },
                prompt="Continue?",
                policy=UserInputPolicy(),
                ordinal=1,
            )["request"]
            snapshot = RunSnapshot(
                run_id,
                "waiting_input",
                1,
                None,
                None,
                () if run_id == "root" else ({"kind": "input", **request},),
                (),
            )
            workflow = {"children": [{"run_id": "root" if invalid_source == "cycle" else "child"}]}
            return RunDiagnostics(
                snapshot, {}, "a" * 64, {}, workflow if run_id == "root" else None
            )

        def parent_run_id(self, run_id):
            return "foreign" if invalid_source == "parent" else "root"

    with pytest.raises(DefinitionMismatch):
        asyncio.run(TaskControlBridge(Source(), Scope()).pending_inputs("root"))


@pytest.mark.parametrize("bound", ["width", "depth"])
def test_discovery_bounds_original_reads_without_dispatch(bound):
    class Source(Controls):
        reads = 0

        def diagnostics(self, run_id):
            self.reads += 1
            children = (
                [{"run_id": f"n{index}"} for index in range(1, 4098)]
                if bound == "width"
                else [{"run_id": f"n{int(run_id[1:]) + 1}"}]
            )
            return RunDiagnostics(self.status(run_id), {}, "a" * 64, {}, {"children": children})

        def parent_run_id(self, run_id):
            return f"n{int(run_id[1:]) - 1}"

    source = Source()
    with pytest.raises(DefinitionMismatch, match="bounded"):
        asyncio.run(TaskControlBridge(source, Scope()).pending_inputs("n0"))
    assert source.reads == (1 if bound == "width" else 17)


def test_async_native_temporal_public_question_discovery_and_reply(monkeypatch, tmp_path):
    from .temporal_agent_fixture import engine
    from .test_user_input_api_temporal import InputClient

    async def run():
        source = InputClient()
        authority = engine(monkeypatch, client=source, release=source.worker_runtime.manifest)
        inbox = SQLiteInbox(tmp_path / "native-inbox.sqlite")

        async def auth(headers):
            return Scope()

        app = A2AApplication(
            engine_for_scope=lambda scope: authority,
            inbox=inbox,
            authenticate=auth,
            spec=AgentSpec("a", "Ask", ("request_input",)),
            url="http://test/rpc",
            enable_user_input=True,
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = A2AClient("http://test/rpc", client=http)
                root = (await client.send_message("start", "Choose"))["id"]
                task = await client.get_task(root)
                question = task["metadata"]["ralf"]["pending"][0]
                assert question["ownerTaskId"] == question["owner"]["run_id"] == root
                assert question["owner"]["release_digest"] == source.states[root].release_digest
                reply = await client.send_input(
                    question["ownerTaskId"],
                    question["pending_id"],
                    question["target_digest"],
                    "wire",
                    command_id="answer",
                )
                assert reply["status"]["state"] == "completed"
                assert reply["artifacts"][0]["parts"][0]["data"]["result"] == "Selected wire"
                assert not (await client.get_task(root))["metadata"]["ralf"].get("pending")
        finally:
            inbox.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["team", "graph", "nested"])
def test_async_temporal_original_child_questions_are_public_on_root(monkeypatch, tmp_path, kind):
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.user_input import register_user_input

    from .temporal_agent_fixture import engine
    from .temporal_composite_agent_fixture import CompositeClient
    from .test_temporal_user_input import QuestionProvider
    from .test_user_input_api_temporal import InputClient

    class InputComposite(CompositeClient, InputClient):
        def __init__(self):
            super().__init__()
            tools = ToolRegistry()
            register_user_input(tools)
            self.worker_runtime = TemporalRuntime(
                providers={"default": QuestionProvider()}, tools=tools
            )

    async def run():
        source = InputComposite()
        authority = engine(
            monkeypatch, client=source, release=source.worker_runtime.orchestration_release
        )
        worker = AgentSpec("ask", "Ask", ("request_input",))
        graph = GraphWorkflowSpec("graph", [GraphNode("ask", agent=worker)])
        spec = {
            "team": TeamSpec("team", {"ask": worker}),
            "graph": graph,
            "nested": TeamSpec("outer", {"inner": graph}, child_budget=24),
        }[kind]
        inbox = SQLiteInbox(tmp_path / "parent-inbox.sqlite")

        async def auth(headers):
            return Scope()

        app = A2AApplication(
            engine_for_scope=lambda scope: authority,
            inbox=inbox,
            authenticate=auth,
            spec=spec,
            url="http://test/rpc",
            enable_user_input=True,
            budget=64,
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = A2AClient("http://test/rpc", client=http)
                root = (await client.send_message("start", "Choose"))["id"]
                task = await client.get_task(root)
                question = task["metadata"]["ralf"]["pending"][0]
                assert question["ownerTaskId"] == question["owner"]["run_id"] != root
                owner = await client.get_task(question["ownerTaskId"])
                assert owner["status"]["state"] == "input-required"
                await client.send_input(
                    question["ownerTaskId"],
                    question["pending_id"],
                    question["target_digest"],
                    "wire",
                    command_id="answer",
                )
                completed = await client.get_task(root)
                assert completed["status"]["state"] == "completed"
                assert not completed["metadata"]["ralf"].get("pending")
                assert "Selected wire" in str(completed["artifacts"])
        finally:
            inbox.close()

    asyncio.run(run())


def test_selected_composite_requires_discovery_before_accepting_business(tmp_path):
    async def run():
        class Legacy(InputAuthority):
            submissions = 0

            def submit(self, *arguments, **options):
                self.submissions += 1
                return super().submit(*arguments, **options)

        engine, inbox = Legacy(), SQLiteInbox(tmp_path / "inbox.sqlite")

        async def auth(headers):
            return Scope()

        options = dict(
            engine_for_scope=lambda scope: engine,
            inbox=inbox,
            authenticate=auth,
            spec=TeamSpec("team", {"worker": AgentSpec("a", "A")}),
            url="http://test/rpc",
        )
        try:
            selected = A2AApplication(**options, enable_user_input=True)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=selected)) as http:
                client = A2AClient("http://test/rpc", client=http)
                with pytest.raises(A2ARemoteError):
                    await client.send_message("selected", "task")
            assert engine.submissions == 0 and inbox.pending(Scope()) == []
            legacy = A2AApplication(**options)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=legacy)) as http:
                task = await A2AClient("http://test/rpc", client=http).send_message(
                    "legacy", "task"
                )
                assert task["id"] == "run"
            assert engine.submissions == 1
        finally:
            inbox.close()

    asyncio.run(run())


def test_selected_extension_requires_reply_port_before_inbox_or_business_acceptance(tmp_path):
    async def run():
        class ReadOnly(Controls):
            submissions = 0

            def submit(self, *arguments, **options):
                self.submissions += 1
                return super().submit(*arguments, **options)

        engine, inbox = ReadOnly(), SQLiteInbox(tmp_path / "read-only-inbox.sqlite")
        assert await TaskControlBridge(engine, Scope()).pending_inputs("run") == []

        async def auth(headers):
            return Scope()

        options = dict(
            engine_for_scope=lambda scope: engine,
            inbox=inbox,
            authenticate=auth,
            spec=AgentSpec("a", "A"),
            url="http://test/rpc",
        )
        try:
            app = A2AApplication(**options, enable_user_input=True)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                with pytest.raises(A2ARemoteError):
                    await A2AClient("http://test/rpc", client=http).send_message("selected", "task")
            assert engine.submissions == 0 and inbox.pending(Scope()) == []
            assert inbox.result(Scope(), "selected") is None
            legacy = A2AApplication(**options)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=legacy)) as http:
                await A2AClient("http://test/rpc", client=http).send_message("legacy", "task")
            assert engine.submissions == 1
        finally:
            inbox.close()

    asyncio.run(run())


@pytest.mark.parametrize("drift", ["scope", "method", "input"])
def test_optional_async_discovery_refuses_registration_drift_after_await(drift):
    class Async:
        scope = Scope()

        async def submit(self, *arguments, **options):
            return Controls().submit(*arguments, **options)

        async def status(self, run_id):
            return Controls().status(run_id)

        async def cancel(self, *arguments, **options):
            return Controls().cancel(*arguments, **options)

        async def send_input(self, *arguments, **options):
            return CommandReceipt("input", "run", "send_input")

        async def diagnostics(self, run_id):
            await asyncio.sleep(0)
            if drift == "scope":
                self.scope = Scope("other", "owner")
            elif drift == "method":
                self.diagnostics = lambda run_id: None
            else:
                self.send_input = lambda *arguments, **options: None
            return RunDiagnostics(Controls().status(run_id), {}, "a" * 64, {})

    async def run():
        engine = Async()
        controls = TaskControlBridge(engine, Scope())
        error = AuthorizationDenied if drift == "scope" else DefinitionMismatch
        with pytest.raises(error):
            await controls.pending_inputs("run")

    asyncio.run(run())


def test_advertised_input_continuation_routes_and_replays_same_message(tmp_path):
    async def run():
        engine, inbox, wakeups = InputAuthority(), SQLiteInbox(tmp_path / "inbox.db"), []

        async def auth(headers):
            return Scope()

        async def wakeup(scope, run_id):
            wakeups.append(run_id)

        app = A2AApplication(
            engine_for_scope=lambda scope: engine,
            spec=AgentSpec("a", "A"),
            inbox=inbox,
            authenticate=auth,
            url="http://test/rpc",
            wakeup=wakeup,
            enable_user_input=True,
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = A2AClient("http://test/rpc", client=http)
                card = await client.discover()
                assert any(
                    ext["uri"] == "urn:ralf:a2a:user-input:v1"
                    for ext in card["capabilities"]["extensions"]
                )
                first = await client.send_input(
                    "run", "input:" + "b" * 64, "a" * 64, "prod", command_id="reply"
                )
                second = await client.send_input(
                    "run", "input:" + "b" * 64, "a" * 64, "prod", command_id="reply"
                )
                assert first == second
                assert engine.answers == [("run", "input:" + "b" * 64, "a" * 64, "prod", "reply")]
                assert wakeups == ["run", "run"]
                assert first["metadata"]["ralf"]["inputReceipt"]["command_id"] == "reply"
                with pytest.raises(A2ARemoteError):
                    await client.send_input(
                        "run", "input:" + "b" * 64, "a" * 64, "staging", command_id="reply"
                    )
                assert len(engine.answers) == 1
        finally:
            inbox.close()

    asyncio.run(run())


def test_enabled_extension_still_rejects_ordinary_task_text(tmp_path):
    async def run():
        engine, inbox = InputAuthority(), SQLiteInbox(tmp_path / "inbox.db")

        async def auth(headers):
            return Scope()

        app = A2AApplication(
            engine_for_scope=lambda scope: engine,
            spec=AgentSpec("a", "A"),
            inbox=inbox,
            authenticate=auth,
            url="http://test/rpc",
            enable_user_input=True,
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = A2AClient("http://test/rpc", client=http)
                with pytest.raises(A2ARemoteError) as failure:
                    await client.rpc(
                        "message/send",
                        {
                            "message": {
                                "kind": "message",
                                "role": "user",
                                "messageId": "ordinary",
                                "taskId": "run",
                                "parts": [{"kind": "text", "text": "prod"}],
                            }
                        },
                    )
                assert failure.value.rpc_code == -32004
                assert engine.answers == []
        finally:
            inbox.close()

    asyncio.run(run())
