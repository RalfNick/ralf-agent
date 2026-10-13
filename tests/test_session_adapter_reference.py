"""Independent Session data, with no native SDK Memory delegate."""

import asyncio
import importlib
import inspect
import os
import sqlite3
from dataclasses import asdict

import pytest

from ralf_agent import Scope
from ralf_agent.errors import DefinitionMismatch, IdempotencyConflict, ValidationError


def reference():
    try:
        return importlib.import_module("ralf_agent.session_adapter_contract_reference")
    except ModuleNotFoundError:
        pytest.fail("The independent Session adapter reference is missing")


def test_fixture_independently_isolates_both_scope_fields_across_eight_real_addresses(tmp_path):
    from ralf_agent.memory import memory_call

    async def scenario():
        session = reference().offline_session_fixture().prepare("S03", tmp_path)
        try:
            actual = {
                (address.scope.workspace, address.scope.principal, address.session_id)
                for address in session.addresses
            }
            expected = {
                (workspace, principal, address)
                for workspace in ("contract-alpha", "contract-beta")
                for principal in ("author-a", "author-b")
                for address in ("first", "second")
            }
            assert actual == expected and len(session.addresses) == 8
            for address in session.addresses:
                message = {"scope": asdict(address.scope), "address": address.session_id}
                assert await memory_call(session.store.read, address.scope, address.session_id) == (
                    0,
                    [],
                )
                assert (
                    await memory_call(
                        session.store.append,
                        address.scope,
                        address.session_id,
                        message,
                        expected_revision=0,
                        message_id="same-id-in-every-scope",
                    )
                    == 1
                )
            for address in session.addresses:
                message = {"scope": asdict(address.scope), "address": address.session_id}
                assert await memory_call(session.store.read, address.scope, address.session_id) == (
                    1,
                    [message],
                )
                receipt = await memory_call(
                    session.store.inspect_message,
                    address.scope,
                    address.session_id,
                    "same-id-in-every-scope",
                )
                assert receipt["scope"] == asdict(address.scope)
                assert receipt["receipt"] == {"revision": 1, "message": message}
            with sqlite3.connect(session.store.source.path) as connection:
                rows = list(
                    connection.execute("SELECT workspace,principal,address FROM session_messages")
                )
                assert set(rows) == expected and len(rows) == 8
        finally:
            for resource in session.resources:
                await resource.resource.aclose()

    asyncio.run(scenario())


def test_independent_core_orders_scoped_messages_and_deduplicates_before_cas(tmp_path):
    api = reference()
    source = api.ReferenceSessionSource(tmp_path / "sessions.sqlite")
    store = api.ReferenceSQLiteSessionStore(source)
    scope = Scope("project", "person")
    try:
        assert store.read(scope, "a") == (0, [])
        message = {"role": "user", "content": {"value": [1, 2]}}
        assert store.append(scope, "a", message, expected_revision=0, message_id="one") == 1
        message["content"]["value"].append(3)
        assert (
            store.append(scope, "a", {"content": "two"}, expected_revision=1, message_id="two") == 2
        )
        same = {"content": {"value": [1, 2]}, "role": "user"}
        assert store.append(scope, "a", same, expected_revision=0, message_id="one") == 1
        for revision in (0, 3):
            with pytest.raises(ValidationError):
                store.append(
                    scope, "a", {"content": "new"}, expected_revision=revision, message_id="new"
                )
        with pytest.raises(IdempotencyConflict):
            store.append(
                scope, "a", {"content": "different"}, expected_revision=2, message_id="one"
            )
        revision, messages = store.read(scope, "a")
        assert revision == 2 and messages == [same, {"content": "two"}]
        messages[0]["content"]["value"].append(99)
        assert store.read(scope, "a") == (2, [same, {"content": "two"}])
        assert store.read(scope, "b") == (0, [])
        assert store.read(Scope("project", "other"), "a") == (0, [])
        assert not hasattr(store, "inspect_message")
        assert not hasattr(store, "session_receipt_version")
        assert "SQLiteMemory" not in inspect.getsource(api)
    finally:
        source.close()


