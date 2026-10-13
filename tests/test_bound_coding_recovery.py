"""Bound root Coding retains the original Action and release across cold recovery."""

import asyncio

import pytest

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, ToolRegistry, WorkflowSpec
from ralf_agent.binding_catalog import BindingCatalog
from ralf_agent.binding_definitions import AgentDefinition, BoundDefinition
from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
from ralf_agent.delegated_coding import register_coding_tool
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.storage import SQLiteStore

from .helpers import ScriptedProvider, tool_response
from .test_local_delegated_coding import LifecycleRunner


def setup_bound(tmp_path, runners, responses):
    tools, catalog = ToolRegistry(), BindingCatalog(scope=Scope())
    for name, runner in runners.items():
        register_coding_tool(tools, runner, name=name)
        catalog.register("runner", name, "1", runner)
    provider = ScriptedProvider(responses)
    engine = LocalEngine(
        SQLiteStore(tmp_path / "bound.db"),
        providers={"default": provider},
        tools=tools,
        binding_catalog=catalog,
    )
    return engine, provider, catalog


def definition(name="coding", *, mode="inherit"):
    selection = BindingSelection.inherit() if mode == "inherit" else BindingSelection.ref(name, "1")
    return AgentDefinition(AgentSpec("a", "x", (name,)), AgentBindingDescriptor(runner=selection))


def test_bound_first_acceptance_activates_schema14_before_queued_save(tmp_path):
    runner = LifecycleRunner()
    engine, provider, _ = setup_bound(tmp_path, {"coding": runner}, [])
    original = engine.store.save_run

    def save(run):
        assert (
            engine.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "14"
        )
        return original(run)

    engine.store.save_run = save
    handle = engine.submit(definition(), "x", command_id="s")
    run = engine.store.run(handle.run_id)
    assert run["manifest"]["kernel"] == "local-bindings-18"
    assert run["manifest"]["delegated_execution_protocol"] == 1
    assert provider.calls == 0 and runner.calls == []
    engine.close()


@pytest.mark.parametrize("mode", ["inherit", "ref"])
def test_bound_queued_cold_attach_checks_public_store_gate_before_model(tmp_path, mode):
    async def exercise():
        runner = LifecycleRunner()
        engine, provider, catalog = setup_bound(
            tmp_path,
            {"coding": runner},
            [tool_response("coding", {"task": "one"}), ModelResponse(output="done")],
        )
        handle = engine.submit(definition(mode=mode), "x", command_id="s")
        engine.close()
        rebuilt = LocalEngine(
            SQLiteStore(tmp_path / "bound.db"),
            providers={"default": provider},
            tools=engine.tools,
            binding_catalog=catalog,
        )
        original = rebuilt.store.delegated_pending
        rebuilt.store.delegated_pending = lambda scope: original(scope)
        with pytest.raises(ValidationError, match="Store"):
            await rebuilt.drive(handle.run_id)
        assert provider.calls == 0 and runner.calls == []
        rebuilt.store.delegated_pending = original
        await rebuilt.drive(handle.run_id)
        action = rebuilt.store.run(handle.run_id)["actions"][-1]
        rebuilt.approve(handle.run_id, action["id"], action["digest"], command_id="a")
        await rebuilt.drive(handle.run_id)
        assert rebuilt.status(handle.run_id).state == "succeeded"
        assert (
            len(
                next(a for a in rebuilt.store.run(handle.run_id)["actions"] if a["kind"] == "tool")[
                    "attempts"
                ]
            )
            == 1
        )
        rebuilt.close()

    asyncio.run(exercise())


def test_bound_sequence_uses_each_steps_actual_runner(tmp_path):
    async def exercise():
        first, second = LifecycleRunner(), LifecycleRunner()
        engine, provider, _ = setup_bound(
            tmp_path,
            {"first": first, "second": second},
            [
                tool_response("first", {"task": "one"}),
                ModelResponse(output="step one"),
                tool_response("second", {"task": "two"}),
                ModelResponse(output="step two"),
            ],
        )
        spec = WorkflowSpec(
            "sequence", [AgentSpec("first", "x", ("first",)), AgentSpec("second", "x", ("second",))]
        )
        bound = BoundDefinition(
            spec,
            {
                f"sequence/steps/{index}": AgentBindingDescriptor(
                    runner=BindingSelection.ref(name, "1")
                )
                for index, name in enumerate(("first", "second"))
            },
        )
        handle = engine.submit(bound, "x", command_id="s")
        for index in range(2):
            await engine.drive(handle.run_id)
            action = engine.store.run(handle.run_id)["actions"][-1]
            engine.approve(handle.run_id, action["id"], action["digest"], command_id=f"a{index}")
            await engine.drive(handle.run_id)
        run = engine.store.run(handle.run_id)
        actions = [a for a in run["actions"] if a["kind"] == "tool"]
        assert run["state"] == "succeeded"
        assert [a["node"] for a in actions] == [0, 1]
        assert first.envelope.arguments == {"task": "one"}
        assert second.envelope.arguments == {"task": "two"}
        assert first.calls.count("execute") == second.calls.count("execute") == 1
        assert all(len(a["attempts"]) == 1 for a in actions)
        assert provider.calls == 4
        engine.close()

    asyncio.run(exercise())


