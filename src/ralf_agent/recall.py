"""Bounded memory recall ports and an explicit bridge for legacy full reads.

Character limits count canonical JSON, including the surrounding item list.
Native bounded reads limit candidate records; they are not database byte limits.
"""

import base64
import inspect
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .errors import DefinitionMismatch, ValidationError
from .types import Scope, canonical, digest


def _integer(value, name, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValidationError(f"{name} must be an integer within its supported limits")


def _name(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")


def _method_backend(method):
    """Capture a delegated bound client's identity before invoking its method."""
    owner = getattr(method, "__self__", None)
    identity = getattr(owner, "backend_id", None)
    if identity is not None:
        _name(identity, "Memory method backend identity")
        return owner, identity
    return None, None


def _validate_cursor(cursor):
    if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096):
        raise ValidationError("Recall cursor must be a non-empty string of at most 4096 characters")


@dataclass(frozen=True)
class RecallQuery:
    max_items: int = 32
    max_chars: int = 8000
    scan_limit: int = 256
    text: str | None = None
    cursor: str | None = None

    def __post_init__(self):
        _integer(self.max_items, "Recall item limit", 1, 1000)
        _integer(self.max_chars, "Recall character limit", 2, 1_000_000)
        _integer(self.scan_limit, "Recall scan limit", self.max_items, 10_000)
        if self.text is not None and not isinstance(self.text, str):
            raise ValidationError("Recall text must be a string or None")
        _validate_cursor(self.cursor)


@dataclass(frozen=True)
class RecallPage:
    items: list[dict]
    next_cursor: str | None
    used_chars: int
    scanned: int
    skipped: int
    snapshot_id: str
    backend_bounded: bool = True

    def __post_init__(self):
        if not isinstance(self.items, list) or any(not isinstance(i, dict) for i in self.items):
            raise ValidationError("Recall items must be a list of JSON objects")
        payload = canonical(self.items)
        _integer(self.used_chars, "Recall used characters", 2)
        _integer(self.scanned, "Recall scanned records")
        _integer(self.skipped, "Recall skipped records")
        if self.used_chars != len(payload):
            raise ValidationError("Recall used characters do not match the canonical item payload")
        if self.skipped > self.scanned or len(self.items) > self.scanned:
            raise ValidationError("Recall page counts are inconsistent")
        _validate_cursor(self.next_cursor)
        _name(self.snapshot_id, "Recall snapshot identity")
        if type(self.backend_bounded) is not bool:
            raise ValidationError("Recall backend_bounded must be a boolean")
        object.__setattr__(self, "items", json.loads(payload))


def _query_config(query):
    return {key: value for key, value in asdict(query).items() if key != "cursor"}


@dataclass(frozen=True)
class MemoryRecallPolicy:
    facts: RecallQuery = field(default_factory=RecallQuery)
    session: RecallQuery = field(default_factory=lambda: RecallQuery(max_items=20))
    max_pages: int = 1

    def __post_init__(self):
        for query in (self.facts, self.session):
            if not isinstance(query, RecallQuery) or query.cursor is not None:
                raise ValidationError(
                    "Recall policy queries must be RecallQuery values without cursors"
                )
        _integer(self.max_pages, "Recall page limit", 1, 10)

    @property
    def identity(self):
        return {
            "kind": "bounded-memory-recall",
            "version": "1",
            "facts": _query_config(self.facts),
            "session": _query_config(self.session),
            "max_pages": self.max_pages,
        }


class PaginatedSessionStore(Protocol):
    backend_id: str

    def read_page(self, scope: Scope, session_id: str, query: RecallQuery) -> RecallPage: ...


class RecallPlanner(Protocol):
    """Pure selection of a fixed query for one new model Action."""

    identity: dict

    def plan(
        self, scope: Scope, namespace: str, session_id: str, text: str
    ) -> MemoryRecallPolicy: ...


class FixedRecallPlanner:
    def __init__(self, policy=None):
        self.policy = MemoryRecallPolicy() if policy is None else policy
        if not isinstance(self.policy, MemoryRecallPolicy):
            raise ValidationError("FixedRecallPlanner requires a MemoryRecallPolicy")

    @property
    def identity(self):
        return {"kind": "fixed-recall-planner", "version": "1", "policy": self.policy.identity}

    def plan(self, scope, namespace, session_id, text):
        return self.policy


class RecallMemoryStore(Protocol):
    """Bounded recall; optional recall_mode='window' declares no pagination.

    Cursor mode is the legacy default. A window backend ranks candidates using
    the complete scan_limit, returns up to max_items and never returns a cursor.
    Scoped bindings preserve this distinction without requiring inheritance.
    """

    backend_id: str

    def recall(self, scope: Scope, namespace: str, query: RecallQuery) -> RecallPage: ...


class AsyncPaginatedSessionStore(Protocol):
    backend_id: str

    async def read_page(self, scope: Scope, session_id: str, query: RecallQuery) -> RecallPage: ...


class AsyncRecallMemoryStore(Protocol):
    """Native async recall with the same optional recall_mode metadata."""

    backend_id: str

    async def recall(self, scope: Scope, namespace: str, query: RecallQuery) -> RecallPage: ...


class FactReferenceValidator(Protocol):
    backend_id: str

    def validate_facts(self, scope: Scope, namespace: str, items: list[dict]) -> None: ...


class AsyncFactReferenceValidator(Protocol):
    backend_id: str

    async def validate_facts(self, scope: Scope, namespace: str, items: list[dict]) -> None: ...


def _fact_records(items):
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValidationError("Fact references must be a list of JSON objects")
    detached = json.loads(canonical(items))
    keys = set()
    for item in detached:
        if not {"key", "value", "version", "expires_at"} <= set(item):
            raise ValidationError("Fact references require key, value, version and expires_at")
        _name(item["key"], "Fact reference key")
        _integer(item["version"], "Fact reference version", 1)
        expiry = item["expires_at"]
        if expiry is not None:
            if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
                raise ValidationError("Fact expiration must be a finite timestamp or None")
            try:
                valid = math.isfinite(float(expiry))
            except OverflowError:
                valid = False
            if not valid:
                raise ValidationError("Fact expiration must be a finite timestamp or None")
        if item["key"] in keys:
            raise ValidationError("Fact reference keys must be unique")
        keys.add(item["key"])
    return detached


def _fact_inputs(scope, namespace, items):
    if not isinstance(scope, Scope):
        raise ValidationError("Fact validation requires a trusted Scope")
    _name(namespace, "Fact namespace")
    return _fact_records(items)


def _current_fact(reference, version, expiry, now):
    if (
        version != reference["version"]
        or expiry != reference["expires_at"]
        or (expiry is not None and expiry <= now)
    ):
        raise ValidationError("Fact reference is no longer current")


def _binding(backend_id, scope, domain, name, query):
    if not isinstance(query, RecallQuery):
        raise ValidationError("Recall requires a RecallQuery")
    if not isinstance(scope, Scope):
        raise ValidationError("Recall requires a trusted Scope")
    _name(backend_id, "Memory backend identity")
    _name(name, "Recall namespace or session")
    return digest(
        {
            "backend": backend_id,
            "scope": asdict(scope),
            "domain": domain,
            "name": name,
            "query": _query_config(query),
        }
    )


def _encode_cursor(binding, snapshot, position):
    value = {"v": 1, "b": binding, "s": snapshot, "p": position}
    encoded = base64.urlsafe_b64encode(canonical(value).encode()).decode().rstrip("=")
    _validate_cursor(encoded)
    return encoded


def _decode_cursor(cursor, binding):
    if cursor is None:
        return None
    _validate_cursor(cursor)
    try:
        if re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
            raise ValueError("Invalid base64url")
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        canonical(payload)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "b", "s", "p"}
            or type(payload["v"]) is not int
            or payload["v"] != 1
            or payload["b"] != binding
            or not isinstance(payload["s"], dict)
            or type(payload["p"]) is not int
            or payload["p"] < 0
            or payload["p"] > 2**63 - 1
        ):
            raise ValueError("Cursor binding mismatch")
        return payload["s"], payload["p"]
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValidationError("Recall cursor is invalid or belongs to another query") from exc


