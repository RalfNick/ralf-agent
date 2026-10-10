import asyncio
import importlib

import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    MemoryAdmissionPolicy,
    ModelResponse,
    Scope,
    SQLiteStore,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from tests.helpers import ScriptedProvider


def policy(memory, **kwargs):
    cls = importlib.import_module("ralf_agent.managed_memory").ManagedMemoryPolicy
    return cls(memory, **kwargs)


def engine(path, provider=None, **kwargs):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": provider or ScriptedProvider([ModelResponse(output={"x": 1})])},
        tools=kwargs.pop("tools", ToolRegistry()),
        **kwargs,
    )


def schema(runtime):
    return runtime.store.conn.execute(
        "SELECT value FROM metadata WHERE key='schema_version'"
    ).fetchone()[0]


def test_default_has_no_stage_or_schema_change(tmp_path):
    with engine(tmp_path / "run.sqlite") as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert "managed_memory" not in runtime.diagnostics(h.run_id).manifest
        assert schema(runtime) == "1"
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory.facts(runtime.scope, "auto-memory") == []


def test_policy_is_grounded_and_pins_borrowed_write_target():
    memory = InMemoryMemory(backend_id="facts")
    stage = policy(memory, admission=MemoryAdmissionPolicy({"x": ("result", "x")}))
    assert stage.propose({"result": {"x": 2}})[0].to_dict()["value"] == 2
    memory.backend_id = "swapped"
    with pytest.raises(DefinitionMismatch):
        _ = stage.identity


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), True, 61])
def test_stage_timeout_is_bounded(timeout):
    with pytest.raises(ValidationError):
        policy(InMemoryMemory(), timeout=timeout)


def test_facts_view_cannot_be_used_as_write_target():
    from ralf_agent.binding_data import FactsView

    memory = InMemoryMemory()
    with pytest.raises(ValidationError):
        policy(FactsView(memory, Scope(), "reads", memory.backend_id))


def test_stage_scope_and_version_gate_are_atomic(tmp_path):
    stage = policy(InMemoryMemory(), scope=Scope("elsewhere", "alice"))
    with engine(tmp_path / "run.sqlite", stage_policy=stage) as runtime:
        with pytest.raises(AuthorizationDenied):
            runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert schema(runtime) == "1"
        assert runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_optional_store_extension_must_be_explicit(tmp_path):
    class Store(SQLiteStore):
        managed_stage_version = None

    with LocalEngine(
        Store(tmp_path / "run.sqlite"),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
        stage_policy=policy(InMemoryMemory()),
    ) as runtime:
        with pytest.raises(ValidationError):
            runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert schema(runtime) == "1"


def test_stage_binding_ref_disabled_and_pinned_manifest(tmp_path):
    from ralf_agent.binding_catalog import BindingCatalog
    from ralf_agent.binding_definitions import AgentDefinition
    from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection

    memory = InMemoryMemory()
    stage = policy(memory, namespace="observations")
    catalog = BindingCatalog(scope=Scope())
    catalog.register("stage_policy", "memory", "1", stage)
    spec = AgentSpec("a", "Answer")
    selected = AgentDefinition(
        spec, AgentBindingDescriptor(stage_policy=BindingSelection.ref("memory", "1"))
    )
    disabled = AgentDefinition(
        spec, AgentBindingDescriptor(stage_policy=BindingSelection.disabled())
    )
    with engine(tmp_path / "run.sqlite", binding_catalog=catalog, stage_policy=stage) as runtime:
        h = runtime.submit(selected, "q", command_id="s")
        manifest = runtime.diagnostics(h.run_id).manifest
        entry = manifest["agent_bindings"]["steps"]["agent"]
        assert entry["manifest"]["managed_memory"] == stage.identity
        assert manifest["kernel"] == "local-bindings-7"
        assert schema(runtime) == "7"
        off = runtime.submit(disabled, "q", command_id="off")
        assert (
            "managed_memory"
            not in runtime.diagnostics(off.run_id).manifest["agent_bindings"]["steps"]["agent"][
                "manifest"
            ]
        )


