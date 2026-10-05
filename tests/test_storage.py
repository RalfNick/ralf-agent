from concurrent.futures import ThreadPoolExecutor

import pytest

from ralf_agent.errors import BudgetExceeded, IdempotencyConflict, NotFound, ValidationError
from ralf_agent.storage import SQLiteStore
from ralf_agent.types import Scope


def test_reservation_replay_does_not_charge_twice(tmp_path):
    with SQLiteStore(tmp_path / "runs.db") as store:
        store.create_budget("r1", 3)
        store.reserve("r1", "a1", 2)
        store.reserve("r1", "a1", 2)
        assert store.budget("r1") == {"limit": 3, "held": 2, "spent": 0}
        with pytest.raises(IdempotencyConflict):
            store.reserve("r1", "a1", 1)
        with pytest.raises(BudgetExceeded):
            store.reserve("r1", "a2", 2)


def test_concurrent_reservations_cannot_spend_the_same_balance(tmp_path):
    path = tmp_path / "budget.db"
    with SQLiteStore(path) as store:
        store.create_budget("r1", 3)

    def reserve(attempt):
        with SQLiteStore(path) as store:
            try:
                store.reserve("r1", attempt, 2)
                return True
            except BudgetExceeded:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, ["a1", "a2"])) == [False, True]
    with SQLiteStore(path) as store:
        assert store.budget("r1")["held"] == 2


def test_unknown_usage_keeps_reservation_and_late_settlement_deduplicates(tmp_path):
    with SQLiteStore(tmp_path / "runs.db") as store:
        store.create_budget("r1", 4)
        store.reserve("r1", "a1", 3)
        store.mark_unknown("a1")
        assert store.budget("r1")["held"] == 3
        store.settle("a1", 2, {"input_tokens": 10, "output_tokens": 3})
        store.settle("a1", 2, {"input_tokens": 10, "output_tokens": 3})
        assert store.budget("r1") == {"limit": 4, "held": 0, "spent": 2}
        with pytest.raises(IdempotencyConflict):
            store.settle("a1", 1, {})


def test_command_id_conflicts_and_scoped_deduplication(tmp_path):
    scope = Scope("workspace-a", "alice")
    with SQLiteStore(tmp_path / "runs.db") as store:
        first = store.command(scope, "request", "submit", {"x": 1}, "run-a", lambda: {})
        replay = store.command(scope, "request", "submit", {"x": 1}, "run-b", lambda: {})
        assert first.run_id == replay.run_id == "run-a"
        assert replay.apply_state == "applied"
        with pytest.raises(IdempotencyConflict):
            store.command(scope, "request", "submit", {"x": 2}, "run-b", lambda: {})
        other = store.command(
            Scope("workspace-b", "alice"), "request", "submit", {}, "r2", lambda: {}
        )
        assert other.run_id == "r2"


@pytest.mark.parametrize("amount", [-1, 1.5, True])
def test_invalid_budget_amounts_are_rejected(tmp_path, amount):
    with SQLiteStore(tmp_path / "runs.db") as store:
        with pytest.raises(ValueError):
            store.create_budget("r1", amount)


def test_readonly_observation_never_creates_a_missing_database(tmp_path):
    path = tmp_path / "missing" / "runs.db"
    with pytest.raises(NotFound):
        SQLiteStore(path, readonly=True)
    assert not path.parent.exists()


def test_readonly_observation_cannot_write_or_upgrade_schema(tmp_path):
    path = tmp_path / "runs.db"
    with SQLiteStore(path) as store:
        store.create_budget("r1", 3)
    with SQLiteStore(path, readonly=True) as observer:
        assert observer.budget("r1") == {"limit": 3, "held": 0, "spent": 0}
        with pytest.raises(ValidationError):
            observer.create_budget("new", 1)


def test_failed_compare_and_swap_does_not_mutate_the_callers_revision(tmp_path):
    with SQLiteStore(tmp_path / "revision.db") as store:
        record = {"id": "r1", "revision": 0}
        store.insert_run(record)
        stale = dict(record)
        store.save_run(record)
        with pytest.raises(ValidationError):
            store.save_run(stale)
        assert stale["revision"] == 0
