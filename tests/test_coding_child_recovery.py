"""Original recorded Coding children retain authority and physical stop closure."""

import asyncio

import pytest

from relf_agent import AgentSpec, DynamicWorkflowSpec, LocalEngine, ModelResponse, TeamSpec
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.storage import SQLiteStore

from .helpers import tool_response
from .test_local_delegated_coding import LifecycleRunner, coding_engine


class LostTurnRunner(LifecycleRunner):
    async def execute(self, envelope, authority):
        class LostReceipt:
            def __getattr__(self, name):
                return getattr(authority, name)

            def adopt(self, kind, evidence):
                if kind == "turn":
                    raise RuntimeError("original native Turn response lost")
                return authority.adopt(kind, evidence)

        return await super().execute(envelope, LostReceipt())


def parent_spec(kind="team", *, nested=False):
    member = AgentSpec("worker", "write", ("coding",))
    if nested:
        member = TeamSpec("inner", {"worker": member}, child_budget=8)
    cls = TeamSpec if kind == "team" else DynamicWorkflowSpec
    return cls("outer", {"member": member}, child_budget=16 if nested else 8)


def original_leaf(engine, parent_id):
    run = engine.store.run(parent_id)
    while run.get("orchestration") is not None:
        assert len(run["orchestration"]["children"]) == 1
        call = run["orchestration"]["children"][0]
        child = engine.store.run(call["run_id"])
        assert child["parent_call"] == {
            "parent_id": run["id"],
            "call_id": call["id"],
            "reservation": call["reservation"],
        }
        assert child["manifest"]["parent_call"] == child["parent_call"]
        run = child
    return run


@pytest.mark.parametrize("kind", ["team", "dynamic"])
@pytest.mark.parametrize("nested", [False, True])
def test_original_child_approval_survives_cold_parent_restart(tmp_path, kind, nested):
    async def exercise():
        runner = LifecycleRunner()
        engine, provider = coding_engine(tmp_path, runner)
        handle = engine.submit(parent_spec(kind, nested=nested), "x", command_id="s")
        root = engine.store.run(handle.run_id)
        assert root["manifest"]["delegated_composition_protocol"] == 1
        assert root["manifest"]["kernel"] == "local-11"
        assert (
            engine.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "14"
        )
        assert (await engine.drive(handle.run_id)).state == "waiting_approval"
        leaf = original_leaf(engine, handle.run_id)
        action = leaf["actions"][-1]
        engine.close()
        rebuilt = LocalEngine(
            SQLiteStore(tmp_path / "coding.db"), providers={"default": provider}, tools=engine.tools
        )
        rebuilt.approve(leaf["id"], action["id"], action["digest"], command_id="approve")
        assert (await rebuilt.drive(handle.run_id)).state == "succeeded"
        saved = original_leaf(rebuilt, handle.run_id)
        tool = next(a for a in saved["actions"] if a["kind"] == "tool")
        request = tool["delegated_execution"]["request"]
        assert request["dispatch"]["run_id"] == leaf["id"]
        assert request["release_digest"] == saved["release_digest"]
        assert len(tool["attempts"]) == 1 and runner.calls.count("execute") == 1
        assert provider.calls == 2
        rebuilt.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("lost_turn", [False, True])
def test_cold_parent_cancel_retains_original_child_stop_fault_and_unknown_escrow(
    tmp_path, nested, lost_turn
):
    async def exercise():
        runner = (LostTurnRunner if lost_turn else LifecycleRunner)(crash=True, fail_stop=True)
        engine, provider = coding_engine(tmp_path, runner, [tool_response("coding", {"task": "x"})])
        handle = engine.submit(parent_spec(nested=nested), "x", command_id="s")
        await engine.drive(handle.run_id)
        leaf = original_leaf(engine, handle.run_id)
        action = leaf["actions"][-1]
        engine.approve(leaf["id"], action["id"], action["digest"], command_id="approve")
        assert (await engine.drive(handle.run_id)).state == "outcome_unknown"
        request = original_leaf(engine, handle.run_id)["actions"][-1]["delegated_execution"][
            "request"
        ]
        if lost_turn:
            original = original_leaf(engine, handle.run_id)["actions"][-1]["delegated_execution"]
            assert "turn/start" in original["grants"] and "turn" not in original
        engine.store.close()
        engine.coordinator.release()
        rebuilt = LocalEngine(
            SQLiteStore(tmp_path / "coding.db"), providers={"default": provider}, tools=engine.tools
        )
        rebuilt.cancel(handle.run_id, command_id="cancel")
        assert rebuilt.status(handle.run_id).state == "cancelling"
        assert (await rebuilt.drive(handle.run_id)).state == "cancelling"
        assert rebuilt.store.delegated_pending(rebuilt.scope) == (leaf["id"],)
        assert rebuilt.store.budget(handle.run_id)["held"] > 0
        runner.fail_stop = False
        assert (await rebuilt.drive(handle.run_id)).state == "cancelled"
        saved = original_leaf(rebuilt, handle.run_id)
        coding = next(a for a in saved["actions"] if a["kind"] == "tool")
        assert coding["delegated_execution"]["request"] == request
        assert coding["delegated_execution"]["effect_case"] == "unknown"
        if lost_turn:
            assert "turn" not in coding["delegated_execution"]
        assert len(coding["attempts"]) == 1 and runner.calls.count("execute") == 1
        assert rebuilt.store.delegated_pending(rebuilt.scope) == ()
        assert rebuilt.store.budget(handle.run_id)["held"] > 0
        assert not rebuilt.store.run(handle.run_id)["orchestration"]["quiescent"]
        rebuilt.close()

    asyncio.run(exercise())


