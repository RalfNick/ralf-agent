"""SQLite state authority and atomic command/budget journal."""

import json
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import BudgetExceeded, IdempotencyConflict, NotFound, ValidationError
from .types import CommandReceipt, RunEvent, canonical, credits, digest


class SQLiteStore:
    native_history_version = 1
    session_admission_version = 5
    managed_stage_version = 1
    context_stage_version = 1
    model_memory_stage_version = 1
    data_context_stage_version = 1
    composite_context_stage_version = 1
    composite_memory_stage_version = 1

    def __init__(self, path, *, readonly=False):
        # Resolve once: a later chdir or an input symlink must not move the WAL,
        # backend identity, or coordinator away from this execution database.
        self.path = ":memory:" if str(path) == ":memory:" else str(Path(path).resolve())
        self.readonly = readonly
        self.backend_id = (
            f"sqlite-memory:{uuid.uuid4().hex}"
            if self.path == ":memory:"
            else f"sqlite:{self.path}"
        )
        self._coordinator = None
        self._transaction_failed = False
        self._path_identity = self._file_identity(required=False)
        if readonly:
            if self.path == ":memory:" or self._path_identity is None:
                raise NotFound("Execution database not found; submit a Run first")
            self.conn = sqlite3.connect(
                Path(self.path).as_uri() + "?mode=ro",
                uri=True,
                isolation_level=None,
                timeout=10,
            )
            self.conn.row_factory = sqlite3.Row
            try:
                self._assert_file_identity()
                row = self.conn.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()
                if row is None or row[0] not in {
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "6",
                    "7",
                    "8",
                    "9",
                    "10",
                    "11",
                    "12",
                    "13",
                }:
                    raise ValidationError("Unsupported execution database Schema")
            except (sqlite3.DatabaseError, ValidationError) as exc:
                self.close()
                raise ValidationError("Unsupported execution database Schema") from exc
            return
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        self.conn.row_factory = sqlite3.Row
        try:
            # Check again after creation/open and before SQLite may attach WAL.
            # Hard-linked names share the main file but not their WAL sidecars.
            self._assert_file_identity()
        except BaseException:
            self.close()
            raise
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
        if row and row[0] not in {
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "10",
            "11",
            "12",
            "13",
        }:
            self.close()
            raise ValidationError("Unsupported execution database Schema")
        self.conn.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version','1')")

    @property
    def conn(self):
        if self._transaction_failed:
            raise ValidationError("Execution database rollback failed; close and reopen the Store")
        return self._conn

    def prepare_native_history(self):
        """Activate native publication facts within the original acceptance transaction."""
        if self.readonly or not self.conn.in_transaction:
            raise ValidationError("Native history requires its execution transaction")
        self.create_session_admission()._prepare(13)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS native_history_publications (workspace TEXT NOT NULL, principal TEXT NOT NULL, stream TEXT NOT NULL, seq INTEGER NOT NULL, message_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(workspace,principal,stream,seq), UNIQUE(workspace,principal,stream,message_id))"
        )

    def native_history_publications(self, scope, stream):
        row = self.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row[0] != "13":
            return []
        rows = self.conn.execute(
            "SELECT data FROM native_history_publications WHERE workspace=? AND principal=? AND stream=? ORDER BY seq LIMIT 129",
            (scope.workspace, scope.principal, stream),
        ).fetchall()
        if len(rows) > 128:
            raise ValidationError("Native history publication capacity exceeded")
        return [json.loads(row[0]) for row in rows]

    def publish_native_history(self, scope, stream, message_id, evidence):
        if self.readonly or not self.conn.in_transaction:
            raise ValidationError("Native publication requires its original success transaction")
        encoded = canonical(evidence)
        previous = self.conn.execute(
            "SELECT data FROM native_history_publications WHERE workspace=? AND principal=? AND stream=? AND message_id=?",
            (scope.workspace, scope.principal, stream, message_id),
        ).fetchone()
        if previous is not None:
            if previous[0] != encoded:
                raise IdempotencyConflict("Native publication identity conflict")
            return
        records = self.native_history_publications(scope, stream)
        if len(records) >= 128:
            raise ValidationError("Native history publication capacity exceeded")
        self.conn.execute(
            "INSERT INTO native_history_publications VALUES (?,?,?,?,?,?)",
            (scope.workspace, scope.principal, stream, len(records) + 1, message_id, encoded),
        )

    def prepare_managed_stages(self):
        """Optional semantic activation, atomically with first stage Run admission."""
        if self.readonly or not self.conn.in_transaction:
            raise ValidationError("Managed stages require their execution transaction")
        self.create_session_admission().prepare_managed_stages()

    def managed_stage_reservation(self, run_id, reservation_id):
        """Independent accounting evidence; absence is not permission to recreate."""
        row = self.conn.execute(
            "SELECT * FROM reservations WHERE id=? AND run_id=?", (reservation_id, run_id)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["usage"] = None if row["usage"] is None else json.loads(row["usage"])
        return result

    def prepare_model_memory_stages(self):
        if self.readonly or not self.conn.in_transaction:
            raise ValidationError("Model memory requires its execution transaction")
        self.create_session_admission().prepare_model_memory_stages()

    def prepare_data_context_stages(self):
        if self.readonly or not self.conn.in_transaction:
            raise ValidationError("Data context requires its execution transaction")
        self.create_session_admission()._prepare(10)

    def prepare_composite_context_stages(self):
        if self.readonly or not self.conn.in_transaction:
            raise ValidationError("Composite context requires its execution transaction")
        self.create_session_admission()._prepare(11)

    def prepare_composite_memory_stages(self):
        if self.readonly or not self.conn.in_transaction:
            raise ValidationError("Composite memory requires its execution transaction")
        self.create_session_admission()._prepare(12)

    def prepare_context_stages(self):
        if self.readonly or not self.conn.in_transaction:
            raise ValidationError("Context stages require their execution transaction")
        self.create_session_admission().prepare_context_stages()

    @conn.setter
    def conn(self, connection):
        self._conn = connection

    def _file_identity(self, *, required=True):
        if self.path == ":memory:":
            return None
        try:
            info = Path(self.path).lstat()
        except FileNotFoundError as exc:
            if not required:
                return None
            raise ValidationError("Execution database file identity changed") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ValidationError("Execution database must be a regular file")
        if info.st_nlink != 1:
            raise ValidationError(
                "Execution database hard links are unsupported; use one file path"
            )
        return info.st_dev, info.st_ino

    def _assert_file_identity(self):
        identity = self._file_identity()
        if self._path_identity is not None and identity != self._path_identity:
            raise ValidationError("Execution database file identity changed")
        self._path_identity = identity

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._conn.close()

    def create_coordinator(self):
        from .coordinator import FileCoordinator, InProcessCoordinator

        if self.readonly:
            raise ValidationError("Observation stores cannot own an execution coordinator")
        self._assert_file_identity()
        if self._coordinator is None:
            self._coordinator = (
                InProcessCoordinator()
                if self.path == ":memory:"
                else FileCoordinator(
                    self.path + ".coordinator", resource_validator=self._assert_file_identity
                )
            )
        return self._coordinator

    def create_memory(self):
        from .memory import SQLiteMemory

        if self.readonly:
            raise ValidationError("Observation stores cannot initialize memory tables")
        return SQLiteMemory(self)

    def create_session_admission(self):
        from .sqlite_sessions import SQLiteSessionAdmission

        return SQLiteSessionAdmission(self)

    @contextmanager
    def transaction(self):
        if self.readonly:
            raise ValidationError("Execution database was opened for observation only")
        self._assert_file_identity()
        if self.conn.in_transaction:
            yield
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            # SQLite can reject COMMIT while retaining uncommitted writes.
            self.conn.commit()
        except BaseException as error:
            try:
                self.conn.rollback()
            except BaseException:
                self._transaction_failed = True
                error.add_note("Execution database rollback failed; Store is unusable")
                try:
                    self._conn.close()
                except BaseException:
                    error.add_note("Execution database close also failed; retry close")
            raise

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
        next_data = {**data, "revision": expected + 1}
        cursor = self.conn.execute(
            "UPDATE runs SET revision=?,data=? WHERE id=? AND revision=?",
            (next_data["revision"], canonical(next_data), data["id"], expected),
        )
        if cursor.rowcount != 1:
            raise ValidationError("Run state revision conflict")
        data["revision"] = next_data["revision"]

    def _scoped_runs(self, scope):
        for row in self.conn.execute("SELECT data FROM runs"):
            run = json.loads(row[0])
            if run["scope"] == {"workspace": scope.workspace, "principal": scope.principal}:
                yield run

    def session_owner(self, scope, session_id):
        return next(
            (
                run["id"]
                for run in self._scoped_runs(scope)
                if session_id in run.get("session_ids", [run["session_id"]])
                and (
                    run["state"] not in {"succeeded", "failed", "cancelled"}
                    or run.get("workflow", {}).get("quiescent") is False
                    or run.get("orchestration", {}).get("quiescent") is False
                )
            ),
            None,
        )

    def session_resource_owner(self, scope, resource):
        """Address-based admission shares the Run transaction and quiescence."""
        from .session_resources import run_session_claims, same_session_address

        if (
            not isinstance(resource, dict)
            or set(resource) != {"backend_id", "session_id"}
            or any(not isinstance(value, str) or not value.strip() for value in resource.values())
        ):
            raise ValidationError("Session resource requires backend_id and actual session_id")
        version = self.conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()[0]
        if version in {"2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"}:
            owner = self.create_session_admission().route_owner(scope, resource)
            if owner is not None:
                return owner
        for run in self._scoped_runs(scope):
            if any(same_session_address(resource, claim) for claim in run_session_claims(run)) and (
                run["state"] not in {"succeeded", "failed", "cancelled"}
                or run.get("workflow", {}).get("quiescent") is False
                or run.get("orchestration", {}).get("quiescent") is False
            ):
                return run["id"]
        return None

    def unresolved_effect(self, scope, tool, arguments, exclude_action_id):
        for run in self._scoped_runs(scope):
            for action in run["actions"]:
                if (
                    action["kind"] == "tool"
                    and action["id"] != exclude_action_id
                    and action["tool"] == tool
                    and action["arguments"] == arguments
                    and action["status"] in {"outcome_unknown", "executing"}
                ):
                    return {"run_id": run["id"], "action_id": action["id"]}
        return None

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
