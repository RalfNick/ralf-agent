import asyncio
import base64
import importlib
import json
import threading
from dataclasses import replace

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.memory import InMemoryMemory, SQLiteMemory, ThreadedMemoryAdapter
from ralf_agent.types import Scope, canonical


def api():
    return importlib.import_module("ralf_agent.recall")


@pytest.fixture(params=["memory", "sqlite"])
def memory(request, tmp_path):
    backend = (
        InMemoryMemory() if request.param == "memory" else SQLiteMemory(tmp_path / "memory.db")
    )
    yield backend
    backend.close()


def query(**kwargs):
    return api().RecallQuery(**kwargs)


def collect(method, scope, name, request):
    pages = []
    while True:
        page = method(scope, name, request)
        assert page.used_chars == len(canonical(page.items)) <= request.max_chars
        assert len(page.items) <= request.max_items
        assert page.scanned <= request.scan_limit
        pages.append(page)
        if page.next_cursor is None:
            return pages
        request = replace(request, cursor=page.next_cursor)
        assert len(pages) < 30


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_items": True},
        {"max_items": 1.5},
        {"max_items": 0},
        {"max_items": 1001},
        {"max_chars": 1},
        {"max_chars": 1000001},
        {"max_chars": False},
        {"scan_limit": 31},
        {"scan_limit": 10001},
        {"scan_limit": 32.0},
        {"text": 4},
        {"cursor": ""},
        {"cursor": "x" * 4097},
        {"cursor": 4},
    ],
)
def test_query_rejects_invalid_contract(kwargs):
    with pytest.raises(ValidationError):
        query(**kwargs)


def test_page_detaches_json_and_checks_payload_accounting():
    source = [{"value": {"locale": "zh"}}]
    page_type = api().RecallPage
    page = page_type(source, None, len(canonical(source)), 1, 0, "revision:1")
    source[0]["value"]["locale"] = "changed"
    assert page.items == [{"value": {"locale": "zh"}}]
    for changes in (
        {"used_chars": 2},
        {"scanned": True},
        {"skipped": -1},
        {"snapshot_id": ""},
        {"next_cursor": ""},
        {"backend_bounded": 1},
        {"items": ["not a message"]},
    ):
        with pytest.raises(ValidationError):
            replace(page, **changes)


def test_policy_has_stable_detached_identity_and_no_caller_cursor():
    policy = api().MemoryRecallPolicy()
    assert policy.facts == query()
    assert policy.session == query(max_items=20)
    first = policy.identity
    first["facts"]["max_items"] = 9
    assert policy.identity["facts"]["max_items"] == 32
    for changes in (
        {"facts": query(cursor="opaque")},
        {"max_pages": 0},
        {"max_pages": 11},
        {"max_pages": True},
        {"session": {}},
    ):
        with pytest.raises(ValidationError):
            replace(policy, **changes)


def test_fact_pages_keep_insertion_order_and_old_api_keeps_key_order(memory):
    scope = Scope()
    for key in ("z", "a", "m", "b"):
        memory.put_fact(scope, "a", key, {"name": key}, expected_version=0)
    pages = collect(memory.recall, scope, "a", query(max_items=2))
    assert [item["key"] for page in pages for item in page.items] == ["z", "a", "m", "b"]
    assert [item["key"] for item in memory.facts(scope, "a")] == ["a", "b", "m", "z"]
    assert all(page.backend_bounded for page in pages)
    assert len({page.snapshot_id for page in pages}) == 1
    pages[0].items[0]["value"]["name"] = "changed"
    assert memory.facts(scope, "a")[-1]["value"]["name"] == "z"


@pytest.mark.parametrize("boundary", ["scope", "namespace", "quota", "text", "backend"])
def test_fact_cursor_cannot_cross_recall_boundaries(memory, boundary):
    scope = Scope()
    for key in ("a", "b"):
        memory.put_fact(scope, "a", key, key, expected_version=0)
    request = query(max_items=1)
    cursor = memory.recall(scope, "a", request).next_cursor
    request = replace(request, cursor=cursor)
    namespace = "a"
    backend = memory
    other = None
    if boundary == "scope":
        scope = Scope(principal="another")
    elif boundary == "namespace":
        namespace = "b"
    elif boundary == "quota":
        request = replace(request, max_chars=9000)
    elif boundary == "text":
        request = replace(request, text="a")
    else:
        other = InMemoryMemory()
        backend = other
    try:
        with pytest.raises(ValidationError):
            backend.recall(scope, namespace, request)
    finally:
        if other:
            other.close()