def test_unsupported_composite_store_refuses_before_schema_or_run_admission(tmp_path, monkeypatch):
    from ralf_agent import GraphNode, GraphWorkflowSpec

    spec = GraphWorkflowSpec("g", [GraphNode("a", agent=AgentSpec("a", "Answer"))])
    monkeypatch.setattr(SQLiteStore, "composite_memory_stage_version", None)
    with engine(tmp_path / "run.sqlite", stage_policy=policy(InMemoryMemory())) as runtime:
        with pytest.raises(ValidationError):
            runtime.submit(spec, "q", command_id="s")
        assert schema(runtime) == "1"
        assert runtime.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_managed_stage_completes_and_uses_run_budget(tmp_path):
    memory = InMemoryMemory()
    stage = policy(memory, admission=MemoryAdmissionPolicy({"x": ("result", "x")}))
    with engine(tmp_path / "run.sqlite", stage_policy=stage) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        result = asyncio.run(runtime.drive(h.run_id))
        assert result.state == "succeeded" and result.result == {"x": 1}
        receipts = runtime.memory_stages(h.run_id)
        assert receipts[0]["status"] == "completed"
        facts = memory.facts(runtime.scope, "auto-memory")
        assert len(facts) == 1 and facts[0]["value"]["value"] == 1
        assert facts[0]["value"]["trust"] == "completed-result-observation"
        assert receipts[0]["source"]["action_id"] == result.actions[0]["id"]
        assert runtime.diagnostics(h.run_id).budget["spent"] == 2
        assert len(result.actions) == 1
        receipts[0]["status"] = "corrupted"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "completed"


def test_insufficient_auxiliary_budget_does_not_fail_business(tmp_path):
    memory = InMemoryMemory()
    with engine(tmp_path / "run.sqlite", stage_policy=policy(memory)) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=1)
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["error"]["code"] == "budget_exceeded"
        assert memory.facts(runtime.scope, "auto-memory") == []
        assert runtime.diagnostics(h.run_id).budget["held"] == 0


def test_sequence_has_separate_source_stages(tmp_path):
    provider = ScriptedProvider([ModelResponse(output="first"), ModelResponse(output="last")])
    memory = InMemoryMemory()
    with engine(tmp_path / "run.sqlite", provider, stage_policy=policy(memory)) as runtime:
        h = runtime.submit(
            WorkflowSpec("flow", [AgentSpec("a", "Answer"), AgentSpec("b", "Answer")]),
            "q",
            command_id="s",
            budget=4,
        )
        assert asyncio.run(runtime.drive(h.run_id)).result == "last"
        receipts = runtime.memory_stages(h.run_id)
        assert [r["status"] for r in receipts] == ["completed", "completed"]
        assert [r["source"]["result"] for r in receipts] == ["first", "last"]
        assert len(memory.facts(runtime.scope, "auto-memory")) == 2
        assert runtime.diagnostics(h.run_id).budget["spent"] == 4


def test_lost_ack_terminal_restart_only_queries_and_settles_exact_evidence(tmp_path):
    from ralf_agent.errors import MemoryBackendError

    class LostAck(InMemoryMemory):
        writes = 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            super().put_fact(*args, **kwargs)
            raise MemoryBackendError("lost acknowledgement")

    memory = LostAck(backend_id="durable-target")
    provider = ScriptedProvider([ModelResponse(output="observed")])
    path = tmp_path / "run.sqlite"
    with engine(path, provider, stage_policy=policy(memory)) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "outcome_unknown"
        assert runtime.diagnostics(h.run_id).budget["held"] == 1
    with engine(path, provider, stage_policy=policy(memory)) as runtime:
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "completed"
        assert runtime.diagnostics(h.run_id).budget["held"] == 0
        assert runtime.diagnostics(h.run_id).budget["spent"] == 2
        assert memory.writes == 1 and provider.calls == 1


