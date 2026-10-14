"""Original Registry Workflow routing; no business execution or safe-release claim."""

import asyncio
import copy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import DeploymentAdmissionPolicy, Scope
from ralf_agent.types import digest

pytest.importorskip("temporalio")

POLICY = DeploymentAdmissionPolicy("workflow-admission", max_active_root_runs=1).identity
NAMESPACE = {"name": "original", "id": "12345678-1234-1234-1234-123456789abc"}
SCOPE = asdict(Scope("workspace", "owner"))


class EnvelopeSubclass(dict):
    pass


def selected(monkeypatch, *, accepted=None, **info):
    from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow, workflow

    monkeypatch.setattr(
        workflow,
        "info",
        lambda: SimpleNamespace(
            **{
                "workflow_id": "ralf-temporal-deployment-" + digest(POLICY["deployment_id"]),
                "namespace": NAMESPACE["name"],
                **info,
            }
        ),
    )
    return TemporalCommandRegistryWorkflow(
        accepted
        if accepted is not None
        else {"deployment_admission": {"version": 1, "policy": POLICY, "namespace": NAMESPACE}}
    )


def submission(command="first", *, scope=SCOPE):
    return {
        "scope": copy.deepcopy(scope),
        "command_id": command,
        "kind": "submit",
        "target": "ralf-temporal-" + digest([POLICY["deployment_id"], scope, command]),
        "payload_digest": "a" * 64,
        "admission_policy": copy.deepcopy(POLICY),
        "namespace": copy.deepcopy(NAMESPACE),
        "root_admission": {"version": 1, "manifest_digest": "b" * 64},
    }


def query(scope=SCOPE):
    return {
        "kind": "deployment_admission",
        "scope": copy.deepcopy(scope),
        "admission_policy": copy.deepcopy(POLICY),
        "namespace": copy.deepcopy(NAMESPACE),
    }


def test_selected_registry_routes_original_reserve_and_private_observation(monkeypatch):
    registry = selected(monkeypatch)
    first = asyncio.run(registry.reserve(submission()))
    assert first["record_state"] == "durably_recorded"
    assert first["apply_state"] == "not_applied"
    assert asyncio.run(registry.reserve(submission())) == first
    own = registry.view(query())
    assert "error" not in own
    assert submission()["target"] in str(own)
    foreign = registry.view(query(asdict(Scope("workspace", "other"))))
    assert submission()["target"] not in str(foreign)
    assert '"owner"' not in str(foreign)


def test_full_update_has_typed_transient_capacity_error_without_record(monkeypatch):
    from temporalio.exceptions import ApplicationError

    registry = selected(monkeypatch)
    first = asyncio.run(registry.reserve(submission()))
    with pytest.raises(ApplicationError) as error:
        asyncio.run(registry.reserve(submission("refused")))
    assert error.value.type == "capacity_exceeded" and error.value.non_retryable
    assert "refused" not in str(registry.view(query()))
    assert asyncio.run(registry.reserve(submission())) == first


@pytest.mark.parametrize(
    "info",
    [{"namespace": "replacement"}, {"workflow_id": "wrong-original-registry"}],
)
def test_registry_initialization_rejects_actual_address_mismatch(monkeypatch, info):
    from ralf_agent.errors import DefinitionMismatch

    with pytest.raises(DefinitionMismatch):
        selected(monkeypatch, **info)


@pytest.mark.parametrize(
    "accepted",
    [
        {"deployment_admission": None},
        {"deployment_admission": {"version": True, "policy": POLICY, "namespace": NAMESPACE}},
        {"deployment_admission": {"version": 1, "policy": POLICY}},
        {
            "deployment_admission": {"version": 1, "policy": POLICY, "namespace": NAMESPACE},
            "scope": SCOPE,
        },
        {
            "deployment_admission": {
                "version": 1,
                "policy": POLICY,
                "namespace": NAMESPACE,
                "extra": 1,
            }
        },
        {"deployment_admission": {"version": 1, "policy": None, "namespace": None}},
        {"deployment_admission": {"version": 1, "policy": None, "namespace": NAMESPACE}},
        {"deployment_admission": {"version": 1, "policy": POLICY, "namespace": None}},
    ],
)
def test_registry_initialization_requires_exact_explicit_envelope(monkeypatch, accepted):
    from ralf_agent.errors import RalfError

    with pytest.raises(RalfError):
        selected(monkeypatch, accepted=accepted)


@pytest.mark.parametrize(
    "accepted",
    [
        None,
        [],
        1,
        EnvelopeSubclass(
            {"deployment_admission": {"version": 1, "policy": POLICY, "namespace": NAMESPACE}}
        ),
    ],
)
def test_registry_initialization_rejects_nonplain_outer_envelope(monkeypatch, accepted):
    from ralf_agent.errors import DefinitionMismatch
    from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow

    selected(monkeypatch)
    with pytest.raises(DefinitionMismatch):
        TemporalCommandRegistryWorkflow(accepted)


@pytest.mark.parametrize(
    "operation",
    ["admit_coding_composition_submission", "close_coding_composition_submissions"],
)
def test_deployment_mode_refuses_unintegrated_composition_routes(monkeypatch, operation):
    from temporalio.exceptions import ApplicationError

    registry = selected(monkeypatch)
    with pytest.raises(ApplicationError):
        asyncio.run(getattr(registry, operation)({"scope": None}))


@pytest.mark.parametrize(
    "extra", [{"kind": "unknown"}, {"extra": True}, {"namespace": NAMESPACE["name"]}]
)
def test_selected_query_rejects_malformed_or_unscoped_observation(monkeypatch, extra):
    registry = selected(monkeypatch)
    result = registry.view({**query(), **extra})
    assert set(result) == {"error"}
    assert result["error"] in {"validation_error", "definition_mismatch", "authorization_denied"}


def test_binding_update_is_explicit_and_does_not_exist_in_default_mode(monkeypatch):
    from temporalio.exceptions import ApplicationError

    from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow

    registry = selected(monkeypatch)
    assert asyncio.iscoroutinefunction(registry.bind_deployment_root)
    with pytest.raises(ApplicationError):
        asyncio.run(TemporalCommandRegistryWorkflow({"scope": SCOPE}).bind_deployment_root({}))


def test_original_binding_update_pins_epoch_and_retains_initial_reservation(monkeypatch):
    from temporalio.exceptions import ApplicationError

    registry = selected(monkeypatch)
    first = asyncio.run(registry.reserve(submission()))
    root = first["root_admission"]
    request = {
        "scope": SCOPE,
        "admission_policy": POLICY,
        "namespace": NAMESPACE,
        "command_id": root["command_id"],
        "run_id": root["run_id"],
        "request_digest": root["request_digest"],
        "manifest_digest": root["manifest_digest"],
        "proof_digest": root["proof_digest"],
        "execution_epoch": "original-sdk-epoch",
    }
    bound = asyncio.run(registry.bind_deployment_root(request))
    assert bound["execution_epoch"] == "original-sdk-epoch"
    assert bound["state"] == "held-bound"
    assert asyncio.run(registry.bind_deployment_root(request)) == bound
    assert asyncio.run(registry.reserve(submission())) == first
    with pytest.raises(ApplicationError) as error:
        asyncio.run(registry.bind_deployment_root({**request, "execution_epoch": "replacement"}))
    assert error.value.type == "definition_mismatch"
    assert registry.view(query())["held_roots"] == [bound]