def test_fact_write_invalidates_cursor_but_failed_cas_does_not(memory):
    scope = Scope()
    for key in ("a", "b"):
        memory.put_fact(scope, "a", key, key, expected_version=0)
    request = query(max_items=1)
    cursor = memory.recall(scope, "a", request).next_cursor
    with pytest.raises(ValidationError):
        memory.put_fact(scope, "a", "a", "bad", expected_version=0)
    assert memory.recall(scope, "a", replace(request, cursor=cursor)).items[0]["key"] == "b"
    memory.put_fact(scope, "a", "a", "new", expected_version=1)
    with pytest.raises(ValidationError):
        memory.recall(scope, "a", replace(request, cursor=cursor))
    assert [r["key"] for r in memory.recall(scope, "a", query()).items] == ["a", "b"]


def test_cursor_rejects_non_integer_generation_and_cross_domain(memory):
    memory.put_fact(Scope(), "s", "a", "a", expected_version=0)
    memory.put_fact(Scope(), "s", "b", "b", expected_version=0)
    request = query(max_items=1)
    first = memory.recall(Scope(), "s", request)
    with pytest.raises(ValidationError):
        memory.read_page(Scope(), "s", replace(request, cursor=first.next_cursor))
    payload = json.loads(
        base64.urlsafe_b64decode(first.next_cursor + "=" * (-len(first.next_cursor) % 4))
    )
    # Python equality considers 2.0 equal to 2: generations still require integers.
    payload["s"]["generation"] = 2.0
    malformed = base64.urlsafe_b64encode(canonical(payload).encode()).decode().rstrip("=")
    with pytest.raises(ValidationError):
        memory.recall(Scope(), "s", replace(request, cursor=malformed))


@pytest.mark.parametrize("malformed_position", [10**100, "deep-json"])
def test_cursor_large_position_and_deep_json_are_typed_rejections(memory, malformed_position):
    for key in ("a", "b"):
        memory.put_fact(Scope(), "a", key, key, expected_version=0)
    request = query(max_items=1)
    first = memory.recall(Scope(), "a", request)
    payload = json.loads(
        base64.urlsafe_b64decode(first.next_cursor + "=" * (-len(first.next_cursor) % 4))
    )
    if malformed_position == "deep-json":
        raw = (
            '{"v":1,"b":'
            + canonical(payload["b"])
            + ',"p":1,"s":{"nested":'
            + "[" * 1100
            + "0"
            + "]" * 1100
            + "}}"
        )
    else:
        payload["p"] = malformed_position
        raw = canonical(payload)
    cursor = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    assert len(cursor) <= 4096
    with pytest.raises(ValidationError):
        memory.recall(Scope(), "a", replace(request, cursor=cursor))


def test_ttl_is_rechecked_per_page_and_expiration_preserves_cas(memory, monkeypatch):
    monkeypatch.setattr("ralf_agent.memory.time.time", lambda: 100)
    scope = Scope()
    memory.put_fact(scope, "a", "first", 1, expected_version=0)
    memory.put_fact(scope, "a", "expires", 2, expected_version=0, expires_at=110)
    request = query(max_items=1)
    first = memory.recall(scope, "a", request)
    monkeypatch.setattr("ralf_agent.memory.time.time", lambda: 111)
    page = memory.recall(scope, "a", replace(request, cursor=first.next_cursor))
    assert page.items == [] and page.scanned == page.skipped == 1
    with pytest.raises(ValidationError):
        memory.put_fact(scope, "a", "expires", 3, expected_version=0)
    assert memory.put_fact(scope, "a", "expires", 3, expected_version=1) == 2


