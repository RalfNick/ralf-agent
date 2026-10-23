import asyncio
import json
import time
from dataclasses import replace

import pytest

from relf_agent import AliasQueryTransform, RecallQuery, Scope
from relf_agent.errors import DefinitionMismatch, ValidationError

from .semantic_fixture import Embedding, facts


def test_semantic_recall_finds_nonlexical_fact_and_preserves_raw_records():
    from relf_agent import SemanticMemoryStore

    async def run():
        backend = facts()
        memory = SemanticMemoryStore(backend, Embedding())
        raw = backend.inspect_fact(Scope(), "assistant", "b")
        result = await memory.recall(Scope(), "assistant", RecallQuery(text="vehicle", max_items=1))
        assert result.items == [raw] and result.scanned == 3 and result.next_cursor is None
        assert result.skipped == 2 and result.backend_bounded
        await memory.validate_facts(Scope(), "assistant", result.items)
        result.items[0]["value"] = "mutated"
        assert backend.inspect_fact(Scope(), "assistant", "b") == raw
        assert memory.inspect_fact(Scope(), "assistant", "b") == raw
        assert memory.put_fact(Scope(), "assistant", "new", "value", expected_version=0) == 1
        empty = await memory.recall(
            Scope("other", "user"), "assistant", RecallQuery(text="vehicle")
        )
        assert empty.items == []

    asyncio.run(run())


def test_candidate_window_clears_lexical_filter_and_obeys_scan_budget():
    from relf_agent import SemanticMemoryStore

    async def run():
        backend = facts()
        original = backend.recall

        def bounded(scope, namespace, query):
            assert query.text is None and query.scan_limit == 2 and query.max_items == 2
            return original(scope, namespace, query)

        backend.recall = bounded
        memory = SemanticMemoryStore(backend, Embedding())
        result = await memory.recall(
            Scope(), "assistant", RecallQuery(text="vehicle", max_items=1, scan_limit=2)
        )
        assert [i["key"] for i in result.items] == ["b"] and result.scanned == 2

    asyncio.run(run())


def test_transformed_queries_rank_by_best_cosine_and_min_score_is_explicit():
    from relf_agent import SemanticMemoryStore

    async def run():
        memory = SemanticMemoryStore(
            facts(), Embedding(), AliasQueryTransform({"transport": "vehicle"}), min_score=0.5
        )
        result = await memory.recall(Scope(), "assistant", RecallQuery(text="transport"))
        assert [i["key"] for i in result.items] == ["a", "b", "c"]
        strict = SemanticMemoryStore(facts(), Embedding(), min_score=0.5)
        result = await strict.recall(Scope(), "assistant", RecallQuery(text="vehicle"))
        assert [i["key"] for i in result.items] == ["b", "c"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "query",
    [
        RecallQuery(),
        RecallQuery(text=""),
        RecallQuery(text="\ud800"),
        RecallQuery(text="x" * 4097),
        RecallQuery(text="vehicle", cursor="cursor"),
    ],
)
def test_invalid_query_never_reads_or_embeds(query):
    from relf_agent import SemanticMemoryStore

    async def run():
        backend = facts()

        def forbidden(*args):
            raise AssertionError("Invalid query reached source")

        backend.recall = forbidden
        with pytest.raises(ValidationError):
            await SemanticMemoryStore(backend, Embedding()).recall(Scope(), "assistant", query)

    asyncio.run(run())


@pytest.mark.parametrize(
    "value", [[], [[1, 0]], [[True, 0]] * 4, [[0, 0]] * 4, [[float("nan"), 0]] * 4, [[1, 0, 0]] * 4]
)
def test_invalid_embedding_response_fails_without_lexical_fallback(value):
    from relf_agent import SemanticMemoryStore

    class Invalid(Embedding):
        async def embed(self, texts):
            return value

    async def run():
        with pytest.raises(ValidationError):
            await SemanticMemoryStore(facts(), Invalid()).recall(
                Scope(), "assistant", RecallQuery(text="vehicle")
            )

    asyncio.run(run())


@pytest.mark.parametrize("change", ["source", "expiry", "backend", "method", "embedding", "inputs"])
def test_changes_during_embedding_cannot_adopt_stale_or_incompatible_facts(change):
    from relf_agent import SemanticMemoryStore

    async def run():
        backend = facts()
        memory = None
        if change == "expiry":
            backend.put_fact(
                Scope(),
                "assistant",
                "b",
                "automobile servicing",
                expected_version=1,
                expires_at=time.time() + 0.02,
            )

        class Updating(Embedding):
            async def embed(self, texts):
                if change == "source":
                    backend.put_fact(Scope(), "assistant", "b", "changed", expected_version=1)
                elif change == "expiry":
                    await asyncio.sleep(0.04)
                elif change == "backend":
                    memory.backend = facts()
                elif change == "method":
                    backend.validate_facts = lambda *args: None
                elif change == "embedding":
                    memory.embedding = Embedding()
                else:
                    texts[0] = "maritime transport"
                return await super().embed(texts)

        memory = SemanticMemoryStore(backend, Updating())
        with pytest.raises((DefinitionMismatch, ValidationError)):
            await memory.recall(Scope(), "assistant", RecallQuery(text="vehicle"))

    asyncio.run(run())


