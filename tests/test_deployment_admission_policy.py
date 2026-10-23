"""Portable admission policy is independent of existing Run policy releases."""

import importlib
from dataclasses import FrozenInstanceError

import pytest

from relf_agent.errors import ValidationError
from relf_agent.governance import LocalExecutionPolicy, TemporalExecutionPolicy


def policy(**options):
    cls = importlib.import_module("relf_agent.governance").DeploymentAdmissionPolicy
    return cls(**{"deployment_id": "orders", **options})


def test_admission_identity_is_immutable_detached_and_round_trips():
    selected = policy(max_active_root_runs=3, max_active_root_runs_per_scope=2)
    assert selected.identity == {
        "kind": "deployment-admission-policy",
        "deployment_id": "orders",
        "version": "1",
        "max_active_root_runs": 3,
        "max_active_root_runs_per_scope": 2,
    }
    assert type(selected).from_identity(selected.identity) == selected
    detached = selected.identity
    detached["max_active_root_runs"] = 100
    assert selected.max_active_root_runs == 3
    with pytest.raises(FrozenInstanceError):
        selected.max_active_root_runs = 100
    import relf_agent

    assert relf_agent.DeploymentAdmissionPolicy is type(selected)


@pytest.mark.parametrize(
    "options",
    [
        {"deployment_id": ""},
        {"deployment_id": "   "},
        {"deployment_id": None},
        {"version": ""},
        {"version": True},
        {"max_active_root_runs": True},
        {"max_active_root_runs": 0},
        {"max_active_root_runs": -1},
        {"max_active_root_runs": 1.5},
        {"max_active_root_runs": "3"},
        {"max_active_root_runs": 10001},
        {"max_active_root_runs": 1 << 1000},
        {"max_active_root_runs_per_scope": False},
        {"max_active_root_runs_per_scope": 0},
        {"max_active_root_runs_per_scope": float("nan")},
        {"max_active_root_runs": 1, "max_active_root_runs_per_scope": 2},
    ],
)
def test_admission_limits_are_exact_bounded_counts(options):
    with pytest.raises(ValidationError):
        policy(**options)


def test_existing_execution_policy_identities_do_not_gain_admission_fields():
    local = LocalExecutionPolicy(run_timeout_seconds=30).identity
    assert local == {
        "kind": "local-execution-policy",
        "version": "1",
        "run_timeout_seconds": 30,
        "approval_timeout_seconds": None,
    }
    temporal = TemporalExecutionPolicy().identity
    assert set(temporal) == {
        "kind",
        "version",
        "max_children",
        "max_concurrency",
        "max_depth",
        "run_timeout_seconds",
        "approval_timeout_seconds",
        "allowed_tools",
    }
