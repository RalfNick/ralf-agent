"""Borrowed parallel retrieval with bounded proposals and one source authority."""

import asyncio
import copy
import inspect
import re
from dataclasses import asdict

from .errors import DefinitionMismatch, MemoryBackendError, ProviderError, ValidationError
from .ports import is_async_callable, is_sync_callable
from .retrieval import (
    RetrievalQuery,
    _bounded_result,
    _check_method_bindings,
    _component_identity,
    _integer,
    _items_chars,
    _method_bindings,
    _retrieved,
    _scope,
    _store_identity,
    _validate_chunks,
    _validate_result,
)
from .retrieval_ranking import FusionRank, PreserveOrderReranker, RRFFusion
from .task_controls import _binding
from .tools import _callable_identity
from .types import digest


def _component(component, methods):
    identity = _component_identity(component)
    bindings = []
    for name in methods:
        method = getattr(component, name, None)
        mode = (
            "async" if is_async_callable(method) else "sync" if is_sync_callable(method) else None
        )
        if mode is None:
            raise ValidationError("Retrieval component requires completed sync/async port")
        bindings.append((name, _binding(method), mode))
        identity[name + "_implementation"] = digest(_callable_identity(method))
    return component, identity, bindings


def _lazy(value):
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()


async def _invoke(captured, name, *args, **kwargs):
    obj, _, bindings = captured
    mode = next(mode for method, _, mode in bindings if method == name)
    try:
        result = getattr(obj, name)(*args, **kwargs)
        if mode == "async":
            if not inspect.isawaitable(result):
                _lazy(result)
                raise ValidationError("Async retrieval port must return awaitable")
            result = await result
        elif inspect.isawaitable(result):
            _lazy(result)
            raise ValidationError("Sync retrieval port returned unexpected awaitable")
        return result
    except (DefinitionMismatch, MemoryBackendError, ProviderError, ValidationError):
        raise
    except Exception:
        raise MemoryBackendError("Retrieval component operation failed") from None


