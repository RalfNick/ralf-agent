import asyncio
import copy

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry
from relf_agent.context import ContextAssembler
from relf_agent.errors import DefinitionMismatch
from relf_agent.memory import InMemoryMemory, SQLiteMemory


class RecordingProvider:
    identity = {"kind": "retrieval-integration-provider", "version": "1"}

    def __init__(self, fail_once=False):
        self.requests = []
        self.fail_once = fail_once

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        if self.fail_once and len(self.requests) == 1:
            raise TimeoutError("Model response was lost")
        return ModelResponse(output="Verified answer")


def policy(**kwargs):
    from relf_agent.recall import MemoryRecallPolicy, RecallQuery

    return MemoryRecallPolicy(
        facts=RecallQuery(max_items=2, max_chars=1024, scan_limit=8),
        session=RecallQuery(max_items=2, max_chars=1024, scan_limit=8),
        **kwargs,
    )


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_opt_in_recall_uses_bounded_ports_and_recent_complete_session_records(tmp_path, kind):
    class Memory(InMemoryMemory if kind == "memory" else SQLiteMemory):
        def facts(self, *args):
            pytest.fail("An enabled paginated backend must not materialize facts()")

    backend = (
        Memory(backend_id="bounded:v1") if kind == "memory" else Memory(tmp_path / "memory.db")
    )
    scope = Scope()
    for index in range(6):
        backend.put_fact(scope, "assistant", f"fact-{index}", f"value-{index}", expected_version=0)
        backend.append(
            scope,
            "shared",
            {"role": "assistant", "content": f"message-{index}"},
            expected_revision=index,
            message_id=f"message-{index}",
        )
    provider = RecordingProvider()
    try:
        with LocalEngine(
            SQLiteStore(tmp_path / "run.db"),
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=backend,
            memory_store=backend,
            recall_policy=policy(),
        ) as engine:
            handle = engine.submit(
                AgentSpec("assistant", "Use recalled evidence"),
                "question",
                command_id="start",
                session_id="shared",
            )
            done = asyncio.run(engine.drive(handle.run_id))
            assert done.state == "succeeded"
            request = str(provider.requests[0])
            assert "value-0" in request and "value-1" in request and "value-2" not in request
            assert "message-4" in request and "message-5" in request and "message-3" not in request
            assert engine.store.run(handle.run_id)["manifest"]["memory_recall"]
    finally:
        backend.close()


def test_multiple_empty_pages_can_progress_without_exceeding_total_recall_quota(tmp_path):
    from relf_agent.recall import MemoryRecallPolicy, RecallQuery

    memory = InMemoryMemory(backend_id="bounded-pages:v1")
    for index in range(4):
        memory.put_fact(Scope(), "assistant", f"large-{index}", "x" * 4000, expected_version=0)
    for index in range(12):
        memory.put_fact(
            Scope(), "assistant", f"small-{index}", f"answer-{index}", expected_version=0
        )
    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        memory_store=memory,
        recall_policy=MemoryRecallPolicy(
            facts=RecallQuery(max_items=4, max_chars=2048, scan_limit=8),
            max_pages=4,
        ),
    ) as engine:
        handle = engine.submit(
            AgentSpec("assistant", "Use available facts"), "question", command_id="s"
        )
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded"
        request = str(provider.requests[0])
        assert "answer-0" in request and "x" * 4000 not in request
        manifest = done.actions[0]["context_manifest"]["memory_recall"]
        assert manifest["facts"]["scanned"] <= 8
        assert manifest["facts"]["used_chars"] <= 2048
        assert manifest["facts"]["items"] <= 4


def test_default_profile_keeps_manifest_and_submit_identity_without_new_capabilities(tmp_path):
    database = tmp_path / "run.db"
    spec = AgentSpec("default", "Answer")
    with LocalEngine(
        SQLiteStore(database), providers={"default": RecordingProvider()}, tools=ToolRegistry()
    ) as engine:
        original = engine.submit(spec, "question", command_id="s")
        manifest = engine.store.run(original.run_id)["manifest"]
        assert "memory_recall" not in manifest and "knowledge" not in manifest
    with LocalEngine(
        SQLiteStore(database), providers={"default": RecordingProvider()}, tools=ToolRegistry()
    ) as engine:
        assert engine.submit(spec, "question", command_id="s") == original
        assert asyncio.run(engine.drive(original.run_id)).state == "succeeded"


