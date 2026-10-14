"""Deployment quota belongs to original roots, effects and actual work."""

import asyncio
import copy
import threading

import pytest

import ralf_agent.errors as errors
import ralf_agent.governance as governance
from ralf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from ralf_agent.orchestration_types import DynamicWorkflowSpec, TeamSpec
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.types import submission_request

from .helpers import ScriptedProvider, tool_response


def policy(**options):
    return governance.DeploymentAdmissionPolicy(
        "test-deployment", max_active_root_runs=options.pop("max_active_root_runs", 1), **options
    )


def engine(path, provider=None, tools=None, **options):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": provider or EchoProvider("admission")},
        tools=ToolRegistry() if tools is None else tools,
        **options,
    )


def tools_with(handler, *, approval=False, cost=1):
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change",
            "Change a business value",
            {"type": "object"},
            effect="unqueryable_write",
            requires_approval=approval,
            cost=cost,
        ),
        handler,
    )
    return tools


async def eventually(predicate):
    end = asyncio.get_running_loop().time() + 3
    while not predicate():
        if asyncio.get_running_loop().time() >= end:
            pytest.fail("Original admission obligation did not reach the expected checkpoint")
        await asyncio.sleep(0.002)


def holders(runtime):
    return runtime.store.local_capacity_holders(runtime.scope)


def test_unconfigured_default_preserves_original_request_manifest_and_schema(tmp_path):
    spec = AgentSpec("a", "Answer")
    assert set(submission_request(spec, "q")) == {"definition", "input", "budget", "session_id"}
    with engine(tmp_path / "default.sqlite") as runtime:
        handle = runtime.submit(spec, "q", command_id="s")
        record = runtime.store.run(handle.run_id)
        assert "local_admission" not in record
        assert "local_admission_protocol" not in record["manifest"]
        assert "admission_policy" not in record["manifest"]
        assert (
            runtime.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "1"
        )


def test_full_deployment_returns_accepted_duplicate_before_fresh_admission(tmp_path):
    provider = ScriptedProvider([])
    with engine(tmp_path / "full.sqlite", provider, admission_policy=policy()) as runtime:
        spec = AgentSpec("a", "Answer")
        original = runtime.submit(spec, "q", command_id="first")
        assert holders(runtime) == (original.run_id,)
        with pytest.raises(errors.CapacityExceeded):
            runtime.submit(spec, "other", command_id="second")
        assert runtime.submit(spec, "q", command_id="first") == original
        assert provider.calls == 0
        assert runtime.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert runtime.store.conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 1
        runtime.cancel(original.run_id, command_id="cancel")
        retry = runtime.submit(spec, "other", command_id="second")
        assert retry.run_id != original.run_id


@pytest.mark.parametrize("complete", [False, True], ids=["queued-cancel", "completed"])
def test_actual_completion_or_quiet_queued_cancel_releases_exactly_one_root(tmp_path, complete):
    with engine(tmp_path / "release.sqlite", admission_policy=policy()) as runtime:
        handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="first")
        if complete:
            assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"
        else:
            runtime.cancel(handle.run_id, command_id="cancel")
        assert holders(runtime) == ()
        second = runtime.submit(AgentSpec("a", "Answer"), "next", command_id="second")
        assert holders(runtime) == (second.run_id,)
        assert runtime.status(handle.run_id).state == ("succeeded" if complete else "cancelled")