@pytest.mark.parametrize("mutation", ["value", "expiry", "journal", "marker"])
def test_unknown_recovery_rejects_changed_or_missing_evidence(tmp_path, mutation):
    from ralf_agent.errors import MemoryBackendError

    class LostAck(InMemoryMemory):
        def put_fact(self, *args, **kwargs):
            super().put_fact(*args, **kwargs)
            raise MemoryBackendError("lost acknowledgement")

    memory = LostAck()
    path = tmp_path / "run.sqlite"
    with engine(path, stage_policy=policy(memory)) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        asyncio.run(runtime.drive(h.run_id))
        fact = memory.facts(runtime.scope, "auto-memory")[0]
        if mutation in {"value", "expiry"}:
            InMemoryMemory.put_fact(
                memory,
                runtime.scope,
                "auto-memory",
                fact["key"],
                {"changed": True} if mutation == "value" else fact["value"],
                expected_version=1,
                expires_at=9999999999 if mutation == "expiry" else None,
            )
        else:
            with runtime.store.transaction():
                run = runtime.store.run(h.run_id)
                if mutation == "journal":
                    run.pop("memory_stages")
                else:
                    run["actions"][0].pop("memory_stage")
                runtime.store.save_run(run)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(h.run_id))
        assert runtime.status(h.run_id).state == "succeeded"
        assert runtime.diagnostics(h.run_id).budget["held"] == 1


def test_lazy_or_fabricated_proposals_are_auxiliary_failures(tmp_path):
    from contextlib import contextmanager

    from ralf_agent.memory_extraction import FactProposal

    cls = importlib.import_module("ralf_agent.managed_memory").ManagedMemoryPolicy

    class Lazy(cls):
        @contextmanager
        def propose(self, evidence):
            raise AssertionError("deferred code must not run")
            yield

    class Fabricated(cls):
        def propose(self, evidence):
            return [FactProposal("result", "forged", ["result"])]

    for kind in (Lazy, Fabricated):
        memory = InMemoryMemory()
        with engine(tmp_path / (kind.__name__ + ".sqlite"), stage_policy=kind(memory)) as runtime:
            h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
            assert runtime.memory_stages(h.run_id)[0]["status"] == "failed"
            assert memory.facts(runtime.scope, "auto-memory") == []


def test_cancel_during_write_retains_evidence_and_does_not_upgrade_business(tmp_path):
    class Slow(InMemoryMemory):
        def __init__(self):
            super().__init__()
            self.started, self.release = asyncio.Event(), asyncio.Event()
            self.writes = 0

        async def put_fact(self, *args, **kwargs):
            self.writes += 1
            version = super().put_fact(*args, **kwargs)
            self.started.set()
            await self.release.wait()
            return version

    async def run():
        memory = Slow()
        with engine(tmp_path / "run.sqlite", stage_policy=policy(memory)) as runtime:
            h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            task = asyncio.create_task(runtime.drive(h.run_id))
            await asyncio.wait_for(memory.started.wait(), 1)
            runtime.cancel(h.run_id, command_id="cancel")
            memory.release.set()
            assert (await task).state == "cancelled"
            before = runtime.memory_stages(h.run_id)
            assert before[0]["facts"][0]["status"] == "completed"
            assert (await runtime.drive(h.run_id)).state == "cancelled"
            assert memory.writes == 1

    asyncio.run(run())


def test_facade_observes_and_explicitly_recovers_auxiliary_receipts(tmp_path):
    from ralf_agent import Runtime
    from ralf_agent.errors import MemoryBackendError
    from tests.test_remote_session_recovery import settled

    class LostAck(InMemoryMemory):
        def put_fact(self, *args, **kwargs):
            super().put_fact(*args, **kwargs)
            raise MemoryBackendError("lost acknowledgement")

    async def run():
        memory = LostAck()
        local = engine(tmp_path / "run.sqlite", stage_policy=policy(memory))
        async with Runtime(local, owned=True) as runtime:
            task = await runtime.create_agent(AgentSpec("a", "Answer")).submit("q", command_id="s")
            assert (await task.wait(wait_timeout=1)).snapshot.state == "succeeded"
            await settled(runtime)
            assert (await task.pending())[0]["kind"] == "auxiliary"
            assert (await task.memory_stages())[0]["status"] == "outcome_unknown"
            await task.resume()
            await settled(runtime)
            assert (await task.memory_stages())[0]["status"] == "completed"
            assert await task.pending() == []

    asyncio.run(run())


