import asyncio
import copy
from contextlib import contextmanager

import pytest

from relf_agent import (
    AgentSpec,
    ArtifactReference,
    InMemoryArtifactStore,
    ModelResponse,
    Scope,
    SQLiteArtifactStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.types import canonical
from tests.helpers import ScriptedProvider
from tests.test_managed_memory_stage import engine, schema


def context(store, **kwargs):
    from relf_agent.data_context import ManagedDataContext

    return ManagedDataContext(store, tool_result_chars=1024, preview_chars=64, **kwargs)


def history():
    return [
        {"role": "system", "content": "Answer"},
        {"role": "user", "content": "Task"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c"}]},
        {"role": "tool", "tool_call_id": "c", "content": "BIG" * 3000},
    ]


def test_large_latest_tool_group_is_projected_without_losing_pairing_or_raw_evidence():
    artifacts = InMemoryArtifactStore(backend_id="artifacts")
    builder = context(artifacts)
    original = history()
    before = copy.deepcopy(original)
    messages, manifest = builder.assemble(original, [], 2000)
    assert original == before and messages[-1]["tool_call_id"] == "c"
    assert messages[-2] == original[-2]
    assert len(canonical(messages)) < 2000 and "BIGBIG" in messages[-1]["content"]
    assert manifest["artifact_projection"][0]["message_index"] == 3
    assert builder.prepare(original, [], 2000) is None


def test_reference_excerpt_preserves_provenance_without_impersonating_original_fact():
    builder = context(InMemoryArtifactStore(backend_id="artifacts"), reference_chars=128)
    references = [{"key": "doc", "version": 3, "value": "EVIDENCE" * 1000}]
    messages, manifest = builder.assemble(history()[:2], references, 2000)
    text = canonical(messages)
    assert "EVIDENCE" in text and "incomplete" in text and '"version":3' in messages[-1]["content"]
    assert manifest["reference_compression"][0]["source_digest"]
    assert references[0]["value"] == "EVIDENCE" * 1000


def test_target_methods_and_configuration_cannot_change_under_fixed_release():
    store = InMemoryArtifactStore(backend_id="artifacts")
    builder = context(store)
    store.get = lambda *args, **kwargs: "fabricated"
    with pytest.raises(DefinitionMismatch):
        builder.assemble(history(), [], 2000)


def test_actual_backend_cannot_move_behind_an_unchanged_declared_identity():
    class Store(InMemoryArtifactStore):
        @property
        def identity(self):
            return {"kind": "fixed", "backend_id": "artifacts", "version": "1"}

    store = Store(backend_id="artifacts")
    builder = context(store)
    store._backend_id = "different"
    with pytest.raises(DefinitionMismatch):
        _ = builder.identity


@pytest.mark.parametrize("kwargs", [{"preview_chars": True}, {"reference_chars": 0}])
def test_invalid_projection_budget_is_rejected(kwargs):
    from relf_agent.data_context import ManagedDataContext

    with pytest.raises(ValidationError):
        ManagedDataContext(InMemoryArtifactStore(), **kwargs)


def test_opt_in_schema_gate_and_scope_are_atomic(tmp_path):
    builder = context(InMemoryArtifactStore(backend_id="artifacts"))
    with engine(tmp_path / "runs.db", context_assembler=builder) as local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert schema(local) == "10"
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
    with engine(
        tmp_path / "other.db",
        context_assembler=context(InMemoryArtifactStore(), scope=Scope("elsewhere", "x")),
    ) as local:
        with pytest.raises(AuthorizationDenied):
            local.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert schema(local) == "1"


def business():
    tools = ToolRegistry()
    writes = []

    def read(args, ctx):
        writes.append(1)
        return "BIG" * 3000

    tools.register(
        ToolSpec("read", "evidence", {"type": "object"}, effect="read_only", cost=0), read
    )
    return tools, writes


def provider():
    return ScriptedProvider(
        [
            ModelResponse(tool_calls=[ToolCall("read", {}, call_id="c")]),
            ModelResponse(output="finished"),
        ]
    )


def crash_after_committed_event(local, event, crash, before_crash=None):
    """Crash outside the transaction; throwing in _commit would roll it back."""
    commit, transaction = local._commit, local.store.transaction
    pending = []
    depth = 0

    def recording(run, kind, data=None):
        commit(run, kind, data)
        if kind == event and (kind != "model_response_recorded" or run.get("context_artifacts")):
            pending.append(copy.deepcopy(run))

    @contextmanager
    def durable():
        nonlocal depth
        depth += 1
        try:
            with transaction():
                yield
        finally:
            depth -= 1
        if depth == 0 and pending:
            if before_crash:
                before_crash(pending[-1])
            raise crash()

    local._commit, local.store.transaction = recording, durable


def test_real_run_unloads_once_and_preserves_execution_evidence(tmp_path):
    artifacts = SQLiteArtifactStore(tmp_path / "artifacts.db")
    tools, effects = business()
    model = provider()
    try:
        with engine(
            tmp_path / "runs.db", model, tools=tools, context_assembler=context(artifacts)
        ) as local:
            h = local.submit(
                AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000),
                "q",
                command_id="s",
            )
            assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
            raw = local.store.run(h.run_id)
            assert len(effects) == 1 and model.calls == 2
            assert "BIG" * 3000 in canonical(raw["messages"])
            assert (
                "artifact" in canonical(model.messages[-1])
                and len(canonical(model.messages[-1])) <= 2000
            )
            record = next(iter(raw["context_artifacts"].values()))
            assert record["status"] == "verified"
            assert artifacts.get(
                Scope(), ArtifactReference.from_dict(record["intent"]["reference"])
            ) == canonical("BIG" * 3000)
    finally:
        artifacts.close()


@pytest.mark.parametrize(
    "event", ["context_artifact_intent", "context_artifact_dispatched", "context_artifact_verified"]
)
def test_original_run_restarts_without_repeating_tool(tmp_path, event):
    class Crash(BaseException):
        pass

    artifacts = SQLiteArtifactStore(tmp_path / "artifacts.db")
    tools, effects = business()
    model = provider()
    local = engine(tmp_path / "runs.db", model, tools=tools, context_assembler=context(artifacts))
    h = local.submit(
        AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000), "q", command_id="s"
    )

    def lost_ack(run):
        if event == "context_artifact_dispatched":
            record = next(iter(run["context_artifacts"].values()))
            artifacts.put(Scope(), "context-results", record["value"])

    crash_after_committed_event(local, event, Crash, lost_ack)
    try:
        with pytest.raises(Crash):
            asyncio.run(local.drive(h.run_id))
    finally:
        local.close()
        artifacts.close()
    restored_artifacts = SQLiteArtifactStore(tmp_path / "artifacts.db")
    remaining = ScriptedProvider([ModelResponse(output="finished")])
    try:
        with engine(
            tmp_path / "runs.db",
            remaining,
            tools=tools,
            context_assembler=context(restored_artifacts),
        ) as restored:
            assert asyncio.run(restored.drive(h.run_id)).state == "succeeded"
            assert len(effects) == 1 and remaining.calls == 1
            assert (
                next(iter(restored.store.run(h.run_id)["context_artifacts"].values()))["status"]
                == "verified"
            )
    finally:
        restored_artifacts.close()


