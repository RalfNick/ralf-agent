"""Strict native history uses complete bounded Session pages and no full reads."""

import asyncio
import importlib
import json
from dataclasses import replace

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.memory import InMemoryMemory, SQLiteMemory
from ralf_agent.recall import LegacyMemoryRecallAdapter, RecallPage
from ralf_agent.types import Scope, canonical

STREAM = "a" * 64
ADDRESS = "ralf-native-model-history-v1:" + STREAM


def api():
    try:
        return importlib.import_module("ralf_agent.native_session_history")
    except ModuleNotFoundError:
        pytest.fail("Complete native Session read adapter is missing")


def envelope(seq):
    return {
        "kind": "ralf-native-model-turn",
        "version": 1,
        "stream": STREAM,
        "source": {
            "root_run_id": f"root-{seq}",
            "run_id": f"run-{seq}",
            "node": "root",
            "release_digest": "b" * 64,
            "turn_id": f"turn-{seq}",
            "turn_seq": seq,
        },
        "history": [
            {"role": "system", "content": "System"},
            {"role": "user", "content": f"task-{seq}"},
            {"role": "assistant", "content": f"answer-{seq}", "tool_calls": []},
        ],
        "final_digest": "c" * 64,
    }


@pytest.fixture(params=["memory", "sqlite"])
def backend(request, tmp_path):
    value = (
        InMemoryMemory() if request.param == "memory" else SQLiteMemory(tmp_path / "memory.sqlite")
    )
    yield value
    if request.param == "sqlite":
        value.close()


def append(backend, count):
    for seq in range(count):
        backend.append(
            Scope(), ADDRESS, envelope(seq), expected_revision=seq, message_id=f"native-{seq}"
        )


def test_native_reader_restores_append_order_across_complete_real_pages(backend):
    append(backend, 128)
    result = asyncio.run(api().read_native_history(backend, Scope(), ADDRESS, stream=STREAM))
    assert set(result) == {"snapshot_id", "revision", "turns"}
    assert result["revision"] == 128
    assert json.loads(result["snapshot_id"])["revision"] == 128
    assert [turn["source"]["turn_seq"] for turn in result["turns"]] == list(range(128))
    result["turns"][0]["history"][1]["content"] = "mutated"
    again = asyncio.run(api().read_native_history(backend, Scope(), ADDRESS, stream=STREAM))
    assert again["turns"][0]["history"][1]["content"] == "task-0"


def test_native_reader_empty_snapshot_is_complete(backend):
    result = asyncio.run(api().read_native_history(backend, Scope(), ADDRESS, stream=STREAM))
    assert result["turns"] == []
    assert result["revision"] == 0


def test_native_reader_keeps_two_large_valid_turns_that_cannot_share_one_page(backend):
    original = [envelope(0), envelope(1)]
    for seq, value in enumerate(original):
        value["history"][-1]["content"] = "x" * 600_000
        backend.append(Scope(), ADDRESS, value, expected_revision=seq, message_id=f"large-{seq}")
    result = asyncio.run(api().read_native_history(backend, Scope(), ADDRESS, stream=STREAM))
    assert result["revision"] == 2
    assert result["turns"] == original


def test_native_reader_accepts_maximum_envelope_in_original_one_million_character_page(backend):
    original = envelope(0)
    original["history"][-1]["content"] += "x" * (999_998 - len(canonical(original)))
    assert len(canonical(original)) == 999_998
    backend.append(Scope(), ADDRESS, original, expected_revision=0, message_id="largest")
    result = asyncio.run(api().read_native_history(backend, Scope(), ADDRESS, stream=STREAM))
    assert result["revision"] == 1
    assert result["turns"] == [original]


class PageSource:
    backend_id = "custom-native-test"

    def __init__(self, pages):
        self.pages = iter(pages)

    async def read_page(self, scope, address, query):
        assert scope == Scope()
        assert address == ADDRESS
        assert (query.text, query.max_items, query.scan_limit, query.max_chars) == (
            None,
            1,
            1,
            1_000_000,
        )
        return next(self.pages)

    def read(self, *args):
        pytest.fail("Native reading must never use an unbounded read")


def page(items, *, cursor=None, revision=None, **kwargs):
    revision = len(items) if revision is None else revision
    return RecallPage(
        items,
        cursor,
        len(canonical(items)),
        len(items),
        0,
        canonical({"generation": 0, "revision": revision}),
        **kwargs,
    )


