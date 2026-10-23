import asyncio
import importlib
import importlib.util
from dataclasses import replace

import pytest

from relf_agent import Document, InMemoryKnowledgeStore, KnowledgeContext, Scope
from relf_agent.errors import DefinitionMismatch, MemoryBackendError, ValidationError
from relf_agent.retrieval import RetrievalQuery, _bounded_result, _retrieved


def api():
    assert importlib.util.find_spec("relf_agent.retrieval_pipeline"), "Missing composable retrieval"
    return importlib.import_module("relf_agent.retrieval_pipeline"), importlib.import_module(
        "relf_agent.retrieval_ranking"
    )


def docs():
    s = InMemoryKnowledgeStore()
    for name, text in [("a", "pool alpha"), ("b", "pool beta"), ("c", "gamma")]:
        s.put(
            Scope(), "docs", Document(name, text, source_uri="user://" + name), expected_version=0
        )
    return s


class Branch:
    identity = {"kind": "test-branch", "version": "1"}

    def __init__(self, store, names):
        self.store, self.names = store, names

    async def retrieve(self, scope, namespace, query):
        return _bounded_result(
            [_retrieved(self.store.chunks(scope, namespace, n)[0], 10**6) for n in self.names],
            query,
            "fixture",
        )

    async def validate(self, scope, namespace, items):
        pass


def test_rrf_literal_scores_and_custom_subset_reranker():
    p, r = api()
    values = r.RRFFusion(rank_constant=60).fuse(
        {"lexical": ("a", "b"), "vector": ("b", "c")}, limit=3
    )
    assert [v.chunk_id for v in values] == ["b", "a", "c"]
    assert [v.score for v in values] == pytest.approx([1 / 62 + 1 / 61, 1 / 61, 1 / 62])

    async def run():
        s = docs()

        class Reverse:
            identity = {"kind": "reverse", "version": "1"}

            def rerank(self, query, candidates, *, limit):
                return tuple(x.chunk_id for x in reversed(candidates))[:limit]

        h = p.HybridRetriever(
            s,
            {"lexical": Branch(s, ["a", "b"]), "vector": Branch(s, ["b", "c"])},
            reranker=Reverse(),
        )
        result = await h.retrieve(Scope(), "docs", RetrievalQuery("pool", limit=3))
        assert len(result.items) == 3 and result.mode == "hybrid:rrf"
        assert (
            result.items[-1].document_id == "b" and len(set(x.chunk_id for x in result.items)) == 3
        )
        await h.validate(Scope(), "docs", result.items)
        references = await KnowledgeContext(h, namespace="docs").references(Scope(), "pool")
        assert references and all(
            ref["_knowledge"]["scope"] == {"workspace": "default", "principal": "local-owner"}
            for ref in references
        )

    asyncio.run(run())


def test_branches_parallel_and_final_output_bounds():
    p, _ = api()

    async def run():
        s = docs()
        arrived = 0
        both = asyncio.Event()

        class Parallel(Branch):
            async def retrieve(self, *args):
                nonlocal arrived
                arrived += 1
                if arrived == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 2)
                return await super().retrieve(*args)

        h = p.HybridRetriever(s, {"a": Parallel(s, ["a", "b"]), "b": Parallel(s, ["b", "c"])})
        result = await h.retrieve(Scope(), "docs", RetrievalQuery("pool", limit=1, max_chars=1000))
        assert len(result.items) == 1 and result.used_chars <= 1000

    asyncio.run(run())


