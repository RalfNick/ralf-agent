import asyncio
import importlib.util

import pytest

from relf_agent import AgentSpec, LocalEngine, SQLiteStore, ToolRegistry
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import EchoProvider


def api():
    assert importlib.util.find_spec("relf_agent.teams"), "Missing Team strategy subsystem"
    from relf_agent.orchestration_types import TeamSpec
    from relf_agent.teams import RouterTeam, SequentialTeam, SupervisorTeam

    return TeamSpec, SequentialTeam, RouterTeam, SupervisorTeam


def make_engine(path, **options):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": EchoProvider("worker")},
        tools=ToolRegistry(),
        **options,
    )


def test_team_sequential_children_recover_and_share_total_budget(tmp_path):
    TeamSpec, *_ = api()
    path = tmp_path / "team.sqlite"
    spec = TeamSpec(
        "team",
        {"research": AgentSpec("research", "Research"), "write": AgentSpec("write", "Write")},
        child_budget=4,
    )
    with make_engine(path) as e:
        handle = e.submit(spec, "question", command_id="start", budget=8, session_id="team")
        assert e.submit(spec, "question", command_id="start", budget=8, session_id="team") == handle
    with make_engine(path) as e:
        result = asyncio.run(e.drive(handle.run_id))
        assert result.state == "succeeded"
        details = e.diagnostics(handle.run_id).workflow
        assert len(details["children"]) == 2
        first, second = details["children"]
        assert first["run_id"] != second["run_id"]
        assert e.store.run(first["run_id"])["parent_id"] == handle.run_id
        assert (
            e.store.run(second["run_id"])["input"]["results"]["research"]
            == e.status(first["run_id"]).result
        )
        assert e.diagnostics(handle.run_id).budget == {"limit": 8, "held": 0, "spent": 2}
        assert asyncio.run(e.drive(handle.run_id)) == result
        assert len(e.diagnostics(handle.run_id).workflow["children"]) == 2


def test_router_only_executes_selected_member(tmp_path):
    TeamSpec, *_ = api()
    spec = TeamSpec(
        "router",
        {"one": AgentSpec("one", "One"), "two": AgentSpec("two", "Two")},
        strategy="router",
        strategy_config={"route_field": "route", "routes": {"a": "one", "b": "two"}},
        child_budget=2,
    )
    with make_engine(tmp_path / "router.sqlite") as e:
        handle = e.submit(spec, {"route": "b"}, command_id="s", budget=2)
        assert asyncio.run(e.drive(handle.run_id)).state == "succeeded"
        children = e.diagnostics(handle.run_id).workflow["children"]
        assert [c["member"] for c in children] == ["two"]


def test_supervisor_workers_then_summary(tmp_path):
    TeamSpec, *_ = api()
    members = {name: AgentSpec(name, "Answer") for name in ["one", "two", "boss"]}
    spec = TeamSpec(
        "supervisor",
        members,
        strategy="supervisor",
        strategy_config={"supervisor": "boss"},
        max_concurrency=2,
        child_budget=3,
    )
    with make_engine(tmp_path / "boss.sqlite") as e:
        handle = e.submit(spec, "task", command_id="s", budget=9)
        assert asyncio.run(e.drive(handle.run_id)).state == "succeeded"
        children = e.diagnostics(handle.run_id).workflow["children"]
        assert [c["member"] for c in children] == ["one", "two", "boss"]
        boss = e.store.run(children[-1]["run_id"])
        assert set(boss["input"]["results"]) == {"one", "two"}