def test_child_stop_predicate_rejects_replaced_original_ownership(tmp_path):
    async def exercise():
        runner = LifecycleRunner()
        engine, _ = coding_engine(tmp_path, runner)
        handle = engine.submit(parent_spec(), "x", command_id="s")
        await engine.drive(handle.run_id)
        leaf = original_leaf(engine, handle.run_id)
        with engine.store.transaction():
            leaf["parent_call"]["reservation"] = "other-escrow"
            engine.store.save_run(leaf)
        from relf_agent.local_coding_children import stops_settled

        with pytest.raises(DefinitionMismatch, match="ownership"):
            stops_settled(engine, engine.store.run(handle.run_id))
        engine.close()

    asyncio.run(exercise())


def test_owned_nested_original_child_stops_under_ancestor_quarantine_and_retries(tmp_path):
    from relf_agent.runtime_lifecycle import BuildContext, RuntimeInstance

    from .test_coding_lifecycle import Journal, OwnedRunner

    async def exercise():
        runner = OwnedRunner(crash=True, fail_stop=True)
        engine, provider = coding_engine(tmp_path, runner, [tool_response("coding", {"task": "x"})])
        handle = engine.submit(parent_spec(nested=True), "x", command_id="s")
        await engine.drive(handle.run_id)
        leaf = original_leaf(engine, handle.run_id)
        action = leaf["actions"][-1]
        engine.approve(leaf["id"], action["id"], action["digest"], command_id="approve")
        await engine.drive(handle.run_id)
        runner.engine, runner.run_id = engine, leaf["id"]
        context = BuildContext(
            engine.store, tmp_path / "coding.db", engine.scope, tmp_path, allow_async=True
        )
        journal = context.own(Journal(runner))
        context.own_async(runner)
        runtime = RuntimeInstance(engine, context)
        with pytest.raises(ValidationError, match="incomplete"):
            await runtime.aclose()
        assert runner.closed == journal.closed == 0
        assert len(context._resources) == 2
        with pytest.raises(ValidationError, match="open|cleanup"):
            engine.cancel(handle.run_id, command_id="new-cancel")
        with pytest.raises(ValidationError, match="open|cleanup"):
            await engine.drive(handle.run_id)
        runner.fail_stop = False
        await runtime.aclose()
        assert runner.closed == journal.closed == 1
        assert runner.calls.count("execute") == provider.calls == 1
        assert runner.envelope.context.run_id == leaf["id"]
        assert "reconcile" not in runner.calls
        assert engine._lifecycle == "closed"

    asyncio.run(exercise())


