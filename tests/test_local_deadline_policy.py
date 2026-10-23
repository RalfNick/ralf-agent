import dataclasses

import pytest

from relf_agent import governance
from relf_agent.errors import ValidationError


def test_local_policy_is_immutable_and_separate_from_temporal_policy():
    policy = governance.LocalExecutionPolicy(
        version="business-1", run_timeout_seconds=60, approval_timeout_seconds=12.5
    )
    assert policy.identity == {
        "kind": "local-execution-policy",
        "version": "business-1",
        "run_timeout_seconds": 60,
        "approval_timeout_seconds": 12.5,
    }
    assert policy.identity != governance.TemporalExecutionPolicy().identity
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.run_timeout_seconds = 120


@pytest.mark.parametrize("value", [True, 0, -1, 86401, float("nan"), float("inf"), "30"])
def test_local_policy_rejects_invalid_deadline_before_execution(value):
    with pytest.raises(ValidationError):
        governance.LocalExecutionPolicy(run_timeout_seconds=value)