def test_failed_child_immediately_cancels_running_sibling_before_its_next_tool(tmp_path):
    from relf_agent import ModelResponse, ToolSpec

    from .helpers import tool_response

    async def scenario():
        slow_started, release, parent_failed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        effects = []

        class Provider:
            identity = {"kind": "fail-fast", "version": "1"}

            async def complete(self, messages, tools):
                instruction = messages[0]["content"]
                if instruction == "fail":
                    await slow_started.wait()
                    return ModelResponse()
                assert instruction == "slow"
                slow_started.set()
                await release.wait()
                return tool_response()

        tools = ToolRegistry()
        tools.register(
            ToolSpec("change", "Count", {"type": "object"}, effect="read_only"),
            lambda arguments, context: effects.append(context.effect_key),
        )
        TeamSpec, *_ = api()
        e = LocalEngine(
            SQLiteStore(tmp_path / "fail-fast.sqlite"),
            providers={"default": Provider()},
            tools=tools,
        )
        task = None
        try:
            handle = e.submit(
                TeamSpec(
                    "fail-fast",
                    {
                        "bad": AgentSpec("bad", "fail"),
                        "slow": AgentSpec("slow", "slow", ("change",)),
                        "boss": AgentSpec("boss", "summarize"),
                    },
                    strategy="supervisor",
                    strategy_config={"supervisor": "boss"},
                    max_concurrency=2,
                    child_budget=4,
                ),
                "task",
                command_id="start",
                budget=12,
            )
            emit = e.store.emit

            def observe_failure(run_id, kind, data=None):
                result = emit(run_id, kind, data)
                if run_id == handle.run_id and kind == "run_failed":
                    parent_failed.set()
                return result

            e.store.emit = observe_failure
            task = asyncio.create_task(e.drive(handle.run_id))
            await asyncio.wait_for(slow_started.wait(), 2)
            await asyncio.wait_for(parent_failed.wait(), 1)
            children = e.diagnostics(handle.run_id).workflow["children"]
            assert len(children) == 2
            assert e.status(children[1]["run_id"]).state in {"cancelling", "cancelled"}
            assert not task.done()  # Real calls retain the coordinator until they finish.
            release.set()
            result = await asyncio.wait_for(task, 2)
            assert result.state == "failed" and result.error["code"] == "child_run_failed"
            assert e.status(children[1]["run_id"]).state == "cancelled"
            assert effects == []
            assert e.diagnostics(handle.run_id).budget["held"] == 0
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await e.wait_for_threads()
            e.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("limit", [0, -1, True, 65])
def test_team_concurrency_has_a_hard_limit(limit):
    TeamSpec, *_ = api()
    with pytest.raises(ValidationError):
        TeamSpec("bad", {"one": AgentSpec("one", "One")}, max_concurrency=limit)


def test_team_cannot_allocate_past_parent_budget(tmp_path):
    TeamSpec, *_ = api()
    spec = TeamSpec("budget", {"one": AgentSpec("one", "One")}, child_budget=4)
    with make_engine(tmp_path / "budget.sqlite") as e:
        h = e.submit(spec, "task", command_id="s", budget=3)
        assert asyncio.run(e.drive(h.run_id)).state == "failed"
        assert e.status(h.run_id).error["code"] == "budget_exceeded"
        assert e.diagnostics(h.run_id).workflow["children"] == []


def test_child_approval_survives_parent_restart_and_replays_once(tmp_path):
    from relf_agent import ModelResponse

    from .helpers import ScriptedProvider, tool_response
    from .test_engine import engine, registry

    TeamSpec, *_ = api()
    effects = []

    async def change(args, ctx):
        effects.append(ctx.effect_key)
        return args

    tools = registry(change)
    path = tmp_path / "approval.sqlite"
    spec = TeamSpec(
        "approval", {"operator": AgentSpec("op", "Change", ("change",))}, child_budget=8
    )
    with engine(path, ScriptedProvider([tool_response()]), tools) as e:
        h = e.submit(spec, "task", command_id="s", budget=8)
        assert asyncio.run(e.drive(h.run_id)).state == "waiting_approval"
        child = e.diagnostics(h.run_id).workflow["children"][0]["run_id"]
        pending = e.status(child).pending[0]
        assert not effects
    with engine(path, ScriptedProvider([ModelResponse(output="verified")]), tools) as e:
        receipt = e.approve(child, pending["action_id"], pending["digest"], command_id="approve")
        assert (
            e.approve(child, pending["action_id"], pending["digest"], command_id="approve")
            == receipt
        )
        assert asyncio.run(e.drive(h.run_id)).state == "succeeded"
        assert len(effects) == 1
        assert e.diagnostics(h.run_id).budget["held"] == 0


def test_parent_cancellation_before_child_dispatch_has_no_effect(tmp_path):
    TeamSpec, *_ = api()
    with make_engine(tmp_path / "cancel.sqlite") as e:
        spec = TeamSpec("cancel", {"one": AgentSpec("one", "One")})
        h = e.submit(spec, "task", command_id="s")
        e.cancel(h.run_id, command_id="cancel")
        assert asyncio.run(e.drive(h.run_id)).state == "cancelled"
        assert e.diagnostics(h.run_id).workflow["children"] == []


