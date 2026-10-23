"""Explicit, resumable full-corpus Facts indexing and authority-checked recall."""

import copy
import math
import time
from dataclasses import asdict

from .errors import BudgetExceeded, DefinitionMismatch, ValidationError
from .fact_index_ports import _FixedPorts
from .fact_scan import FactScanPage, FactScanQuery
from .query_transform import query_text
from .recall import (
    RecallPage,
    RecallQuery,
    _fact_inputs,
    _fact_records,
    _integer,
    _name,
    _validate_cursor,
)
from .retrieval_pipeline import _lazy
from .semantic_memory import _fact_text
from .task_controls import _binding
from .tools import _callable_identity
from .types import canonical, digest
from .vector import VectorEntry, VectorHit, _unit


class IndexedMemoryStore:
    def __init__(
        self,
        backend,
        embedding,
        index,
        catalog,
        *,
        batch_size=32,
        max_page_bytes=64000,
        min_score=-1,
        max_records=100000,
    ):
        if (
            type(getattr(backend, "fact_scan_version", None)) is not int
            or backend.fact_scan_version != 1
        ):
            raise ValidationError("Index source requires native bounded Fact scanning")
        _integer(batch_size, "Index batch size", 1, 128)
        _integer(max_page_bytes, "Index source page bytes", 2, 64000)
        _integer(max_records, "Index total record allowance", 1, 100000)
        dims = getattr(embedding, "dimensions", None)
        _integer(dims, "Index embedding dimensions", 1, 32768)
        if type(index.dimensions) is not int or index.dimensions != dims:
            raise ValidationError("Index and embedding dimensions differ")
        if (
            type(min_score) not in (int, float)
            or not math.isfinite(min_score)
            or not -1 <= min_score <= 1
        ):
            raise ValidationError("Index threshold must be finite in[-1,1]")
        self.backend, self.embedding, self.index, self.catalog = backend, embedding, index, catalog
        self._fixed = _FixedPorts(
            {
                "source": (
                    backend,
                    ["scan_facts", "fact_snapshot", "inspect_fact", "validate_facts"],
                    True,
                ),
                "embedding": (embedding, ["embed"], False),
                "vector": (index, ["upsert", "search"], True),
                "catalog": (catalog, ["load", "save"], False),
            }
        )
        self._hooks = {
            name: _binding(getattr(self, name))
            for name in (
                "rebuild",
                "recall",
                "validate_facts",
                "_state",
                "_load",
                "_save",
                "_active",
                "_activate",
                "_current",
                "_snapshot",
                "_address",
                "_validate_raw",
                "__getattr__",
            )
        }
        self._config = dict(
            kind="indexed-facts-recall",
            version="1",
            batch_size=min(batch_size, 32768 // dims),
            max_page_bytes=max_page_bytes,
            dimensions=dims,
            min_score=float(min_score),
            max_records=max_records,
            components=self._fixed.identity,
            implementation={
                name: digest(_callable_identity(getattr(self, name))) for name in self._hooks
            },
        )
        self._config_pin = canonical(self._config)

    @property
    def identity(self):
        if (
            canonical(self._config) != self._config_pin
            or any(
                _binding(getattr(self, name)) != original for name, original in self._hooks.items()
            )
            or any(
                getattr(self, {"source": "backend", "vector": "index"}.get(name, name))
                is not backend
                for name, (backend, _) in self._fixed._ports.items()
            )
        ):
            raise DefinitionMismatch("Facts index composition changed")
        self._fixed.check()
        return copy.deepcopy(self._config)

    @property
    def backend_id(self):
        return "indexed-facts:" + digest(self.identity)

    def __getattr__(self, name):
        if name in {"facts", "put_fact", "inspect_fact", "fact_inspection_version"}:
            _ = self.identity
            return getattr(self.backend, name)
        raise AttributeError(name)

    def _address(self, scope, namespace):
        _fact_inputs(scope, namespace, [])
        return digest({"definition": self.identity, "scope": asdict(scope), "namespace": namespace})

    async def _snapshot(self, scope, namespace):
        _ = self.identity
        value = await self._fixed.call("source", "fact_snapshot", scope, namespace)
        _ = self.identity
        _name(value, "Index source snapshot")
        return value

    async def _current(self, scope, namespace, snapshot):
        if await self._snapshot(scope, namespace) != snapshot:
            raise ValidationError("Facts index source snapshot changed; rebuild required")

    async def _save(self, scope, address, state, revision):
        self._state(state, address)
        result = await self._fixed.call(
            "catalog", "save", scope, address, "build", state, expected_version=revision
        )
        if type(result) is not int or result != revision + 1:
            _lazy(result)
            raise ValidationError("Invalid catalog commit receipt")
        return result

    async def _load(self, scope, address, key):
        result = await self._fixed.call("catalog", "load", scope, address, key)
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or type(result[0]) is not int
            or result[0] < 0
            or (result[1] is not None and not isinstance(result[1], dict))
        ):
            _lazy(result)
            raise ValidationError("Catalog load requires a completed revision/state pair")
        return result

    def _state(self, state, address):
        fields = {
            "schema_version",
            "definition",
            "build_id",
            "source_snapshot",
            "status",
            "phase",
            "cursor",
            "scanned",
            "indexed",
            "expired",
        }
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("phase"), str)
            or state.get("phase") not in {"scan", "embedded"}
            or set(state) != fields | ({"pending"} if state.get("phase") == "embedded" else set())
            or state.get("schema_version") != 1
            or type(state["schema_version"]) is not int
            or not isinstance(state.get("status"), str)
            or state.get("status") not in {"building", "ready"}
        ):
            raise ValidationError("Invalid index state receipt")
        _name(state["source_snapshot"], "Index state snapshot")
        _validate_cursor(state["cursor"])
        for name in ("scanned", "indexed", "expired"):
            _integer(state[name], "Index state " + name, 0, self._config["max_records"])
        if (
            state["definition"] != address
            or state["build_id"] != digest([address, state["source_snapshot"]])
            or state["scanned"] != state["indexed"] + state["expired"]
            or (
                state["status"] == "ready"
                and (state["phase"] != "scan" or state["cursor"] is not None)
            )
        ):
            raise ValidationError("Index receipt does not prove complete publication")
        if state["phase"] == "embedded":
            pending = state["pending"]
            if not isinstance(pending, dict) or set(pending) != {
                "items",
                "vectors",
                "scanned",
                "expired",
                "next_cursor",
            }:
                raise ValidationError("Invalid accepted index response")
            items = _fact_records(pending["items"])
            _integer(pending["scanned"], "Index pending count", 0, self._config["batch_size"])
            _integer(pending["expired"], "Index pending expired", 0, pending["scanned"])
            _validate_cursor(pending["next_cursor"])
            if (
                len(items) + pending["expired"] != pending["scanned"]
                or not isinstance(pending["vectors"], list)
                or len(pending["vectors"]) != len(items)
            ):
                raise ValidationError("Index accepted response has invalid coverage")
            for vector in pending["vectors"]:
                _unit(vector, self._config["dimensions"])
        return copy.deepcopy(state)

    async def rebuild(self, scope, namespace, *, max_pages=64):
        _integer(max_pages, "Index rebuild page allowance", 1, 256)
        address = self._address(scope, namespace)
        snapshot = await self._snapshot(scope, namespace)
        revision, state = await self._load(scope, address, "build")
        if state is not None:
            state = self._state(state, address)
        if state is None or state["source_snapshot"] != snapshot:
            state = {
                "schema_version": 1,
                "definition": address,
                "build_id": digest([address, snapshot]),
                "source_snapshot": snapshot,
                "status": "building",
                "phase": "scan",
                "cursor": None,
                "scanned": 0,
                "indexed": 0,
                "expired": 0,
            }
            revision = await self._save(scope, address, state, revision)
        if state["status"] == "ready":
            await self._activate(scope, address, state)
            await self._current(scope, namespace, snapshot)
            return copy.deepcopy(state)
        for _ in range(max_pages):
            await self._current(scope, namespace, snapshot)
            if state["phase"] == "scan":
                page = await self._fixed.call(
                    "source",
                    "scan_facts",
                    scope,
                    namespace,
                    FactScanQuery(
                        limit=self._config["batch_size"],
                        max_bytes=self._config["max_page_bytes"],
                        cursor=state["cursor"],
                    ),
                )
                if not isinstance(page, FactScanPage):
                    _lazy(page)
                    raise ValidationError("Index source must return FactScanPage")
                page = FactScanPage(**asdict(page))
                if (
                    not page.backend_bounded
                    or page.snapshot_id != snapshot
                    or len(page.items) > self._config["batch_size"]
                    or page.used_bytes > self._config["max_page_bytes"]
                    or (not page.items and page.next_cursor is not None)
                    or (page.next_cursor is not None and page.next_cursor == state["cursor"])
                ):
                    raise ValidationError("Index scan exceeded allowance or made no progress")
                now = time.time()
                if state["scanned"] + page.scanned > self._config["max_records"]:
                    raise BudgetExceeded("Facts index total record allowance is exhausted")
                eligible = [
                    i for i in page.items if i["expires_at"] is None or i["expires_at"] > now
                ]
                texts = [_fact_text(i) for i in eligible]
                if any(len(t) > 32768 for t in texts):
                    raise ValidationError("Fact index text exceeds embedding input allowance")
                before = digest(texts)
                vectors = await self._fixed.call("embedding", "embed", texts) if texts else []
                _ = self.identity
                if (
                    not isinstance(vectors, (list, tuple))
                    or len(vectors) != len(eligible)
                    or digest(texts) != before
                ):
                    _lazy(vectors)
                    raise ValidationError(
                        "Embedding changed inputs or returned invalid vector count"
                    )
                vectors = [list(_unit(v, self._config["dimensions"])) for v in vectors]
                await self._current(scope, namespace, snapshot)
                state["pending"] = {
                    "items": eligible,
                    "vectors": vectors,
                    "scanned": page.scanned,
                    "expired": page.scanned - len(eligible),
                    "next_cursor": page.next_cursor,
                }
                state["phase"] = "embedded"
                revision = await self._save(scope, address, state, revision)
            pending = state["pending"]
            pairs = [
                (i, v)
                for i, v in zip(pending["items"], pending["vectors"], strict=True)
                if i["expires_at"] is None or i["expires_at"] > time.time()
            ]
            raw = [i for i, _ in pairs]
            await self._validate_raw(scope, namespace, raw)
            entries = [
                VectorEntry(
                    digest([i["key"], i["version"], digest(i["value"])]),
                    i["key"],
                    i["version"],
                    digest(i["value"]),
                    tuple(v),
                )
                for i, v in pairs
            ]
            result = await self._fixed.call(
                "vector", "upsert", scope, "fact-index:" + state["build_id"], entries
            )
            if result is not None:
                _lazy(result)
                raise ValidationError("Vector upsert must return completed None")
            await self._current(scope, namespace, snapshot)
            state["scanned"] += pending["scanned"]
            state["indexed"] += len(entries)
            state["expired"] += pending["expired"] + len(pending["items"]) - len(entries)
            state["cursor"] = pending["next_cursor"]
            del state["pending"]
            state["phase"] = "scan"
            if state["cursor"] is None:
                state["status"] = "ready"
            revision = await self._save(scope, address, state, revision)
            if state["status"] == "ready":
                await self._activate(scope, address, state)
                await self._current(scope, namespace, snapshot)
                break
        return copy.deepcopy(state)

    async def _activate(self, scope, address, state):
        revision, active = await self._load(scope, address, "active")
        if active == state:
            return
        result = await self._fixed.call(
            "catalog", "save", scope, address, "active", state, expected_version=revision
        )
        if type(result) is not int or result != revision + 1:
            _lazy(result)
            raise ValidationError("Invalid active index commit receipt")

    async def _active(self, scope, namespace):
        address = self._address(scope, namespace)
        _, state = await self._load(scope, address, "active")
        if state is None:
            raise ValidationError("Facts index is not complete; explicit rebuild required")
        state = self._state(state, address)
        if state["status"] != "ready":
            raise ValidationError("Facts index is not complete; explicit rebuild required")
        await self._current(scope, namespace, state["source_snapshot"])
        return state

    async def _validate_raw(self, scope, namespace, items):
        original = digest(items)
        result = await self._fixed.call(
            "source", "validate_facts", scope, namespace, copy.deepcopy(items)
        )
        if result is not None or digest(items) != original:
            _lazy(result)
            raise ValidationError("Facts validation returned an invalid completion")
        for item in items:
            current = await self._fixed.call(
                "source", "inspect_fact", scope, namespace, item["key"]
            )
            if current is None or any(
                canonical(current[k]) != canonical(item[k])
                for k in ("key", "value", "version", "expires_at")
            ):
                raise ValidationError("Indexed fact content is no longer authoritative")
        if any(i["expires_at"] is not None and i["expires_at"] <= time.time() for i in items):
            raise ValidationError("Indexed facts expired before confirmation")

    async def recall(self, scope, namespace, query):
        from .recall import _binding, _decode_cursor, _encode_cursor

        if not isinstance(query, RecallQuery):
            raise ValidationError("Indexed recall requires a bounded RecallQuery")
        query = RecallQuery(**asdict(query))
        text = query_text(query.text)
        state = await self._active(scope, namespace)
        binding = _binding(self.backend_id, scope, "indexed-facts-query-v1", namespace, query)
        decoded = _decode_cursor(query.cursor, binding)
        texts = [text]
        original = digest(texts)
        vectors = await self._fixed.call("embedding", "embed", texts)
        if not isinstance(vectors, (list, tuple)) or len(vectors) != 1 or digest(texts) != original:
            _lazy(vectors)
            raise ValidationError("Query embedding changed inputs or returned invalid count")
        unit = _unit(vectors[0], self._config["dimensions"])
        snapshot = {"build_id": state["build_id"], "vector_digest": digest(unit)}
        offset = 0
        if decoded is not None:
            saved, offset = decoded
            if saved != snapshot or offset > 256:
                raise ValidationError("Index query snapshot changed")
        await self._current(scope, namespace, state["source_snapshot"])
        limit = min(offset + query.scan_limit + 1, 256)
        hits = await self._fixed.call(
            "vector",
            "search",
            scope,
            "fact-index:" + state["build_id"],
            unit,
            limit=limit,
        )
        if (
            not isinstance(hits, list)
            or len(hits) > limit
            or any(not isinstance(h, VectorHit) for h in hits)
        ):
            _lazy(hits)
            raise ValidationError("Facts index returned invalid bounded hits")
        hits = sorted(
            [VectorHit(**asdict(h)) for h in hits],
            key=lambda h: (-h.score, h.document_id, h.chunk_id),
        )
        items, skipped, scanned, seen = [], 0, 0, set()
        position = offset
        for hit in hits[offset : offset + query.scan_limit]:
            if len(items) == query.max_items:
                break
            if hit.document_id in seen or hit.score < self._config["min_score"]:
                skipped += 1
                scanned += 1
                position += 1
                continue
            seen.add(hit.document_id)
            raw = await self._fixed.call(
                "source", "inspect_fact", scope, namespace, hit.document_id
            )
            if raw is not None:
                raw = _fact_records([raw])[0]
            if (
                raw is None
                or raw["key"] != hit.document_id
                or raw["version"] != hit.version
                or digest(raw["value"]) != hit.text_digest
                or hit.chunk_id != digest([raw["key"], raw["version"], digest(raw["value"])])
                or (raw["expires_at"] is not None and raw["expires_at"] <= time.time())
            ):
                skipped += 1
                scanned += 1
                position += 1
                continue
            raw["_fact_index"] = {
                "build_id": state["build_id"],
                "source_snapshot": state["source_snapshot"],
                "definition": state["definition"],
            }
            if items and len(canonical([*items, raw])) > query.max_chars:
                break
            scanned += 1
            position += 1
            if len(canonical([raw])) > query.max_chars:
                skipped += 1
            else:
                items.append(raw)
        await self.validate_facts(scope, namespace, items)
        cursor = (
            _encode_cursor(binding, snapshot, position)
            if position < len(hits) and position < 256
            else None
        )
        return RecallPage(
            items, cursor, len(canonical(items)), scanned, skipped, canonical(snapshot), True
        )

    async def validate_facts(self, scope, namespace, items):
        values = _fact_inputs(scope, namespace, items)
        state = await self._active(scope, namespace)
        marker = {
            "build_id": state["build_id"],
            "source_snapshot": state["source_snapshot"],
            "definition": state["definition"],
        }
        if any(i.get("_fact_index") != marker for i in values):
            raise ValidationError("Facts index evidence does not match its publication")
        await self._validate_raw(
            scope,
            namespace,
            [{k: i[k] for k in ("key", "value", "version", "expires_at")} for i in values],
        )
        await self._current(scope, namespace, state["source_snapshot"])