@pytest.mark.parametrize("damage", ["duplicate", "unknown", "generator", "awaitable", "wrongtype"])
def test_rerank_cannot_forge_or_return_lazy_candidates(damage):
    p, _ = api()

    async def run():
        s = docs()

        class Invalid:
            identity = {"kind": "invalid", "version": "1"}

            def rerank(self, query, candidates, *, limit):
                first = candidates[0].chunk_id
                if damage == "duplicate":
                    return (first, first)
                if damage == "unknown":
                    return ("fake",)
                if damage == "generator":
                    return iter((first,))
                if damage == "wrongtype":
                    return (candidates[0],)

                async def lazy():
                    return (first,)

                return lazy()

        h = p.HybridRetriever(s, {"a": Branch(s, ["a"])}, reranker=Invalid())
        with pytest.raises(ValidationError):
            await h.retrieve(Scope(), "docs", RetrievalQuery("pool"))

    asyncio.run(run())


def test_reranker_await_cannot_disclose_updated_or_deleted_source():
    p, _ = api()

    async def run():
        s = docs()

        class Update:
            identity = {"kind": "update", "version": "1"}

            async def rerank(self, query, candidates, *, limit):
                await asyncio.sleep(0)
                s.delete(Scope(), "docs", "a", expected_version=1)
                return tuple(c.chunk_id for c in candidates)

        h = p.HybridRetriever(s, {"a": Branch(s, ["a"])}, reranker=Update())
        with pytest.raises(ValidationError):
            await h.retrieve(Scope(), "docs", RetrievalQuery("pool"))

    asyncio.run(run())


@pytest.mark.parametrize("degrade", [False, True])
def test_failure_policy_explicit_and_missing_branch_visible(degrade):
    p, _ = api()

    async def run():
        s = docs()

        class Down(Branch):
            async def retrieve(self, *args):
                raise MemoryBackendError("private backend details")

        h = p.HybridRetriever(
            s,
            {"lexical": Branch(s, ["a"]), "vector": Down(s, [])},
            failure_policy="degrade" if degrade else "strict",
        )
        if degrade:
            result = await h.retrieve(Scope(), "docs", RetrievalQuery("pool"))
            assert len(result.items) == 1 and result.mode == "hybrid:rrf:degraded:vector"
        else:
            with pytest.raises(MemoryBackendError):
                await h.retrieve(Scope(), "docs", RetrievalQuery("pool"))

    asyncio.run(run())


def test_malformed_cross_scope_and_conflicting_evidence_never_degrade():
    p, _ = api()

    async def run():
        for mode in ["cross-scope", "conflict", "duplicate", "oversized"]:
            s = docs()

            class Invalid(Branch):
                async def retrieve(self, scope, namespace, query, mode=mode):
                    c = self.store.chunks(scope, namespace, "a")[0]
                    if mode == "cross-scope":
                        c = replace(c, scope=Scope("foreign", "owner"))
                    if mode == "conflict":
                        c = replace(c, text="tamper")
                    items = [_retrieved(c, 1)]
                    if mode == "duplicate":
                        items = items * 2
                    q = query if mode != "oversized" else RetrievalQuery(query.text, 1000, 1000000)
                    if mode == "oversized":
                        items = items * 100
                    return _bounded_result(items, q, "bad")

            h = p.HybridRetriever(
                s, {"good": Branch(s, ["a"]), "bad": Invalid(s, [])}, failure_policy="degrade"
            )
            with pytest.raises(ValidationError):
                await h.retrieve(Scope(), "docs", RetrievalQuery("pool"))

    asyncio.run(run())


def test_cancellation_drains_sibling_and_method_drift_rejected():
    p, _ = api()

    async def run():
        s = docs()
        started = asyncio.Event()
        stopped = asyncio.Event()

        class Waiting(Branch):
            async def retrieve(self, *args):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        h = p.HybridRetriever(s, {"a": Waiting(s, [])})
        task = asyncio.create_task(h.retrieve(Scope(), "docs", RetrievalQuery("pool")))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()

        class Drift(Branch):
            async def retrieve(self, *args):
                result = await super().retrieve(*args)
                self.retrieve = None
                return result

        with pytest.raises(DefinitionMismatch):
            await p.HybridRetriever(s, {"a": Drift(s, ["a"])}).retrieve(
                Scope(), "docs", RetrievalQuery("pool")
            )

    asyncio.run(run())


