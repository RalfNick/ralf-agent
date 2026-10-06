"""Independent integration checks for bounded recall and current-source injection."""

import asyncio
import copy

import pytest

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry
from ralf_agent.memory import InMemoryMemory
from ralf_agent.recall import MemoryRecallPolicy, RecallQuery
from ralf_agent.retrieval import InMemoryKnowledgeStore, KnowledgeContext, LexicalRetriever


class ReviewProvider:
    identity = {"kind": "recall-rag-review", "version": "1"}

    def __init__(self, *, fail_once=False):
        self.requests = []
        self.fail_once = fail_once

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        if self.fail_once and len(self.requests) == 1:
            raise TimeoutError("Response was lost")
        return ModelResponse(output="done")


@pytest.mark.parametrize("change", ["expired", "updated"])
def test_fact_changed_while_loading_other_references_is_not_injected_as_current_evidence(
    tmp_path, monkeypatch, change
):
    clock = {"now": 1000.0}
    monkeypatch.setattr("ralf_agent.memory.time.time", lambda: clock["now"])

    async def scenario():
        class SlowKnowledge(KnowledgeContext):
            def __init__(self, retriever):
                super().__init__(retriever)
                self.started, self.release = asyncio.Event(), asyncio.Event()

            async def references(self, scope, text):
                references = await super().references(scope, text)
                self.started.set()
                await self.release.wait()
                return references

        memory = InMemoryMemory(backend_id="review-memory")
        memory.put_fact(
            Scope(),
            "review",
            "temporary-permission",
            "EXPIRED_CANARY",
            expected_version=0,
            expires_at=1001,
        )
        knowledge = SlowKnowledge(LexicalRetriever(InMemoryKnowledgeStore()))
        provider = ReviewProvider()
        with LocalEngine(
            SQLiteStore(tmp_path / "ttl.db"),
            providers={"default": provider},
            tools=ToolRegistry(),
            memory_store=memory,
            recall_policy=MemoryRecallPolicy(),
            knowledge=knowledge,
        ) as engine:
            handle = engine.submit(
                AgentSpec("review", "Use current evidence"), "question", command_id="s"
            )
            driving = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(knowledge.started.wait(), 2)
            if change == "expired":
                clock["now"] = 1002.0
            else:
                memory.put_fact(
                    Scope(),
                    "review",
                    "temporary-permission",
                    "NEW_CANARY",
                    expected_version=1,
                    expires_at=1001,
                )
            knowledge.release.set()
            done = await asyncio.wait_for(driving, 2)
            assert provider.requests == []
            assert done.state == "failed" and done.error["code"] == "validation_error"
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["expired", "updated"])
def test_unknown_model_retry_rejects_changed_facts_without_recall_or_snapshot_replacement(
    tmp_path, monkeypatch, change
):
    clock = {"now": 1000.0}
    monkeypatch.setattr("ralf_agent.memory.time.time", lambda: clock["now"])

    class CountedMemory(InMemoryMemory):
        recall_calls = 0

        def recall(self, *arguments):
            self.recall_calls += 1
            return super().recall(*arguments)

    memory = CountedMemory(backend_id="review-retry-memory")
    memory.put_fact(
        Scope(), "review", "fact", "ORIGINAL_CANARY", expected_version=0, expires_at=1001
    )
    provider = ReviewProvider(fail_once=True)
    with LocalEngine(
        SQLiteStore(tmp_path / "retry.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        memory_store=memory,
        recall_policy=MemoryRecallPolicy(),
    ) as engine:
        handle = engine.submit(AgentSpec("review", "Use evidence"), "question", command_id="s")
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_reconciliation"
        original = copy.deepcopy(waiting.actions[0]["snapshot"])
        if change == "expired":
            clock["now"] = 1002.0
        else:
            memory.put_fact(
                Scope(), "review", "fact", "NEW_CANARY", expected_version=1, expires_at=1001
            )
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "validation_error"
        assert len(provider.requests) == memory.recall_calls == 1
        assert done.actions[0]["snapshot"] == original
        assert len(done.actions[0]["attempts"]) == 1
        assert done.actions[0]["attempts"][0]["status"] == "unknown"
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 1, "spent": 0}


