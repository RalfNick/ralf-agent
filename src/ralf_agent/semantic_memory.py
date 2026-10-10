"""Bounded semantic ordering of authoritative Facts, without a second memory store."""

import copy
import json
import math
import time
from dataclasses import asdict

from .errors import DefinitionMismatch, ValidationError
from .query_transform import IdentityQueryTransform, query_proposal, query_text
from .recall import RecallPage, RecallQuery, _fact_inputs, _integer
from .retrieval import _scope, _text
from .retrieval_pipeline import _component, _invoke, _lazy
from .task_controls import _binding
from .tools import _callable_identity
from .types import canonical, digest
from .vector import _unit


class _FactsPort:
    def __init__(self, backend):
        self.backend = backend

    @property
    def identity(self):
        return {
            "backend_id": self.backend.backend_id,
            "fact_inspection_version": getattr(self.backend, "fact_inspection_version", None),
        }

    def __getattr__(self, name):
        return getattr(self.backend, name)


def _fact_text(record):
    value = record["value"]
    if isinstance(value, dict) and value.get("trust") == "completed-result-observation":
        value = {"key": value.get("key"), "value": value.get("value")}
    else:
        value = {"key": record["key"], "value": value}
    return canonical(value)


class SemanticMemoryStore:
    def __init__(
        self,
        backend,
        embedding,
        transform=None,
        *,
        max_candidates=256,
        max_candidate_chars=64000,
        min_score=-1,
    ):
        _text(getattr(backend, "backend_id", None), "Semantic Facts source identity")
        _integer(max_candidates, "Semantic candidate limit", 1, 256)
        _integer(max_candidate_chars, "Semantic candidate chars", 2, 262144)
        dimensions = getattr(embedding, "dimensions", None)
        _integer(dimensions, "Semantic embedding dimensions", 1, 65536)
        if (
            type(min_score) not in (int, float)
            or not -1 <= min_score <= 1
            or not math.isfinite(min_score)
        ):
            raise ValidationError("Semantic threshold must be finite in[-1,1]")
        self.backend, self.embedding = backend, embedding
        self.transform = IdentityQueryTransform() if transform is None else transform
        self._source = _FactsPort(backend)
        methods = ["recall", "validate_facts"]
        methods.extend(
            name
            for name in ("facts", "put_fact", "inspect_fact")
            if callable(getattr(backend, name, None))
        )
        self._ports = {
            "source": _component(self._source, methods),
            "embedding": _component(embedding, ["embed"]),
            "transform": _component(self.transform, ["transform"]),
        }
        self._hooks = {
            name: _binding(getattr(self, name))
            for name in ("recall", "validate_facts", "_check", "__getattr__", "_expiry")
        }
        self._config_json = canonical(
            dict(
                kind="semantic-facts-recall",
                version="1",
                dimensions=dimensions,
                max_candidates=max_candidates,
                max_candidate_chars=max_candidate_chars,
                min_score=float(min_score),
                candidate_policy="bounded-native-window-v1",
                components={k: v[1] for k, v in self._ports.items()},
                implementation={
                    k: digest(_callable_identity(getattr(self, k))) for k in self._hooks
                },
            )
        )
        self._config_pin = self._config_json

    def _check(self):
        if (
            self._config_json != self._config_pin
            or self.backend is not self._source.backend
            or any(
                _binding(getattr(self, name)) != original for name, original in self._hooks.items()
            )
        ):
            raise DefinitionMismatch(
                "Semantic Facts configuration, source or implementation changed"
            )
        for name, (obj, identity, bindings) in self._ports.items():
            current = self._source if name == "source" else getattr(self, name)
            if (
                current is not obj
                or any(
                    _binding(getattr(obj, method, None)) != original
                    for method, original, _ in bindings
                )
                or digest(_component(obj, [m for m, _, _ in bindings])[1]) != digest(identity)
            ):
                raise DefinitionMismatch("Semantic Facts component registration changed")
        if self.embedding.dimensions != json.loads(self._config_json)["dimensions"]:
            raise DefinitionMismatch("Semantic embedding dimensions changed")

    @property
    def identity(self):
        self._check()
        return json.loads(self._config_json)

    @property
    def backend_id(self):
        return "semantic-facts:" + digest(self.identity)

    def __getattr__(self, name):
        if name in {"facts", "put_fact", "inspect_fact", "fact_inspection_version"}:
            self._check()
            return getattr(self.backend, name)
        raise AttributeError(name)

    async def validate_facts(self, scope, namespace, items):
        self._check()
        values = _fact_inputs(scope, namespace, items)
        self._expiry(values)
        original = digest(values)
        result = await _invoke(self._ports["source"], "validate_facts", scope, namespace, values)
        self._check()
        self._expiry(values)
        if result is not None or digest(values) != original:
            _lazy(result)
            raise ValidationError("Facts validator must complete without changing evidence")

    @staticmethod
    def _expiry(items):
        now = time.time()
        if any(item["expires_at"] is not None and item["expires_at"] <= now for item in items):
            raise ValidationError("Semantic Facts source has expired")

    async def recall(self, scope, namespace, query):
        _scope(scope, namespace)
        if not isinstance(query, RecallQuery) or query.cursor is not None:
            raise ValidationError(
                "Semantic recall requires a single candidate window, without cursor"
            )
        query = RecallQuery(**asdict(query))
        query_text(query.text)
        config = self.identity
        limit = min(query.scan_limit, config["max_candidates"])
        page = await _invoke(
            self._ports["source"],
            "recall",
            scope,
            namespace,
            RecallQuery(max_items=limit, scan_limit=limit, max_chars=config["max_candidate_chars"]),
        )
        self._check()
        if not isinstance(page, RecallPage):
            _lazy(page)
            raise ValidationError("Semantic source must return completed RecallPage")
        page = RecallPage(**asdict(page))
        if (
            len(page.items) > limit
            or page.scanned > limit
            or page.used_chars > config["max_candidate_chars"]
            or not page.backend_bounded
        ):
            raise ValidationError("Semantic source exceeded native candidate bounds")
        items = _fact_inputs(scope, namespace, page.items)
        await self.validate_facts(scope, namespace, items)
        if not items:
            return RecallPage([], None, 2, page.scanned, page.scanned, page.snapshot_id, True)
        queries = query_proposal(await _invoke(self._ports["transform"], "transform", query.text))
        self._check()
        texts = [*queries, *(_fact_text(item) for item in items)]
        if (
            len(texts) * config["dimensions"] > 4000000
            or sum(map(len, texts)) > 262144
            or any(len(t) > 32768 for t in texts)
        ):
            raise ValidationError("Semantic embedding input exceeds finite volume bounds")
        try:
            for text in texts:
                text.encode("utf-8")
        except UnicodeError:
            raise ValidationError("Semantic input requires valid Unicode scalars") from None
        await self.validate_facts(scope, namespace, items)
        original = digest(texts)
        vectors = await _invoke(self._ports["embedding"], "embed", texts)
        self._check()
        if (
            digest(texts) != original
            or not isinstance(vectors, (list, tuple))
            or len(vectors) != len(texts)
        ):
            _lazy(vectors)
            raise ValidationError("Semantic embedding changed inputs or returned wrong count")
        units = [_unit(v, config["dimensions"]) for v in vectors]
        await self.validate_facts(scope, namespace, items)
        query_units = units[: len(queries)]
        scores = [
            max(
                max(-1.0, min(1.0, sum(a * b for a, b in zip(q, v, strict=True))))
                for q in query_units
            )
            for v in units[len(queries) :]
        ]
        selected = []
        for index in sorted(range(len(items)), key=lambda i: (-scores[i], i)):
            if scores[index] < config["min_score"]:
                continue
            if len(selected) >= query.max_items:
                break
            if len(canonical([*selected, items[index]])) <= query.max_chars:
                selected.append(copy.deepcopy(items[index]))
        self._expiry(selected)
        snapshot = canonical(
            {
                "source": page.snapshot_id,
                "query": digest(query.text),
                "release": digest(config),
                "candidates": digest(items),
            }
        )
        return RecallPage(
            selected,
            None,
            len(canonical(selected)),
            page.scanned,
            page.scanned - len(selected),
            snapshot,
            True,
        )
