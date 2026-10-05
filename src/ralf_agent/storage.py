"""SQLite state authority and atomic command/budget journal."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .errors import BudgetExceeded, IdempotencyConflict, NotFound, ValidationError
from .types import CommandReceipt, RunEvent, canonical, credits, digest


class SQLiteStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(run_id,seq));
            CREATE TABLE IF NOT EXISTS commands (workspace TEXT NOT NULL, principal TEXT NOT NULL, id TEXT NOT NULL, digest TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(workspace,principal,id));
            CREATE TABLE IF NOT EXISTS budgets (run_id TEXT PRIMARY KEY, allowance INTEGER NOT NULL CHECK(allowance>=0));
            CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0), state TEXT NOT NULL, actual INTEGER, usage TEXT);
            CREATE INDEX IF NOT EXISTS reservation_run ON reservations(run_id);
        """)
        row = self.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row and row[0] != "1":
            self.close()
            raise ValidationError("Unsupported execution database Schema")
        self.conn.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version','1')")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.conn.close()

    @contextmanager
    def transaction(self):
        if self.conn.in_transaction:
            yield
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def command(self, scope, command_id, kind, payload, run_id, apply):
        if not isinstance(command_id, str) or not command_id:
            raise ValidationError("A non-empty command_id is required")
        request_digest = digest({"kind": kind, "payload": payload})
        with self.transaction():
            row = self.conn.execute(
                "SELECT digest,receipt FROM commands WHERE workspace=? AND principal=? AND id=?",
                (scope.workspace, scope.principal, command_id),
            ).fetchone()
            if row:
                if row["digest"] != request_digest:
                    raise IdempotencyConflict("command_id was already used for a different request")
                return CommandReceipt(**json.loads(row["receipt"]))
            outcome = apply()
            state = "rejected" if outcome.pop("rejected", False) else "applied"
            receipt = CommandReceipt(command_id, run_id, kind, apply_state=state, outcome=outcome)
            from dataclasses import asdict

            self.conn.execute(
                "INSERT INTO commands VALUES (?,?,?,?,?)",
                (
                    scope.workspace,
                    scope.principal,
                    command_id,
                    request_digest,
                    canonical(asdict(receipt)),
                ),
            )
            return receipt

    def insert_run(self, data):
        self.conn.execute(
            "INSERT INTO runs VALUES (?,?,?)", (data["id"], data["revision"], canonical(data))
        )

    def run(self, run_id):
        row = self.conn.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise NotFound("Run not found")
        return json.loads(row[0])

    def save_run(self, data):
        expected = data["revision"]
        data["revision"] += 1
        cursor = self.conn.execute(
            "UPDATE runs SET revision=?,data=? WHERE id=? AND revision=?",
            (data["revision"], canonical(data), data["id"], expected),
        )
        if cursor.rowcount != 1:
            raise ValidationError("Run state revision conflict")

    def emit(self, run_id, kind, data=None):
        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run_id,)
        ).fetchone()
        self.conn.execute(
            "INSERT INTO events VALUES (?,?,?,?)", (run_id, row[0], kind, canonical(data or {}))
        )

    def events(self, run_id, after=0, limit=1000):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValidationError("Invalid event cursor or page size")
        return [
            RunEvent(run_id, row["seq"], row["kind"], json.loads(row["data"]))
            for row in self.conn.execute(
                "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, after, limit),
            )
        ]

    def create_budget(self, run_id, allowance):
        credits(allowance)
        with self.transaction():
            row = self.conn.execute(
                "SELECT allowance FROM budgets WHERE run_id=?", (run_id,)
            ).fetchone()
            if row and row[0] != allowance:
                raise IdempotencyConflict("Budget already created with another limit")
            self.conn.execute("INSERT OR IGNORE INTO budgets VALUES (?,?)", (run_id, allowance))

    def budget(self, run_id):
        row = self.conn.execute(
            "SELECT allowance FROM budgets WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise NotFound("Budget not found")
        totals = self.conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN state IN ('reserved','unknown') THEN amount ELSE 0 END),0),COALESCE(SUM(CASE WHEN state='settled' THEN actual ELSE 0 END),0) FROM reservations WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return {"limit": row[0], "held": totals[0], "spent": totals[1]}

    def reserve(self, run_id, reservation_id, amount):
        credits(amount)
        with self.transaction():
            row = self.conn.execute(
                "SELECT * FROM reservations WHERE id=?", (reservation_id,)
            ).fetchone()
            if row:
                if row["run_id"] != run_id or row["amount"] != amount:
                    raise IdempotencyConflict("Reservation identity conflict")
                return
            current = self.budget(run_id)
            if current["spent"] + current["held"] + amount > current["limit"]:
                raise BudgetExceeded("Execution credit budget exhausted")
            self.conn.execute(
                "INSERT INTO reservations VALUES (?,?,?,'reserved',NULL,NULL)",
                (reservation_id, run_id, amount),
            )

    def mark_unknown(self, reservation_id):
        with self.transaction():
            self.conn.execute(
                "UPDATE reservations SET state='unknown' WHERE id=? AND state='reserved'",
                (reservation_id,),
            )

    def settle(self, reservation_id, actual, usage):
        credits(actual)
        with self.transaction():
            row = self.conn.execute(
                "SELECT * FROM reservations WHERE id=?", (reservation_id,)
            ).fetchone()
            if row is None:
                raise NotFound("Reservation not found")
            if actual > row["amount"]:
                raise BudgetExceeded("Settlement exceeds reserved execution credits")
            encoded = canonical(usage)
            if row["state"] == "settled":
                if row["actual"] != actual or row["usage"] != encoded:
                    raise IdempotencyConflict("Conflicting settlement receipt")
                return
            self.conn.execute(
                "UPDATE reservations SET state='settled',actual=?,usage=? WHERE id=?",
                (actual, encoded, reservation_id),
            )
