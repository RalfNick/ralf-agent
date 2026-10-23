"""Deployment root claims remain facts of the original SQLite authority."""

import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from relf_agent import Scope, SQLiteStore
from relf_agent.errors import AuthorizationDenied, CapacityExceeded, ValidationError
from relf_agent.types import digest


def identity(*, maximum=2, per_scope=None):
    return {
        "kind": "deployment-admission-policy",
        "deployment_id": "deployment",
        "version": "1",
        "max_active_root_runs": maximum,
        "max_active_root_runs_per_scope": per_scope,
    }


def record(identifier, *, state="queued", scope=None, parent=None):
    scope = Scope() if scope is None else scope
    value = {
        "id": identifier,
        "revision": 0,
        "scope": {"workspace": scope.workspace, "principal": scope.principal},
        "state": state,
        "actions": [],
        "manifest": {},
        "release_digest": "a" * 64,
        "definition": {"kind": "agent"},
        "session_id": identifier,
    }
    if parent is not None:
        value.update(
            parent_id=parent,
            call_id=identifier,
            parent_call={
                "parent_id": parent,
                "call_id": identifier,
                "reservation": "escrow:" + identifier,
            },
        )
    return value


def publish(value, policy, root=None):
    value["manifest"].update(local_admission_protocol=1, admission_policy=policy)
    value["local_admission"] = {"version": 1, "root_run_id": root or value["id"]}
    value["local_admission_digest"] = digest(value["local_admission"])
    return value


def schema(store):
    return store.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]


def install(store, policy=None):
    with store.transaction():
        store.prepare_local_capacity(identity() if policy is None else policy)


def test_optional_admission_port_preserves_default_schema_and_mandatory_port(tmp_path):
    ports = importlib.import_module("relf_agent.ports")
    assert getattr(ports, "LocalAdmissionExecutionStore", None) is not None
    assert "local_capacity_acquire" not in vars(ports.ExecutionStore)
    with SQLiteStore(tmp_path / "default.sqlite") as store:
        assert getattr(store, "local_admission_version", None) == 1
        assert store.local_capacity_policy() is None
        assert schema(store) == "1"
        with pytest.raises(ValidationError, match="transaction"):
            store.prepare_local_capacity(identity())
        assert schema(store) == "1"


def test_schema16_activation_rolls_back_and_preserves_schema15_publications(tmp_path):
    path = tmp_path / "activation.sqlite"
    with SQLiteStore(path) as store:
        with store.transaction():
            store.prepare_local_deadlines()
            store.publish_native_history(Scope(), "stream", "message", {"original": True})
        with pytest.raises(RuntimeError):
            with store.transaction():
                store.prepare_local_capacity(identity())
                raise RuntimeError("activation failed")
        assert schema(store) == "15" and store.local_capacity_policy() is None
        install(store)
        assert schema(store) == "16"
        assert store.native_history_publications(Scope(), "stream") == [{"original": True}]
        assert store.create_session_admission()._enabled()
        original = store.local_capacity_policy()
        original["max_active_root_runs"] = 999
        assert store.local_capacity_policy() == identity()
        install(store)
        with pytest.raises(ValidationError):
            install(store, identity(maximum=3))
    with SQLiteStore(path, readonly=True) as reader:
        assert reader.local_capacity_policy() == identity()
        assert reader.native_history_publications(Scope(), "stream") == [{"original": True}]


def test_fresh16_has_session_and_native_read_tables(tmp_path):
    with SQLiteStore(tmp_path / "fresh.sqlite") as store:
        install(store)
        assert schema(store) == "16"
        assert store.native_history_publications(Scope(), "none") == []
        assert store.create_session_admission().load(Scope(), "none") is None


def test_atomic_claim_limits_and_scope_privacy(tmp_path):
    scope, other = Scope("w", "a"), Scope("w", "b")
    with SQLiteStore(tmp_path / "claims.sqlite") as store:
        install(store, identity(maximum=2, per_scope=1))
        with store.transaction():
            assert store.local_capacity_acquire(scope, "a") is None
            assert store.local_capacity_acquire(scope, "a") is None
            store.insert_run(publish(record("a", scope=scope), store.local_capacity_policy()))
        with pytest.raises(CapacityExceeded) as denied:
            with store.transaction():
                store.local_capacity_acquire(scope, "a-two")
        assert denied.value.code == "capacity_exceeded"
        with store.transaction():
            store.local_capacity_acquire(other, "b")
            store.insert_run(publish(record("b", scope=other), store.local_capacity_policy()))
        assert store.local_capacity_holders(scope) == ("a",)
        assert store.local_capacity_holders(other) == ("b",)
        with pytest.raises(CapacityExceeded) as full:
            with store.transaction():
                store.local_capacity_acquire(Scope("w", "c"), "c")
        assert full.value.code == "capacity_exceeded"
        assert str(full.value) == "Deployment admission capacity is unavailable"
        with pytest.raises(AuthorizationDenied):
            with store.transaction():
                store.local_capacity_release(other, "a")