def test_changed_recall_policy_cannot_continue_a_pinned_run(tmp_path):
    from relf_agent.recall import MemoryRecallPolicy, RecallQuery

    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        recall_policy=policy(),
    ) as engine:
        handle = engine.submit(AgentSpec("assistant", "Answer"), "question", command_id="s")
        engine.recall_policy = MemoryRecallPolicy(facts=RecallQuery(max_items=1))
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(handle.run_id))
        assert provider.requests == []


def knowledge_context():
    from relf_agent.retrieval import (
        Document,
        InMemoryKnowledgeStore,
        KnowledgeContext,
        LexicalRetriever,
    )

    store = InMemoryKnowledgeStore()
    store.put(
        Scope(),
        "runbooks",
        Document("cache", "Cache timeout: inspect connection pool.", source_uri="runbook://cache"),
        expected_version=0,
    )
    context = KnowledgeContext(LexicalRetriever(store), namespace="runbooks")
    return store, context


def test_knowledge_is_injected_as_evidence_with_versions_and_source_uri(tmp_path):
    store, knowledge = knowledge_context()
    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        knowledge=knowledge,
    ) as engine:
        handle = engine.submit(
            AgentSpec("assistant", "Use source evidence"), "cache timeout", command_id="s"
        )
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded"
        assert "runbook://cache" in str(provider.requests[0])
        refs = done.actions[0]["knowledge_references"]
        assert len(refs) == 1 and refs[0]["version"] == 1
        assert refs[0]["_knowledge"]["scope"] == {
            "workspace": "default",
            "principal": "local-owner",
        }
        assert engine.store.run(handle.run_id)["manifest"]["knowledge"]


def test_source_deleted_during_assembly_is_rejected_before_provider_call(tmp_path):
    store, knowledge = knowledge_context()

    class DeletingContext(ContextAssembler):
        identity = {"kind": "delete-source-during-assembly", "version": "1"}

        def assemble(self, history, references, max_chars):
            result = super().assemble(history, references, max_chars)
            store.delete(Scope(), "runbooks", "cache", expected_version=1)
            return result

    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        knowledge=knowledge,
        context_assembler=DeletingContext(),
    ) as engine:
        handle = engine.submit(AgentSpec("assistant", "Answer"), "cache timeout", command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and provider.requests == []
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}


def test_model_retry_reuses_original_knowledge_snapshot_without_new_retrieval(tmp_path):
    from relf_agent.retrieval import KnowledgeContext

    store, initial = knowledge_context()

    class CountingContext(KnowledgeContext):
        queries = 0

        async def references(self, scope, text):
            self.queries += 1
            return await super().references(scope, text)

    knowledge = CountingContext(initial.retriever, namespace="runbooks")
    provider = RecordingProvider(fail_once=True)
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        knowledge=knowledge,
    ) as engine:
        handle = engine.submit(AgentSpec("assistant", "Answer"), "cache timeout", command_id="s")
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_reconciliation"
        before = waiting.actions[0]["snapshot"]
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded" and knowledge.queries == 1
        assert provider.requests == [before, before]
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 1, "spent": 1}


def test_model_retry_refuses_changed_source_instead_of_replacing_original_snapshot(tmp_path):
    from relf_agent.retrieval import Document

    store, knowledge = knowledge_context()
    provider = RecordingProvider(fail_once=True)
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        knowledge=knowledge,
    ) as engine:
        handle = engine.submit(AgentSpec("assistant", "Answer"), "cache timeout", command_id="s")
        waiting = asyncio.run(engine.drive(handle.run_id))
        before = waiting.actions[0]["snapshot"]
        store.put(
            Scope(),
            "runbooks",
            Document("cache", "New cache timeout instructions"),
            expected_version=1,
        )
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and len(provider.requests) == 1
        assert done.actions[0]["snapshot"] == before
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 1, "spent": 0}
