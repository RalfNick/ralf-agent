"""Mutable root identity, scoped CAS and historical write receipts."""

import hashlib
import importlib.util
from dataclasses import asdict

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, IdempotencyConflict, ValidationError
from ralf_agent.types import digest
from ralf_agent.workspace import WorkspaceError

SCOPE = r.Scope()


def memory(files=None, **options):
    cls = getattr(r, "InMemoryWritableWorkspace", None)
    assert cls is not None, "public InMemoryWritableWorkspace is missing"
    return cls(files, version="1", **options)


def test_public_write_port_extends_original_read_contract():
    port = getattr(r, "WritableWorkspacePort", None)
    assert port is not None, "public WritableWorkspacePort is missing"
    for name in ("stat", "list", "read_text", "write_text", "query_write", "close"):
        assert callable(getattr(port, name, None))


def test_create_cas_and_historical_receipt_reuse_does_not_rewrite_current_file():
    port = memory()
    identity = port.identity
    first = port.write_text(SCOPE, "note", "A", expected_version=None, effect_key="k1")
    assert first == {
        "kind": "workspace-write-receipt",
        "version": "1",
        "scope": asdict(SCOPE),
        "effect_key": "k1",
        "request_digest": digest(
            {"scope": asdict(SCOPE), "path": "note", "text": "A", "expected_version": None}
        ),
        "path": "note",
        "sha256": hashlib.sha256(b"A").hexdigest(),
        "bytes": 1,
        "file_version": port.read_text(SCOPE, "note")["version"],
    }
    second = port.write_text(
        SCOPE, "note", "B", expected_version=first["file_version"], effect_key="k2"
    )
    assert port.stat(SCOPE, "note")["version"] == second["file_version"]
    assert port.query_write(SCOPE, "k1") == first
    assert port.write_text(SCOPE, "note", "A", expected_version=None, effect_key="k1") == first
    assert port.read_text(SCOPE, "note")["text"] == "B"
    assert port.identity == identity


def test_mutable_memory_instances_have_distinct_stable_root_identities():
    a, b = memory({"seed": "A"}), memory({"seed": "A"})
    assert a.identity != b.identity
    before = a.identity
    a.write_text(SCOPE, "new", "B", expected_version=None, effect_key="k")
    assert a.identity == before
    detached = a.identity
    detached.clear()
    assert a.identity == before


def test_cas_revisions_prevent_aba_even_when_content_returns_to_original():
    port = memory({"note": "A"})
    original = port.read_text(SCOPE, "note")["version"]
    second = port.write_text(SCOPE, "note", "B", expected_version=original, effect_key="b")
    third = port.write_text(
        SCOPE, "note", "A", expected_version=second["file_version"], effect_key="a"
    )
    assert third["file_version"] != original
    with pytest.raises(WorkspaceError):
        port.write_text(SCOPE, "note", "stale", expected_version=original, effect_key="stale")
    assert port.query_write(SCOPE, "stale") is None
    assert port.read_text(SCOPE, "note")["text"] == "A"


def test_constructor_receipts_and_query_results_are_detached():
    source = {"seed": "old"}
    port = memory(source)
    source["seed"] = "replacement"
    receipt = port.write_text(SCOPE, "note", "A", expected_version=None, effect_key="k")
    receipt["scope"]["workspace"] = "wrong"
    queried = port.query_write(SCOPE, "k")
    assert queried["scope"] == asdict(SCOPE)
    queried.clear()
    assert port.query_write(SCOPE, "k")["path"] == "note"
    assert port.read_text(SCOPE, "seed")["text"] == "old"


def test_duplicate_key_conflict_and_capacity_refuse_before_any_file_mutation():
    port = memory(capacity=1)
    first = port.write_text(SCOPE, "note", "A", expected_version=None, effect_key="k")
    with pytest.raises(IdempotencyConflict):
        port.write_text(SCOPE, "other", "B", expected_version=None, effect_key="k")
    with pytest.raises(WorkspaceError):
        port.write_text(SCOPE, "other", "B", expected_version=None, effect_key="other")
    assert port.query_write(SCOPE, "other") is None
    assert [v["path"] for v in port.list(SCOPE)["entries"]] == ["note"]
    assert port.write_text(SCOPE, "note", "A", expected_version=None, effect_key="k") == first


def test_create_only_and_compare_exact_original_version():
    port = memory({"note": "old"})
    for version in (None, "0" * 64):
        with pytest.raises(WorkspaceError):
            port.write_text(SCOPE, "note", "new", expected_version=version, effect_key="k")
    assert port.query_write(SCOPE, "k") is None
    assert port.read_text(SCOPE, "note")["text"] == "old"
    with pytest.raises(WorkspaceError):
        port.write_text(SCOPE, "missing/child", "A", expected_version=None, effect_key="parent")