def test_fusion_drift_rejected_before_async_reranker_dispatch():
    p, r = api()

    async def run():
        s = docs()
        called = []

        class Ranker:
            identity = {"kind": "ranker", "version": "1"}

            async def rerank(self, query, candidates, *, limit):
                called.append(1)
                return tuple(c.chunk_id for c in candidates)

        ranker = Ranker()

        class Fusion:
            identity = {"kind": "fusion", "version": "1"}

            def fuse(self, rankings, *, limit):
                ranker.identity = {"kind": "ranker", "version": "2"}
                return r.RRFFusion().fuse(rankings, limit=limit)

        with pytest.raises(DefinitionMismatch):
            await p.HybridRetriever(
                s, {"lexical": Branch(s, ["a"])}, fusion=Fusion(), reranker=ranker
            ).retrieve(Scope(), "docs", RetrievalQuery("pool"))
        assert not called

    asyncio.run(run())


def test_pure_defaults_rerank_subset_and_fusion_input_validation():
    _, r = api()
    s = docs()
    candidates = tuple(_retrieved(s.chunks(Scope(), "docs", n)[0], 1) for n in ["c", "a", "b"])
    assert r.PreserveOrderReranker().rerank("alpha", candidates, limit=2) == tuple(
        c.chunk_id for c in candidates[:2]
    )
    assert r.TokenOverlapReranker().rerank("alpha", candidates, limit=1) == (
        candidates[1].chunk_id,
    )
    for rankings in [{"a": ("x", "x")}, {"a": iter(("x",))}]:
        with pytest.raises(ValidationError):
            r.RRFFusion().fuse(rankings, limit=2)
    with pytest.raises(ValidationError):
        r.RRFFusion(weights={"unknown": 2}).fuse({"a": ("x",)}, limit=1)


def test_rerank_list_is_frozen_before_final_authority_await():
    p, _ = api()

    async def run():
        ready = False
        order = []

        class Source(InMemoryKnowledgeStore):
            async def get_chunk(self, *args):
                await asyncio.sleep(0)
                if ready:
                    order[:] = [order[0], order[0]]
                return super().get_chunk(*args)

        source = Source()
        for name in ["a", "b"]:
            source.put(Scope(), "docs", Document(name, "pool " + name), expected_version=0)

        class Shared:
            identity = {"kind": "shared-order", "version": "1"}

            def rerank(self, query, candidates, *, limit):
                nonlocal ready
                order[:] = [c.chunk_id for c in candidates]
                ready = True
                return order

        result = await p.HybridRetriever(
            source, {"a": Branch(source, ["a", "b"])}, reranker=Shared()
        ).retrieve(Scope(), "docs", RetrievalQuery("pool"))
        assert len(result.items) == 2 and {c.document_id for c in result.items} == {"a", "b"}

    asyncio.run(run())


def test_expired_during_pure_fusion_never_reaches_external_reranker():
    p, r = api()
    import time

    async def run():
        source = InMemoryKnowledgeStore()
        called = []
        source.put(
            Scope(), "docs", Document("a", "pool"), expected_version=0, expires_at=time.time() + 0.3
        )

        class SlowFusion:
            identity = {"kind": "slow", "version": "1"}

            def fuse(self, rankings, *, limit):
                time.sleep(0.4)
                return r.RRFFusion().fuse(rankings, limit=limit)

        class External:
            identity = {"kind": "external", "version": "1"}

            async def rerank(self, query, candidates, *, limit):
                called.append(1)
                return tuple(c.chunk_id for c in candidates)

        with pytest.raises(ValidationError):
            await p.HybridRetriever(
                source, {"a": Branch(source, ["a"])}, fusion=SlowFusion(), reranker=External()
            ).retrieve(Scope(), "docs", RetrievalQuery("pool"))
        assert not called

    asyncio.run(run())
