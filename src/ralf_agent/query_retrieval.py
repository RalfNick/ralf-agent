"""Borrowed bounded query expansion over the original Retriever source authority."""

import copy
import json
from dataclasses import asdict

from .errors import DefinitionMismatch, ValidationError
from .query_transform import IdentityQueryTransform, query_proposal, query_text
from .retrieval import (
    Chunk,
    LexicalRetriever,
    RetrievalQuery,
    RetrievedChunk,
    _bounded_result,
    _integer,
    _items_chars,
    _scope,
    _validate_expiry,
    _validate_result,
)
from .retrieval_pipeline import HybridRetriever, _body, _component, _invoke, _lazy
from .skill_retrieval import SkillDirectoryRetriever
from .task_controls import _binding
from .tools import _callable_identity
from .types import canonical, digest
from .vector import VectorRetriever


def _native_resources(retriever):
    """Pin public native composition edges; custom ports own their internals."""
    resources = []

    def add(path, obj, methods):
        if len(resources) >= 128:
            raise ValidationError("Query native composition exceeds resource bounds")
        resources.append((path, obj, tuple((m, _binding(getattr(obj, m, None))) for m in methods)))

    def visit(path, obj, ancestors):
        if id(obj) in ancestors or len(ancestors) >= 16:
            raise ValidationError("Query native composition is cyclic or too deep")
        add(path, obj, ("retrieve", "validate"))
        ancestors = (*ancestors, id(obj))
        if isinstance(obj, LexicalRetriever):
            add(path + ".store", obj.store, ("lexical", "get_chunk"))
        elif isinstance(obj, SkillDirectoryRetriever):
            add(path + ".catalog", obj.catalog, ("list", "get"))
            add(path + ".selector", obj.selector, ("select",))
        elif isinstance(obj, VectorRetriever):
            add(path + ".store", obj.store, ("get", "get_chunk", "chunks"))
            add(path + ".index", obj.index, ("search", "upsert", "delete_document"))
            add(path + ".embedding", obj.embedding, ("embed",))
        elif isinstance(obj, HybridRetriever):
            add(path + ".store", obj.store, ("get_chunk",))
            add(path + ".fusion", obj.fusion, ("fuse",))
            add(path + ".reranker", obj.reranker, ("rerank",))
            for key in sorted(obj.retrievers):
                visit(path + ".branches." + key, obj.retrievers[key], ancestors)
        elif isinstance(obj, QueryTransformRetriever):
            add(path + ".transform", obj.transform, ("transform",))
            visit(path + ".retriever", obj.retriever, ancestors)

    visit("retriever", retriever, ())
    return tuple(resources)


class QueryTransformRetriever:
    def __init__(self, retriever, transform=None, *, max_candidates=128, max_candidate_chars=64000):
        _integer(max_candidates, "Query candidate limit", minimum=4)
        _integer(max_candidate_chars, "Query candidate character limit", minimum=8)
        if max_candidates > 256 or max_candidate_chars > 262144:
            raise ValidationError("Query retrieval exceeds finite candidate bounds")
        self.retriever = retriever
        self.transform = IdentityQueryTransform() if transform is None else transform
        self._ports = {
            "retriever": _component(self.retriever, ["retrieve", "validate"]),
            "transform": _component(self.transform, ["transform"]),
        }
        self._resources = _native_resources(self.retriever)
        self._hooks = {
            name: _binding(getattr(self, name)) for name in ("retrieve", "validate", "_check")
        }
        self._config_json = canonical(
            dict(
                kind="query-transform-retriever",
                version="1",
                max_candidates=max_candidates,
                max_candidate_chars=max_candidate_chars,
                components={k: v[1] for k, v in self._ports.items()},
                implementation={
                    **{k: digest(_callable_identity(getattr(self, k))) for k in self._hooks},
                    "native_resources": digest(_callable_identity(_native_resources)),
                },
            )
        )
        self._config_pin = self._config_json

    def _check(self):
        if self._config_json != self._config_pin or any(
            _binding(getattr(self, name)) != original for name, original in self._hooks.items()
        ):
            raise DefinitionMismatch("Query retrieval configuration or implementation changed")
        current = _native_resources(self.retriever)
        if len(current) != len(self._resources) or any(
            path != old_path or obj is not old_obj or bindings != old_bindings
            for (path, obj, bindings), (old_path, old_obj, old_bindings) in zip(
                current, self._resources, strict=True
            )
        ):
            raise DefinitionMismatch("Query native retrieval resource or method changed")
        for name, captured in self._ports.items():
            obj, identity, bindings = captured
            if (
                getattr(self, name) is not obj
                or any(
                    _binding(getattr(obj, method, None)) != original
                    for method, original, _ in bindings
                )
                or digest(_component(obj, [m for m, _, _ in bindings])[1]) != digest(identity)
            ):
                raise DefinitionMismatch("Query retrieval source or transform changed")

    @property
    def identity(self):
        self._check()
        return json.loads(self._config_json)

    async def retrieve(self, scope, namespace, query):
        _scope(scope, namespace)
        if not isinstance(query, RetrievalQuery):
            raise ValidationError("Query retrieval requires RetrievalQuery")
        query_text(query.text)
        config = self.identity
        queries = query_proposal(await _invoke(self._ports["transform"], "transform", query.text))
        self._check()
        items = {}
        for text in queries:
            if items:
                await self.validate(scope, namespace, tuple(items.values()))
            self._check()
            child_query = RetrievalQuery(
                text,
                config["max_candidates"] // len(queries),
                config["max_candidate_chars"] // len(queries),
            )
            result = await _invoke(
                self._ports["retriever"], "retrieve", scope, namespace, child_query
            )
            self._check()
            result = _validate_result(result, scope, namespace, child_query)
            if len({c.chunk_id for c in result.items}) != len(result.items):
                raise ValidationError("Query source repeated candidates")
            for item in result.items:
                if item.chunk_id in items and _body(items[item.chunk_id]) != _body(item):
                    raise ValidationError("Query expansion returned conflicting source bodies")
                items.setdefault(item.chunk_id, copy.deepcopy(item))
            await self.validate(scope, namespace, tuple(items.values()))
        return _bounded_result(list(items.values()), query, "query-transform:" + str(len(queries)))

    async def validate(self, scope, namespace, items):
        _scope(scope, namespace)
        config = self.identity
        if not isinstance(items, (list, tuple)) or len(items) > config["max_candidates"]:
            raise ValidationError("Query source snapshot exceeded item bounds")
        if (
            any(
                not isinstance(item, (Chunk, RetrievedChunk))
                or item.scope != scope
                or item.namespace != namespace
                for item in items
            )
            or _items_chars(items) > config["max_candidate_chars"]
        ):
            raise ValidationError("Query source snapshot is invalid or exceeds source bounds")
        # A wrapped retriever may bound its validation batches below our union.
        items = copy.deepcopy(tuple(items))
        _validate_expiry(items)
        for item in items:
            evidence = (copy.deepcopy(item),)
            original = digest([asdict(v) for v in evidence])
            result = await _invoke(self._ports["retriever"], "validate", scope, namespace, evidence)
            self._check()
            if result is not None or digest([asdict(v) for v in evidence]) != original:
                _lazy(result)
                raise ValidationError(
                    "Query source validator must complete without changing evidence"
                )
        _validate_expiry(items)
