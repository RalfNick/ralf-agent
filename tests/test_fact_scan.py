"""Authoritative Fact scan contracts; recall must keep its existing visibility."""

import asyncio
import importlib
from dataclasses import asdict

import pytest

from relf_agent import InMemoryMemory, Scope, SQLiteMemory
from relf_agent.errors import ValidationError
from relf_agent.types import canonical


def query(**kwargs):
    module = importlib.import_module("relf_agent")
    assert hasattr(module, "FactScanQuery"), "Missing authoritative bounded Fact scan port"
    return module.FactScanQuery(**kwargs)


@pytest.fixture(params=["memory", "sqlite"])
def backend(request, tmp_path):
    source = (
        InMemoryMemory() if request.param == "memory" else SQLiteMemory(tmp_path / "facts.sqlite")
    )
    yield source
    source.close()


def test_scan_covers_all_records_including_expired_without_changing_recall(backend):
    backend.put_fact(Scope(), "facts", "current", {"text": "中文🙂"}, expected_version=0)
    backend.put_fact(Scope(), "facts", "expired", "evidence", expected_version=0, expires_at=0)
    backend.put_fact(Scope("other", "user"), "facts", "foreign", 7, expected_version=0)
    q = query(limit=1)
    first = backend.scan_facts(Scope(), "facts", q)
    assert len(first.items) == first.scanned == 1 and first.backend_bounded
    assert first.used_bytes == len(canonical(first.items).encode("utf-8"))
    assert first.next_cursor
    second = backend.scan_facts(Scope(), "facts", query(limit=1, cursor=first.next_cursor))
    assert second.next_cursor is None and second.snapshot_id == first.snapshot_id
    assert {v["key"] for v in first.items + second.items} == {"current", "expired"}
    assert [v["key"] for v in backend.facts(Scope(), "facts")] == ["current"]


def test_scan_continuation_cannot_mix_mutated_snapshot_or_other_scope(backend):
    for key in ["one", "two"]:
        backend.put_fact(Scope(), "facts", key, key, expected_version=0)
    page = backend.scan_facts(Scope(), "facts", query(limit=1))
    with pytest.raises(ValidationError):
        backend.scan_facts(Scope("other", "user"), "facts", query(limit=1, cursor=page.next_cursor))
    backend.put_fact(Scope(), "facts", "one", "changed", expected_version=1)
    with pytest.raises(ValidationError):
        backend.scan_facts(Scope(), "facts", query(limit=1, cursor=page.next_cursor))


def test_scan_byte_stop_preserves_next_record_and_does_not_silently_skip(backend):
    for key in ["one", "two"]:
        backend.put_fact(Scope(), "facts", key, "中文🙂", expected_version=0)
    original = backend.scan_facts(Scope(), "facts", query(limit=1)).items[0]
    bound = len(canonical([original]).encode("utf-8"))
    page = backend.scan_facts(Scope(), "facts", query(limit=2, max_bytes=bound))
    assert page.items == [original] and page.next_cursor and page.used_bytes == bound
    following = backend.scan_facts(
        Scope(), "facts", query(limit=2, max_bytes=bound, cursor=page.next_cursor)
    )
    assert len(following.items) == 1 and following.items[0]["key"] != original["key"]
    assert following.next_cursor is None
    assert asdict(page)["used_bytes"] == bound


def test_invalid_unicode_source_is_rejected_with_typed_error(backend):
    import json

    invalid = chr(0xD800)
    if isinstance(backend, SQLiteMemory):
        backend.put_fact(Scope(), "facts", "bad", "safe", expected_version=0)
        backend.store.conn.execute(
            "UPDATE memory_facts SET value=? WHERE key='bad'", (json.dumps(invalid),)
        )
    else:
        backend.put_fact(Scope(), "facts", "bad", invalid, expected_version=0)
    with pytest.raises(ValidationError):
        backend.scan_facts(Scope(), "facts", query())


@pytest.mark.parametrize(
    "options",
    [
        {"limit": True},
        {"limit": 0},
        {"limit": 1001},
        {"max_bytes": True},
        {"max_bytes": 1},
        {"max_bytes": 1024 * 1024 + 1},
        {"cursor": ""},
        {"cursor": 1},
        {"cursor": "x" * 4097},
    ],
)
def test_invalid_scan_query_is_rejected(options):
    with pytest.raises(ValidationError):
        query(**options)


def test_scan_empty_page_is_explicit_and_detached(backend):
    page = backend.scan_facts(Scope(), "facts", query(max_bytes=2))
    assert page.items == [] and page.scanned == 0 and page.used_bytes == 2
    assert page.next_cursor is None and page.backend_bounded


def test_sqlite_does_not_decode_oversize_payload_before_budget_refusal(tmp_path, monkeypatch):
    import json

    from relf_agent.errors import BudgetExceeded

    with_store = SQLiteMemory(tmp_path / "facts.sqlite")
    try:
        with_store.put_fact(Scope(), "facts", "huge", "x" * 10000, expected_version=0)
        original = json.loads

        def bounded(payload, *args, **kwargs):
            if isinstance(payload, bytes):
                assert len(payload) <= 256, "Decoded oversized SQL payload before refusal"
            return original(payload, *args, **kwargs)

        monkeypatch.setattr(json, "loads", bounded)
        with pytest.raises(BudgetExceeded):
            with_store.scan_facts(Scope(), "facts", query(max_bytes=256))
    finally:
        with_store.close()