def test_lost_put_ack_is_verified_without_repeating_write(tmp_path):
    class LostAck(InMemoryArtifactStore):
        puts = 0

        def put(self, *args, **kwargs):
            self.puts += 1
            super().put(*args, **kwargs)
            raise RuntimeError("ack lost")

    artifacts = LostAck(backend_id="artifacts")
    tools, effects = business()
    model = provider()
    with engine(
        tmp_path / "runs.db", model, tools=tools, context_assembler=context(artifacts)
    ) as local:
        h = local.submit(
            AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000), "q", command_id="s"
        )
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert artifacts.puts == 1 and len(effects) == 1 and model.calls == 2


@pytest.mark.parametrize("after_response", [False, True])
def test_missing_artifact_blocks_disclosure_but_not_adoption_of_received_model_response(
    tmp_path, after_response
):
    class Crash(BaseException):
        pass

    artifacts = SQLiteArtifactStore(tmp_path / "artifacts.db")
    tools, effects = business()
    model = provider()
    local = engine(tmp_path / "runs.db", model, tools=tools, context_assembler=context(artifacts))
    h = local.submit(
        AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000), "q", command_id="s"
    )

    def remove(run):
        record = next(iter(run["context_artifacts"].values()))
        artifacts.delete(Scope(), ArtifactReference.from_dict(record["intent"]["reference"]))

    crash_after_committed_event(
        local,
        "model_response_recorded" if after_response else "context_artifact_verified",
        Crash,
        remove,
    )
    try:
        with pytest.raises(Crash):
            asyncio.run(local.drive(h.run_id))
    finally:
        local.close()
        artifacts.close()
    target = SQLiteArtifactStore(tmp_path / "artifacts.db")
    remaining = ScriptedProvider([ModelResponse(output="finished")])
    try:
        with engine(
            tmp_path / "runs.db", remaining, tools=tools, context_assembler=context(target)
        ) as restored:
            result = asyncio.run(restored.drive(h.run_id))
            assert result.state == ("succeeded" if after_response else "failed")
            assert remaining.calls == 0 and len(effects) == 1
    finally:
        target.close()