@pytest.mark.parametrize(
    "change",
    [
        "unbounded",
        "skipped",
        "scanned",
        "revision",
        "early_end",
        "snapshot",
        "cursor",
        "duplicate",
        "stream",
        "oversize",
        "lazy",
    ],
)
def test_native_reader_rejects_incomplete_or_untrusted_page_evidence(change):
    first = page([envelope(0)], revision=1)
    pages = [first]
    if change == "unbounded":
        pages = [replace(first, backend_bounded=False)]
    elif change == "skipped":
        pages = [replace(first, scanned=2, skipped=1)]
    elif change == "scanned":
        pages = [replace(first, scanned=2)]
    elif change == "revision":
        pages = [replace(first, snapshot_id='{"revision":true}')]
    elif change == "early_end":
        pages = [replace(first, snapshot_id='{"revision":2}')]
    elif change == "snapshot":
        pages = [page([envelope(1)], cursor="one", revision=2), page([envelope(0)], revision=3)]
    elif change == "cursor":
        pages = [
            page([envelope(1)], cursor="one", revision=2),
            page([envelope(0)], cursor="one", revision=2),
        ]
    elif change == "duplicate":
        pages = [page([envelope(0)], cursor="one", revision=2), page([envelope(0)], revision=2)]
    elif change == "stream":
        item = envelope(0)
        item["stream"] = "d" * 64
        pages = [page([item])]
    elif change == "oversize":
        item = envelope(0)
        item["history"][-1]["content"] = "x" * 1_000_000
        pages = [page([item])]
    else:
        pages = [(item for item in [])]
    with pytest.raises(ValidationError):
        asyncio.run(api().read_native_history(PageSource(pages), Scope(), ADDRESS, stream=STREAM))


def test_native_reader_pins_snapshot_despite_append_between_pages(backend):
    append(backend, 101)

    class AppendDuringRead:
        backend_id = "snapshot-append-test"

        def read_page(self, scope, address, query):
            value = backend.read_page(scope, address, query)
            if query.cursor is None:
                backend.append(
                    scope, address, envelope(101), expected_revision=101, message_id="late"
                )
            return value

    result = asyncio.run(
        api().read_native_history(AppendDuringRead(), Scope(), ADDRESS, stream=STREAM)
    )
    assert result["revision"] == 101
    assert [turn["source"]["turn_seq"] for turn in result["turns"]] == list(range(101))


@pytest.mark.parametrize("limit", ["turns", "chars", "invalid_turns", "invalid_chars"])
def test_native_reader_rejects_limits_without_truncating(backend, limit):
    append(backend, 2)
    kwargs = {
        "turns": {"max_turns": 1},
        "chars": {"max_chars": 500},
        "invalid_turns": {"max_turns": True},
        "invalid_chars": {"max_chars": 8_388_609},
    }[limit]
    with pytest.raises(ValidationError):
        asyncio.run(api().read_native_history(backend, Scope(), ADDRESS, stream=STREAM, **kwargs))


def test_native_reader_rejects_legacy_adapter_before_any_unbounded_read():
    class Legacy:
        backend_id = "legacy"

        def read(self, *args):
            pytest.fail("Legacy adapter must be refused before I/O")

    with pytest.raises(ValidationError):
        asyncio.run(
            api().read_native_history(
                LegacyMemoryRecallAdapter(Legacy()), Scope(), ADDRESS, stream=STREAM
            )
        )


@pytest.mark.parametrize("boundary", ["address", "scope"])
def test_native_reader_checks_isolated_address_and_scope_before_data_io(boundary):
    scope = {} if boundary == "scope" else Scope()
    address = "ordinary-session" if boundary == "address" else ADDRESS
    with pytest.raises(ValidationError):
        asyncio.run(api().read_native_history(PageSource([]), scope, address, stream=STREAM))


def test_native_reader_rechecks_mutated_page_json_before_copying_a_deferred_value():
    entered = []

    def deferred():
        entered.append(True)
        yield "native"

    lazy = deferred()
    returned = page([envelope(0)])
    returned.items[0]["history"][2]["content"] = lazy
    try:
        with pytest.raises(ValidationError):
            asyncio.run(
                api().read_native_history(PageSource([returned]), Scope(), ADDRESS, stream=STREAM)
            )
        assert entered == []
        assert lazy.gi_frame is None
    finally:
        lazy.close()


def test_native_reader_refuses_session_view_legacy_fallback_before_full_read():
    from ralf_agent.binding_sessions import SessionBindingResource

    class Legacy:
        backend_id = "legacy-view"

        def read(self, *args):
            pytest.fail("Native data must refuse a view's legacy full read fallback")

        def append(self, *args, **kwargs):
            pytest.fail("Native read must never append")

    view = SessionBindingResource(Legacy()).select({}, Scope())
    with pytest.raises(ValidationError):
        asyncio.run(api().read_native_history(view, Scope(), ADDRESS, stream=STREAM))


@pytest.mark.parametrize("changed", ["client", "connection", "pool", "method"])
def test_native_reader_rejects_data_port_drift_during_its_await(changed):
    class Client:
        connection_pool = object()

    class DriftSource:
        backend_id = "drifting-native-source"

        def __init__(self):
            self._client = Client()
            self.connection = object()

        async def read_page(self, scope, address, query):
            if changed == "client":
                self._client = Client()
            elif changed == "connection":
                self.connection = object()
            elif changed == "pool":
                self._client.connection_pool = object()
            else:
                self.read_page = lambda *args: page([])
            return page([envelope(0)])

    with pytest.raises(DefinitionMismatch):
        asyncio.run(api().read_native_history(DriftSource(), Scope(), ADDRESS, stream=STREAM))