def test_parallel_stores_cannot_overbook_deployment(tmp_path):
    path = tmp_path / "concurrency.sqlite"
    with SQLiteStore(path) as store:
        install(store, identity(maximum=1))

    def acquire(index):
        with SQLiteStore(path) as store:
            try:
                with store.transaction():
                    store.local_capacity_acquire(Scope(), f"root-{index}")
                    store.insert_run(
                        publish(record(f"root-{index}"), store.local_capacity_policy())
                    )
            except CapacityExceeded as error:
                assert error.code == "capacity_exceeded"
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(acquire, (1, 2))) == [False, True]


def test_root_acceptance_rollback_releases_unaccepted_claim(tmp_path):
    with SQLiteStore(tmp_path / "rollback.sqlite") as store:
        install(store, identity(maximum=1))
        with pytest.raises(RuntimeError):
            with store.transaction():
                store.local_capacity_acquire(Scope(), "first")
                store.insert_run(publish(record("first"), store.local_capacity_policy()))
                raise RuntimeError("rollback original acceptance")
        assert store.local_capacity_holders(Scope()) == ()
        assert store.local_capacity_policy() == identity(maximum=1)
        with store.transaction():
            store.local_capacity_acquire(Scope(), "second")
            store.insert_run(publish(record("second"), store.local_capacity_policy()))


def test_mandatory_insert_cannot_bypass_original_capacity(tmp_path):
    with SQLiteStore(tmp_path / "bypass.sqlite") as store:
        install(store)
        with pytest.raises(ValidationError):
            with store.transaction():
                store.insert_run(record("hidden-port"))
        with pytest.raises(ValidationError):
            with store.transaction():
                store.insert_run(publish(record("no-claim"), store.local_capacity_policy()))


def test_legacy_roots_seed_all_scopes_without_rewriting_releases(tmp_path):
    scopes = (Scope("w", "a"), Scope("w", "b"))
    with SQLiteStore(tmp_path / "legacy.sqlite") as store:
        originals = [
            record("one", scope=scopes[0]),
            record("two", state="cancelled", scope=scopes[1]),
        ]
        originals[1]["actions"] = [{"kind": "tool", "status": "outcome_unknown"}]
        for value in originals:
            store.insert_run(value)
        install(store, identity(maximum=1))
        assert store.local_capacity_holders(scopes[0]) == ("one",)
        assert store.local_capacity_holders(scopes[1]) == ("two",)
        assert [store.run(value["id"]) for value in originals] == originals
        with pytest.raises(CapacityExceeded) as full:
            with store.transaction():
                store.local_capacity_acquire(scopes[0], "three")
        assert full.value.code == "capacity_exceeded"


def test_terminal_zero_reservation_holds_until_original_settlement(tmp_path):
    with SQLiteStore(tmp_path / "zero.sqlite") as store:
        original = record("zero", state="cancelled")
        store.insert_run(original)
        store.create_budget("zero", 0)
        store.reserve("zero", "attempt", 0)
        store.mark_unknown("attempt")
        assert store.budget("zero")["held"] == 0
        install(store)
        with store.transaction():
            assert store.local_capacity_release(Scope(), "zero") is False
            store.settle("attempt", 0, {"original": "confirmed"})
            assert store.local_capacity_release(Scope(), "zero") is True
            assert store.local_capacity_release(Scope(), "zero") is True
        assert store.local_capacity_holders(Scope()) == ()


def test_child_unknown_retains_one_root_without_double_counting(tmp_path):
    with SQLiteStore(tmp_path / "tree.sqlite") as store:
        root = record("root", state="cancelled")
        child = record("child", state="cancelled", parent="root")
        child["actions"] = [{"kind": "tool", "status": "outcome_unknown"}]
        root["orchestration"] = {
            "quiescent": True,
            "children": [
                {
                    "id": "child",
                    "run_id": "child",
                    "reservation": "escrow:child",
                    "settled": True,
                }
            ],
        }
        store.insert_run(root)
        store.insert_run(child)
        store.create_budget("root", 0)
        store.create_budget("child", 0)
        install(store, identity(maximum=1))
        assert store.local_capacity_holders(Scope()) == ("root",)
        with store.transaction():
            assert store.local_capacity_release(Scope(), "root") is False
            child["actions"][0]["status"] = "completed"
            store.save_run(child)
            assert store.local_capacity_release(Scope(), "root") is True