def test_sibling_failure_waits_for_original_coding_stop_before_parent_failed(tmp_path):
    from relf_agent import ToolRegistry
    from relf_agent.delegated_coding import register_coding_tool
    from relf_agent.orchestration_types import ChildCall

    async def exercise():
        runner = LifecycleRunner(crash=True, fail_stop=True, wait=True)

        class Provider:
            identity = {"kind": "child-stop-failure-fixture", "version": "1"}

            async def complete(self, messages, tools):
                if messages[0]["content"] == "coding":
                    return tool_response("coding", {"task": "x"})
                assert messages[0]["content"] == "fail"
                await runner.entered.wait()
                return ModelResponse()

        tools = ToolRegistry()
        register_coding_tool(tools, runner)
        engine = LocalEngine(
            SQLiteStore(tmp_path / "coding.db"), providers={"default": Provider()}, tools=tools
        )
        handle = engine.submit(
            TeamSpec(
                "parent",
                {
                    "slow": AgentSpec("slow", "coding", ("coding",)),
                    "bad": AgentSpec("bad", "fail"),
                    "boss": AgentSpec("boss", "never-called"),
                },
                strategy="supervisor",
                strategy_config={"supervisor": "boss"},
                max_concurrency=2,
                child_budget=8,
            ),
            "x",
            command_id="s",
            budget=24,
        )
        slow = engine._orchestration.delegate(handle.run_id, ChildCall("slow", "slow", "x"))
        engine._orchestration.delegate(handle.run_id, ChildCall("bad", "bad", "x"))
        await engine.drive(slow["run_id"])
        action = engine.store.run(slow["run_id"])["actions"][-1]
        engine.approve(slow["run_id"], action["id"], action["digest"], command_id="a")
        failed = asyncio.Event()
        emit = engine.store.emit

        def observe_failure(run_id, kind, data=None):
            result = emit(run_id, kind, data)
            if run_id == handle.run_id and kind == "run_failed":
                failed.set()
            return result

        engine.store.emit = observe_failure
        driving = asyncio.create_task(engine.drive(handle.run_id))
        try:
            await asyncio.wait_for(failed.wait(), 2)
            assert engine.status(handle.run_id).state == "cancelling"
            assert not driving.done()
            runner.release.set()
            assert (await asyncio.wait_for(driving, 2)).state == "cancelling"
            parent = engine.store.run(handle.run_id)
            assert len(parent["orchestration"]["children"]) == 2
            assert engine.store.budget(handle.run_id)["held"] >= 8
            runner.fail_stop = False
            result = await engine.drive(handle.run_id)
            assert result.state == "failed" and result.error["code"] == "child_run_failed"
            assert runner.calls.count("execute") == 1
            assert len(engine.store.run(slow["run_id"])["actions"][-1]["attempts"]) == 1
        finally:
            runner.release.set()
            await asyncio.gather(driving, return_exceptions=True)
            runner.fail_stop = False
            await engine.drive(handle.run_id)
            engine.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("owned_cleanup", [False, True])
def test_maximum_original_parent_depth_allows_ninth_run_coding_leaf(tmp_path, owned_cleanup):
    from relf_agent.local_coding_children import stop_children, stops_settled
    from relf_agent.orchestration_types import ChildCall
    from relf_agent.runtime_lifecycle import BuildContext, RuntimeInstance

    from .test_coding_lifecycle import Journal, OwnedRunner

    async def exercise():
        runner = OwnedRunner(crash=True, fail_stop=True)
        engine, provider = coding_engine(tmp_path, runner, [tool_response("coding", {"task": "x"})])
        spec = AgentSpec("leaf", "coding", ("coding",))
        for index in range(8):
            spec = TeamSpec(f"parent-{index}", {"member": spec}, child_budget=8, max_depth=8)
        handle = engine.submit(spec, "x", command_id="s", budget=8)
        parent_id, chain = handle.run_id, [handle.run_id]
        for _ in range(8):
            call = engine._orchestration.delegate(parent_id, ChildCall("member", "member", "x"))
            parent_id = call["run_id"]
            chain.append(parent_id)
        assert len(chain) == 9 and engine.store.run(parent_id).get("orchestration") is None
        assert stops_settled(engine, engine.store.run(handle.run_id))
        await engine.drive(parent_id)
        action = engine.store.run(parent_id)["actions"][-1]
        engine.approve(parent_id, action["id"], action["digest"], command_id="a")
        await engine.drive(parent_id)
        original = engine.store.run(parent_id)["actions"][-1]["delegated_execution"]["request"]
        assert not stops_settled(engine, engine.store.run(handle.run_id))
        runner.engine, runner.run_id = engine, parent_id
        if owned_cleanup:
            context = BuildContext(
                engine.store, tmp_path / "coding.db", engine.scope, tmp_path, allow_async=True
            )
            journal = context.own(Journal(runner))
            context.own_async(runner)
            runtime = RuntimeInstance(engine, context)
            with pytest.raises(ValidationError, match="incomplete"):
                await runtime.aclose()
            assert runner.closed == journal.closed == 0
            runner.fail_stop = False
            assert await stop_children(engine, handle.run_id)
            saved = engine.store.run(parent_id)["actions"][-1]["delegated_execution"]
            assert saved["request"] == original and saved["fenced"]
            await runtime.aclose()
            assert runner.closed == journal.closed == 1
        else:
            engine.cancel(handle.run_id, command_id="cancel")
            assert engine.status(handle.run_id).state == "cancelling"
            assert (await engine.drive(handle.run_id)).state == "cancelling"
            runner.fail_stop = False
            assert (await engine.drive(handle.run_id)).state == "cancelled"
            assert stops_settled(engine, engine.store.run(handle.run_id))
            saved = engine.store.run(parent_id)["actions"][-1]["delegated_execution"]
            assert saved["request"] == original and saved["fenced"]
            engine.close()
        assert runner.calls.count("execute") == provider.calls == 1
        assert "reconcile" not in runner.calls

    asyncio.run(exercise())