def test_recorded_model_response_is_adopted_after_source_changes_without_retrieval(tmp_path):
    from ralf_agent.retrieval import Document

    from .receipt_runtime import ReceiptWindowStore

    class CountedMemory(InMemoryMemory):
        recall_calls = 0

        def recall(self, *arguments):
            self.recall_calls += 1
            return super().recall(*arguments)

    class CountedKnowledge(KnowledgeContext):
        retrieval_calls = 0

        async def references(self, *arguments):
            self.retrieval_calls += 1
            return await super().references(*arguments)

    memory = CountedMemory(backend_id="review-received-memory")
    memory.put_fact(Scope(), "review", "fact", "ORIGINAL_CANARY", expected_version=0)
    authority = InMemoryKnowledgeStore()
    authority.put(
        Scope(), "default", Document("doc", "question evidence", "review://doc"), expected_version=0
    )
    knowledge = CountedKnowledge(LexicalRetriever(authority))
    provider = ReviewProvider()
    store = ReceiptWindowStore(
        tmp_path / "received.db", trigger_event="model_response_recorded", trigger_mode="callback"
    )
    with LocalEngine(
        store,
        providers={"default": provider},
        tools=ToolRegistry(),
        memory_store=memory,
        recall_policy=MemoryRecallPolicy(),
        knowledge=knowledge,
    ) as engine:

        def change_sources(run_id):
            memory.put_fact(Scope(), "review", "fact", "NEW_CANARY", expected_version=1)
            authority.delete(Scope(), "default", "doc", expected_version=1)

        store.after_record = change_sources
        handle = engine.submit(AgentSpec("review", "Use evidence"), "question", command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded" and done.result == "done"
        assert len(provider.requests) == memory.recall_calls == knowledge.retrieval_calls == 1
        assert "ORIGINAL_CANARY" in str(provider.requests[0])
        assert done.actions[0]["received_response"]["output"] == "done"
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 1}


def test_source_expiry_during_later_source_validation_blocks_the_actual_model_request(
    tmp_path, monkeypatch
):
    from ralf_agent.retrieval import Document

    clock = {"now": 1000.0}
    monkeypatch.setattr("ralf_agent.retrieval.time.time", lambda: clock["now"])
    authority = InMemoryKnowledgeStore()
    authority.put(
        Scope(),
        "default",
        Document("a", "incident EXPIRED_SOURCE_CANARY", "review://a"),
        expected_version=0,
        expires_at=1001,
    )
    authority.put(
        Scope(),
        "default",
        Document("b", "incident supporting evidence", "review://b"),
        expected_version=0,
    )

    class SlowAuthority:
        backend_id = "review-two-source-authority"

        def __init__(self):
            self.last_source_reads = 0

        def lexical(self, *arguments):
            return authority.lexical(*arguments)

        async def get_chunk(self, scope, namespace, chunk_id):
            current = authority.get_chunk(scope, namespace, chunk_id)
            if current is not None and current.document_id == "b":
                self.last_source_reads += 1
                # First complete validation is current. During the final validation
                # source a expires while this later remote read is in flight.
                if self.last_source_reads == 2:
                    await asyncio.sleep(0)
                    clock["now"] = 1002.0
            return current

    provider = ReviewProvider()
    source = SlowAuthority()
    with LocalEngine(
        SQLiteStore(tmp_path / "source-ttl.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        knowledge=KnowledgeContext(LexicalRetriever(source)),
    ) as engine:
        handle = engine.submit(
            AgentSpec("review", "Use current sources"), "incident", command_id="s"
        )
        done = asyncio.run(engine.drive(handle.run_id))
        assert source.last_source_reads == 2
        assert provider.requests == []
        assert done.state == "failed" and done.error["code"] == "validation_error"
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}


def test_standalone_knowledge_validation_rejects_sources_expiring_during_later_reads(monkeypatch):
    from ralf_agent.errors import ValidationError
    from ralf_agent.retrieval import Document

    clock = {"now": 1000.0}
    monkeypatch.setattr("ralf_agent.retrieval.time.time", lambda: clock["now"])
    authority = InMemoryKnowledgeStore()
    authority.put(
        Scope(),
        "default",
        Document("a", "incident current source", "review://a"),
        expected_version=0,
        expires_at=1001,
    )
    authority.put(
        Scope(), "default", Document("b", "incident other source", "review://b"), expected_version=0
    )

    class SlowAuthority:
        backend_id = "review-source-validation"

        def lexical(self, *arguments):
            return authority.lexical(*arguments)

        async def get_chunk(self, scope, namespace, chunk_id):
            current = authority.get_chunk(scope, namespace, chunk_id)
            if current is not None and current.document_id == "b":
                await asyncio.sleep(0)
                clock["now"] = 1002.0
            return current

    context = KnowledgeContext(LexicalRetriever(SlowAuthority()))
    references = asyncio.run(context.references(Scope(), "incident"))
    assert [reference["value"]["document_id"] for reference in references] == ["a", "b"]
    with pytest.raises(ValidationError):
        asyncio.run(context.validate(Scope(), references))


