"""SQLite Session routes and Turns, in the existing execution transaction."""

import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar

from .errors import ValidationError
from .session_types import SessionKey, TurnAdmission, integer
from .types import canonical

_permit = ContextVar("session_admission_permit", default=None)


@contextmanager
def admission_permit(store, scope, address):
    token = _permit.set((id(store), scope.workspace, scope.principal, address))
    try:
        yield
    finally:
        _permit.reset(token)


class SQLiteSessionAdmission:
    def __init__(self, store):
        self.transaction_owner = store
        self.authority_backend_id = store.backend_id

    def _enabled(self):
        row = self.transaction_owner.conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        return row[0] == "2"

    def _writing(self):
        if self.transaction_owner.readonly or not self.transaction_owner.conn.in_transaction:
            raise ValidationError("Session admission requires its execution transaction")

    def prepare(self):
        self._writing()
        c = self.transaction_owner.conn
        c.execute(
            "CREATE TABLE IF NOT EXISTS agent_sessions (workspace TEXT, principal TEXT, key_id TEXT, address TEXT, revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(workspace,principal,key_id), UNIQUE(workspace,principal,address))"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS agent_session_turns (workspace TEXT, principal TEXT, key_id TEXT, seq INTEGER, run_id TEXT UNIQUE NOT NULL, data TEXT NOT NULL, PRIMARY KEY(workspace,principal,key_id,seq))"
        )
        c.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")

    def load(self, scope, key_id):
        if not self._enabled():
            return None
        row = self.transaction_owner.conn.execute(
            "SELECT data FROM agent_sessions WHERE workspace=? AND principal=? AND key_id=?",
            (scope.workspace, scope.principal, key_id),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def load_address(self, scope, address):
        if not self._enabled():
            return None
        row = self.transaction_owner.conn.execute(
            "SELECT data FROM agent_sessions WHERE workspace=? AND principal=? AND address=?",
            (scope.workspace, scope.principal, address),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def insert(self, data):
        self._writing()
        key = SessionKey.from_dict(data["key"])
        try:
            self.transaction_owner.conn.execute(
                "INSERT INTO agent_sessions VALUES (?,?,?,?,?,?)",
                (
                    key.workspace,
                    key.principal,
                    key.key_id,
                    key.storage_key,
                    data["revision"],
                    canonical(data),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValidationError(
                "Session identity or actual storage address already registered"
            ) from error

    def save(self, data, *, expected_revision):
        self._writing()
        integer(expected_revision, minimum=0)
        key = SessionKey.from_dict(data["key"])
        next_data = {**data, "revision": expected_revision + 1}
        cursor = self.transaction_owner.conn.execute(
            "UPDATE agent_sessions SET revision=?,data=? WHERE workspace=? AND principal=? AND key_id=? AND revision=?",
            (
                next_data["revision"],
                canonical(next_data),
                key.workspace,
                key.principal,
                key.key_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ValidationError("Session admission revision conflict")
        data["revision"] = next_data["revision"]

    def insert_turn(self, data):
        self._writing()
        turn = TurnAdmission.from_dict(data)
        key = turn.session.key
        self.transaction_owner.conn.execute(
            "INSERT INTO agent_session_turns VALUES (?,?,?,?,?,?)",
            (
                key.workspace,
                key.principal,
                key.key_id,
                turn.turn_seq,
                turn.run.run_id,
                canonical(data),
            ),
        )

    def turns(self, scope, key_id, *, after=0, limit=100):
        integer(after, minimum=0)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValidationError("Turn page limit requires 1 to 1000")
        if not self._enabled():
            return []
        return [
            json.loads(row[0])
            for row in self.transaction_owner.conn.execute(
                "SELECT data FROM agent_session_turns WHERE workspace=? AND principal=? AND key_id=? AND seq>? ORDER BY seq LIMIT ?",
                (scope.workspace, scope.principal, key_id, after, limit),
            )
        ]

    def confirmed_result(self, scope, address, message_id, expected):
        row = self.transaction_owner.conn.execute(
            "SELECT data FROM memory_session_items WHERE workspace=? AND principal=? AND session=? AND message_id=? AND EXISTS (SELECT 1 FROM memory_session_index_state s WHERE s.workspace=? AND s.principal=? AND s.session=? AND s.dirty=0)",
            (
                scope.workspace,
                scope.principal,
                address,
                message_id,
                scope.workspace,
                scope.principal,
                address,
            ),
        ).fetchone()
        return row is not None and canonical(json.loads(row[0])) == canonical(expected)

    @property
    def session_backend_id(self):
        store = self.transaction_owner
        return store.backend_id if store.path == ":memory:" else "sqlite-memory:" + store.path

    def legacy_owner(self, scope, address, *, exclude_run_id=None):
        from .session_resources import run_session_claims, same_session_address

        resource = {"backend_id": self.session_backend_id, "session_id": address}
        for run in self.transaction_owner._scoped_runs(scope):
            if run["id"] == exclude_run_id:
                continue
            if any(same_session_address(resource, claim) for claim in run_session_claims(run)) and (
                run["state"] not in {"succeeded", "failed", "cancelled"}
                or run.get("workflow", {}).get("quiescent") is False
                or run.get("orchestration", {}).get("quiescent") is False
                or any(
                    a["kind"] == "tool"
                    and a["status"] in {"executing", "outcome_unknown", "receipt_received"}
                    for a in run["actions"]
                )
            ):
                return run["id"]
        return None

    def route_owner(self, scope, resource):
        if resource["backend_id"] not in {
            self.authority_backend_id,
            "threaded:" + self.authority_backend_id,
            self.session_backend_id,
            "threaded:" + self.session_backend_id,
        }:
            return None
        state = self.load_address(scope, resource["session_id"])
        if state is None or _permit.get() == (
            id(self.transaction_owner),
            scope.workspace,
            scope.principal,
            resource["session_id"],
        ):
            return None
        return state["active_run"] or "session-route:" + SessionKey.from_dict(state["key"]).key_id