def test_oversize_key_advances_empty_page_without_truncation(memory):
    scope = Scope()
    memory.put_fact(scope, "a", "x" * 20000, "big", expected_version=0)
    memory.put_fact(scope, "a", "small", "ok", expected_version=0)
    request = query(max_items=1, scan_limit=1, max_chars=150)
    first = memory.recall(scope, "a", request)
    assert first.items == [] and first.scanned == first.skipped == 1
    assert first.next_cursor and len(first.next_cursor) <= 4096
    second = memory.recall(scope, "a", replace(request, cursor=first.next_cursor))
    assert second.items == [{"key": "small", "value": "ok", "version": 1, "expires_at": None}]
    assert second.next_cursor is None


def test_case_sensitive_fact_filter_searches_key_and_canonical_value(memory):
    scope = Scope()
    for key, value in (
        ("Project", "unrelated"),
        ("other", {"owner": "Project"}),
        ("lower", "project"),
    ):
        memory.put_fact(scope, "a", key, value, expected_version=0)
    page = memory.recall(scope, "a", query(text="Project"))
    assert [r["key"] for r in page.items] == ["Project", "other"]
    assert page.scanned == 3 and page.skipped == 1


def append_messages(memory, count):
    for index in range(count):
        memory.append(
            Scope(),
            "s",
            {"role": "user", "content": str(index)},
            expected_revision=index,
            message_id=f"m{index}",
        )


def test_session_pages_keep_initial_watermark_and_chronological_items(memory):
    append_messages(memory, 5)
    request = query(max_items=2)
    first = memory.read_page(Scope(), "s", request)
    assert [r["content"] for r in first.items] == ["3", "4"]
    memory.append(
        Scope(), "s", {"role": "user", "content": "new"}, expected_revision=5, message_id="m5"
    )
    rest = collect(memory.read_page, Scope(), "s", replace(request, cursor=first.next_cursor))
    assert [[r["content"] for r in p.items] for p in rest] == [["1", "2"], ["0"]]
    assert all(p.snapshot_id == first.snapshot_id for p in rest)
    assert [r["content"] for r in memory.read_page(Scope(), "s", query()).items][-1] == "new"


def test_session_oversize_and_filter_are_counted_and_advance(memory):
    memory.append(
        Scope(), "s", {"role": "user", "content": "wanted"}, expected_revision=0, message_id="m0"
    )
    memory.append(
        Scope(), "s", {"role": "user", "content": "x" * 300}, expected_revision=1, message_id="m1"
    )
    request = query(max_items=1, scan_limit=1, max_chars=100)
    first = memory.read_page(Scope(), "s", request)
    assert first.items == [] and first.scanned == first.skipped == 1
    assert (
        memory.read_page(Scope(), "s", replace(request, cursor=first.next_cursor)).items[0][
            "content"
        ]
        == "wanted"
    )
    page = memory.read_page(Scope(), "s", query(text="wanted"))
    assert page.scanned == 2 and page.skipped == 1 and len(page.items) == 1
    with pytest.raises(ValidationError):
        memory.read_page(Scope(principal="other"), "s", replace(request, cursor=first.next_cursor))


@pytest.mark.parametrize("namespace,key", [("", "a"), ("a", ""), (4, "a"), ("a", None)])
def test_fact_identifiers_are_validated_before_mutation(memory, namespace, key):
    with pytest.raises(ValidationError):
        memory.put_fact(Scope(), namespace, key, "value", expected_version=0)
    assert memory.facts(Scope(), "a") == []


def test_sqlite_legacy_blob_append_preserves_cursor_and_rewrite_invalidates(tmp_path):
    with_memory = SQLiteMemory(tmp_path / "memory.db")
    try:
        append_messages(with_memory, 4)
        request = query(max_items=1)
        first = with_memory.read_page(Scope(), "s", request)
        records = with_memory._records(Scope(), "s")
        records.append(["old-writer", {"role": "user", "content": "old-append"}])
        with_memory.store.conn.execute("UPDATE memory_sessions SET data=?", (canonical(records),))
        with_memory.store.conn.commit()
        assert (
            with_memory.read_page(Scope(), "s", replace(request, cursor=first.next_cursor)).items[
                0
            ]["content"]
            == "2"
        )
        records[0][1]["content"] = "rewritten"
        with_memory.store.conn.execute("UPDATE memory_sessions SET data=?", (canonical(records),))
        with_memory.store.conn.commit()
        with pytest.raises(ValidationError):
            with_memory.read_page(Scope(), "s", replace(request, cursor=first.next_cursor))
    finally:
        with_memory.close()