def test_independent_receipts_survive_reopen_and_keep_original_revision(tmp_path):
    api = reference()
    path = tmp_path / "sessions.sqlite"
    source = api.ReferenceSessionSource(path)
    store = api.ReferenceSQLiteReceiptSessionStore(source)
    scope = Scope()
    first = {"role": "assistant", "content": "one"}
    identity = store.backend_id
    try:
        assert store.inspect_message(scope, "s", "one") == {
            "scope": asdict(scope),
            "session_id": "s",
            "message_id": "one",
            "revision": 0,
            "receipt": None,
        }
        store.append(scope, "s", first, expected_revision=0, message_id="one")
        store.append(scope, "s", {"content": "two"}, expected_revision=1, message_id="two")
        source.reopen()
        assert store.inspect_message(scope, "s", "one")["receipt"] == {
            "revision": 1,
            "message": first,
        }
        assert store.inspect_message(scope, "other", "one")["receipt"] is None
        assert store.inspect_message(Scope(principal="other"), "s", "one")["receipt"] is None
    finally:
        source.close()
    other = api.ReferenceSessionSource(path)
    try:
        reopened = api.ReferenceSQLiteReceiptSessionStore(other)
        assert reopened.backend_id == identity
        assert reopened.read(scope, "s")[0] == 2
        assert reopened.inspect_message(scope, "s", "one")["receipt"] == {
            "revision": 1,
            "message": first,
        }
    finally:
        other.close()


@pytest.mark.parametrize("operation", ["read", "append", "inspect_message"])
def test_live_same_path_database_replacement_is_refused_and_close_never_writes_replacement(
    tmp_path, operation
):
    api = reference()
    path = tmp_path / "sessions.sqlite"
    source = api.ReferenceSessionSource(path)
    store = api.ReferenceSQLiteReceiptSessionStore(source)
    descriptor = source._file_descriptor
    alternate = api.ReferenceSessionSource(tmp_path / "alternate.sqlite")
    other_identity = api.ReferenceSQLiteReceiptSessionStore(alternate).backend_id
    alternate.close()
    os.replace(alternate.path, path)
    with sqlite3.connect(path) as connection:
        before = list(connection.execute("SELECT kind,count FROM audit"))
    try:
        with pytest.raises(DefinitionMismatch):
            if operation == "read":
                store.read(Scope(), "s")
            elif operation == "append":
                store.append(Scope(), "s", {}, expected_revision=0, message_id="one")
            else:
                store.inspect_message(Scope(), "s", "one")
    finally:
        source.close()
    assert source._closed and source._file_descriptor is None
    with pytest.raises(OSError):
        os.fstat(descriptor)
    with sqlite3.connect(path) as connection:
        assert list(connection.execute("SELECT kind,count FROM audit")) == before
    reopened = api.ReferenceSessionSource(path)
    try:
        assert api.ReferenceSQLiteReceiptSessionStore(reopened).backend_id != store.backend_id
        assert other_identity != store.backend_id
    finally:
        reopened.close()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_receipt_lost_ack_persists_exact_data_before_raising(tmp_path, asynchronous):
    api = reference()
    source = api.ReferenceSessionSource(tmp_path / "sessions.sqlite")
    cls = (
        api.AsyncReferenceSQLiteReceiptSessionStore
        if asynchronous
        else api.ReferenceSQLiteReceiptSessionStore
    )
    store = cls(source)
    store._fault = "append-ack-lost"
    message = {"content": "accepted"}

    async def scenario():
        from ralf_agent.memory import memory_call

        with pytest.raises(Exception, match="Memory backend operation failed"):
            await memory_call(
                store.append, Scope(), "s", message, expected_revision=0, message_id="one"
            )
        receipt = await memory_call(store.inspect_message, Scope(), "s", "one")
        assert receipt["receipt"] == {"revision": 1, "message": message}
        store._fault = None
        assert (
            await memory_call(
                store.append, Scope(), "s", message, expected_revision=0, message_id="one"
            )
            == 1
        )
        assert source.audit()["save_count"] == 1

    try:
        asyncio.run(scenario())
    finally:
        source.close()