def _snapshot(snapshot):
    return canonical(snapshot)


def _select(candidates, query, domain):
    """Candidates carry stable integer positions, in the desired scan direction."""
    items, used, scanned, skipped, position = [], 2, 0, 0, None
    now = time.time()
    for candidate_position, item in candidates:
        if scanned >= query.scan_limit or len(items) >= query.max_items:
            break
        scanned += 1
        position = candidate_position
        matches = True
        if domain == "facts":
            expiry = item.get("expires_at")
            matches = expiry is None or expiry > now
            if query.text is not None:
                matches = matches and (
                    query.text in item["key"] or query.text in canonical(item["value"])
                )
        elif query.text is not None:
            matches = query.text in canonical(item)
        size = len(canonical(item)) + (1 if items else 0)
        if not matches or used + size > query.max_chars:
            skipped += 1
            continue
        items.append(item)
        used += size
    return items, scanned, skipped, position


def _page(candidates, query, domain, binding, snapshot, *, bounded=True, has_more=False):
    items, scanned, skipped, position = _select(candidates, query, domain)
    if domain == "session":
        items.reverse()
    next_cursor = (
        _encode_cursor(binding, snapshot, position)
        if (scanned < len(candidates) or has_more) and position is not None
        else None
    )
    return RecallPage(
        items, next_cursor, len(canonical(items)), scanned, skipped, _snapshot(snapshot), bounded
    )