def test_sqlite_clean_pages_do_not_reload_full_session_blob(tmp_path, monkeypatch):
    memory = SQLiteMemory(tmp_path / "memory.db")
    try:
        append_messages(memory, 20)
        first = memory.read_page(Scope(), "s", query(max_items=2))

        def forbidden(*args):
            raise AssertionError("clean pagination read the legacy full session blob")

        monkeypatch.setattr(memory, "_records", forbidden)
        second = memory.read_page(Scope(), "s", query(max_items=2, cursor=first.next_cursor))
        assert [r["content"] for r in second.items] == ["16", "17"]
        assert not memory.store.conn.in_transaction
    finally:
        memory.close()


@pytest.mark.parametrize("change", ["delete-and-recreate", "clear-and-recreate"])
def test_sqlite_session_sequence_reuse_invalidates_cursor_even_with_same_content(tmp_path, change):
    memory = SQLiteMemory(tmp_path / "memory.db")
    try:
        append_messages(memory, 3)
        request = query(max_items=1)
        first = memory.read_page(Scope(), "s", request)
        original = canonical(memory._records(Scope(), "s"))
        if change == "delete-and-recreate":
            memory.store.conn.execute("DELETE FROM memory_sessions")
            memory.store.conn.execute(
                "INSERT INTO memory_sessions VALUES (?,?,?,?)",
                ("default", "local-owner", "s", original),
            )
        else:
            memory.store.conn.execute("UPDATE memory_sessions SET data='[]'")
            memory.store.conn.execute("UPDATE memory_sessions SET data=?", (original,))
        memory.store.conn.commit()
        with pytest.raises(ValidationError):
            memory.read_page(Scope(), "s", replace(request, cursor=first.next_cursor))
    finally:
        memory.close()