def test_parent_cancel_propagates_to_running_children(tmp_path):
    from relf_agent import ModelResponse

    from .test_engine import engine

    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()

        class Provider:
            identity = {"kind": "wait", "version": "1"}
            calls = 0

            async def complete(self, messages, tools):
                self.calls += 1
                started.set()
                await finish.wait()
                return ModelResponse(output="late")

        TeamSpec, *_ = api()
        provider = Provider()
        e = engine(tmp_path / "cancel-active.sqlite", provider, ToolRegistry())
        try:
            h = e.submit(
                TeamSpec("cancel", {"one": AgentSpec("one", "One")}), "task", command_id="s"
            )
            task = asyncio.create_task(e.drive(h.run_id))
            await asyncio.wait_for(started.wait(), 2)
            e.cancel(h.run_id, command_id="cancel")
            child = e.diagnostics(h.run_id).workflow["children"][0]["run_id"]
            assert e.status(child).state in {"cancelling", "cancelled"}
            finish.set()
            result = await task
            assert result.state == "cancelled" and result.error is None
            assert e.status(child).state == "cancelled"
        finally:
            finish.set()
            await e.wait_for_threads()
            e.close()

    asyncio.run(scenario())


def test_custom_strategy_cannot_delegate_same_member_twice(tmp_path):
    from relf_agent.orchestration_types import ChildCall, TeamSelection

    TeamSpec, *_ = api()

    class Strategy:
        identity = {"kind": "duplicate", "version": "1"}

        def select(self, request):
            return TeamSelection([ChildCall("first", "one", "x"), ChildCall("second", "one", "y")])

    with make_engine(tmp_path / "duplicate.sqlite", team_strategies={"bad": Strategy()}) as e:
        h = e.submit(
            TeamSpec("bad", {"one": AgentSpec("one", "One")}, strategy="bad"),
            "task",
            command_id="s",
        )
        assert asyncio.run(e.drive(h.run_id)).state == "failed"
        assert e.diagnostics(h.run_id).workflow["children"] == []


def test_team_call_links_and_escrow_roll_back_together(tmp_path):
    TeamSpec, *_ = api()
    from relf_agent.orchestration_types import ChildCall

    with make_engine(tmp_path / "atomic.sqlite") as e:
        h = e.submit(TeamSpec("atomic", {"one": AgentSpec("one", "One")}), "task", command_id="s")
        original = e.store.insert_run

        def refuse(data):
            if data.get("definition", {}).get("kind") == "agent":
                raise ValidationError("refuse child creation")
            return original(data)

        e.store.insert_run = refuse
        with pytest.raises(ValidationError):
            e._orchestration.delegate(h.run_id, ChildCall("one", "one", "task"))
        assert e.diagnostics(h.run_id).budget == {"limit": 32, "held": 0, "spent": 0}
        assert e.diagnostics(h.run_id).workflow["children"] == []
        e.store.insert_run = original
        assert asyncio.run(e.drive(h.run_id)).state == "succeeded"


def test_child_unknown_write_holds_parent_escrow_until_reconciled(tmp_path):
    from relf_agent import ModelResponse

    from .helpers import ScriptedProvider, tool_response
    from .test_engine import engine, registry

    TeamSpec, *_ = api()
    writes = []

    async def change(args, ctx):
        writes.append(ctx.effect_key)
        raise TimeoutError("business accepted; response missing")

    tools = registry(change, approval=False)
    with engine(
        tmp_path / "unknown.sqlite",
        ScriptedProvider([tool_response(), ModelResponse(output="verified")]),
        tools,
    ) as e:
        h = e.submit(
            TeamSpec("unknown", {"one": AgentSpec("one", "Change", ("change",))}, child_budget=8),
            "task",
            command_id="s",
            budget=8,
        )
        assert asyncio.run(e.drive(h.run_id)).state == "outcome_unknown"
        child = e.diagnostics(h.run_id).workflow["children"][0]["run_id"]
        assert e.diagnostics(h.run_id).budget["held"] == 8
        assert asyncio.run(e.drive(h.run_id)).state == "outcome_unknown"
        assert len(writes) == 1
        action = next(a for a in e.status(child).actions if a["kind"] == "tool")
        e.reconcile(child, action["id"], {"value": 1}, command_id="reconcile")
        assert asyncio.run(e.drive(h.run_id)).state == "succeeded"
        assert len(writes) == 1 and e.diagnostics(h.run_id).budget["held"] == 0