class HybridRetriever:
    def __init__(
        self,
        store,
        retrievers,
        *,
        fusion=None,
        reranker=None,
        branch_limit=10,
        candidate_limit=32,
        max_candidate_chars=64000,
        failure_policy="strict",
    ):
        if (
            not isinstance(retrievers, dict)
            or not 1 <= len(retrievers) <= 8
            or any(
                not isinstance(k, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", k)
                for k in retrievers
            )
        ):
            raise ValidationError("Register 1..8 named retrieval branches")
        for name, value in [("Branch", branch_limit), ("Candidate", candidate_limit)]:
            _integer(value, name + " limit", minimum=1)
            if value > 256:
                raise ValidationError(name + " limit exceeds256")
        _integer(max_candidate_chars, "Candidate character bound", minimum=2)
        if max_candidate_chars > 1024 * 1024 or branch_limit * len(retrievers) > candidate_limit:
            raise ValidationError("Branches exceed total candidate capacity")
        if failure_policy not in {"strict", "degrade"}:
            raise ValidationError("Unknown retrieval failure policy")
        _store_identity(store)
        _component(store_with_identity(store), ["get_chunk"])
        self._store_bindings = _method_bindings(store, ("get_chunk",))
        for branch in retrievers.values():
            _component(branch, ["retrieve", "validate"])
        fusion = RRFFusion() if fusion is None else fusion
        reranker = PreserveOrderReranker() if reranker is None else reranker
        if not is_sync_callable(getattr(fusion, "fuse", None)):
            raise ValidationError("RankFusion must be synchronous")
        _component(fusion, ["fuse"])
        _component(reranker, ["rerank"])
        self.store, self.retrievers, self.fusion, self.reranker = (
            store,
            dict(retrievers),
            fusion,
            reranker,
        )
        self.branch_limit, self.candidate_limit, self.max_candidate_chars, self.failure_policy = (
            branch_limit,
            candidate_limit,
            max_candidate_chars,
            failure_policy,
        )

    @property
    def identity(self):
        return {
            "kind": "hybrid-retriever",
            "version": "1",
            "store": _store_identity(self.store),
            "branches": {
                k: _component(v, ["retrieve", "validate"])[1] for k, v in self.retrievers.items()
            },
            "fusion": _component(self.fusion, ["fuse"])[1],
            "reranker": _component(self.reranker, ["rerank"])[1],
            "branch_limit": self.branch_limit,
            "candidate_limit": self.candidate_limit,
            "max_candidate_chars": self.max_candidate_chars,
            "failure_policy": self.failure_policy,
        }

    def _capture(self):
        store = self.store
        _check_method_bindings(store, self._store_bindings)
        source_binding = _binding(store.get_chunk)
        values = {k: _component(v, ["retrieve", "validate"]) for k, v in self.retrievers.items()}
        return (
            store,
            source_binding,
            values,
            _component(self.fusion, ["fuse"]),
            _component(self.reranker, ["rerank"]),
            copy.deepcopy(self.identity),
        )

    def _check(self, captured):
        store, binding, branches, fusion, reranker, identity = captured
        _check_method_bindings(store, self._store_bindings)
        try:
            if (
                self.store is not store
                or not callable(getattr(store, "get_chunk", None))
                or _binding(store.get_chunk) != binding
                or set(self.retrievers) != set(branches)
                or self.fusion is not fusion[0]
                or self.reranker is not reranker[0]
            ):
                raise DefinitionMismatch("Retrieval registration changed")
            for name, value in branches.items():
                if self.retrievers[name] is not value[0]:
                    raise DefinitionMismatch("Retrieval branch replaced")
            all_components = [*branches.values(), fusion, reranker]
            for obj, _, bindings in all_components:
                if any(
                    not callable(getattr(obj, name, None)) or _binding(getattr(obj, name)) != entry
                    for name, entry, _ in bindings
                ):
                    raise DefinitionMismatch("Retrieval method changed")
            if digest(self.identity) != digest(identity):
                raise DefinitionMismatch("Retrieval configuration changed")
        except ValidationError:
            raise DefinitionMismatch("Retrieval component is no longer valid") from None

    async def retrieve(self, scope, namespace, query):
        _scope(scope, namespace)
        if not isinstance(query, RetrievalQuery) or len(query.text) > 32768:
            raise ValidationError("Hybrid retrieval requires bounded RetrievalQuery")
        query = RetrievalQuery(query.text, query.limit, query.max_chars)
        captured = self._capture()
        self._check(captured)
        store, _, branches, fusion, reranker, configuration = captured
        branch_query = RetrievalQuery(
            query.text, self.branch_limit, max(2, self.max_candidate_chars // len(branches))
        )
        missing = []

        async def retrieve(name, branch):
            try:
                result = await _invoke(
                    branch, "retrieve", scope, namespace, copy.deepcopy(branch_query)
                )
                self._check(captured)
                result = _validate_result(result, scope, namespace, branch_query)
                if len(set(c.chunk_id for c in result.items)) != len(result.items):
                    raise ValidationError("Duplicate branch candidates")
                return result
            except (MemoryBackendError, ProviderError):
                if configuration["failure_policy"] == "strict":
                    raise
                missing.append(name)
                return None

        try:
            async with asyncio.TaskGroup() as group:
                tasks = {
                    name: group.create_task(retrieve(name, value))
                    for name, value in branches.items()
                }
        except ExceptionGroup as errors:
            error = errors.exceptions[0]
            while isinstance(error, ExceptionGroup):
                error = error.exceptions[0]
            raise error from None
        self._check(captured)
        if len(missing) == len(branches):
            raise MemoryBackendError("All retrieval branches failed")
        rankings, items = {}, {}
        for name, task in tasks.items():
            result = task.result()
            rankings[name] = tuple(c.chunk_id for c in result.items) if result else ()
            for c in () if result is None else result.items:
                if c.chunk_id in items and _body(items[c.chunk_id]) != _body(c):
                    raise ValidationError("Conflicting candidate provenance")
                items[c.chunk_id] = copy.deepcopy(c)
        await _validate_chunks(
            store, scope, namespace, tuple(items.values()), check=lambda: self._check(captured)
        )
        self._check(captured)
        fused = await _invoke(fusion, "fuse", copy.deepcopy(rankings), limit=self.candidate_limit)
        self._check(captured)
        if (
            not isinstance(fused, (tuple, list))
            or len(fused) > self.candidate_limit
            or any(not isinstance(v, FusionRank) for v in fused)
        ):
            _lazy(fused)
            raise ValidationError("Fusion returned invalid completed ranks")
        fused = tuple(FusionRank(v.chunk_id, v.score) for v in fused)
        if len(set(v.chunk_id for v in fused)) != len(fused) or any(
            v.chunk_id not in items for v in fused
        ):
            raise ValidationError("Fusion forged or repeated candidate")
        selected = _bounded_result(
            [_retrieved(items[v.chunk_id], v.score) for v in fused],
            RetrievalQuery(query.text, self.candidate_limit, self.max_candidate_chars),
            "fusion",
        ).items
        # Pure ranking can still outlive a source's TTL. Confirm source bodies
        # immediately before dispatching a potentially remote reranker.
        await _validate_chunks(
            store, scope, namespace, tuple(items.values()), check=lambda: self._check(captured)
        )
        self._check(captured)
        order = await _invoke(
            reranker,
            "rerank",
            query.text,
            copy.deepcopy(selected),
            limit=min(query.limit, self.candidate_limit),
        )
        self._check(captured)
        if (
            not isinstance(order, (tuple, list))
            or len(order) > min(query.limit, self.candidate_limit)
            or any(not isinstance(k, str) for k in order)
        ):
            _lazy(order)
            raise ValidationError("Reranker must return completed candidate IDs")
        order = tuple(order)
        candidates = {c.chunk_id: c for c in selected}
        if len(set(order)) != len(order) or any(k not in candidates for k in order):
            raise ValidationError("Reranker forged or repeated candidate")
        await _validate_chunks(
            store, scope, namespace, tuple(items.values()), check=lambda: self._check(captured)
        )
        self._check(captured)
        kind = "rrf" if isinstance(self.fusion, RRFFusion) else "fusion"
        mode = "hybrid:" + kind + (":degraded:" + ",".join(sorted(missing)) if missing else "")
        return _bounded_result([candidates[k] for k in order], query, mode)

    async def validate(self, scope, namespace, items):
        _scope(scope, namespace)
        if (
            not isinstance(items, (tuple, list))
            or len(items) > self.candidate_limit
            or _items_chars(items) > self.max_candidate_chars
        ):
            raise ValidationError("Invalid retrieval snapshot")
        captured = self._capture()
        self._check(captured)
        await _validate_chunks(
            captured[0],
            scope,
            namespace,
            copy.deepcopy(tuple(items)),
            check=lambda: self._check(captured),
        )
        self._check(captured)


def _body(chunk):
    value = asdict(chunk)
    value.pop("score", None)
    return value


def store_with_identity(store):
    # Constructor validation only; preserve the actual source read binding.
    if not callable(getattr(store, "get_chunk", None)):
        raise ValidationError("Hybrid requires authoritative get_chunk")

    class Source:
        identity = _store_identity(store)
        get_chunk = staticmethod(store.get_chunk)

    return Source()