def test_sqlite_old_fact_writer_invalidates_recall_cursor(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.db")
    try:
        for key in ("a", "b"):
            memory.put_fact(Scope(), "a", key, key, expected_version=0)
        request = query(max_items=1)
        first = memory.recall(Scope(), "a", request)
        memory.store.conn.execute("UPDATE memory_facts SET value='\"changed\"' WHERE key='a'")
        memory.store.conn.commit()
        with pytest.raises(ValidationError):
            memory.recall(Scope(), "a", replace(request, cursor=first.next_cursor))
    finally:
        memory.close()


class OldMemory:
    def __init__(self):
        self.backend_id = "old-client"
        self.inner = InMemoryMemory()

    def read(self, *args):
        return self.inner.read(*args)

    def facts(self, *args):
        return self.inner.facts(*args)


def test_legacy_adapter_limits_payload_but_marks_full_backend_read():
    backend = OldMemory()
    append_messages(backend.inner, 3)
    for key in ("a", "b"):
        backend.inner.put_fact(Scope(), "a", key, key, expected_version=0)
    adapter = api().LegacyMemoryRecallAdapter(backend)
    assert adapter.backend_id == backend.backend_id
    pages = collect(adapter.recall, Scope(), "a", query(max_items=1))
    assert [r["key"] for p in pages for r in p.items] == ["a", "b"]
    assert all(not p.backend_bounded for p in pages)
    first = adapter.read_page(Scope(), "s", query(max_items=1))
    backend.inner.append(
        Scope(), "s", {"role": "user", "content": "new"}, expected_revision=3, message_id="m3"
    )
    assert (
        adapter.read_page(Scope(), "s", query(max_items=1, cursor=first.next_cursor)).items[0][
            "content"
        ]
        == "1"
    )


def test_explicit_legacy_adapter_preserves_existing_memory_ports():
    backend = InMemoryMemory()
    adapter = api().LegacyMemoryRecallAdapter(backend)
    adapter.put_fact(Scope(), "a", "key", "value", expected_version=0)
    adapter.append(
        Scope(), "s", {"role": "user", "content": "hello"}, expected_revision=0, message_id="m1"
    )
    assert adapter.facts(Scope(), "a")[0]["value"] == "value"
    assert adapter.read(Scope(), "s")[0] == 1
    assert not adapter.read_page(Scope(), "s", query()).backend_bounded


def test_legacy_async_read_and_facts_are_awaitable():
    class AsyncOld(OldMemory):
        async def read(self, *args):
            return super().read(*args)

        async def facts(self, *args):
            return super().facts(*args)

    backend = AsyncOld()
    append_messages(backend.inner, 1)
    adapter = api().LegacyMemoryRecallAdapter(backend)

    async def check():
        assert (await adapter.read_page(Scope(), "s", query())).items[0]["content"] == "0"
        assert (await adapter.recall(Scope(), "a", query())).items == []

    asyncio.run(check())


def test_thread_bridge_uses_legacy_fallback_and_rejects_native_async_paging():
    backend = OldMemory()
    append_messages(backend.inner, 1)
    bridge = ThreadedMemoryAdapter(backend)

    async def check():
        assert not (await bridge.read_page(Scope(), "s", query())).backend_bounded
        assert not (await bridge.recall(Scope(), "a", query())).backend_bounded

    asyncio.run(check())

    class AsyncPages(OldMemory):
        async def read_page(self, *args):
            pass

    with pytest.raises(ValidationError):
        ThreadedMemoryAdapter(AsyncPages())

    class AsyncValidator(OldMemory):
        async def validate_facts(self, *args):
            pass

    with pytest.raises(ValidationError):
        ThreadedMemoryAdapter(AsyncValidator())


def test_thread_bridge_checks_actual_old_client_after_it_is_replaced():
    started, release = threading.Event(), threading.Event()

    class BlockingOld(OldMemory):
        def read(self, *args):
            started.set()
            assert release.wait(5)
            self.backend_id = "mutated-old-client"
            return super().read(*args)

    old = BlockingOld()
    bridge = ThreadedMemoryAdapter(old)

    async def check():
        task = asyncio.create_task(bridge.read_page(Scope(), "s", query()))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            bridge.backend = OldMemory()
            release.set()
            with pytest.raises(DefinitionMismatch):
                await task
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("legacy", [False, True])
def test_thread_recall_pins_delegated_method_owner_not_only_proxy_identity(legacy):
    started, release = threading.Event(), threading.Event()

    class BlockingClient(InMemoryMemory):
        def block(self):
            started.set()
            assert release.wait(5)
            self.backend_id = "changed-old-client"

        def read(self, *args):
            if legacy:
                self.block()
            return super().read(*args)

        def read_page(self, *args):
            self.block()
            return super().read_page(*args)

    class Proxy:
        def __init__(self, inner):
            self.inner = inner

        @property
        def backend_id(self):
            return self.inner.backend_id

        def __getattr__(self, name):
            if legacy and name in {"read_page", "recall"}:
                raise AttributeError(name)
            return getattr(self.inner, name)

    proxy = Proxy(BlockingClient(backend_id="original-client"))
    bridge = ThreadedMemoryAdapter(proxy)

    async def check():
        task = asyncio.create_task(bridge.read_page(Scope(), "s", query()))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            proxy.inner = InMemoryMemory(backend_id="original-client")
            release.set()
            with pytest.raises(DefinitionMismatch):
                await task
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())