class LegacyMemoryRecallAdapter:
    """Limit the returned payload after an existing full read.

    Both synchronous and asynchronous legacy clients are accepted. This adapter
    cannot bound the client's remote read or full materialization, and says so
    in every returned page. Append-only session prefixes remain valid cursors.
    """

    def __init__(self, backend):
        _name(getattr(backend, "backend_id", None), "Memory backend identity")
        self.backend = backend

    @property
    def backend_id(self):
        return self.backend.backend_id

    def __getattr__(self, name):
        # Preserve configured old ports without inventing operations absent on
        # the wrapped client. Resource ownership remains with the caller.
        if name in {"read", "append", "facts", "put_fact"}:
            return getattr(self.backend, name)
        raise AttributeError(name)

    def _invoke(self, name, scope, key, query, convert):
        backend = self.backend
        identity = backend.backend_id
        binding = _binding(identity, scope, "legacy-" + name, key, query)
        method = getattr(backend, name, None)
        if not callable(method):
            raise ValidationError(f"Legacy memory backend requires {name}")
        owner, owner_identity = _method_backend(method)
        result = method(scope, key)

        def finish(value):
            if backend.backend_id != identity or self.backend is not backend:
                raise DefinitionMismatch("Memory backend identity changed during recall")
            if owner is not None and owner.backend_id != owner_identity:
                raise DefinitionMismatch("Memory method backend identity changed during recall")
            return convert(value, query, binding)

        if inspect.isawaitable(result):

            async def awaited():
                return finish(await result)

            return awaited()
        return finish(result)

    def read_page(self, scope, session_id, query):
        return self._invoke("read", scope, session_id, query, self._session)

    def recall(self, scope, namespace, query):
        return self._invoke("facts", scope, namespace, query, self._facts)

    def validate_facts(self, scope, namespace, items):
        """Recheck a full legacy read; this operation is deliberately unbounded."""
        references = _fact_inputs(scope, namespace, items)
        if not references:
            return None
        backend = self.backend
        identity = backend.backend_id
        method = getattr(backend, "facts", None)
        if not callable(method):
            raise ValidationError("Legacy memory backend requires facts")
        owner, owner_identity = _method_backend(method)
        result = method(scope, namespace)

        def finish(value):
            if backend.backend_id != identity or self.backend is not backend:
                raise DefinitionMismatch("Memory backend identity changed during validation")
            if owner is not None and owner.backend_id != owner_identity:
                raise DefinitionMismatch("Memory method backend identity changed during validation")
            current = {item["key"]: item for item in _fact_records(value)}
            now = time.time()
            for reference in references:
                actual = current.get(reference["key"])
                if actual is None or canonical(actual["value"]) != canonical(reference["value"]):
                    raise ValidationError("Fact reference is no longer current")
                _current_fact(reference, actual["version"], actual["expires_at"], now)
            return None

        if inspect.isawaitable(result):

            async def awaited():
                return finish(await result)

            return awaited()
        return finish(result)

    @staticmethod
    def _session(result, query, binding):
        if not isinstance(result, (tuple, list)) or len(result) != 2:
            raise ValidationError("Legacy session read must return revision and messages")
        revision, messages = result
        _integer(revision, "Session revision")
        if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
            raise ValidationError("Legacy session messages must be JSON objects")
        messages = json.loads(canonical(messages))
        decoded = _decode_cursor(query.cursor, binding)
        if decoded is None:
            snapshot = {
                "revision": revision,
                "watermark": len(messages),
                "prefix": digest(messages),
            }
            before = len(messages) + 1
        else:
            snapshot, before = decoded
            if (
                set(snapshot) != {"revision", "watermark", "prefix"}
                or type(snapshot["revision"]) is not int
                or snapshot["revision"] < 0
                or type(snapshot["watermark"]) is not int
                or snapshot["watermark"] < 0
                or snapshot["watermark"] > len(messages)
                or before > snapshot["watermark"]
                or snapshot["prefix"] != digest(messages[: snapshot["watermark"]])
            ):
                raise ValidationError("Session recall snapshot is no longer available")
        candidates = [
            (seq, messages[seq - 1])
            for seq in range(before - 1, max(0, before - query.scan_limit - 1), -1)
        ]
        return _page(
            candidates,
            query,
            "session",
            binding,
            snapshot,
            bounded=False,
            has_more=before - 1 > len(candidates),
        )

    @staticmethod
    def _facts(result, query, binding):
        items = _fact_records(result)
        snapshot = {"generation": digest(items)}
        decoded = _decode_cursor(query.cursor, binding)
        after = 0
        if decoded is not None:
            previous, after = decoded
            if previous != snapshot or after > len(items):
                raise ValidationError("Fact recall snapshot is no longer available")
        candidates = list(enumerate(items[after : after + query.scan_limit], start=after + 1))
        return _page(
            candidates,
            query,
            "facts",
            binding,
            snapshot,
            bounded=False,
            has_more=after + len(candidates) < len(items),
        )
