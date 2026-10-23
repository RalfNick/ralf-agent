import asyncio
from contextlib import closing
from dataclasses import asdict

import pytest

from relf_agent import (
    InMemoryMemory,
    Scope,
    SessionBindingResource,
    SQLiteMemory,
    SQLiteStore,
    ThreadedMemoryAdapter,
)
from relf_agent.errors import ValidationError
from relf_agent.session_receipts import supports_remote_session, validate_inspection
from relf_agent.types import canonical


@pytest.fixture(params=["memory", "sqlite"])
def backend(request, tmp_path):
    value = (
        InMemoryMemory(backend_id="receipt-memory")
        if request.param == "memory"
        else SQLiteMemory(tmp_path / "data.sqlite")
    )
    yield value
    close = getattr(value, "close", None)
    if close is not None:
        close()


def test_default_receipt_is_exact_scoped_and_preserves_original_revision(backend):
    scope = Scope()
    assert supports_remote_session(backend)
    assert backend.inspect_message(scope, "s", "first") == {
        "scope": asdict(scope),
        "session_id": "s",
        "message_id": "first",
        "revision": 0,
        "receipt": None,
    }
    message = {"role": "assistant", "task": {"target": 1}, "content": ["中文🙂"]}
    backend.append(scope, "s", message, expected_revision=0, message_id="first")
    backend.append(scope, "s", {"content": "second"}, expected_revision=1, message_id="second")
    assert backend.append(scope, "s", message, expected_revision=0, message_id="first") == 1
    receipt = backend.inspect_message(scope, "s", "first")
    assert receipt == {
        "scope": asdict(scope),
        "session_id": "s",
        "message_id": "first",
        "revision": 2,
        "receipt": {"revision": 1, "message": message},
    }
    assert validate_inspection(receipt, scope, "s", "first") == receipt
    assert backend.inspect_message(Scope("other", scope.principal), "s", "first")["receipt"] is None
    assert backend.inspect_message(scope, "other", "first")["receipt"] is None
    assert backend.inspect_message(scope, "s", "missing")["revision"] == 2
    receipt["receipt"]["message"]["content"].append("caller change")
    assert backend.inspect_message(scope, "s", "first")["receipt"]["message"] == message


def test_default_session_view_inspects_namespaced_receipt_without_reading_history(
    backend, monkeypatch
):
    async def run():
        view = SessionBindingResource(
            backend, namespaces=("red", "blue"), default_namespace="red"
        ).select({}, Scope())
        await view.append(
            Scope(), "s", {"content": "original"}, expected_revision=0, message_id="m"
        )
        monkeypatch.setattr(
            backend, "read", lambda *args: pytest.fail("inspection must not load history")
        )
        receipt = await view.inspect_message(Scope(), "s", "m")
        assert receipt["session_id"] == 'ralf-session-v1:["red","s"]'
        assert receipt["receipt"]["message"] == {"content": "original"}
        other = SessionBindingResource(
            backend, namespaces=("blue",), default_namespace="blue"
        ).select({}, Scope())
        assert (await other.inspect_message(Scope(), "s", "m"))["receipt"] is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", None),
        ("scope", {}),
        ("session_id", None),
        ("session_id", True),
        ("session_id", " "),
        ("message_id", None),
        ("message_id", True),
        ("message_id", " "),
    ],
)
def test_invalid_inspection_address_fails_before_read(backend, field, value):
    args = {"scope": Scope(), "session_id": "s", "message_id": "m", field: value}
    with pytest.raises(ValidationError):
        backend.inspect_message(**args)


def test_inspection_does_not_claim_a_non_record_message(backend):
    backend.append(Scope(), "s", [], expected_revision=0, message_id="m")
    with pytest.raises(ValidationError):
        backend.inspect_message(Scope(), "s", "m")


def test_sqlite_receipt_survives_reopen_and_does_not_parse_clean_history(tmp_path, monkeypatch):
    path = tmp_path / "data.sqlite"
    with SQLiteStore(path) as store:
        original = SQLiteMemory(store)
        for i in range(200):
            original.append(Scope(), "s", {"content": i}, expected_revision=i, message_id=f"m{i}")
        original.close()
        assert store.conn.execute("SELECT 1").fetchone()[0] == 1
    with closing(SQLiteMemory(path)) as restored:
        monkeypatch.setattr(
            restored,
            "_records",
            lambda *args: pytest.fail("clean receipt cannot decode full history"),
        )
        receipt = restored.inspect_message(Scope(), "s", "m3")
        assert receipt["revision"] == 200
        assert receipt["receipt"] == {"revision": 4, "message": {"content": 3}}


