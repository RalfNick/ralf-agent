import importlib
from dataclasses import replace

import pytest

from ralf_agent.errors import (
    AuthorizationDenied,
    BudgetExceeded,
    DefinitionMismatch,
    NotFound,
    ValidationError,
)
from ralf_agent.types import Scope, digest


def api():
    return importlib.import_module("ralf_agent.artifacts")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    a = api()
    s = (
        a.InMemoryArtifactStore(max_bytes=1024, capacity=2)
        if request.param == "memory"
        else a.SQLiteArtifactStore(tmp_path / "artifacts.sqlite", max_bytes=1024, capacity=2)
    )
    yield s
    s.close()


def test_content_addressed_put_get_detachment_and_reference_roundtrip(store):
    a = api()
    scope = Scope()
    value = {"evidence": ["confirmed", {"value": 7}]}
    ref = store.put(scope, "results", value)
    assert ref.content_digest == digest(value)
    assert store.put(scope, "results", value) == ref
    value["evidence"][1]["value"] = 99
    actual = store.get(scope, ref)
    assert actual["evidence"][1]["value"] == 7
    actual["evidence"].clear()
    assert len(store.get(scope, ref)["evidence"]) == 2
    assert a.ArtifactReference.from_dict(ref.to_dict()) == ref
    with pytest.raises((AttributeError, TypeError)):
        ref.byte_length = 1


def test_scope_and_backend_mismatch_fail_before_disclosure(store):
    scope = Scope("workspace", "alice")
    ref = store.put(scope, "results", {"private": "evidence"})
    for foreign in [Scope("other", "alice"), Scope("workspace", "bob")]:
        with pytest.raises(AuthorizationDenied):
            store.get(foreign, ref)
        with pytest.raises(AuthorizationDenied):
            store.delete(foreign, ref)
    other = api().InMemoryArtifactStore()
    try:
        with pytest.raises(DefinitionMismatch):
            other.get(scope, ref)
    finally:
        other.close()


def test_namespace_capacity_duplicate_and_explicit_delete(store):
    scope = Scope()
    first = store.put(scope, "a", {"n": 1})
    store.put(scope, "a", {"n": 2})
    assert store.put(scope, "a", {"n": 1}) == first
    with pytest.raises(BudgetExceeded):
        store.put(scope, "a", {"n": 3})
    store.put(scope, "b", {"n": 3})
    store.put(Scope("other", "owner"), "a", {"n": 3})
    assert store.delete(scope, first) is True
    assert store.delete(scope, first) is False
    with pytest.raises(NotFound):
        store.get(scope, first)
    store.put(scope, "a", {"n": 3})


def test_finite_expiry_is_part_of_immutable_reference_and_expired_capacity_is_retained(
    store, monkeypatch
):
    a = api()
    monkeypatch.setattr(a.time, "time", lambda: 100)
    first = store.put(Scope(), "ttl", {"n": 1}, expires_at=101)
    second = store.put(Scope(), "ttl", {"n": 1}, expires_at=102)
    assert first != second and store.get(Scope(), first) == {"n": 1}
    monkeypatch.setattr(a.time, "time", lambda: 103)
    with pytest.raises(NotFound):
        store.get(Scope(), first)
    with pytest.raises(BudgetExceeded):
        store.put(Scope(), "ttl", {"n": 2})
    assert store.delete(Scope(), first)
    store.put(Scope(), "ttl", {"n": 2})


@pytest.mark.parametrize("expiry", [True, "1", float("nan"), float("inf"), 10**400])
def test_invalid_expiry_never_becomes_permanent_storage(store, expiry):
    with pytest.raises(ValidationError):
        store.put(Scope(), "results", {}, expires_at=expiry)


def test_utf8_bytes_and_bounded_read_are_enforced(store):
    with pytest.raises(ValidationError):
        store.put(Scope(), "results", "中" * 400)
    with pytest.raises(ValidationError):
        store.put(Scope(), "results", float("nan"))
    with pytest.raises(ValidationError):
        store.put(Scope(), "results", "\ud800")
    ref = store.put(Scope(), "results", "中" * 100)
    with pytest.raises(ValidationError):
        store.get(Scope(), ref, max_bytes=100)
    for limit in [True, 0, 2 * 1024 * 1024]:
        with pytest.raises(ValidationError):
            store.get(Scope(), ref, max_bytes=limit)


def test_forged_reference_is_rejected_and_closed_store_cannot_continue(store):
    ref = store.put(Scope(), "results", {"n": 1})
    with pytest.raises(ValidationError):
        replace(ref, byte_length=1)
    data = ref.to_dict()
    data["extra"] = "injected"
    with pytest.raises(ValidationError):
        api().ArtifactReference.from_dict(data)
    store.close()
    with pytest.raises(ValidationError):
        store.get(Scope(), ref)
    with pytest.raises(ValidationError):
        store.put(Scope(), "results", {})


def test_sqlite_reopen_integrity_and_uncommitted_transaction_are_guarded(tmp_path):
    a = api()
    path = tmp_path / "artifacts.sqlite"
    first = a.SQLiteArtifactStore(path)
    ref = first.put(Scope(), "results", {"evidence": "confirmed"})
    first.close()
    with a.SQLiteArtifactStore(path) as reopened:
        assert reopened.get(Scope(), ref) == {"evidence": "confirmed"}
        reopened.conn.execute("BEGIN")
        with pytest.raises(ValidationError):
            reopened.put(Scope(), "results", {"different": 1})
        reopened.conn.execute("ROLLBACK")
        reopened.conn.execute(
            "UPDATE ralf_artifacts SET payload=? WHERE artifact_id=?",
            ('{"changed":true}', ref.artifact_id),
        )
        with pytest.raises(ValidationError):
            reopened.get(Scope(), ref)


@pytest.mark.parametrize(
    "options",
    [{"max_bytes": True}, {"max_bytes": 2 * 1024 * 1024}, {"capacity": 0}, {"capacity": 1000000}],
)
def test_bad_configuration_rejected_before_creating_database(tmp_path, options):
    path = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        api().SQLiteArtifactStore(path, **options)
    assert not path.exists()


def test_sqlite_hard_links_and_path_replacement_are_rejected(tmp_path):
    import os

    a = api()
    path = tmp_path / "artifacts.sqlite"
    with a.SQLiteArtifactStore(path) as store:
        ref = store.put(Scope(), "results", {})
        alias = tmp_path / "alias.sqlite"
        os.link(path, alias)
        with pytest.raises(ValidationError):
            a.SQLiteArtifactStore(alias)
        with pytest.raises(ValidationError):
            store.get(Scope(), ref)
        alias.unlink()
        path.rename(tmp_path / "moved.sqlite")
        path.touch()
        with pytest.raises(ValidationError):
            store.get(Scope(), ref)