@pytest.mark.parametrize(
    "obligation",
    [
        {"workflow": {"quiescent": False}},
        {"context_preparations": {"key": {"status": "response_received"}}},
        {"memory_stages": {"key": {"status": "outcome_unknown", "facts": []}}},
        {"context_artifacts": {"key": {"status": "writing", "dispatched": True}}},
        {"remote_session_saves": {"turn": {"attempts": 1, "receipt": None}}},
        {
            "actions": [
                {
                    "kind": "tool",
                    "status": "completed",
                    "delegated_execution": {
                        "pending_stop": True,
                        "fenced": False,
                        "effect_case": "confirmed",
                    },
                }
            ]
        },
    ],
)
def test_terminal_auxiliary_obligations_keep_root(tmp_path, obligation):
    with SQLiteStore(tmp_path / "auxiliary.sqlite") as store:
        value = {**record("root", state="failed"), **obligation}
        store.insert_run(value)
        install(store)
        with store.transaction():
            assert store.local_capacity_release(Scope(), "root") is False


def test_child_admission_uses_existing_root_and_original_parent_scope(tmp_path):
    with SQLiteStore(tmp_path / "new-tree.sqlite") as store:
        install(store, identity(maximum=1))
        root = publish(record("root"), store.local_capacity_policy())
        root["orchestration"] = {"quiescent": False, "children": []}
        with store.transaction():
            store.local_capacity_acquire(Scope(), "root")
            store.insert_run(root)
            child = publish(record("child", parent="root"), store.local_capacity_policy(), "root")
            store.insert_run(child)
            root["orchestration"]["children"].append(
                {
                    "id": "child",
                    "run_id": "child",
                    "reservation": "escrow:child",
                    "settled": False,
                }
            )
            store.save_run(root)
        assert store.local_capacity_holders(Scope()) == ("root",)
        assert store.run("child")["local_admission"]["root_run_id"] == "root"
        with pytest.raises(AuthorizationDenied):
            with store.transaction():
                store.insert_run(
                    publish(
                        record("foreign", scope=Scope("another", "scope"), parent="root"),
                        store.local_capacity_policy(),
                        "root",
                    )
                )


def test_incomplete_original_child_links_cannot_release_a_root(tmp_path):
    with SQLiteStore(tmp_path / "broken-tree.sqlite") as store:
        root = record("root", state="cancelled")
        root["orchestration"] = {"quiescent": True, "children": []}
        store.insert_run(root)
        store.create_budget("root", 0)
        install(store)
        assert store.local_capacity_holders(Scope()) == ()
        # Root identity cannot be revived by manufacturing an unlinked child.
        with pytest.raises(ValidationError):
            with store.transaction():
                store.insert_run(
                    publish(
                        record("child", state="cancelled", parent="root"),
                        store.local_capacity_policy(),
                        "root",
                    )
                )


@pytest.mark.parametrize(
    "data",
    [
        {"state": "cancelled", "actions": [], "context_preparation_markers": {"missing": "proof"}},
        {"state": "failed", "actions": [], "context_artifact_dispatches": {"missing": "proof"}},
        {
            "state": "cancelled",
            "actions": [],
            "remote_session_saves": {"turn": {"attempts": 1, "receipt": {}}},
        },
    ],
)
def test_malformed_auxiliary_evidence_cannot_grant_release(data):
    from relf_agent.capacity_rules import capacity_obligations

    assert capacity_obligations(data) is True


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_original_undispatched_business_action_can_retire_after_terminal(state):
    from relf_agent.capacity_rules import capacity_obligations

    assert (
        capacity_obligations(
            {
                "state": state,
                "actions": [
                    {
                        "kind": "tool",
                        "status": "waiting_approval",
                        "attempts": [],
                    }
                ],
            }
        )
        is False
    )


@pytest.mark.parametrize("mutation", ["missing-marker", "schema-downgrade", "both-removed"])
def test_activation_metadata_cannot_silently_disable_a_fixed_deployment(tmp_path, mutation):
    with SQLiteStore(tmp_path / "metadata.sqlite") as store:
        install(store)
        active = store.conn.execute(
            "SELECT value FROM metadata WHERE key='local_admission_active'"
        ).fetchone()
        assert active is not None and active[0] == digest(identity())
        with store.transaction():
            if mutation in {"missing-marker", "both-removed"}:
                store.conn.execute("DELETE FROM metadata WHERE key='local_admission_active'")
            if mutation in {"schema-downgrade", "both-removed"}:
                store.conn.execute("UPDATE metadata SET value='15' WHERE key='schema_version'")
        with pytest.raises(ValidationError):
            store.local_capacity_policy()
        with pytest.raises(ValidationError):
            with store.transaction():
                store.insert_run(record("bypass"))


def test_subsequent_schema_activation_does_not_forget_the_original_capacity(tmp_path):
    with SQLiteStore(tmp_path / "future-schema.sqlite") as store:
        install(store)
        with store.transaction():
            store.conn.execute("UPDATE metadata SET value='17' WHERE key='schema_version'")
        assert store.local_capacity_policy() == identity()
