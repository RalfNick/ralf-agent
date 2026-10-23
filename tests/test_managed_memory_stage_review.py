import asyncio
import importlib

import pytest

from relf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    ManagedMemoryPolicy,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
)
from relf_agent.errors import DefinitionMismatch, MemoryBackendError
from tests.helpers import ScriptedProvider
from tests.test_managed_memory_stage import engine, policy


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_large_namespace_exact_inspection_does_not_exhaust_or_hold(tmp_path, backend):
    store = SQLiteStore(tmp_path / "run.sqlite")
    memory = InMemoryMemory() if backend == "memory" else store.create_memory()
    stage = ManagedMemoryPolicy(memory)
    with LocalEngine(
        store,
        providers={"default": ScriptedProvider([ModelResponse(output="ok")])},
        tools=ToolRegistry(),
        stage_policy=stage,
    ) as runtime:
        for i in range(8192):
            memory.put_fact(runtime.scope, "auto-memory", f"existing:{i}", i, expected_version=0)
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "completed"
        assert runtime.diagnostics(h.run_id).budget["held"] == 0


def test_recall_only_target_persists_scan_continuation(tmp_path):
    class RecallOnly:
        backend_id = "legacy-target"

        def __init__(self):
            self.inner, self.writes = InMemoryMemory(), 0

        def put_fact(self, *args, **kwargs):
            self.writes += 1
            return self.inner.put_fact(*args, **kwargs)

        def recall(self, *args, **kwargs):
            return self.inner.recall(*args, **kwargs)

        def validate_facts(self, *args, **kwargs):
            return self.inner.validate_facts(*args, **kwargs)

    target = RecallOnly()
    with engine(tmp_path / "run.sqlite", stage_policy=policy(target)) as runtime:
        for i in range(8192):
            target.inner.put_fact(
                runtime.scope, "auto-memory", f"existing:{i}", i, expected_version=0
            )
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "outcome_unknown"
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "completed"
        assert target.writes == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "stage_status",
        "fact_status",
        "fact_state_rewind",
        "receipt",
        "missing_reservation",
        "wrong_amount",
        "wrong_owner",
    ],
)
def test_inconsistent_unknown_stage_evidence_is_refused(tmp_path, mutation):
    class LostAck(InMemoryMemory):
        def put_fact(self, *args, **kwargs):
            super().put_fact(*args, **kwargs)
            raise MemoryBackendError("lost acknowledgement")

    memory = LostAck()
    with engine(tmp_path / "run.sqlite", stage_policy=policy(memory)) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        asyncio.run(runtime.drive(h.run_id))
        with runtime.store.transaction():
            run = runtime.store.run(h.run_id)
            record = run["memory_stages"]["0"]
            fact = record["facts"][0]
            if mutation == "stage_status":
                record["status"] = "completed"
            elif mutation == "fact_status":
                fact["status"] = "made-up"
            elif mutation == "fact_state_rewind":
                fact["status"] = "prepared"
            elif mutation == "receipt":
                fact["status"] = "receipt_received"
                fact["receipt"] = {"source_digest": "forged"}
            elif mutation == "missing_reservation":
                runtime.store.conn.execute(
                    "DELETE FROM reservations WHERE id=?", (fact["reservation_id"],)
                )
            elif mutation == "wrong_amount":
                runtime.store.conn.execute(
                    "UPDATE reservations SET amount=0 WHERE id=?", (fact["reservation_id"],)
                )
            else:
                runtime.store.conn.execute(
                    "UPDATE reservations SET run_id='foreign' WHERE id=?", (fact["reservation_id"],)
                )
            runtime.store.save_run(run)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(h.run_id))
        with pytest.raises(DefinitionMismatch):
            runtime.memory_stages(h.run_id)
        assert runtime.status(h.run_id).state == "succeeded"


def test_missing_prepared_reservation_refuses_before_new_cas(tmp_path, monkeypatch):
    module = importlib.import_module("relf_agent.managed_memory_stage")
    original = module._execute

    async def crash(*args, **kwargs):
        raise RuntimeError("lost process after proposal adoption")

    memory = InMemoryMemory(backend_id="target")
    provider = ScriptedProvider([ModelResponse(output="ok")])
    path = tmp_path / "run.sqlite"
    with engine(path, provider, stage_policy=policy(memory)) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        monkeypatch.setattr(module, "_execute", crash)
        with pytest.raises(RuntimeError):
            asyncio.run(runtime.drive(h.run_id))
        monkeypatch.setattr(module, "_execute", original)
        runtime.store.conn.execute("DELETE FROM reservations WHERE id LIKE 'memory:%'")
    with engine(path, provider, stage_policy=policy(memory)) as runtime:
        assert asyncio.run(runtime.drive(h.run_id)).state == "failed"
        assert memory.facts(runtime.scope, "auto-memory") == []
        assert provider.calls == 1


@pytest.mark.parametrize("after", ["expired", "revised", "offline"])
def test_recorded_receipt_settles_without_live_fact_dependency(tmp_path, monkeypatch, after):
    from relf_agent import MemoryAdmissionPolicy

    clock = [1]
    monkeypatch.setattr("relf_agent.managed_memory_stage.time.time", lambda: clock[0])

    class CrashStore(SQLiteStore):
        def settle(self, reservation_id, actual, usage):
            if reservation_id.startswith("memory:"):
                raise RuntimeError("crash after exact receipt")
            return super().settle(reservation_id, actual, usage)

    class Memory(InMemoryMemory):
        offline = False

        def recall(self, *args, **kwargs):
            if self.offline:
                raise MemoryBackendError("unavailable")
            return super().recall(*args, **kwargs)

        def inspect_fact(self, *args, **kwargs):
            if self.offline:
                raise MemoryBackendError("unavailable")
            return super().inspect_fact(*args, **kwargs)

    memory = Memory(backend_id="persisted-memory")
    provider = ScriptedProvider([ModelResponse(output="ok")])
    stage = policy(memory, admission=MemoryAdmissionPolicy(expires_at=10))
    path = tmp_path / "run.sqlite"
    with LocalEngine(
        CrashStore(path), providers={"default": provider}, tools=ToolRegistry(), stage_policy=stage
    ) as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        with pytest.raises(RuntimeError):
            asyncio.run(runtime.drive(h.run_id))
        assert runtime.memory_stages(h.run_id)[0]["facts"][0]["status"] == "receipt_received"
        fact = memory.facts(runtime.scope, "auto-memory")[0]
        if after == "revised":
            memory.put_fact(runtime.scope, "auto-memory", fact["key"], "new", expected_version=1)
    if after == "expired":
        clock[0] = 11
    memory.offline = after == "offline"
    with engine(path, provider, stage_policy=stage) as runtime:
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.memory_stages(h.run_id)[0]["status"] == "completed"
        assert runtime.diagnostics(h.run_id).budget["held"] == 0
        assert runtime.diagnostics(h.run_id).budget["spent"] == 2 and provider.calls == 1


def test_thread_bridge_cannot_swap_same_named_underlying_target():
    from relf_agent import ThreadedMemoryAdapter

    bridge = ThreadedMemoryAdapter(InMemoryMemory(backend_id="same-name"))
    stage = ManagedMemoryPolicy(bridge)
    bridge.backend = InMemoryMemory(backend_id="same-name")
    with pytest.raises(DefinitionMismatch):
        _ = stage.identity