def test_bound_pending_cold_stop_preserves_original_attempt_epoch_and_handles(tmp_path):
    async def exercise():
        runner = LifecycleRunner(crash=True, fail_stop=True)
        engine, provider, catalog = setup_bound(
            tmp_path, {"coding": runner}, [tool_response("coding", {"task": "one"})]
        )
        handle = engine.submit(definition(), "x", command_id="s")
        await engine.drive(handle.run_id)
        action = engine.store.run(handle.run_id)["actions"][-1]
        engine.approve(handle.run_id, action["id"], action["digest"], command_id="a")
        await engine.drive(handle.run_id)
        original = engine.store.run(handle.run_id)["actions"][-1]["delegated_execution"]["request"]
        engine.cancel(handle.run_id, command_id="cancel")
        engine.store.close()
        engine.coordinator.release()
        rebuilt = LocalEngine(
            SQLiteStore(tmp_path / "bound.db"),
            providers={"default": provider},
            tools=engine.tools,
            binding_catalog=catalog,
        )
        runner.fail_stop = False
        await rebuilt.drive(handle.run_id)
        run = rebuilt.store.run(handle.run_id)
        action = next(a for a in run["actions"] if a["kind"] == "tool")
        assert run["state"] == "cancelled"
        assert action["delegated_execution"]["request"] == original
        assert len(action["attempts"]) == 1
        assert runner.calls.count("execute") == 1
        assert "reconcile" not in runner.calls
        assert action["delegated_execution"]["effect_case"] == "unknown"
        rebuilt.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("change", ["identity", "method", "resource"])
def test_bound_queued_runner_drift_fails_before_model(tmp_path, change):
    async def exercise():
        runner = LifecycleRunner()
        engine, provider, _ = setup_bound(tmp_path, {"coding": runner}, [])
        handle = engine.submit(definition(mode="ref"), "x", command_id="s")
        original_identity = runner.identity
        original_method = runner.execute
        original_resource = engine.tools.get("coding").handler._runner
        if change == "identity":
            runner.identity = {**runner.identity, "version": "changed"}
        elif change == "method":

            async def replacement(envelope, authority):
                raise AssertionError("replacement native method ran")

            runner.execute = replacement
        else:
            engine.tools.get("coding").handler._runner = LifecycleRunner()
        with pytest.raises(DefinitionMismatch):
            await engine.drive(handle.run_id)
        assert provider.calls == 0 and runner.calls == []
        runner.identity, runner.execute = original_identity, original_method
        engine.tools.get("coding").handler._runner = original_resource
        engine.close()

    asyncio.run(exercise())


def test_unselected_coding_grant_does_not_activate_delegated_protocol(tmp_path):
    runner = LifecycleRunner()
    engine, _, catalog = setup_bound(tmp_path, {"coding": runner}, [])
    catalog.register("tool_set", "none", "1", [])
    bound = AgentDefinition(
        AgentSpec("a", "x", ("coding",)),
        AgentBindingDescriptor(tool_set=BindingSelection.ref("none", "1")),
    )
    handle = engine.submit(bound, "x", command_id="s")
    assert "delegated_execution_protocol" not in engine.store.run(handle.run_id)["manifest"]
    assert (
        engine.store.conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()[0]
        == "1"
    )
    engine.close()


@pytest.mark.parametrize("parent_kind", ["team", "dynamic"])
def test_nested_explicit_runner_disabled_refuses_before_parent_acceptance(tmp_path, parent_kind):
    from ralf_agent import DynamicWorkflowSpec, TeamSpec

    engine, provider, _ = setup_bound(tmp_path, {"coding": LifecycleRunner()}, [])
    parent = (TeamSpec if parent_kind == "team" else DynamicWorkflowSpec)(
        "parent", {"member": AgentSpec("a", "x")}
    )
    parent = BoundDefinition(
        parent,
        {
            f"{parent_kind}/members/member": AgentBindingDescriptor(
                runner=BindingSelection.disabled()
            )
        },
    )
    with pytest.raises(ValidationError, match="root unbound"):
        engine.submit(parent, "x", command_id="s")
    assert provider.calls == 0
    assert engine.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    engine.close()


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("physical", ["root", "docker", "journal"])
def test_concrete_physical_drift_rejected_before_model(tmp_path, bound, physical):
    from ralf_agent.codex_runner import CodexCodingRunner
    from ralf_agent.runner_journal import RunnerJournal

    async def exercise():
        root, journal_dir, executable = tmp_path / "root", tmp_path / "journal", tmp_path / "docker"
        root.mkdir(mode=0o700)
        journal_dir.mkdir(mode=0o700)
        executable.write_text("#!/bin/sh\nexit 1\n")
        executable.chmod(0o700)
        journal = RunnerJournal(str(journal_dir / "starts.db"), identity={"kind": "fixture"})
        runner = CodexCodingRunner(
            root,
            journal=journal,
            docker_executable=str(executable),
            docker_host="unix:///fixture.sock",
        )
        engine, provider, _ = setup_bound(
            tmp_path, {"coding": runner}, [ModelResponse(output="done")]
        )
        selected = definition() if bound else AgentSpec("a", "x", ("coding",))
        handle = engine.submit(selected, "x", command_id="s")
        original = {"root": root, "docker": executable, "journal": journal_dir}[physical]
        moved = original.with_name(original.name + "-moved")
        original.rename(moved)
        if physical == "docker":
            original.write_text("#!/bin/sh\nexit 1\n")
            original.chmod(0o700)
        else:
            original.mkdir(mode=0o700)
        try:
            with pytest.raises(DefinitionMismatch):
                await engine.drive(handle.run_id)
            assert provider.calls == 0
            assert engine.store.run(handle.run_id)["actions"] == []
        finally:
            original.unlink() if physical == "docker" else original.rmdir()
            moved.rename(original)
            engine.close()
            journal.close()

    asyncio.run(exercise())