def test_changed_async_artifact_target_is_refused_after_await(tmp_path):
    class AsyncStore:
        def __init__(self):
            self.storage = InMemoryArtifactStore(backend_id="artifacts")
            self.identity = self.storage.identity
            self.backend_id = "artifacts"
            self.change = None

        async def put(self, *args, **kwargs):
            result = self.storage.put(*args, **kwargs)
            if self.change:
                self.change()
            return result

        async def get(self, *args, **kwargs):
            return self.storage.get(*args, **kwargs)

    target = AsyncStore()
    builder = context(target)
    target.change = lambda: setattr(builder, "artifacts", AsyncStore())
    tools, effects = business()
    model = provider()
    with engine(tmp_path / "runs.db", model, tools=tools, context_assembler=builder) as local:
        h = local.submit(
            AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000), "q", command_id="s"
        )
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert model.calls == 1 and len(effects) == 1


@pytest.mark.parametrize("corruption", ["intent", "receipt", "value"])
def test_artifact_evidence_corruption_is_detected_by_offline_query(tmp_path, corruption):
    artifacts = InMemoryArtifactStore(backend_id="artifacts")
    tools, _ = business()
    with engine(
        tmp_path / "runs.db", provider(), tools=tools, context_assembler=context(artifacts)
    ) as local:
        h = local.submit(
            AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000), "q", command_id="s"
        )
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        run = local.store.run(h.run_id)
        key = next(iter(run["context_artifacts"]))
        if corruption == "value":
            run["context_artifacts"][key]["value"] = "forged"
        else:
            run["context_artifact_" + ("intents" if corruption == "intent" else "receipts")].pop(
                key
            )
        with local.store.transaction():
            local._commit(run, "corrupted")
        with pytest.raises(DefinitionMismatch):
            local.context_artifacts(h.run_id)


@pytest.mark.parametrize("mode", ["excerpt", "model"])
def test_summary_reuses_original_coverage_with_large_tool_projection(tmp_path, mode):
    from tests.test_context_preparation import Provider
    from tests.test_context_preparation import tools as context_tools

    model = Provider()
    artifacts = InMemoryArtifactStore(backend_id="artifacts")
    with engine(
        tmp_path / "runs.db",
        model,
        tools=context_tools(),
        context_assembler=context(artifacts, mode=mode, summary_max_chars=128),
    ) as local:
        h = local.submit(
            AgentSpec("a", "Answer", tools=["lookup"], max_context_chars=1100), "q", command_id="s"
        )
        assert asyncio.run(local.drive(h.run_id)).state == "succeeded"
        assert model.business == 3
        stages = local.context_stages(h.run_id)
        assert len(stages) == 1 and stages[0]["status"] == "completed"
        assert model.summaries == (mode == "model")


def test_session_projection_retains_recent_evidence_instead_of_old_prefix():
    builder = context(InMemoryArtifactStore(backend_id="artifacts"), reference_chars=128)
    session = {
        "session": [
            {"role": "assistant", "task": "old", "content": "OLD" * 1000},
            {"role": "assistant", "task": "current", "content": "CURRENT"},
        ]
    }
    messages, _ = builder.assemble(history()[:2], [session], 2000)
    assert "CURRENT" in canonical(messages)


