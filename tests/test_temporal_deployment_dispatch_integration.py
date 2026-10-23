"""Worker-only SDK integration; public assembly and safe release remain gated."""

import asyncio
from types import SimpleNamespace

import pytest

from relf_agent import DeploymentAdmissionPolicy, ModelResponse, TemporalRuntime, ToolRegistry
from relf_agent.errors import DefinitionMismatch, ValidationError


class Provider:
    identity = {"kind": "deployment-integration-provider", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output="done")


def runtime(**options):
    return TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry(), **options)


def test_worker_policy_is_explicit_and_published_with_original_identity():
    policy = DeploymentAdmissionPolicy("worker-only", max_active_root_runs=1)
    selected = runtime(_deployment_admission_policy=policy)
    manifest = selected.manifest
    protocol = manifest["deployment_admission_protocol"]
    assert protocol["version"] == 1 and protocol["policy"] == policy.identity
    assert selected.validate_release(manifest) == manifest
    manifest["deployment_admission_protocol"]["policy"]["version"] = "changed"
    with pytest.raises(DefinitionMismatch):
        selected.validate_release(manifest)


@pytest.mark.parametrize("value", [{}, True, lambda: None, object()])
def test_invalid_worker_policy_is_rejected_before_provider_inspection(value):
    class UnusedProvider:
        @property
        def identity(self):
            raise AssertionError("Invalid policy reached component inspection")

    with pytest.raises(ValidationError):
        TemporalRuntime(
            providers={"default": UnusedProvider()},
            tools=ToolRegistry(),
            _deployment_admission_policy=value,
        )


def test_unselected_default_manifest_has_no_deployment_protocol():
    omitted = runtime()
    explicit = runtime(_deployment_admission_policy=None)
    assert explicit.manifest == omitted.manifest
    assert "deployment_admission_protocol" not in omitted.manifest


@pytest.mark.parametrize("change", ["replace", "clear", "identity"])
def test_worker_policy_owner_and_identity_cannot_change(change):
    policy = DeploymentAdmissionPolicy("fixed")
    selected = runtime(_deployment_admission_policy=policy)
    if change == "replace":
        selected._deployment_admission_policy = DeploymentAdmissionPolicy("fixed")
    elif change == "clear":
        selected._deployment_admission_policy = None
    else:
        object.__setattr__(policy, "version", "2")
    with pytest.raises(DefinitionMismatch):
        selected.validate_release()


def test_public_engine_refuses_incomplete_worker_only_protocol_before_network():
    from relf_agent.temporal import TemporalEngine

    selected = runtime(_deployment_admission_policy=DeploymentAdmissionPolicy("worker-only"))
    with pytest.raises(ValidationError, match="deployment"):
        TemporalEngine(object(), task_queue="unused", release=selected.manifest)


def test_selected_coding_has_no_legacy_scoped_registry_fallback():
    with pytest.raises(ValidationError, match="deployment"):
        runtime(
            _deployment_admission_policy=DeploymentAdmissionPolicy("worker-only"),
            coding_execution=True,
        )


def test_selected_worker_wraps_all_registered_activity_categories(monkeypatch):
    pytest.importorskip("temporalio")
    import temporalio.worker
    from temporalio import activity

    from relf_agent.temporal import build_temporal_worker
    from relf_agent.temporal_deployment_execution import ACTIVITY

    recorded = {}

    def fake_worker(client, **options):
        recorded.update(options)
        return SimpleNamespace(options=options)

    monkeypatch.setattr(temporalio.worker, "Worker", fake_worker)
    selected = runtime(_deployment_admission_policy=DeploymentAdmissionPolicy("worker-only"))
    build_temporal_worker(
        SimpleNamespace(namespace="original"), runtime=selected, task_queue="queue"
    )
    functions = recorded["activities"]
    names = {activity._Definition.must_from_callable(f).name for f in functions}
    assert ACTIVITY in names
    for function in functions:
        name = activity._Definition.must_from_callable(function).name
        if name != ACTIVITY:
            assert hasattr(function, "__wrapped__"), name
    assert any("reconcile" in n for n in names)
    assert any("evidence" in n for n in names)
    assert any("selection" in n for n in names)
    assert any("completion" in n for n in names)


def test_both_original_workflow_types_use_admission_before_business():
    pytest.importorskip("temporalio")
    from relf_agent.temporal_parent_workflow import TemporalParentWorkflow
    from relf_agent.temporal_workflow import TemporalRunWorkflow

    assert asyncio.iscoroutinefunction(TemporalRunWorkflow._ensure_deployment_admission)
    assert (
        TemporalParentWorkflow._ensure_deployment_admission
        is TemporalRunWorkflow._ensure_deployment_admission
    )