@pytest.mark.parametrize(
    "overrides",
    [
        {"path": "../escape"},
        {"path": "/absolute"},
        {"path": ".ralf/state"},
        {"path": ".git/config"},
        {"path": "a//b"},
        {"path": "x\0"},
        {"path": ""},
        {"text": b"bytes"},
        {"text": "x\0"},
        {"text": "bad\ud800"},
        {"text": "12345"},
        {"text": "界界"},
        {"expected_version": True},
        {"expected_version": 1},
        {"expected_version": float("nan")},
        {"expected_version": ""},
        {"expected_version": "A" * 64},
        {"expected_version": "0" * 63},
        {"effect_key": True},
        {"effect_key": 1},
        {"effect_key": ""},
        {"effect_key": "  "},
        {"effect_key": "k" * 257},
        {"effect_key": b"k"},
        {"effect_key": "bad\ud800"},
    ],
)
def test_invalid_write_requests_are_rejected_before_mutation(overrides):
    port = memory({"seed": "old"}, max_bytes=4)
    arguments = {
        "path": "note",
        "text": "A",
        "expected_version": None,
        "effect_key": "k",
        **overrides,
    }
    with pytest.raises(ValidationError):
        port.write_text(SCOPE, **arguments)
    assert port.query_write(SCOPE, "k") is None
    assert [v["path"] for v in port.list(SCOPE)["entries"]] == ["seed"]


@pytest.mark.parametrize(
    "options",
    [
        {"max_bytes": True},
        {"max_bytes": 0},
        {"max_bytes": 16777217},
        {"max_bytes": 1.0},
        {"capacity": True},
        {"capacity": 0},
        {"capacity": 100001},
        {"capacity": 1.0},
    ],
)
def test_write_store_limits_are_strict_before_construction(options):
    with pytest.raises(ValidationError):
        memory(**options)


def test_allowed_scopes_have_separate_keys_and_denied_scope_has_no_mutation():
    other = r.Scope("workspace", "other")
    port = memory(scopes=[SCOPE, other])
    a = port.write_text(SCOPE, "a", "A", expected_version=None, effect_key="k")
    b = port.write_text(other, "b", "B", expected_version=None, effect_key="k")
    assert port.query_write(SCOPE, "k") == a
    assert port.query_write(other, "k") == b
    denied = r.Scope("denied", "owner")
    for call in (
        lambda: port.write_text(denied, "c", "C", expected_version=None, effect_key="k"),
        lambda: port.query_write(denied, "k"),
    ):
        with pytest.raises(AuthorizationDenied):
            call()
    assert [v["path"] for v in port.list(SCOPE)["entries"]] == ["a", "b"]


def test_empty_utf8_file_and_existing_parent_are_valid():
    port = memory({"directory/seed": "old"})
    receipt = port.write_text(
        SCOPE, "directory/empty", "", expected_version=None, effect_key="empty"
    )
    assert receipt["bytes"] == 0
    assert port.read_text(SCOPE, "directory/empty")["text"] == ""
    assert port.list(SCOPE, "directory")["entries"][0]["path"] == "directory/empty"


def test_successful_close_is_idempotent_and_refuses_all_later_operations():
    port = memory()
    port.close()
    port.close()
    for call in (
        lambda: port.write_text(SCOPE, "note", "A", expected_version=None, effect_key="k"),
        lambda: port.query_write(SCOPE, "k"),
        lambda: port.list(SCOPE),
    ):
        with pytest.raises(WorkspaceError):
            call()


def test_pure_receipt_validation_preserves_exact_request_and_scope():
    assert importlib.util.find_spec("ralf_agent.workspace_writes") is not None, (
        "write helpers missing"
    )
    from ralf_agent.workspace_writes import validate_write_receipt, write_receipt, write_request

    request, data = write_request(SCOPE, "note", "界", None, "k", max_bytes=3)
    assert data == "界".encode()
    value = write_receipt(SCOPE, "k", request, "0" * 64)
    accepted = validate_write_receipt(value, SCOPE, "k", request)
    assert accepted == value and accepted is not value
    for field, invalid in (
        ("scope", asdict(r.Scope("other", "owner"))),
        ("request_digest", "1" * 64),
        ("bytes", True),
        ("file_version", "bad"),
        ("extra", "ignored"),
    ):
        with pytest.raises(ValidationError):
            validate_write_receipt({**value, field: invalid}, SCOPE, "k", request)
