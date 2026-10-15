"""Registry configuration and original Session SDK parent stay distinct from edges."""

import copy

import pytest

from ralf_agent import temporal_deployment_control_projection as projection
from ralf_agent import temporal_deployment_execution_state as deployment
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_bindings import request_release_digest
from ralf_agent.temporal_state import TemporalCommandRegistryState
from ralf_agent.types import digest
from tests.test_temporal_deployment_coding_registry import coding_request
from tests.test_temporal_deployment_control_projection import bound_registry
from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY, SCOPE
from tests.test_temporal_deployment_session_registry import (
    NAMESPACE as SESSION_NS,
)
from tests.test_temporal_deployment_session_registry import (
    POLICY as SESSION_POLICY,
)
from tests.test_temporal_deployment_session_registry import (
    verified,
)
from tests.test_temporal_session_coding_ancestry import coding_original
from tests.test_temporal_session_deployment_coding_registry import coding_intent_request
from tests.test_temporal_session_deployment_execution import admit, coordinator, initialize


def test_compact_configuration_is_original_registry_four_even_for_legacy_coding_three():
    wrapper = TemporalCommandRegistryState(
        admission_policy=POLICY.identity,
        namespace=NAMESPACE,
        admission_protocol=4,
        registry_execution_epoch="original-registry-epoch",
    )
    submitted = coding_request()
    accepted = wrapper.reserve(submitted)
    root = accepted["root_admission"]
    bound = wrapper.bind_deployment_root(
        {
            "scope": SCOPE,
            "admission_policy": POLICY.identity,
            "namespace": NAMESPACE,
            **{
                name: root[name]
                for name in (
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "execution_epoch": "original-epoch",
        }
    )
    state = wrapper.deployment
    state.deployment_registry_execution_epoch = "original-registry-epoch"
    request = {
        "kind": "deployment_coding_validation",
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        **{
            name: bound[name]
            for name in (
                "command_id",
                "run_id",
                "execution_epoch",
                "request_digest",
                "manifest_digest",
            )
        },
    }
    before = copy.deepcopy(vars(state))
    view = projection.registry(state, request)
    assert view["configuration_version"] == 4
    assert view["proof_digest"] == digest(
        {key: value for key, value in view.items() if key != "proof_digest"}
    )
    assert vars(state) == before
    _, legacy, _, _, legacy_request = bound_registry()
    assert projection.registry(legacy, legacy_request)["configuration_version"] == 3


@pytest.mark.parametrize("composition", [False, True])
def test_session_node_identity_keeps_coordinator_outside_business_lineage(composition):
    intent, metadata, state = coding_original(composition=composition)
    initialize(state, metadata, coordinator(intent))
    admit(state)
    proof = deployment.view(state)
    start = {
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "request_digest": digest(state.request),
        "manifest_digest": digest(state.manifest),
        "activity_timeout": intent["submission"]["activity_timeout"],
        "task_queue": intent["submission"]["task_queue"],
    }
    coding = None
    if composition:
        fields = {
            name: proof[name]
            for name in (
                "version",
                "scope",
                "run_id",
                "execution_epoch",
                "original_execution_epoch",
                "namespace",
                "request",
                "request_digest",
                "manifest",
            )
        }
        coding = {
            **fields,
            "release_digest": request_release_digest(state.request, state.manifest),
            "revision": 0,
            "state": "running",
            "physical_stopped": False,
            "action_stops": [],
        }
        coding["proof_digest"] = digest(coding)
    result = projection.node_identity_digest(proof, start, coding)
    assert len(result) == 64 and proof["admission"]["lineage"] == []
    assert proof["admission"]["session_origin"] == metadata["session_origin"]


def bound_session_registry():
    wrapper = TemporalCommandRegistryState(
        admission_policy=SESSION_POLICY.identity,
        namespace=SESSION_NS,
        admission_protocol=4,
        registry_execution_epoch="registry-original",
    )
    state = wrapper.deployment
    intent, request = coding_intent_request(state)
    receipt = state.commit_session_root(request, intent, verified(intent, request))
    root = receipt["root_admission"]
    bound = wrapper.bind_deployment_root(
        {
            "scope": intent["scope"],
            "admission_policy": SESSION_POLICY.identity,
            "namespace": SESSION_NS,
            **{
                name: root[name]
                for name in (
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "execution_epoch": "business-epoch",
        }
    )
    state.deployment_registry_execution_epoch = "registry-original"
    query = {
        "kind": "deployment_coding_validation",
        "scope": intent["scope"],
        "admission_policy": SESSION_POLICY.identity,
        "namespace": SESSION_NS,
        **{
            name: bound[name]
            for name in (
                "command_id",
                "run_id",
                "execution_epoch",
                "request_digest",
                "manifest_digest",
            )
        },
    }
    return state, intent, request, query


def test_session_compact_registry_validates_original_intent_without_ordinary_alias():
    state, intent, request, query = bound_session_registry()
    before = copy.deepcopy(vars(state))
    view = projection.registry(state, query)
    assert view["configuration_version"] == 4 and view["held"] and view["admitted"]
    assert vars(state) == before
    key = digest([intent["scope"], intent["run_command_id"]])
    state.session_roots[key]["intent"]["binding"]["task_queue"] = "forged-original"
    with pytest.raises((DefinitionMismatch, ValidationError)):
        projection.registry(state, query)


def sdk_session_environment(monkeypatch):
    """Inject full SDK proofs; keep exact Session DTOs and compact validators real."""
    from types import SimpleNamespace

    from temporalio.client import WorkflowExecutionStatus

    from ralf_agent import temporal_deployment_execution as execution
    from ralf_agent import temporal_session_deployment_verification as verification
    from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME, WORKFLOW_NAME
    from tests.test_temporal_deployment_coding_validation import Client, Handle, Runtime, seal

    intent, metadata, state = coding_original(composition=False)
    initialize(state, metadata, coordinator(intent))
    admit(state)
    proof = deployment.view(state)
    policy = SESSION_POLICY

    class SessionHandle(Handle):
        async def query(self, name, request):
            if request["kind"] == "deployment_configuration":
                return {
                    "version": 4,
                    "registry_id": self.identity,
                    "policy": policy.identity,
                    "namespace": intent["namespace"],
                }
            if request["kind"] == "deployment_session_root":
                self.client.session_root_reads += 1
                return copy.deepcopy(self.client.record)
            if request["kind"] == "deployment_submission":
                raise AssertionError("A Session root cannot be adopted as an ordinary submission")
            return await super().query(name, request)

    class SessionClient(Client):
        def get_workflow_handle(self, identity, **options):
            return SessionHandle(self, identity, options.get("run_id"))

    client = SessionClient()
    client.namespace_uuid = intent["namespace"]["id"]
    client.session_root_reads, client.origin_reads, client.session_reset = 0, 0, False
    runtime = Runtime(state.manifest)
    runtime._deployment_admission_policy = runtime._deployment_admission_policy_pin = policy
    runtime._deployment_admission_identity = policy.identity
    start = {
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "request_digest": digest(state.request),
        "manifest_digest": digest(state.manifest),
        "activity_timeout": intent["submission"]["activity_timeout"],
        "task_queue": intent["submission"]["task_queue"],
    }
    rid = metadata["root"]["registry_id"]
    for key, run_id, epoch, workflow_type, parent_id, parent_epoch in (
        (
            "root",
            state.run_id,
            state.epoch,
            WORKFLOW_NAME,
            intent["coordinator_id"],
            intent["coordinator_execution_epoch"],
        ),
        (rid, rid, "registry-original", COMMAND_REGISTRY_NAME, None, None),
    ):
        client.descriptions[key] = SimpleNamespace(
            id=run_id,
            run_id=epoch,
            raw_info=SimpleNamespace(first_run_id=epoch),
            namespace=intent["namespace"]["name"],
            status=WorkflowExecutionStatus.RUNNING,
            workflow_type=workflow_type,
            task_queue=start["task_queue"],
            parent_id=parent_id,
            parent_run_id=parent_epoch,
        )
    client.starts["root"] = start
    client.compact["root"] = seal(
        {
            "version": 1,
            "scope": state.scope,
            "namespace": intent["namespace"],
            "run_id": state.run_id,
            "execution_epoch": state.epoch,
            "original_execution_epoch": state.epoch,
            "identity_digest": projection.node_identity_digest(proof, start),
            "revision": 0,
            "state": "running",
            "stop_requested": False,
            "sealed": False,
            "edge": None,
        }
    )
    client.record = {
        "reservation": {
            "command_id": intent["run_command_id"],
            "target": state.run_id,
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
            "root_admission": metadata["root"],
        },
        "submission": intent["submission"],
        "run_receipt": None,
        "execution_epoch": state.epoch,
        "intent": intent,
        "session_origin": metadata["session_origin"],
    }
    client.compact[rid] = seal(
        {
            "version": 1,
            "registry_id": rid,
            "registry_execution_epoch": "registry-original",
            "configuration_version": 4,
            "policy": policy.identity,
            "scope": state.scope,
            "namespace": intent["namespace"],
            "root_identity_digest": projection.root_identity_digest(
                proof["admission_receipt"]["root"]
            ),
            "submission_digest": projection.submission_identity_digest(intent["submission"]),
            "held": True,
            "retired": False,
            "close_requested": False,
            "admitted": True,
        }
    )

    async def original_proof(*args, **kwargs):
        return copy.deepcopy(proof)

    async def original_origin(runtime, actual_client, checked_intent, checked_origin):
        client.origin_reads += 1
        if (
            client.session_reset
            or checked_intent != intent
            or checked_origin != metadata["session_origin"]
        ):
            raise DefinitionMismatch("Original Session coordinator SDK execution changed")
        return {
            "intent": copy.deepcopy(intent),
            "session_origin": copy.deepcopy(metadata["session_origin"]),
        }

    monkeypatch.setattr(execution, "_proof", original_proof)
    monkeypatch.setattr(execution, "_ancestry", original_proof)
    monkeypatch.setattr(verification, "validate_session_origin", original_origin)
    request = {
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "runtime_manifest": state.manifest,
        "coding_request": {"request_digest": digest("native")},
    }
    info = SimpleNamespace(
        workflow_id=state.run_id,
        workflow_run_id=state.epoch,
        workflow_namespace=intent["namespace"]["name"],
        activity_id="original-native",
        attempt=1,
    )
    return runtime, client, request, info


def test_compact_session_native_checks_original_coordinator_after_each_fresh_readset(
    monkeypatch,
):
    import asyncio

    from ralf_agent.temporal_deployment_coding_validation import CodingValidation

    runtime, client, request, info = sdk_session_environment(monkeypatch)
    validator = CodingValidation(runtime, client, request, info)

    async def run():
        assert await validator.permission() is True
        before = client.origin_reads
        assert client.session_root_reads == 1
        assert await validator.permission() is True
        assert client.origin_reads == before + 1 and client.session_root_reads == 1
        client.session_reset = True
        with pytest.raises(DefinitionMismatch):
            await validator.permission()

    asyncio.run(run())


def test_session_reset_during_compact_reads_refuses_before_native_permission(monkeypatch):
    import asyncio

    from ralf_agent.temporal_deployment_coding_validation import CodingValidation

    runtime, client, request, info = sdk_session_environment(monkeypatch)
    validator = CodingValidation(runtime, client, request, info)

    async def reset(identity):
        client.session_reset = True

    async def run():
        assert await validator.permission()
        client.read_hook = reset
        with pytest.raises(DefinitionMismatch):
            await validator.permission()

    asyncio.run(run())


@pytest.mark.parametrize("field", ["intent", "origin", "configuration"])
def test_compact_session_rejects_changed_original_acceptance_and_actual_configuration(
    monkeypatch, field
):
    import asyncio

    from ralf_agent.temporal_deployment_coding_validation import CodingValidation
    from tests.test_temporal_deployment_coding_validation import seal

    runtime, client, request, info = sdk_session_environment(monkeypatch)
    if field == "intent":
        client.record["intent"]["binding"]["task_queue"] = "rebound-queue"
    elif field == "origin":
        client.record["session_origin"]["coordinator_first_execution_epoch"] = "replacement"
    else:
        rid = client.record["reservation"]["root_admission"]["registry_id"]
        client.compact[rid] = seal({**client.compact[rid], "configuration_version": 3})
    validator = CodingValidation(runtime, client, request, info)
    with pytest.raises((DefinitionMismatch, ValidationError)):
        asyncio.run(validator.permission())


def test_compact_session_fresh_origin_verifier_binding_cannot_change(monkeypatch):
    import asyncio

    from ralf_agent import temporal_session_deployment_verification as verification
    from ralf_agent.temporal_deployment_coding_validation import CodingValidation

    runtime, client, request, info = sdk_session_environment(monkeypatch)
    validator = CodingValidation(runtime, client, request, info)

    async def substituted(*args):
        raise AssertionError("Changed verifier must be refused before use")

    async def run():
        assert await validator.permission()
        monkeypatch.setattr(verification, "validate_session_origin", substituted)
        with pytest.raises(DefinitionMismatch):
            await validator.permission()

    asyncio.run(run())