def test_scan_covers_more_than_original_semantic_candidate_window(backend):
    for index in range(330):
        backend.put_fact(Scope(), "facts", str(index), index, expected_version=0)
    cursor, records, snapshot = None, [], None
    while True:
        page = backend.scan_facts(Scope(), "facts", query(limit=37, cursor=cursor))
        assert len(page.items) <= 37
        if snapshot is not None:
            assert page.snapshot_id == snapshot
        snapshot = page.snapshot_id
        records.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(records) == 330 and {v["value"] for v in records} == set(range(330))


def test_threaded_scanner_preserves_snapshot_and_original_owner():
    from relf_agent import ThreadedMemoryAdapter

    source = InMemoryMemory()
    source.put_fact(Scope(), "facts", "one", 1, expected_version=0)
    source.put_fact(Scope(), "facts", "two", 2, expected_version=0)
    bridge = ThreadedMemoryAdapter(source)

    async def run():
        assert bridge.fact_scan_version == 1
        first = await bridge.scan_facts(Scope(), "facts", query(limit=1))
        second = await bridge.scan_facts(Scope(), "facts", query(limit=1, cursor=first.next_cursor))
        assert [i["value"] for i in first.items + second.items] == [1, 2]
        assert first.snapshot_id == second.snapshot_id

    asyncio.run(run())
    assert source.inspect_fact(Scope(), "facts", "one")["version"] == 1


def test_threaded_scan_never_falls_back_to_unbounded_legacy_facts():
    from relf_agent import ThreadedMemoryAdapter

    class Legacy:
        backend_id = "legacy"
        reads = 0

        def facts(self, *args):
            self.reads += 1
            return []

    source = Legacy()

    async def run():
        with pytest.raises(ValidationError):
            await ThreadedMemoryAdapter(source).scan_facts(Scope(), "facts", query())

    asyncio.run(run())
    assert source.reads == 0


def test_threaded_bridge_rejects_async_scan_configuration_before_call():
    from relf_agent import ThreadedMemoryAdapter

    class AsyncScan(InMemoryMemory):
        async def scan_facts(self, *args):
            raise AssertionError("Must use native async source")

    with pytest.raises(ValidationError):
        ThreadedMemoryAdapter(AsyncScan())


def test_snapshot_header_does_not_load_large_or_expired_fact_values(backend):
    backend.put_fact(Scope(), "facts", "big", "x" * 100000, expected_version=0)
    first = backend.fact_snapshot(Scope(), "facts")
    page = backend.scan_facts(Scope(), "facts", query())
    assert first == page.snapshot_id
    backend.put_fact(Scope(), "facts", "big", "updated", expected_version=1, expires_at=0)
    assert backend.fact_snapshot(Scope(), "facts") != first
    assert backend.facts(Scope(), "facts") == []


def test_sqlite_scan_never_projects_full_oversized_key(tmp_path):
    import sqlite3

    from relf_agent.errors import BudgetExceeded

    source = SQLiteMemory(tmp_path / "facts.sqlite")
    try:
        source.put_fact(Scope(), "facts", "k" * 100000, 1, expected_version=0)
        sizes = []

        def rows(cursor, values):
            if cursor.description[0][0] == "position":
                sizes.append(len(values[1]))
            return sqlite3.Row(cursor, values)

        source.store.conn.row_factory = rows
        with pytest.raises(BudgetExceeded):
            source.scan_facts(Scope(), "facts", query(max_bytes=2))
        assert sizes and max(sizes) <= 3
    finally:
        source.close()


def test_recreated_memory_with_same_declared_name_has_new_snapshot_epoch():
    first, second = InMemoryMemory(backend_id="named"), InMemoryMemory(backend_id="named")
    for source in [first, second]:
        source.put_fact(Scope(), "facts", "one", 1, expected_version=0)
    assert first.fact_snapshot(Scope(), "facts") != second.fact_snapshot(Scope(), "facts")


def test_sqlite_snapshot_and_cursor_survive_actual_resource_reopen(tmp_path):
    path = tmp_path / "facts.sqlite"
    source = SQLiteMemory(path)
    try:
        for key in ["one", "two"]:
            source.put_fact(Scope(), "facts", key, key, expected_version=0)
        snapshot = source.fact_snapshot(Scope(), "facts")
        page = source.scan_facts(Scope(), "facts", query(limit=1))
    finally:
        source.close()
    restored = SQLiteMemory(path)
    try:
        assert restored.fact_snapshot(Scope(), "facts") == snapshot
        following = restored.scan_facts(Scope(), "facts", query(limit=1, cursor=page.next_cursor))
        assert following.snapshot_id == snapshot and following.items[0]["key"] == "two"
    finally:
        restored.close()