def test_sqlite_legacy_writer_invalidates_receipt_projection(tmp_path):
    with closing(SQLiteMemory(tmp_path / "data.sqlite")) as backend:
        backend.append(Scope(), "s", {"content": "old"}, expected_revision=0, message_id="m")
        backend.append(Scope(), "s", {"content": "removed"}, expected_revision=1, message_id="gone")
        backend.store.conn.execute(
            "UPDATE memory_sessions SET data=? WHERE workspace=? AND principal=? AND session=?",
            (
                canonical([["m", {"content": "changed"}], ["new", {"content": "new"}]]),
                Scope().workspace,
                Scope().principal,
                "s",
            ),
        )
        assert backend.inspect_message(Scope(), "s", "gone")["receipt"] is None
        assert backend.inspect_message(Scope(), "s", "m")["receipt"] == {
            "revision": 1,
            "message": {"content": "changed"},
        }
        assert backend.inspect_message(Scope(), "s", "new")["receipt"]["revision"] == 2


def test_sqlite_ambiguous_legacy_message_identity_is_not_a_valid_receipt(tmp_path):
    with closing(SQLiteMemory(tmp_path / "data.sqlite")) as backend:
        backend.append(Scope(), "s", {"content": "old"}, expected_revision=0, message_id="m")
        backend.store.conn.execute(
            "UPDATE memory_sessions SET data=? WHERE workspace=? AND principal=? AND session=?",
            (
                canonical([["m", {"content": "old"}], ["m", {"content": "other"}]]),
                Scope().workspace,
                Scope().principal,
                "s",
            ),
        )
        with pytest.raises(ValidationError):
            backend.inspect_message(Scope(), "s", "m")


def test_threaded_default_session_receipts_use_the_same_async_port():
    async def run():
        backend = InMemoryMemory(backend_id="threaded-receipts")
        bridge = ThreadedMemoryAdapter(backend)
        assert supports_remote_session(bridge)
        await bridge.append(
            Scope(), "s", {"content": "original"}, expected_revision=0, message_id="m"
        )
        receipt = await bridge.inspect_message(Scope(), "s", "m")
        assert receipt["receipt"] == {"revision": 1, "message": {"content": "original"}}

    asyncio.run(run())


def test_threaded_receipt_refuses_same_identity_backend_replacement_during_read():
    import threading

    from relf_agent.errors import DefinitionMismatch

    async def run():
        started, finish = threading.Event(), threading.Event()

        class Delayed(InMemoryMemory):
            def inspect_message(self, *args):
                started.set()
                assert finish.wait(5)
                return super().inspect_message(*args)

        backend = Delayed(backend_id="stable")
        backend.append(Scope(), "s", {"content": "old"}, expected_revision=0, message_id="m")
        bridge = ThreadedMemoryAdapter(backend)
        pending = asyncio.create_task(bridge.inspect_message(Scope(), "s", "m"))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            bridge.backend = InMemoryMemory(backend_id="stable")
        finally:
            finish.set()
        with pytest.raises(DefinitionMismatch):
            await pending

    asyncio.run(run())


def test_threaded_bridge_refuses_mixed_async_inspection_at_construction():
    class Mixed(InMemoryMemory):
        async def inspect_message(self, *args):
            return super().inspect_message(*args)

    with pytest.raises(ValidationError):
        ThreadedMemoryAdapter(Mixed())


@pytest.mark.parametrize("preexisting", [False, True])
def test_sqlite_receipt_keeps_original_message_id_type(tmp_path, preexisting):
    path = tmp_path / "typed.sqlite"
    with closing(SQLiteMemory(path)) as backend:
        backend.append(Scope(), "s", {"content": "old"}, expected_revision=0, message_id=1)
    with closing(SQLiteMemory(path)) as backend:
        # A clean projection created by an older writer also lost the ID type.
        if preexisting:
            backend.store.conn.execute("UPDATE memory_session_items SET message_id=?", ("1",))
        assert backend.inspect_message(Scope(), "s", "1")["receipt"] is None
        backend.append(Scope(), "s", {"content": "new"}, expected_revision=1, message_id="1")
        assert backend.inspect_message(Scope(), "s", "1")["receipt"] == {
            "revision": 2,
            "message": {"content": "new"},
        }


def test_sqlite_receipt_after_legacy_writer_clean_projection_keeps_id_type(tmp_path):
    with closing(SQLiteMemory(tmp_path / "legacy.sqlite")) as backend:
        backend.append(Scope(), "s", {"content": "first"}, expected_revision=0, message_id="old")
        backend.inspect_message(Scope(), "s", "old")
        backend.store.conn.execute(
            "UPDATE memory_sessions SET data=?",
            (canonical([[1, {"content": "numeric"}], ["1", {"content": "text"}]]),),
        )
        backend.store.conn.execute("DELETE FROM memory_session_items")
        backend.store.conn.executemany(
            "INSERT INTO memory_session_items VALUES (?,?,?,?,?,?)",
            [
                (Scope().workspace, Scope().principal, "s", seq, "1", canonical(message))
                for seq, message in enumerate([{"content": "numeric"}, {"content": "text"}], 1)
            ],
        )
        backend.store.conn.execute("UPDATE memory_session_index_state SET revision=2,dirty=0")
        assert backend.inspect_message(Scope(), "s", "1")["receipt"] == {
            "revision": 2,
            "message": {"content": "text"},
        }
