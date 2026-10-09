"""Atomic SQLite route storage and portable immutable Session identities."""

from dataclasses import replace

import pytest

import ralf_agent as r
from ralf_agent.errors import ValidationError


def api():
    assert hasattr(r, "SessionKey"), "Missing durable Session identities"
    return r.SessionKey, r.SessionRef, r.TurnAdmission


def record(key):
    return {
        "key": key.to_dict(),
        "coordination_ref": "b" * 64,
        "revision": 0,
        "binding_revision": 1,
        "bindings": {"1": {"definition": {"kind": "agent"}, "manifest": {}}},
        "last_turn_seq": 0,
        "active_run": None,
    }


def test_ref_and_turn_exact_roundtrip_are_immutable():
    Key, Ref, Turn = api()
    key = Key("w", "p", "a" * 64, None, "conversation")
    ref = Ref(key, "b" * 64, 1, "c" * 64)
    turn = Turn("turn", 1, ref, r.RunRef("local", "w", "p", "run", "d" * 64), "e" * 64, "command")
    assert Ref.from_dict(ref.to_dict()) == ref
    assert Turn.from_dict(turn.to_dict()) == turn
    value = ref.to_dict()
    value["key"]["session_id"] = "changed"
    assert ref.key.session_id == "conversation"
    with pytest.raises(ValidationError):
        Ref.from_dict({**ref.to_dict(), "unknown": 1})


@pytest.mark.parametrize(
    "field,value",
    [
        ("binding_revision", True),
        ("binding_revision", 0),
        ("coordination_ref", "https://user:secret@host"),
        ("definition_digest", "bad"),
    ],
)
def test_ref_rejects_ambiguous_revision_and_secret_locator(field, value):
    Key, Ref, _ = api()
    ref = Ref(Key("w", "p", "a" * 64, None, "s"), "b" * 64, 1, "c" * 64)
    with pytest.raises(ValidationError):
        replace(ref, **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("namespace", ""),
        ("resource_id", "bad"),
        ("session_id", ""),
        ("session_id", "x" * 257),
        ("schema_version", True),
    ],
)
def test_key_validation(field, value):
    Key, _, _ = api()
    key = Key("w", "p", "a" * 64, None, "s")
    with pytest.raises(ValidationError):
        replace(key, **{field: value})


def test_feature_activation_and_route_insertion_rollback_together(tmp_path):
    Key, _, _ = api()
    with r.SQLiteStore(tmp_path / "rollback.sqlite") as store:
        admission = store.create_session_admission()
        assert admission.transaction_owner is store
        key = Key("w", "p", "a" * 64, None, "s")
        with pytest.raises(RuntimeError):
            with store.transaction():
                admission.prepare()
                admission.insert(record(key))
                raise RuntimeError("crash before accept")
        assert (
            store.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[
                0
            ]
            == "1"
        )
        assert admission.load(r.Scope("w", "p"), key.key_id) is None
        assert (
            store.conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE name='agent_sessions'"
            ).fetchone()[0]
            == 0
        )


def test_indexed_store_cas_turn_pages_scope_and_reader_schema(tmp_path):
    Key, Ref, Turn = api()
    path = tmp_path / "schema.sqlite"
    scope = r.Scope("w", "p")
    key = Key("w", "p", "a" * 64, "orders", "s")
    ref = Ref(key, "b" * 64, 1, "c" * 64)
    with r.SQLiteStore(path) as store:
        admission = store.create_session_admission()
        with store.transaction():
            admission.prepare()
            data = record(key)
            admission.insert(data)
            data["last_turn_seq"] = 1
            admission.save(data, expected_revision=0)
            admission.insert_turn(
                Turn(
                    "t", 1, ref, r.RunRef("local", "w", "p", "run", "d" * 64), "e" * 64, "c"
                ).to_dict()
            )
        assert admission.load(scope, key.key_id)["revision"] == 1
        assert admission.load(r.Scope("other", "p"), key.key_id) is None
        assert len(admission.turns(scope, key.key_id, after=0, limit=1)) == 1
        assert admission.turns(scope, key.key_id, after=1, limit=1) == []
        with pytest.raises(ValidationError):
            with store.transaction():
                admission.save(data, expected_revision=0)
        assert (
            store.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[
                0
            ]
            == "2"
        )
    with r.SQLiteStore(path, readonly=True) as reader:
        assert reader.conn.execute("SELECT count(*) FROM agent_sessions").fetchone()[0] == 1


def test_actual_namespace_storage_alias_cannot_create_two_routes(tmp_path):
    Key, _, _ = api()
    from ralf_agent.binding_sessions import session_storage_key

    with r.SQLiteStore(tmp_path / "alias.sqlite") as store:
        admission = store.create_session_admission()
        key = Key("w", "p", "a" * 64, "orders", "s")
        alias = Key("w", "p", "a" * 64, None, session_storage_key("orders", "s"))
        with store.transaction():
            admission.prepare()
            admission.insert(record(key))
        with pytest.raises(ValidationError):
            with store.transaction():
                admission.insert(record(alias))
        assert admission.load_address(r.Scope("w", "p"), alias.storage_key)["key"] == key.to_dict()


def test_unused_optional_admission_factory_does_not_change_legacy_raw_submit(tmp_path):
    from .helpers import ScriptedProvider

    class Store(r.SQLiteStore):
        def create_session_admission(self):
            raise RuntimeError("optional feature has not been enabled")

    with r.LocalEngine(
        Store(tmp_path / "native.sqlite"),
        providers={"default": ScriptedProvider([])},
        tools=r.ToolRegistry(),
    ) as raw:
        handle = raw.submit(r.AgentSpec("a", "A"), "q", command_id="raw")
        assert raw.status(handle.run_id).state == "queued"
        assert (
            raw.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "1"
        )
