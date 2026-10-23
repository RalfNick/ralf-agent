"""Explicit compaction of redundant Local working messages, never evidence."""

from .capacity_rules import capacity_obligations
from .coordinator import FileCoordinator, InProcessCoordinator
from .errors import ValidationError
from .storage import SQLiteStore
from .types import canonical, digest

_FIELDS = frozenset(
    {
        "id",
        "revision",
        "scope",
        "state",
        "definition",
        "manifest",
        "input",
        "result",
        "release_digest",
        "error",
        "node",
        "decisions",
        "actions",
        "messages",
        "session_id",
        "message_compaction",
    }
)


def _store(engine):
    store = engine.store
    pin = engine._admission_store_pin
    coordinator = engine.coordinator
    if (
        type(store) is not SQLiteStore
        or pin is None
        or store is not pin[0]
        or store.backend_id != pin[1]
        or store._coordinator is not coordinator
        or not (
            type(coordinator) is FileCoordinator
            and coordinator._file is not None
            and not coordinator._file.closed
            or type(coordinator) is InProcessCoordinator
            and coordinator._owned
        )
    ):
        raise ValidationError("Message compaction requires the original default SQLite coordinator")
    return store


def _safe(engine, store, run):
    if (
        set(run) - _FIELDS
        or run.get("state") != "succeeded"
        or run.get("definition", {}).get("kind") != "agent"
        or run.get("session_id") != run["id"]
        or type(run.get("messages")) is not list
        or len(run["messages"]) < 2
        or capacity_obligations(run)
        or run["id"] in engine._active
        or run["id"] in engine._drive_users
        or engine._operation_active(run["id"])
        or store.conn.execute(
            "SELECT 1 FROM reservations WHERE run_id=? AND state NOT IN ('settled','released') LIMIT 1",
            (run["id"],),
        ).fetchone()
        is not None
        or store.conn.execute("SELECT 1 FROM budgets WHERE run_id=?", (run["id"],)).fetchone()
        is None
    ):
        raise ValidationError("Message compaction requires a settled standalone successful Agent")


def compact_messages(engine, run_id, *, command_id):
    engine._authorized(run_id)
    store = _store(engine)

    def apply():
        run = engine._authorized(run_id)
        engine._check_release(run)
        if _store(engine) is not store or engine._authorized(run_id) != run:
            raise ValidationError("Original compaction resource or revision changed")
        _safe(engine, store, run)
        messages = run["messages"]
        prefix = messages[:2]
        count = len(messages) - len(prefix)
        removed = len(canonical(messages).encode()) - len(canonical(prefix).encode())
        if count:
            run["messages"] = prefix
            run["message_compaction"] = {
                "version": 1,
                "source_digest": digest(messages),
                "removed_messages": count,
                "removed_bytes": removed,
            }
            engine._commit(run, "messages_compacted", run["message_compaction"])
        return {
            "removed_messages": count,
            "removed_bytes": removed,
            "state_revision": run["revision"],
        }

    return store.command(
        engine.scope, command_id, "compact_messages", {"run_id": run_id}, run_id, apply
    )