@pytest.mark.parametrize("expires_during_validation", [False, True])
def test_custom_async_retriever_validation_cannot_bypass_facade_expiry(
    monkeypatch, expires_during_validation
):
    from ralf_agent.errors import ValidationError
    from ralf_agent.retrieval import Document

    clock = {"now": 1000.0}
    monkeypatch.setattr("ralf_agent.retrieval.time.time", lambda: clock["now"])
    authority = InMemoryKnowledgeStore()
    authority.put(
        Scope(),
        "default",
        Document("doc", "incident current source", "review://doc"),
        expected_version=0,
        expires_at=1001,
    )

    class CustomRetriever:
        identity = {"kind": "review-custom-validator", "version": "1"}
        validation_calls = 0

        async def retrieve(self, scope, namespace, query):
            return authority.lexical(scope, namespace, query)

        async def validate(self, scope, namespace, items):
            self.validation_calls += 1
            assert len(items) == 1 and items[0].expires_at == 1001
            await asyncio.sleep(0)
            clock["now"] = 1002.0 if expires_during_validation else 1000.5
            return None

    retriever = CustomRetriever()
    context = KnowledgeContext(retriever)
    references = asyncio.run(context.references(Scope(), "incident"))
    assert len(references) == 1
    if expires_during_validation:
        with pytest.raises(ValidationError, match="expired"):
            asyncio.run(context.validate(Scope(), references))
    else:
        assert asyncio.run(context.validate(Scope(), references)) is None
    assert retriever.validation_calls == 1


def test_multiple_pages_share_one_item_character_and_candidate_allowance(tmp_path):
    class MeteredMemory(InMemoryMemory):
        def __init__(self):
            super().__init__(backend_id="review-metered")
            self.queries = []

        def recall(self, scope, namespace, query):
            self.queries.append(query)
            return super().recall(scope, namespace, query)

    memory = MeteredMemory()
    for index in range(6):
        memory.put_fact(Scope(), "review", str(index), "oversize" * 2000, expected_version=0)
    for index in range(12):
        memory.put_fact(Scope(), "review", f"small-{index}", index, expected_version=0)
    query = RecallQuery(max_items=6, max_chars=1800, scan_limit=12)
    with LocalEngine(
        SQLiteStore(tmp_path / "quota.db"),
        providers={"default": ReviewProvider()},
        tools=ToolRegistry(),
        memory_store=memory,
        recall_policy=MemoryRecallPolicy(facts=query, max_pages=3),
    ) as engine:
        handle = engine.submit(AgentSpec("review", "Use evidence"), "question", command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded"
        assert len(memory.queries) == 3
        assert sum(page.scan_limit for page in memory.queries) <= 12
        assert sum(page.max_items for page in memory.queries) <= 6
        assert sum(page.max_chars for page in memory.queries) <= 1800
        manifest = done.actions[0]["context_manifest"]["memory_recall"]["facts"]
        assert (
            manifest["scanned"] <= 12 and manifest["used_chars"] <= 1800 and manifest["items"] <= 6
        )


@pytest.mark.parametrize("operation", ["read_page", "recall", "validate_facts"])
def test_delegated_async_method_cannot_hide_its_actual_backend_change(tmp_path, operation):
    from ralf_agent.errors import ValidationError

    async def scenario():
        class RemoteClient(InMemoryMemory):
            def __init__(self):
                super().__init__(backend_id="actual-client:v1")
                self.started, self.release = asyncio.Event(), asyncio.Event()

            async def wait_at(self, name):
                if operation == name:
                    self.started.set()
                    await self.release.wait()

            async def read_page(self, *arguments):
                await self.wait_at("read_page")
                return super().read_page(*arguments)

            async def recall(self, *arguments):
                await self.wait_at("recall")
                return super().recall(*arguments)

            async def validate_facts(self, scope, namespace, records):
                await self.wait_at("validate_facts")
                actual = {record["key"]: record for record in super().facts(scope, namespace)}
                if any(actual.get(record["key"]) != record for record in records):
                    raise ValidationError("Fact source changed")

        class DelegatingBackend:
            backend_id = "public-delegating-backend:v1"

            def __init__(self, client):
                self.client = client

            def __getattr__(self, name):
                return getattr(self.client, name)

        client = RemoteClient()
        client.put_fact(Scope(), "review", "fact", "owner-v1", expected_version=0)
        backend = DelegatingBackend(client)
        provider = ReviewProvider()
        with LocalEngine(
            SQLiteStore(tmp_path / "delegation.db"),
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=backend,
            memory_store=backend,
            recall_policy=MemoryRecallPolicy(),
        ) as engine:
            handle = engine.submit(AgentSpec("review", "Use evidence"), "question", command_id="s")
            driving = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(client.started.wait(), 2)
            client.backend_id = "actual-client:v2"
            client.release.set()
            done = await asyncio.wait_for(driving, 2)
            assert done.state == "failed" and done.error["code"] == "definition_mismatch"
            assert provider.requests == []
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}

    asyncio.run(scenario())