def test_threaded_memory_retains_lease_when_event_loop_tasks_cancel(tmp_path):
    import threading

    from ralf_agent import ThreadedMemoryAdapter
    from ralf_agent.errors import CoordinatorBusy

    class Slow(InMemoryMemory):
        def __init__(self):
            super().__init__()
            self.started, self.release = threading.Event(), threading.Event()

        def put_fact(self, *args, **kwargs):
            version = super().put_fact(*args, **kwargs)
            self.started.set()
            self.release.wait(5)
            return version

    async def run():
        memory = Slow()
        runtime = engine(
            tmp_path / "run.sqlite", stage_policy=policy(ThreadedMemoryAdapter(memory))
        )
        try:
            h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            task = asyncio.create_task(runtime.drive(h.run_id))
            async with asyncio.timeout(2):
                while not memory.started.is_set():  # noqa: ASYNC110 -- thread-owned event
                    await asyncio.sleep(0.01)
            for active in asyncio.all_tasks():
                if active is not asyncio.current_task():
                    active.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)
            with pytest.raises(ValidationError):
                runtime.close()
            with pytest.raises(CoordinatorBusy):
                engine(tmp_path / "run.sqlite")
            memory.release.set()
            await runtime.wait_for_threads()
        finally:
            memory.release.set()
            await runtime.wait_for_threads()
            runtime.close()

    asyncio.run(run())


def test_crash_between_receipt_and_settlement_recovers_without_rewrite(tmp_path):
    class CrashStore(SQLiteStore):
        def settle(self, reservation_id, actual, usage):
            if reservation_id.startswith("memory:"):
                raise SystemExit("simulated process loss")
            return super().settle(reservation_id, actual, usage)

    memory = InMemoryMemory(backend_id="persistent-target")
    provider = ScriptedProvider([ModelResponse(output="ok")])
    path = tmp_path / "run.sqlite"

    # Raise at the store boundary without killing the asyncio runner itself.
    class Crash(Exception):
        pass

    class InterruptStore(CrashStore):
        def settle(self, reservation_id, actual, usage):
            if reservation_id.startswith("memory:"):
                raise Crash()
            return SQLiteStore.settle(self, reservation_id, actual, usage)

    with LocalEngine(
        InterruptStore(path),
        providers={"default": provider},
        tools=ToolRegistry(),
        stage_policy=policy(memory),
    ) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        with pytest.raises(Crash):
            asyncio.run(runtime.drive(h.run_id))
        assert runtime.memory_stages(h.run_id)[0]["facts"][0]["status"] == "receipt_received"
    with engine(path, provider, stage_policy=policy(memory)) as runtime:
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "completed"
        assert len(memory.facts(runtime.scope, "auto-memory")) == 1 and provider.calls == 1


def test_expired_skipped_stage_recovery_is_stable(tmp_path, monkeypatch):
    cls = importlib.import_module("ralf_agent.managed_memory").ManagedMemoryPolicy
    clock = [1]
    monkeypatch.setattr("ralf_agent.managed_memory_stage.time.time", lambda: clock[0])

    class SlowSelection(cls):
        def propose(self, evidence):
            clock[0] = 11
            return super().propose(evidence)

    memory = InMemoryMemory()
    stage = SlowSelection(memory, admission=MemoryAdmissionPolicy(expires_at=10))
    with engine(tmp_path / "run.sqlite", stage_policy=stage) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        before = runtime.memory_stages(h.run_id)
        assert before[0]["status"] == "skipped"
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id) == before
        assert runtime.diagnostics(h.run_id).budget["held"] == 0


def test_proposal_journal_commit_failure_rolls_back_and_does_not_mask_host_failure(tmp_path):
    class Store(SQLiteStore):
        def save_run(self, run):
            if run.get("memory_stages", {}).get("0", {}).get("status") == "prepared":
                raise RuntimeError("proposal journal unavailable")
            return super().save_run(run)

    memory = InMemoryMemory(backend_id="facts")
    provider = ScriptedProvider([ModelResponse(output="ok")])
    path = tmp_path / "run.sqlite"
    with LocalEngine(
        Store(path),
        providers={"default": provider},
        tools=ToolRegistry(),
        stage_policy=policy(memory),
    ) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        with pytest.raises(RuntimeError):
            asyncio.run(runtime.drive(h.run_id))
        assert runtime.memory_stages(h.run_id)[0]["status"] == "proposing"
        assert memory.facts(runtime.scope, "auto-memory") == []
        assert runtime.diagnostics(h.run_id).budget["held"] == 0
    with engine(path, provider, stage_policy=policy(memory)) as runtime:
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "failed"
        assert provider.calls == 1
