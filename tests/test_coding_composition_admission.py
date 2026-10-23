"""Complex Coding keeps the existing Local Action and explicit reader gate."""

import pytest

from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec
from relf_agent.errors import DefinitionMismatch
from tests.test_local_delegated_coding import LifecycleRunner, coding_engine


def test_serial_graph_coding_has_new_reader_gate_and_original_store(tmp_path):
    runtime, provider = coding_engine(tmp_path, LifecycleRunner())
    try:
        spec = GraphWorkflowSpec("coding", (GraphNode("edit", tool="coding"),))
        handle = runtime.submit(spec, {"task": "one original task"}, command_id="create")
        run = runtime.store.run(handle.run_id)
        assert run["manifest"]["kernel"] == "local-11"
        assert run["manifest"]["delegated_composition_protocol"] == 1
        assert run["manifest"]["delegated_execution_protocol"] == 1
        assert run["actions"] == []
        assert provider.calls == 0
        assert (
            runtime.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "14"
        )
        runtime._check_release(run)
    finally:
        runtime.close()


def test_unselected_registered_runner_does_not_activate_ordinary_graph(tmp_path):
    runtime, provider = coding_engine(tmp_path, LifecycleRunner())
    try:
        handle = runtime.submit(
            GraphWorkflowSpec("ordinary", (GraphNode("answer", agent=AgentSpec("a", "Answer")),)),
            "ordinary",
            command_id="create",
        )
        manifest = runtime.store.run(handle.run_id)["manifest"]
        assert "delegated_composition_protocol" not in manifest
        assert "delegated_execution_protocol" not in manifest
        assert "delegated_coding_tools" not in manifest
        assert provider.calls == 0
        assert (
            runtime.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "1"
        )
    finally:
        runtime.close()


def test_complex_record_cannot_drop_original_composition_protocol(tmp_path):
    runtime, provider = coding_engine(tmp_path, LifecycleRunner())
    try:
        handle = runtime.submit(
            GraphWorkflowSpec("coding", (GraphNode("edit", tool="coding"),)),
            {"task": "one original task"},
            command_id="create",
        )
        run = runtime.store.run(handle.run_id)
        run["manifest"].pop("delegated_composition_protocol")
        with pytest.raises(DefinitionMismatch):
            runtime._check_release(run)
        assert provider.calls == 0
    finally:
        runtime.close()


def test_bound_direct_tool_graph_keeps_host_tool_grant_without_agent_runner_role(tmp_path):
    import asyncio

    from relf_agent import BoundDefinition

    resource = LifecycleRunner()
    runtime, provider = coding_engine(tmp_path, resource)
    try:
        spec = BoundDefinition(GraphWorkflowSpec("coding", (GraphNode("edit", tool="coding"),)), {})
        handle = runtime.submit(spec, {"task": "one original task"}, command_id="create")

        async def execute():
            pending = (await runtime.drive(handle.run_id)).pending[0]
            runtime.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            snapshot = await runtime.drive(handle.run_id)
            assert snapshot.state == "succeeded"

        asyncio.run(execute())
        assert resource.calls == ["execute", "stop_existing"]
        assert provider.calls == 0
        run = runtime.store.run(handle.run_id)
        assert len(run["actions"]) == 1
        assert len(run["actions"][0]["attempts"]) == 1
    finally:
        runtime.close()


def test_child_cannot_replace_original_parent_escrow_before_native_dispatch(tmp_path):
    import asyncio
    import copy

    from relf_agent import TeamSpec
    from relf_agent.types import digest

    runtime, provider = coding_engine(tmp_path, LifecycleRunner())
    try:
        handle = runtime.submit(
            TeamSpec("team", {"member": AgentSpec("a", "write", ("coding",))}),
            "x",
            command_id="create",
        )
        assert asyncio.run(runtime.drive(handle.run_id)).state == "waiting_approval"
        parent = runtime.store.run(handle.run_id)
        child_id = parent["orchestration"]["children"][0]["run_id"]
        with runtime.store.transaction():
            child = runtime.store.run(child_id)
            child["parent_call"]["reservation"] = "different-parent-escrow"
            child["manifest"]["parent_call"] = copy.deepcopy(child["parent_call"])
            child["release_digest"] = digest(
                {"definition": child["definition"], "manifest": child["manifest"]}
            )
            runtime.store.save_run(child)
        with pytest.raises(DefinitionMismatch, match="ownership"):
            runtime._check_release(runtime.store.run(child_id))
        assert provider.calls == 1
    finally:
        runtime.close()


def test_owned_parallel_cleanup_keeps_original_quiescence_receipt_access(tmp_path):
    import asyncio

    from relf_agent.errors import ValidationError
    from relf_agent.runtime_lifecycle import BuildContext, RuntimeInstance
    from tests.test_coding_lifecycle import Journal, OwnedRunner

    async def execute():
        runner = OwnedRunner(crash=True, fail_stop=True)
        engine, provider = coding_engine(tmp_path, runner)
        handle = engine.submit(
            GraphWorkflowSpec("parallel", (GraphNode("edit", tool="coding"),), max_concurrency=2),
            {"task": "one original task"},
            command_id="create",
        )
        pending = (await engine.drive(handle.run_id)).pending[0]
        engine.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="approve")
        await engine.drive(handle.run_id)
        assert handle.run_id in engine._quiescing_runs
        runner.engine, runner.run_id = engine, handle.run_id
        context = BuildContext(
            engine.store, tmp_path / "coding.db", engine.scope, tmp_path, allow_async=True
        )
        journal = context.own(Journal(runner))
        context.own_async(runner)
        runtime = RuntimeInstance(engine, context)
        with pytest.raises(ValidationError, match="delegated Coding stop remains incomplete"):
            await runtime.aclose()
        assert engine._lifecycle == "open"
        assert journal.closed == runner.closed == 0
        with pytest.raises(ValidationError, match="not open"):
            engine.submit(AgentSpec("forbidden", "x"), "x", command_id="new")
        runner.fail_stop = False
        await runtime.aclose()
        assert journal.closed == runner.closed == 1
        assert engine._lifecycle == "closed"
        assert runner.calls.count("execute") == 1
        assert provider.calls == 0

    asyncio.run(execute())
