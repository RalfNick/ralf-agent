"""Public Registry authority stays in its first SDK History; no service required."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")
from temporalio.exceptions import ApplicationError

from ralf_agent.temporal_deployment_admission import registry_id
from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow, workflow
from tests.test_temporal_deployment_admission_workflow import (
    query as private_query,
)
from tests.test_temporal_deployment_admission_workflow import (
    selected as private_registry,
)
from tests.test_temporal_deployment_admission_workflow import (
    submission as private_submission,
)
from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY, SCOPE, setup

UPDATES = (
    "reserve",
    "record_deployment_submission",
    "release_deployment_root",
    "admit_coding_composition_submission",
    "close_coding_composition_submissions",
    "close_deployment_coding_submissions",
    "bind_deployment_root",
)
QUERY_KINDS = (
    "deployment_configuration",
    "deployment_submission",
    "deployment_retirement",
    "deployment_admission",
    "coding_composition_candidates",
    "coding_composition_admission",
)


def sdk_info(**changes):
    return SimpleNamespace(
        **{
            "namespace": NAMESPACE["name"],
            "workflow_id": registry_id(POLICY.deployment_id),
            "run_id": "first-sdk-epoch",
            "original_execution_run_id": "first-sdk-epoch",
            "first_execution_run_id": "first-sdk-epoch",
            **changes,
        }
    )


def registry(monkeypatch, version, **changes):
    monkeypatch.setattr(workflow, "info", lambda: sdk_info(**changes))
    return TemporalCommandRegistryWorkflow(
        {
            "deployment_admission": {
                "version": version,
                "policy": POLICY.identity,
                "namespace": NAMESPACE,
            }
        }
    )


def configuration(kind="deployment_configuration"):
    return {
        "kind": kind,
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
    }


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("operation", UPDATES)
def test_reset_registry_refuses_every_update_before_acceptance_or_release_io(
    monkeypatch, version, operation
):
    authority = registry(monkeypatch, version, run_id="reset-sdk-epoch")
    before = copy.deepcopy(vars(authority.commands.deployment))
    _, request = setup()
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Reset authority must never verify retirement")

    monkeypatch.setattr(workflow, "execute_activity", forbidden)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(getattr(authority, operation)(request))
    assert error.value.type == "definition_mismatch" and error.value.non_retryable
    assert vars(authority.commands.deployment) == before
    assert calls == []


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("kind", QUERY_KINDS)
def test_reset_registry_does_not_expose_configuration_or_authority_queries(
    monkeypatch, version, kind
):
    authority = registry(monkeypatch, version, run_id="reset-sdk-epoch")
    assert authority.view(configuration(kind)) == {"error": "definition_mismatch"}


@pytest.mark.parametrize("version", [2, 3])
def test_reset_initialization_is_deferred_to_sdk_owned_run(monkeypatch, version):
    authority = registry(monkeypatch, version, run_id="reset-sdk-epoch")
    waited = []

    async def forbidden(*args, **kwargs):
        waited.append(True)

    monkeypatch.setattr(workflow, "wait_condition", forbidden)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(authority.run({}))
    assert error.value.type == "definition_mismatch" and error.value.non_retryable
    assert waited == []


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize(
    "changes",
    [
        {"original_execution_run_id": None},
        {"original_execution_run_id": ""},
        {"original_execution_run_id": 1},
        {"first_execution_run_id": "previous-history"},
        {"first_execution_run_id": None},
        {"run_id": ""},
    ],
)
def test_public_registry_requires_complete_original_sdk_epoch(monkeypatch, version, changes):
    authority = registry(monkeypatch, version, **changes)
    assert authority.view(configuration()) == {"error": "definition_mismatch"}


@pytest.mark.parametrize("version", [2, 3])
def test_first_public_registry_keeps_original_receipts_and_configuration(monkeypatch, version):
    authority = registry(monkeypatch, version)
    _, request = setup()
    first = asyncio.run(authority.reserve(request))
    assert asyncio.run(authority.reserve(request)) == first
    assert len(authority.commands.deployment.roots) == 1
    assert authority.view(configuration())["version"] == version


def test_registry_rechecks_current_sdk_epoch_before_release_prepare(monkeypatch):
    authority = registry(monkeypatch, 2)
    _, request = setup()
    asyncio.run(authority.reserve(request))
    before = copy.deepcopy(vars(authority.commands.deployment))
    monkeypatch.setattr(workflow, "info", lambda: sdk_info(run_id="reset-sdk-epoch"))
    with pytest.raises(ApplicationError) as error:
        asyncio.run(authority.release_deployment_root({}))
    assert error.value.type == "definition_mismatch"
    assert vars(authority.commands.deployment) == before


def test_registry_initialization_refusal_remains_sticky(monkeypatch):
    authority = registry(monkeypatch, 3, run_id="reset-sdk-epoch")
    monkeypatch.setattr(workflow, "info", sdk_info)
    assert authority.view(configuration()) == {"error": "definition_mismatch"}


def test_release_verification_cannot_commit_after_sdk_epoch_changes(monkeypatch):
    authority = registry(monkeypatch, 3)
    calls = []
    monkeypatch.setattr(authority.commands, "deployment_retirement", lambda request: None)
    monkeypatch.setattr(
        authority.commands,
        "prepare_deployment_release",
        lambda request: {
            "root": {"scope": SCOPE},
            "certificate": {},
            "manifest": {},
            "task_queue": "original-queue",
            "activity_timeout": 30,
        },
    )

    async def verify(*args, **kwargs):
        calls.append("verify")
        monkeypatch.setattr(workflow, "info", lambda: sdk_info(run_id="reset-sdk-epoch"))
        return {"ok": True, "result": {}}

    def commit(*args):
        calls.append("commit")
        return {}

    monkeypatch.setattr(workflow, "execute_activity", verify)
    monkeypatch.setattr(authority.commands, "commit_deployment_release", commit)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(authority.release_deployment_root({}))
    assert error.value.type == "definition_mismatch" and error.value.non_retryable
    assert calls == ["verify"]


@pytest.mark.parametrize("version", [2, 3])
def test_first_public_registry_run_retains_original_wait_only_behavior(monkeypatch, version):
    authority = registry(monkeypatch, version)
    waited = []

    async def wait(predicate):
        waited.append(predicate())

    monkeypatch.setattr(workflow, "wait_condition", wait)
    asyncio.run(authority.run({}))
    assert waited == [False]


def test_private_registry_one_keeps_existing_sdk_info_requirements(monkeypatch):
    authority = private_registry(monkeypatch, run_id="reset-sdk-epoch")
    first = asyncio.run(authority.reserve(private_submission()))
    assert asyncio.run(authority.reserve(private_submission())) == first
    assert "error" not in authority.view(private_query())


def test_default_scoped_registry_never_requires_new_sdk_info(monkeypatch):
    def forbidden():
        raise AssertionError("Unselected Registry must not inspect deployment epochs")

    monkeypatch.setattr(workflow, "info", forbidden)
    authority = TemporalCommandRegistryWorkflow({"scope": SCOPE})
    assert authority.view({"scope": SCOPE}) == {
        "scope": SCOPE,
        "capacity": authority.commands.capacity,
        "accepted_commands": 0,
    }