def test_fact_reference_validation_checks_current_version_scope_and_ttl(memory, monkeypatch):
    monkeypatch.setattr("ralf_agent.memory.time.time", lambda: 100)
    memory.put_fact(Scope(), "a", "key", "value", expected_version=0, expires_at=110)
    references = memory.recall(Scope(), "a", query()).items
    assert memory.validate_facts(Scope(), "a", references) is None
    with pytest.raises(ValidationError):
        memory.validate_facts(Scope(principal="other"), "a", references)
    with pytest.raises(ValidationError):
        memory.validate_facts(Scope(), "another", references)
    monkeypatch.setattr("ralf_agent.memory.time.time", lambda: 111)
    with pytest.raises(ValidationError):
        memory.validate_facts(Scope(), "a", references)
    monkeypatch.setattr("ralf_agent.memory.time.time", lambda: 100)
    memory.put_fact(Scope(), "a", "key", "new", expected_version=1, expires_at=110)
    with pytest.raises(ValidationError):
        memory.validate_facts(Scope(), "a", references)


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {},
        ["bad"],
        [{"key": "key"}],
        [{"key": "key", "value": float("nan"), "version": 1, "expires_at": None}],
        [{"key": "key", "value": "value", "version": True, "expires_at": None}],
        [{"key": "key", "value": "value", "version": 1, "expires_at": True}],
        [{"key": "key", "value": "value", "version": 1, "expires_at": "later"}],
        [{"key": "", "value": "value", "version": 1, "expires_at": None}],
    ],
)
def test_fact_reference_validation_rejects_bad_records_before_backend_access(memory, invalid):
    with pytest.raises(ValidationError):
        memory.validate_facts(Scope(), "a", invalid)


def test_sqlite_fact_reference_validation_reads_metadata_without_large_values(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.db")
    try:
        memory.put_fact(Scope(), "a", "key", "x" * 20000, expected_version=0)
        references = memory.facts(Scope(), "a")
        statements = []
        memory.store.conn.set_trace_callback(statements.append)
        assert memory.validate_facts(Scope(), "a", references) is None
        memory.store.conn.set_trace_callback(None)
        assert statements and not any("value" in statement.lower() for statement in statements)
        memory.store.conn.execute("DELETE FROM memory_facts")
        memory.store.conn.commit()
        with pytest.raises(ValidationError):
            memory.validate_facts(Scope(), "a", references)
    finally:
        memory.store.conn.set_trace_callback(None)
        memory.close()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_legacy_fact_validator_reads_full_backend_and_checks_original_value(asynchronous):
    class Legacy(OldMemory):
        reads = 0

        def facts(self, *args):
            self.reads += 1
            if asynchronous:

                async def read():
                    return super(Legacy, self).facts(*args)

                return read()
            return super().facts(*args)

    backend = Legacy()
    backend.inner.put_fact(Scope(), "a", "key", "value", expected_version=0)
    original = backend.inner.facts(Scope(), "a")
    adapter = api().LegacyMemoryRecallAdapter(backend)

    async def check():
        from ralf_agent.memory import memory_call

        assert await memory_call(adapter.validate_facts, Scope(), "a", original) is None
        assert backend.reads == 1
        changed = [{**original[0], "value": "forged"}]
        with pytest.raises(ValidationError):
            await memory_call(adapter.validate_facts, Scope(), "a", changed)
        with pytest.raises(ValidationError):
            await memory_call(adapter.validate_facts, Scope(), "a", [{"key": "bad"}])
        assert backend.reads == 2

    asyncio.run(check())


@pytest.mark.parametrize("legacy", [False, True])
def test_threaded_fact_validator_fallback_pins_actual_bound_client(legacy):
    started, release = threading.Event(), threading.Event()

    class Client(InMemoryMemory):
        def block(self):
            started.set()
            assert release.wait(5)
            self.backend_id = "changed-client"

        def validate_facts(self, *args):
            self.block()
            return super().validate_facts(*args)

        def facts(self, *args):
            if legacy:
                self.block()
            return super().facts(*args)

    class Proxy:
        def __init__(self, inner):
            self.inner = inner

        @property
        def backend_id(self):
            return self.inner.backend_id

        def __getattr__(self, name):
            if legacy and name == "validate_facts":
                raise AttributeError(name)
            return getattr(self.inner, name)

    proxy = Proxy(Client(backend_id="original"))
    proxy.inner.put_fact(Scope(), "a", "key", "value", expected_version=0)
    references = InMemoryMemory.facts(proxy.inner, Scope(), "a")
    bridge = ThreadedMemoryAdapter(proxy)

    async def check():
        task = asyncio.create_task(bridge.validate_facts(Scope(), "a", references))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            proxy.inner = InMemoryMemory(backend_id="original")
            release.set()
            with pytest.raises(DefinitionMismatch):
                await task
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())