def test_bulk_cancel_keeps_real_child_thread_and_coordinator(tmp_path):
    import threading

    from relf_agent.errors import CoordinatorBusy

    from .helpers import ScriptedProvider, tool_response
    from .test_engine import engine, registry
    from .test_review_shutdown import cancel_all_tasks, finish_loop

    TeamSpec, *_ = api()
    started, finish = threading.Event(), threading.Event()

    def change(args, ctx):
        started.set()
        finish.wait(5)
        return args

    path = tmp_path / "thread.sqlite"
    tools = registry(change, approval=False)
    e = engine(path, ScriptedProvider([tool_response()]), tools)
    loop = asyncio.new_event_loop()
    try:
        h = e.submit(
            TeamSpec("thread", {"one": AgentSpec("one", "Change", ("change",))}),
            "task",
            command_id="s",
        )
        loop.create_task(e.drive(h.run_id))

        async def wait_started():
            for _ in range(1000):
                if started.is_set():
                    return
                await asyncio.sleep(0.001)
            pytest.fail("real handler did not start")

        loop.run_until_complete(wait_started())
        cancel_all_tasks(loop)
        with pytest.raises(ValidationError):
            e.close()
        with SQLiteStore(path) as store:
            with pytest.raises(CoordinatorBusy):
                LocalEngine(
                    store, providers={"default": EchoProvider("contender")}, tools=ToolRegistry()
                )
    finally:
        finish.set()
        loop.run_until_complete(e.wait_for_threads())
        e.close()
        finish_loop(loop)
        loop.close()
    with make_engine(path) as restored:
        assert restored.status(h.run_id).state in {"cancelled", "cancelling"}


def test_custom_team_exception_becomes_safe_parent_failure(tmp_path):
    TeamSpec, *_ = api()

    class Strategy:
        identity = {"kind": "failing-team", "version": "1"}

        def select(self, request):
            raise RuntimeError("private auth token")

    with make_engine(tmp_path / "safe.sqlite", team_strategies={"bad": Strategy()}) as e:
        h = e.submit(
            TeamSpec("safe", {"one": AgentSpec("one", "One")}, strategy="bad"),
            "task",
            command_id="s",
        )
        result = asyncio.run(e.drive(h.run_id))
        assert result.state == "failed" and result.error == {"code": "validation_error"}
        assert "private auth" not in str(e.events(h.run_id))


def test_team_definition_and_proposals_are_detached_and_frozen():
    TeamSpec, *_ = api()
    spec = TeamSpec("immutable", {"one": AgentSpec("one", "One")})
    definition = spec.to_dict()
    definition["members"].clear()
    assert spec.members
    with pytest.raises((AttributeError, ValidationError)):
        spec.name = "changed"


def test_parent_cli_text_reports_children_and_planning_revisions(tmp_path, capsys):
    from relf_agent.cli import main

    TeamSpec, *_ = api()
    path = tmp_path / "view.sqlite"
    with make_engine(path) as e:
        h = e.submit(TeamSpec("view", {"one": AgentSpec("one", "One")}), "task", command_id="s")
        asyncio.run(e.drive(h.run_id))
    assert main(["--db", str(path), "--format", "text", "inspect", h.run_id]) == 0
    assert "Child:" in capsys.readouterr().out


def test_child_release_binds_parent_and_refuses_changed_parent_strategy(tmp_path):
    from relf_agent import SequentialTeam
    from relf_agent.errors import DefinitionMismatch

    from .helpers import ScriptedProvider, tool_response
    from .test_engine import engine, registry

    TeamSpec, *_ = api()

    class Strategy:
        version = "1"

        @property
        def identity(self):
            return {"kind": "bound-parent", "version": self.version}

        def select(self, request):
            return SequentialTeam().select(request)

    strategy = Strategy()
    writes = []

    async def change(args, ctx):
        writes.append(ctx.effect_key)
        return args

    with engine(
        tmp_path / "parent-release.sqlite",
        ScriptedProvider([tool_response()]),
        registry(change),
        team_strategies={"bound": strategy},
    ) as e:
        h = e.submit(
            TeamSpec("bound", {"one": AgentSpec("one", "Change", ("change",))}, strategy="bound"),
            "task",
            command_id="s",
        )
        asyncio.run(e.drive(h.run_id))
        child = e.diagnostics(h.run_id).workflow["children"][0]["run_id"]
        pending = e.status(child).pending[0]
        e.approve(child, pending["action_id"], pending["digest"], command_id="approve")
        strategy.version = "2"
        with pytest.raises(DefinitionMismatch):
            asyncio.run(e.drive(child))
        assert not writes
        strategy.version = "1"
        record = e.store.run(child)
        assert record["manifest"]["parent_call"]["parent_id"] == h.run_id
        submitted = next(ev for ev in e.events(child) if ev.kind == "run_submitted")
        assert submitted.data["release_digest"] == record["release_digest"]