def test_empty_and_oversized_candidates_do_not_call_embedding():
    from relf_agent import InMemoryMemory, SemanticMemoryStore

    class Forbidden(Embedding):
        async def embed(self, texts):
            raise AssertionError("Invalid or empty candidate request dispatched")

    async def run():
        memory = SemanticMemoryStore(InMemoryMemory(), Forbidden())
        result = await memory.recall(Scope(), "assistant", RecallQuery(text="vehicle"))
        assert result.items == []
        backend = facts()
        original = backend.recall

        def malformed(scope, namespace, query):
            page = original(scope, namespace, query)
            items = [*page.items, page.items[0]]
            return replace(
                page,
                items=items,
                used_chars=len(
                    json.dumps(items, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                ),
            )

        backend.recall = malformed
        with pytest.raises(ValidationError):
            await SemanticMemoryStore(backend, Forbidden()).recall(
                Scope(), "assistant", RecallQuery(text="vehicle")
            )

    asyncio.run(run())


def test_cancelled_semantic_recall_keeps_embedding_coroutine_owned_until_exit():
    from relf_agent import SemanticMemoryStore

    async def run():
        started, finished = asyncio.Event(), asyncio.Event()

        class Pending(Embedding):
            async def embed(self, texts):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finished.set()

        task = asyncio.create_task(
            SemanticMemoryStore(facts(), Pending()).recall(
                Scope(), "assistant", RecallQuery(text="vehicle")
            )
        )
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert finished.is_set()

    asyncio.run(run())


def test_native_async_source_and_input_volume_guards():
    from relf_agent import InMemoryMemory, SemanticMemoryStore

    async def run():
        backend = facts()

        class AsyncSource:
            backend_id = "async-source"

            async def recall(self, *args):
                await asyncio.sleep(0)
                return backend.recall(*args)

            async def validate_facts(self, *args):
                await asyncio.sleep(0)
                return backend.validate_facts(*args)

        result = await SemanticMemoryStore(AsyncSource(), Embedding()).recall(
            Scope(), "assistant", RecallQuery(text="vehicle", max_items=1)
        )
        assert result.items[0]["key"] == "b"

        class Forbidden(Embedding):
            dimensions = 65536

            async def embed(self, texts):
                raise AssertionError("Unbounded vector volume reached provider")

        crowded = InMemoryMemory()
        for i in range(61):
            crowded.put_fact(Scope(), "assistant", str(i), "small", expected_version=0)
        with pytest.raises(ValidationError, match="volume"):
            await SemanticMemoryStore(crowded, Forbidden()).recall(
                Scope(), "assistant", RecallQuery(text="vehicle")
            )
        oversized = InMemoryMemory()
        oversized.put_fact(Scope(), "assistant", "large", "x" * 33000, expected_version=0)
        with pytest.raises(ValidationError, match="volume"):
            await SemanticMemoryStore(oversized, Forbidden()).recall(
                Scope(), "assistant", RecallQuery(text="vehicle")
            )

    asyncio.run(run())


def test_cosine_roundoff_does_not_filter_default_opposite_candidate():
    from relf_agent import InMemoryMemory, SemanticMemoryStore

    class Opposite:
        dimensions = 3
        identity = {"kind": "opposite", "dimensions": 3}

        async def embed(self, texts):
            return [[1, 1, 1], [-1, -1, -1]]

    async def run():
        backend = InMemoryMemory()
        backend.put_fact(Scope(), "assistant", "opposite", "value", expected_version=0)
        page = await SemanticMemoryStore(backend, Opposite()).recall(
            Scope(), "assistant", RecallQuery(text="query")
        )
        assert len(page.items) == 1

    asyncio.run(run())


def test_cached_expired_candidate_is_rejected_even_if_custom_validator_accepts():
    from relf_agent import SemanticMemoryStore

    async def run():
        backend = facts()
        backend.put_fact(
            Scope(),
            "assistant",
            "b",
            "automobile servicing",
            expected_version=1,
            expires_at=time.time() + 0.02,
        )
        page = backend.recall(Scope(), "assistant", RecallQuery())
        backend.recall = lambda *args: page
        backend.validate_facts = lambda *args: None
        memory = SemanticMemoryStore(backend, Embedding())
        await asyncio.sleep(0.04)
        with pytest.raises(ValidationError):
            await memory.recall(Scope(), "assistant", RecallQuery(text="vehicle"))

    asyncio.run(run())