def test_explicit_cancel_waits_for_artifact_io_and_never_discloses_projection(tmp_path):
    class AsyncStore:
        def __init__(self):
            self.base = InMemoryArtifactStore(backend_id="artifacts")
            self.identity, self.backend_id = self.base.identity, self.base.backend_id
            self.started, self.finish = asyncio.Event(), asyncio.Event()
            self.puts = 0

        async def put(self, *args, **kwargs):
            self.puts += 1
            self.started.set()
            await self.finish.wait()
            return self.base.put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            return self.base.get(*args, **kwargs)

    async def exercise():
        target = AsyncStore()
        tools, effects = business()
        model = provider()
        local = engine(tmp_path / "runs.db", model, tools=tools, context_assembler=context(target))
        h = local.submit(
            AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000), "q", command_id="s"
        )
        task = asyncio.create_task(local.drive(h.run_id))
        await asyncio.wait_for(target.started.wait(), 2)
        local.cancel(h.run_id, command_id="cancel")
        target.finish.set()
        assert (await task).state == "cancelled"
        assert target.puts == 1 and model.calls == 1 and len(effects) == 1
        assert (await local.drive(h.run_id)).state == "cancelled"
        assert target.puts == 1
        local.close()

    asyncio.run(exercise())


def test_cancel_during_initial_artifact_lookup_prevents_a_new_put(tmp_path):
    class AsyncStore:
        def __init__(self):
            self.base = InMemoryArtifactStore(backend_id="artifacts")
            self.identity, self.backend_id = self.base.identity, self.base.backend_id
            self.started, self.finish = asyncio.Event(), asyncio.Event()
            self.puts = 0

        async def put(self, *args, **kwargs):
            self.puts += 1
            return self.base.put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            self.started.set()
            await self.finish.wait()
            return self.base.get(*args, **kwargs)

    async def exercise():
        target = AsyncStore()
        tools, effects = business()
        model = provider()
        local = engine(tmp_path / "runs.db", model, tools=tools, context_assembler=context(target))
        h = local.submit(
            AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000), "q", command_id="s"
        )
        task = asyncio.create_task(local.drive(h.run_id))
        await asyncio.wait_for(target.started.wait(), 2)
        local.cancel(h.run_id, command_id="cancel")
        target.finish.set()
        assert (await task).state == "cancelled"
        assert target.puts == 0 and model.calls == 1 and len(effects) == 1
        local.close()

    asyncio.run(exercise())


def test_fact_change_during_final_artifact_read_blocks_stale_model_disclosure(tmp_path):
    from relf_agent import InMemoryMemory, MemoryRecallPolicy

    memory = InMemoryMemory(backend_id="facts")
    memory.put_fact(Scope(), "a", "state", "BEFORE", expected_version=0)

    class AsyncStore:
        def __init__(self):
            self.base = InMemoryArtifactStore(backend_id="artifacts")
            self.identity, self.backend_id = self.base.identity, self.base.backend_id
            self.change = None

        async def put(self, *args, **kwargs):
            return self.base.put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            value = self.base.get(*args, **kwargs)
            if self.change:
                self.change()
            return value

    target = AsyncStore()
    tools, effects = business()
    model = provider()
    with engine(
        tmp_path / "runs.db",
        model,
        tools=tools,
        memory_store=memory,
        recall_policy=MemoryRecallPolicy(),
        context_assembler=context(target),
    ) as local:
        h = local.submit(
            AgentSpec("a", "Answer", tools=["read"], max_context_chars=3000), "q", command_id="s"
        )

        def change():
            action = local.store.run(h.run_id)["actions"][-1]
            if action["kind"] == "model" and action["status"] == "executing":
                memory.put_fact(Scope(), "a", "state", "AFTER", expected_version=1)
                target.change = None

        target.change = change
        assert asyncio.run(local.drive(h.run_id)).state == "failed"
        assert model.calls == 1 and len(effects) == 1


def test_dispatched_artifact_cannot_be_downgraded_to_prepared(tmp_path):
    class Crash(BaseException):
        pass

    artifacts = InMemoryArtifactStore(backend_id="artifacts")
    tools, _ = business()
    with engine(
        tmp_path / "runs.db", provider(), tools=tools, context_assembler=context(artifacts)
    ) as local:
        h = local.submit(
            AgentSpec("a", "Answer", tools=["read"], max_context_chars=2000), "q", command_id="s"
        )
        crash_after_committed_event(local, "context_artifact_dispatched", Crash)
        with pytest.raises(Crash):
            asyncio.run(local.drive(h.run_id))
        # Restore normal transaction behavior; deliberately corrupt one field.
        from relf_agent.storage import SQLiteStore

        local.store.transaction = SQLiteStore.transaction.__get__(local.store)
        run = local.store.run(h.run_id)
        record = next(iter(run["context_artifacts"].values()))
        assert record["status"] == "writing"
        record["status"] = "prepared"
        with local.store.transaction():
            local._commit(run, "corrupted")
        with pytest.raises(DefinitionMismatch):
            local.context_artifacts(h.run_id)
