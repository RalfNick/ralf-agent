"""Registry4 verifies original SDK evidence before its atomic Session commits."""

import asyncio
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from relf_agent.temporal_state import TemporalCommandRegistryState
from tests.test_temporal_deployment_session_registry import NAMESPACE, POLICY, intent_request


def registry(monkeypatch):
    from relf_agent import temporal_workflow as module
    from relf_agent.temporal_deployment_admission import registry_id

    info = SimpleNamespace(
        namespace=NAMESPACE["name"],
        workflow_id=registry_id(POLICY.deployment_id),
        run_id="registry-original",
        first_execution_run_id="registry-original",
        original_execution_run_id="registry-original",
    )
    monkeypatch.setattr(module.workflow, "info", lambda: info)
    owner = module.TemporalCommandRegistryWorkflow(
        {
            "deployment_admission": {
                "version": 4,
                "policy": POLICY.identity,
                "namespace": NAMESPACE,
            }
        }
    )
    return module, owner, info


def test_registry_four_preserves_shared_original_command_and_root_authority():
    value = TemporalCommandRegistryState(
        admission_policy=POLICY.identity,
        namespace=NAMESPACE,
        admission_protocol=4,
        registry_execution_epoch="registry-original",
    )
    assert value.admission_protocol == 4 and value.deployment.publication_versions == (2, 3, 4)
    assert not value.deployment.commands and not value.deployment.roots


def test_root_commit_waits_for_original_registry_sdk_activity_and_rechecks(monkeypatch):
    module, owner, info = registry(monkeypatch)
    intent, request = intent_request(owner.commands.deployment)
    calls = []

    async def verify(name, body, **options):
        calls.append((name, body, options))
        assert not owner.commands.deployment.roots
        assert body["mode"] == "session_root"
        assert body["registry_execution_epoch"] == info.run_id
        assert body["prepared"]["request"] == request
        assert options["task_queue"] == intent["submission"]["task_queue"]
        assert options["retry_policy"].maximum_attempts == 1
        return {
            "ok": True,
            "result": {key: body["prepared"][key] for key in ("intent", "session_origin")},
        }

    monkeypatch.setattr(module.workflow, "execute_activity", verify)
    first = asyncio.run(owner.reserve_session_root({"request": request, "intent": intent}))
    second = asyncio.run(owner.reserve_session_root({"request": request, "intent": intent}))
    assert first == second and len(calls) == 1
    assert calls[0][0] == "ralf.temporal.session-deployment-verify.v1"
    assert len(owner.commands.deployment.roots) == 1


@pytest.mark.parametrize("fault", ["forged_verification", "registry_reset", "verify_error"])
def test_invalid_sdk_result_never_commits_session_root(monkeypatch, fault):
    module, owner, info = registry(monkeypatch)
    intent, request = intent_request(owner.commands.deployment)

    async def verify(name, body, **options):
        if fault == "registry_reset":
            info.run_id = "replaced"
        if fault == "verify_error":
            return {"ok": False, "code": "definition_mismatch"}
        result = {key: body["prepared"][key] for key in ("intent", "session_origin")}
        if fault == "forged_verification":
            result["intent"] = {**result["intent"], "run_id": "another-run"}
        return {"ok": True, "result": result}

    monkeypatch.setattr(module.workflow, "execute_activity", verify)
    with pytest.raises(ApplicationError):
        asyncio.run(owner.reserve_session_root({"request": request, "intent": intent}))
    assert not owner.commands.deployment.roots


def test_registered_close_update_persists_gate_and_returns_original_inventory(monkeypatch):
    from tests.test_temporal_deployment_session_registry import close_request, command, lookup

    module, owner, _ = registry(monkeypatch)
    definition = module.workflow._Definition.must_from_class(type(owner))
    assert "close_deployment_sessions" in definition.updates
    request = command()
    first = asyncio.run(owner.reserve(request))
    closing = close_request(request["session_submission"]["binding"]["manifest"])
    result = asyncio.run(definition.updates["close_deployment_sessions"].fn(owner, closing))
    assert result == {
        "manifest_digest": closing["manifest_digest"],
        "close_requested": True,
        "candidates": [owner.commands.deployment.deployment_session_command(lookup(request))],
    }
    assert asyncio.run(owner.reserve(request)) == first
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(owner.reserve(command("after-close")))
    assert caught.value.type == "definition_mismatch"
    assert len(owner.commands.deployment.commands) == 1 and not owner.commands.deployment.roots


@pytest.mark.parametrize("fault", ["registry_reset", "invalid_request"])
def test_registered_close_refuses_original_epoch_or_request_change_without_gate(monkeypatch, fault):
    from tests.test_temporal_deployment_session_registry import close_request, command

    module, owner, info = registry(monkeypatch)
    definition = module.workflow._Definition.must_from_class(type(owner))
    assert "close_deployment_sessions" in definition.updates
    closing = close_request(command()["session_submission"]["binding"]["manifest"])
    if fault == "registry_reset":
        info.run_id = "replacement"
    else:
        closing["unexpected"] = True
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(definition.updates["close_deployment_sessions"].fn(owner, closing))
    assert caught.value.type == (
        "definition_mismatch" if fault == "registry_reset" else "validation_error"
    )
    assert caught.value.non_retryable is True
    assert not owner.commands.deployment.session_closed
