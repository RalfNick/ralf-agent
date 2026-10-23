"""Bounded authoritative Fact enumeration for explicit index and lifecycle jobs."""

import re
import uuid
from dataclasses import asdict, dataclass
from typing import Protocol

from .errors import BudgetExceeded, ValidationError
from .recall import (
    _decode_cursor,
    _encode_cursor,
    _fact_inputs,
    _fact_records,
    _integer,
    _name,
    _validate_cursor,
)
from .types import Scope, canonical, digest


def _scan_size(value):
    try:
        return len(canonical(value).encode("utf-8"))
    except UnicodeError:
        raise ValidationError("Fact scan requires valid Unicode scalars") from None


@dataclass(frozen=True)
class FactScanQuery:
    limit: int = 128
    max_bytes: int = 1024 * 1024
    cursor: str | None = None

    def __post_init__(self):
        _integer(self.limit, "Fact scan record limit", 1, 1000)
        _integer(self.max_bytes, "Fact scan byte limit", 2, 1024 * 1024)
        _validate_cursor(self.cursor)


@dataclass(frozen=True)
class FactScanPage:
    items: list[dict]
    next_cursor: str | None
    used_bytes: int
    scanned: int
    snapshot_id: str
    backend_bounded: bool = True

    def __post_init__(self):
        records = _fact_records(self.items)
        _integer(self.used_bytes, "Fact scan used bytes", 2, 1024 * 1024)
        _integer(self.scanned, "Fact scan consumed records", 0, 1000)
        if self.used_bytes != _scan_size(records) or self.scanned != len(records):
            raise ValidationError("Fact scan page counts do not match its records")
        _validate_cursor(self.next_cursor)
        _name(self.snapshot_id, "Fact scan snapshot identity")
        if type(self.backend_bounded) is not bool:
            raise ValidationError("Fact scan backend_bounded must be boolean")
        object.__setattr__(self, "items", records)


class FactScanner(Protocol):
    backend_id: str
    fact_scan_version: int

    def fact_snapshot(self, scope: Scope, namespace: str) -> str: ...

    def scan_facts(self, scope: Scope, namespace: str, query: FactScanQuery) -> FactScanPage: ...


class AsyncFactScanner(Protocol):
    backend_id: str
    fact_scan_version: int

    async def fact_snapshot(self, scope: Scope, namespace: str) -> str: ...

    async def scan_facts(
        self, scope: Scope, namespace: str, query: FactScanQuery
    ) -> FactScanPage: ...


def _scan_binding(backend_id, scope, namespace, query):
    _fact_inputs(scope, namespace, [])
    _name(backend_id, "Fact scanner backend identity")
    if not isinstance(query, FactScanQuery):
        raise ValidationError("Fact scan requires a FactScanQuery")
    query = FactScanQuery(**asdict(query))
    binding = digest(
        {
            "backend": backend_id,
            "scope": asdict(scope),
            "namespace": namespace,
            "domain": "fact-record-scan-v1",
            "limit": query.limit,
            "max_bytes": query.max_bytes,
        }
    )
    return binding, query


def _scan_snapshot(scope, namespace, epoch, generation):
    _fact_inputs(scope, namespace, [])
    _integer(generation, "Fact scan generation")
    if not isinstance(epoch, str) or re.fullmatch(r"[0-9a-f]{32}", epoch) is None:
        raise ValidationError("Fact scan dataset epoch is invalid")
    return {"epoch": epoch, "generation": generation, "address": digest([asdict(scope), namespace])}


def _scan_epoch(store):
    row = store.conn.execute(
        "SELECT value FROM metadata WHERE key='memory_fact_scan_epoch'"
    ).fetchone()
    if row is None:
        epoch = uuid.uuid4().hex
        store.conn.execute("INSERT INTO metadata VALUES ('memory_fact_scan_epoch',?)", (epoch,))
        return epoch
    return row[0]


def _scan_position(binding, snapshot, query):
    decoded = _decode_cursor(query.cursor, binding)
    if decoded is None:
        return snapshot, 0
    previous, after = decoded
    if previous != snapshot:
        raise ValidationError("Fact scan snapshot is no longer current")
    return snapshot, after


def _scan_page(query, binding, snapshot, candidates):
    """Consume lazy (position, loader) rows; never omit an oversize record."""
    items, used, last, more = [], 2, None, False
    for position, load in candidates:
        if len(items) == query.limit:
            more = True
            break
        try:
            record = _fact_records([load()])[0]
            size = _scan_size(record) + bool(items)
            if used + size > query.max_bytes:
                raise BudgetExceeded("Fact record does not fit scan byte budget")
        except BudgetExceeded:
            if not items:
                raise
            more = True
            break
        items.append(record)
        used += size
        last = position
    return FactScanPage(
        items,
        _encode_cursor(binding, snapshot, last) if more else None,
        used,
        len(items),
        canonical(snapshot),
        True,
    )


async def _async_scan_page(query, binding, snapshot, candidates):
    """Bounded async row stream; loaders only decode an already capped row."""
    items, used, last, more = [], 2, None, False
    async for position, load in candidates:
        if len(items) == query.limit:
            more = True
            break
        try:
            record = _fact_records([load()])[0]
            size = _scan_size(record) + bool(items)
            if used + size > query.max_bytes:
                raise BudgetExceeded("Fact record does not fit scan byte budget")
        except BudgetExceeded:
            if not items:
                raise
            more = True
            break
        items.append(record)
        used += size
        last = position
    return FactScanPage(
        items,
        _encode_cursor(binding, snapshot, last) if more else None,
        used,
        len(items),
        canonical(snapshot),
        True,
    )
