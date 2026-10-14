"""Optional Local deadline activation preserves the original SQLite authority."""

import importlib

import pytest

from ralf_agent import Scope, SessionKey, SQLiteStore
from ralf_agent.errors import ValidationError
from ralf_agent.types import digest


def schema(store):
    return store.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]


def test_local_deadline_capability_is_optional_and_default_schema_is_unchanged(tmp_path):
    ports = importlib.import_module("ralf_agent.ports")
    capability = getattr(ports, "LocalDeadlineExecutionStore", None)
    assert capability is not None
    assert "prepare_local_deadlines" not in vars(ports.ExecutionStore)
    with SQLiteStore(tmp_path / "runs.sqlite") as store:
        assert getattr(store, "local_deadline_version", None) == 1
        assert schema(store) == "1"
        with pytest.raises(ValidationError, match="transaction"):
            store.prepare_local_deadlines()
        assert schema(store) == "1"


def test_deadline_activation_rolls_back_original_command_run_budget_and_events(tmp_path):
    with SQLiteStore(tmp_path / "runs.sqlite") as store:

        def accept():
            store.prepare_local_deadlines()
            store.insert_run({"id": "run", "revision": 0})
            store.create_budget("run", 4)
            store.emit("run", "run_submitted")
            raise RuntimeError("acceptance failed")

        with pytest.raises(RuntimeError, match="acceptance failed"):
            store.command(Scope(), "submit", "submit", {}, "run", accept)
        assert schema(store) == "1"
        for table in ("runs", "budgets", "events", "commands"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert (
            store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('agent_sessions','agent_session_turns','native_history_publications')"
            ).fetchall()
            == []
        )


def test_fresh_deadline_activation_prepares_inherited_read_tables(tmp_path):
    with SQLiteStore(tmp_path / "runs.sqlite") as store:
        with store.transaction():
            assert store.prepare_local_deadlines() is None
        assert schema(store) == "15"
        assert store.native_history_publications(Scope(), "missing") == []
        assert store.create_session_admission().load(Scope(), "missing") is None
        assert (
            store.session_resource_owner(
                Scope(), {"backend_id": "external-session", "session_id": "missing"}
            )
            is None
        )


def test_upgrade_preserves_native_publications_and_session_routes(tmp_path):
    scope = Scope("workspace", "principal")
    with SQLiteStore(tmp_path / "runs.sqlite") as store:
        with store.transaction():
            store.prepare_delegated_execution()
            store.publish_native_history(scope, "stream", "message", {"original": True})
            store.conn.execute(
                "INSERT INTO agent_sessions VALUES (?,?,?,?,?,?)",
                (scope.workspace, scope.principal, "key", "address", 0, '{"original":true}'),
            )
            store.conn.execute(
                "INSERT INTO agent_session_turns VALUES (?,?,?,?,?,?)",
                (scope.workspace, scope.principal, "key", 1, "run", '{"original_turn":true}'),
            )
        assert schema(store) == "14"
        with store.transaction():
            store.prepare_local_deadlines()
        assert schema(store) == "15"
        assert store.native_history_publications(scope, "stream") == [{"original": True}]
        admission = store.create_session_admission()
        assert admission._enabled()
        assert admission.load(scope, "key") == {"original": True}
        assert admission.load_address(scope, "address") == {"original": True}
        assert (
            store.conn.execute(
                "SELECT data FROM agent_session_turns WHERE run_id='run'"
            ).fetchone()[0]
            == '{"original_turn":true}'
        )
        with store.transaction():
            store.prepare_delegated_execution()
        assert schema(store) == "15"
        assert store.native_history_publications(scope, "stream") == [{"original": True}]


def test_schema15_keeps_original_scoped_session_occupancy(tmp_path):
    scope = Scope("workspace", "principal")
    with SQLiteStore(tmp_path / "runs.sqlite") as store:
        key = SessionKey(
            scope.workspace,
            scope.principal,
            digest(["sqlite-session-resource", store.backend_id]),
            None,
            "conversation",
        )
        admission = store.create_session_admission()
        with store.transaction():
            store.prepare_delegated_execution()
            admission.insert({"key": key.to_dict(), "revision": 0, "active_run": "original"})
        resource = {"backend_id": admission.session_backend_id, "session_id": key.storage_key}
        assert store.session_resource_owner(scope, resource) == "original"
        with store.transaction():
            store.prepare_local_deadlines()
        assert schema(store) == "15"
        assert store.session_resource_owner(scope, resource) == "original"
        assert store.session_resource_owner(Scope("other", "principal"), resource) is None


@pytest.mark.parametrize("readonly", [False, True])
def test_schema15_reopens_and_readonly_cannot_prepare(tmp_path, readonly):
    path = tmp_path / "runs.sqlite"
    with SQLiteStore(path) as store:
        with store.transaction():
            store.prepare_local_deadlines()
            store.publish_native_history(Scope(), "s", "m", {"value": 1})
    with SQLiteStore(path, readonly=readonly) as store:
        assert schema(store) == "15"
        assert store.native_history_publications(Scope(), "s") == [{"value": 1}]
        if readonly:
            with pytest.raises(ValidationError, match="transaction"):
                store.prepare_local_deadlines()
        else:
            with store.transaction():
                store.prepare_local_deadlines()
        assert schema(store) == "15"