def test_approval_pause_and_ordinary_close_keep_the_claim_for_original_recovery(tmp_path):
    path = tmp_path / "paused.sqlite"
    tools = tools_with(lambda args, ctx: args, approval=True)
    selected = policy()
    with engine(
        path, ScriptedProvider([tool_response()]), tools, admission_policy=selected
    ) as runtime:
        handle = runtime.submit(AgentSpec("a", "Change", ("change",)), "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "waiting_approval"
        with pytest.raises(errors.CapacityExceeded):
            runtime.submit(AgentSpec("b", "Answer"), "q", command_id="blocked")
        original = copy.deepcopy(runtime.store.run(handle.run_id))
    with engine(path, ScriptedProvider([]), tools, admission_policy=selected) as restored:
        assert holders(restored) == (handle.run_id,)
        assert restored.store.run(handle.run_id)["release_digest"] == original["release_digest"]
        assert restored.submit(AgentSpec("a", "Change", ("change",)), "q", command_id="s") == handle
        restored.cancel(handle.run_id, command_id="cancel")
        assert holders(restored) == ()
        restored.submit(AgentSpec("b", "Answer"), "q", command_id="blocked")


def test_deadline_cannot_release_a_root_while_original_model_work_is_active(tmp_path):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class Provider:
            identity = {"kind": "capacity-held-model", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                return ModelResponse(output="late")

        runtime = engine(
            tmp_path / "deadline.sqlite",
            Provider(),
            admission_policy=policy(),
            execution_policy=governance.LocalExecutionPolicy(run_timeout_seconds=0.2),
        )
        task = None
        try:
            handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            task = asyncio.create_task(runtime.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 2)
            await eventually(lambda: runtime.status(handle.run_id).error is not None)
            assert runtime.status(handle.run_id).state == "cancelling"
            assert not task.done()
            assert holders(runtime) == (handle.run_id,)
            with pytest.raises(errors.CapacityExceeded):
                runtime.submit(AgentSpec("b", "Answer"), "next", command_id="blocked")
            release.set()
            assert (await asyncio.wait_for(asyncio.shield(task), 3)).state == "cancelled"
            assert holders(runtime) == ()
            runtime.submit(AgentSpec("b", "Answer"), "next", command_id="blocked")
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await runtime.wait_for_threads()
            runtime.close()

    asyncio.run(scenario())


def test_cancelled_loop_tasks_do_not_release_a_real_sync_handler_or_unknown_effect(tmp_path):
    started, release, ended = threading.Event(), threading.Event(), threading.Event()
    effects = []

    def change(arguments, context):
        started.set()
        try:
            assert release.wait(10), "Test barrier was not released"
            effects.append(context.effect_key)
            return {"changed": True}
        finally:
            ended.set()

    runtime = engine(
        tmp_path / "thread.sqlite",
        ScriptedProvider([tool_response()]),
        tools_with(change),
        admission_policy=policy(),
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        handle = runtime.submit(AgentSpec("a", "Change", ("change",)), "q", command_id="s")
        loop.create_task(runtime.drive(handle.run_id))
        loop.run_until_complete(eventually(started.is_set))
        jobs = asyncio.all_tasks(loop)
        for job in jobs:
            job.cancel()
        loop.run_until_complete(asyncio.gather(*jobs, return_exceptions=True))
        assert not ended.is_set()
        assert runtime._threads.has_active_for(handle.run_id)
        assert holders(runtime) == (handle.run_id,)
        with pytest.raises(errors.CapacityExceeded):
            runtime.submit(AgentSpec("b", "Answer"), "next", command_id="blocked")
        with pytest.raises(errors.ValidationError):
            runtime.close()
        release.set()
        loop.run_until_complete(runtime.wait_for_threads())
        assert ended.is_set() and len(effects) == 1
        snapshot = loop.run_until_complete(runtime.drive(handle.run_id))
        assert snapshot.state == "cancelled"
        action = next(action for action in snapshot.actions if action["kind"] == "tool")
        assert action["status"] == "outcome_unknown"
        with pytest.raises(errors.CapacityExceeded):
            runtime.submit(AgentSpec("b", "Answer"), "next", command_id="blocked")
        runtime.reconcile(handle.run_id, action["id"], {"changed": True}, command_id="verified")
        assert holders(runtime) == ()
        runtime.submit(AgentSpec("b", "Answer"), "next", command_id="blocked")
    finally:
        release.set()
        jobs = asyncio.all_tasks(loop)
        for job in jobs:
            job.cancel()
        loop.run_until_complete(asyncio.gather(*jobs, return_exceptions=True))
        loop.run_until_complete(runtime.wait_for_threads())
        runtime.close()
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
        asyncio.set_event_loop(None)


def definition(kind):
    worker = AgentSpec("a", "Answer")
    sequence = WorkflowSpec("sequence", (worker, AgentSpec("b", "Answer")))
    if kind == "sequence":
        return sequence
    if kind in {"graph", "parallel"}:
        return GraphWorkflowSpec(
            kind,
            [GraphNode("one", agent=worker), GraphNode("two", agent=worker)],
            max_concurrency=2 if kind == "parallel" else 1,
        )
    if kind == "team":
        return TeamSpec("team", {"one": worker, "two": worker}, child_budget=4)
    if kind == "dynamic":
        return DynamicWorkflowSpec("dynamic", {"one": worker, "two": worker}, child_budget=4)
    assert kind == "nested"
    return TeamSpec(
        "outer",
        {"inner": TeamSpec("inner", {"sequence": sequence}, child_budget=4)},
        child_budget=8,
    )


@pytest.mark.parametrize("kind", ["sequence", "graph", "parallel", "team", "dynamic", "nested"])
def test_selected_orchestration_and_original_children_share_exactly_one_root(tmp_path, kind):
    with engine(tmp_path / f"{kind}.sqlite", admission_policy=policy()) as runtime:
        handle = runtime.submit(definition(kind), "q", command_id="s", budget=16)
        assert holders(runtime) == (handle.run_id,)
        snapshot = asyncio.run(runtime.drive(handle.run_id))
        assert snapshot.state == "succeeded"
        visited, pending = set(), [handle.run_id]
        while pending:
            identifier = pending.pop()
            assert identifier not in visited
            visited.add(identifier)
            record = runtime.store.run(identifier)
            assert record["local_admission"] == {"version": 1, "root_run_id": handle.run_id}
            assert record["manifest"]["local_admission_protocol"] == 1
            assert record["manifest"]["admission_policy"] == policy().identity
            for call in record.get("orchestration", {}).get("children", []):
                pending.append(call["run_id"])
        assert holders(runtime) == ()
        runtime.submit(AgentSpec("next", "Answer"), "q", command_id="next")


def test_unknown_child_effect_keeps_root_until_original_reconciliation_and_tree_closure(tmp_path):
    async def lost(arguments, context):
        raise ConnectionError("Business write acknowledgement unavailable")

    with engine(
        tmp_path / "child-unknown.sqlite",
        ScriptedProvider([tool_response()]),
        tools_with(lost),
        admission_policy=policy(),
    ) as runtime:
        handle = runtime.submit(
            TeamSpec(
                "team", {"worker": AgentSpec("worker", "Change", ("change",))}, child_budget=4
            ),
            "q",
            command_id="s",
            budget=8,
        )
        asyncio.run(runtime.drive(handle.run_id))
        child_id = runtime.store.run(handle.run_id)["orchestration"]["children"][0]["run_id"]
        runtime.cancel(handle.run_id, command_id="cancel")
        asyncio.run(runtime.drive(handle.run_id))
        assert holders(runtime) == (handle.run_id,)
        with pytest.raises(errors.CapacityExceeded):
            runtime.submit(AgentSpec("next", "Answer"), "q", command_id="next")
        action = next(
            action for action in runtime.status(child_id).actions if action["kind"] == "tool"
        )
        runtime.reconcile(child_id, action["id"], {"changed": True}, command_id="verified")
        asyncio.run(runtime.drive(handle.run_id))
        assert holders(runtime) == ()
        runtime.submit(AgentSpec("next", "Answer"), "q", command_id="next")


def test_first_activation_seeds_legacy_roots_without_rewriting_their_releases(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with engine(path) as original:
        first = original.submit(AgentSpec("a", "Answer"), "one", command_id="one")
        second = original.submit(AgentSpec("b", "Answer"), "two", command_id="two")
        accepted = {
            item.run_id: copy.deepcopy(original.store.run(item.run_id)) for item in (first, second)
        }
    with engine(path, admission_policy=policy()) as upgraded:
        assert set(holders(upgraded)) == set(accepted)
        for identifier, record in accepted.items():
            assert upgraded.store.run(identifier) == record
        with pytest.raises(errors.CapacityExceeded):
            upgraded.submit(AgentSpec("c", "Answer"), "three", command_id="three")
        assert asyncio.run(upgraded.drive(first.run_id)).state == "succeeded"
        with pytest.raises(errors.CapacityExceeded):
            upgraded.submit(AgentSpec("c", "Answer"), "three", command_id="three")
        assert asyncio.run(upgraded.drive(second.run_id)).state == "succeeded"
        for identifier, record in accepted.items():
            restored = upgraded.store.run(identifier)
            assert restored["manifest"] == record["manifest"]
            assert restored["release_digest"] == record["release_digest"]
            assert "local_admission" not in restored
        assert holders(upgraded) == ()
        upgraded.submit(AgentSpec("c", "Answer"), "three", command_id="three")


def test_scope_limit_and_global_capacity_never_expose_foreign_root_locators(tmp_path):
    path = tmp_path / "scopes.sqlite"
    selected = policy(max_active_root_runs=2, max_active_root_runs_per_scope=1)
    one, two = Scope("workspace", "one"), Scope("workspace", "two")
    with engine(path, scope=one, admission_policy=selected) as runtime:
        foreign = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="same")
    with engine(path, scope=two, admission_policy=selected) as runtime:
        own = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="same")
        assert holders(runtime) == (own.run_id,)
        with pytest.raises(errors.CapacityExceeded) as refusal:
            runtime.submit(AgentSpec("a", "Answer"), "next", command_id="next")
        assert foreign.run_id not in str(refusal.value)
        assert foreign.run_id not in repr(vars(refusal.value))
        runtime.cancel(own.run_id, command_id="cancel")
        replacement = runtime.submit(AgentSpec("a", "Answer"), "next", command_id="next")
        assert holders(runtime) == (replacement.run_id,)
    with engine(path, scope=one, admission_policy=selected) as runtime:
        assert holders(runtime) == (foreign.run_id,)
        assert runtime.submit(AgentSpec("a", "Answer"), "q", command_id="same") == foreign
    with engine(path, scope=Scope("workspace", "three"), admission_policy=selected) as runtime:
        assert holders(runtime) == ()
        with pytest.raises(errors.CapacityExceeded) as refusal:
            runtime.submit(AgentSpec("a", "Answer"), "q", command_id="same")
        assert foreign.run_id not in str(refusal.value)
        assert replacement.run_id not in str(refusal.value)
        assert foreign.run_id not in repr(vars(refusal.value))
        assert replacement.run_id not in repr(vars(refusal.value))


@pytest.mark.parametrize("selection", ["omission", "mismatch", "hidden-port"])
def test_installed_deployment_cannot_be_bypassed_by_omission_or_proxy(tmp_path, selection):
    path = tmp_path / "bypass.sqlite"
    with engine(path, admission_policy=policy()) as original:
        handle = original.submit(AgentSpec("a", "Answer"), "q", command_id="s")

    class HiddenPort:
        def __init__(self, original):
            self.original = original

        def __getattr__(self, name):
            if (
                name == "local_admission_version"
                or name.startswith("local_capacity_")
                or name == "prepare_local_capacity"
            ):
                raise AttributeError(name)
            return getattr(self.original, name)

    with SQLiteStore(path) as store:
        runtime = None
        try:
            with pytest.raises(errors.RalfError):
                runtime = LocalEngine(
                    HiddenPort(store) if selection == "hidden-port" else store,
                    providers={"default": EchoProvider("admission")},
                    tools=ToolRegistry(),
                    **(
                        {"admission_policy": policy(max_active_root_runs=2)}
                        if selection == "mismatch"
                        else {}
                    ),
                )
                runtime.submit(AgentSpec("b", "Answer"), "q", command_id="bypass")
            assert store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
            assert store.conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 1
            assert store.local_capacity_holders(Scope()) == (handle.run_id,)
        finally:
            if runtime is not None:
                runtime.close()


@pytest.mark.parametrize("kind", ["model", "tool"])
def test_zero_credit_unknown_obligation_cannot_free_terminal_root(tmp_path, kind):
    async def lost(arguments, context):
        raise ConnectionError("Acknowledgement unavailable")

    class UnknownProvider:
        identity = {"kind": "zero-credit-unknown-model", "version": "1"}

        async def complete(self, messages, tools):
            raise ConnectionError("Model response unavailable")

    provider = UnknownProvider() if kind == "model" else ScriptedProvider([tool_response()])
    tools = ToolRegistry() if kind == "model" else tools_with(lost, cost=0)
    spec = AgentSpec("a", "Answer", () if kind == "model" else ("change",), model_credits=0)
    with engine(
        tmp_path / f"zero-{kind}.sqlite", provider, tools, admission_policy=policy()
    ) as runtime:
        handle = runtime.submit(spec, "q", command_id="s", budget=0)
        assert asyncio.run(runtime.drive(handle.run_id)).state == "waiting_reconciliation"
        runtime.cancel(handle.run_id, command_id="cancel")
        assert runtime.status(handle.run_id).state == "cancelled"
        assert runtime.store.budget(handle.run_id) == {"limit": 0, "held": 0, "spent": 0}
        assert holders(runtime) == (handle.run_id,)
        with pytest.raises(errors.CapacityExceeded):
            runtime.submit(AgentSpec("next", "Answer"), "q", command_id="next")
        if kind == "tool":
            action = next(
                action
                for action in runtime.status(handle.run_id).actions
                if action["kind"] == "tool"
            )
            runtime.reconcile(handle.run_id, action["id"], {"changed": True}, command_id="verified")
            assert holders(runtime) == ()
            runtime.submit(AgentSpec("next", "Answer"), "q", command_id="next")
