"""SDK release verifies v3 call fences without weakening old v2 records."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.types import digest


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


def environment(monkeypatch, publication=3, registry_version=3):
    from ralf_agent import temporal_deployment_release_state as state_module

    from .test_temporal_deployment_coding_registry import coding_request
    from .test_temporal_deployment_execution import sealed
    from .test_temporal_deployment_release import environment as ordinary

    runtime, client, state, proof, info = ordinary(monkeypatch)
    if publication == 3:
        manifest = copy.deepcopy(coding_request()["root_admission"]["submission"]["manifest"])
        manifest["deployment_admission_protocol"].update(
            policy=runtime._deployment_admission_identity,
            registry_id=client.registry.registry_id,
        )
        runtime.manifest = state.manifest = manifest
        root = copy.deepcopy(proof["admission"]["root"])
        root["manifest_digest"] = digest(manifest)
        root["proof_digest"] = digest(
            {k: v for k, v in root.items() if k not in {"proof_digest", "state", "execution_epoch"}}
        )
        metadata = {"version": 1, "root": root, "lineage": []}
        bound = {**root, "state": "held-bound", "execution_epoch": state.epoch}
        client.registry.roots[digest([state.scope, root["command_id"]])] = bound
        receipt = sealed(
            {
                "version": 1,
                "run_id": state.run_id,
                "execution_epoch": state.epoch,
                "root": bound,
                "metadata_digest": digest(metadata),
            }
        )
        proof = sealed(
            {
                **proof,
                "manifest": manifest,
                "manifest_digest": digest(manifest),
                "admission": metadata,
                "admission_receipt": receipt,
            }
        )
        client.proofs[state.run_id] = proof
    state.tool_executions = {}
    original_handle = client.get_workflow_handle
    client.cold_candidate = None

    class Handle:
        def __init__(self, original):
            self.original = original

        async def describe(self):
            return await self.original.describe()

        async def query(self, name, value):
            if value["kind"] == "deployment_configuration":
                result = await self.original.query(name, value)
                return {**result, "version": registry_version}
            if value["kind"] == "deployment_coding_call_candidate":
                return copy.deepcopy(client.cold_candidate)
            return await self.original.query(name, value)

        async def execute_update(self, *args, **kwargs):
            return await self.original.execute_update(*args, **kwargs)

    client.get_workflow_handle = lambda *args, **kwargs: Handle(original_handle(*args, **kwargs))
    identity = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "activity_id": "original-call",
        "activity_name": "ralf.temporal.tool.v1",
        "attempt": 1,
        "invocation_id": "a" * 32,
        "request_digest": "a" * 64,
        "manifest_digest": digest(runtime.manifest),
    }
    state_module.begin_activity(state, identity)
    state_module.end_activity(state, identity)
    return runtime, client, state, proof, info, identity


def test_normal_stopped_v3_call_has_none_fence_and_can_release(monkeypatch):
    from ralf_agent import temporal_deployment_release as release

    async def run():
        runtime, client, state, proof, _, _ = environment(monkeypatch)
        assert next(iter(state.deployment_calls.values()))["fence_proof"] is None
        value = await release._closure(
            runtime, client, runtime._deployment_admission_identity, proof
        )
        assert value["ready"] is True

    asyncio.run(run())


@pytest.mark.parametrize("fault", [None, "identity", "changed-candidate", "extra-field", "present"])
def test_persisted_v3_fence_must_match_exact_original_history_candidate(monkeypatch, fault):
    from ralf_agent import temporal_deployment_release as release

    async def run():
        runtime, client, state, proof, _, identity = environment(monkeypatch)
        owner = {
            "version": 1,
            "pid": 123,
            "start": "original-birth",
            "deployment": "b" * 64,
            "invocation_id": "native-owner",
        }
        candidate = {
            "version": 1,
            "identity": identity,
            "action_id": "original-tool",
            "tool_request_digest": "a" * 64,
            "owner": owner,
            "owner_stop_proof": {"original": "durable-proof"},
            "runner": {"original": "runner"},
            "namespace": proof["namespace"],
            "execution_epoch": state.epoch,
        }
        client.cold_candidate = copy.deepcopy(candidate)
        attestation = {**candidate, "process_present": False, "native_fenced": True}
        if fault == "identity":
            attestation["identity"] = {**identity, "request_digest": "c" * 64}
        elif fault == "changed-candidate":
            client.cold_candidate["tool_request_digest"] = "c" * 64
        elif fault == "extra-field":
            attestation["caller_claim"] = True
        elif fault == "present":
            attestation["process_present"] = True
        next(iter(state.deployment_calls.values()))["fence_proof"] = attestation
        if fault is None:
            assert (
                await release._closure(
                    runtime, client, runtime._deployment_admission_identity, proof
                )
            )["ready"] is True
        else:
            with pytest.raises(DefinitionMismatch):
                await release._closure(
                    runtime, client, runtime._deployment_admission_identity, proof
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    "publication,registry_version,allowed",
    [(2, 2, True), (2, 3, True), (3, 3, True), (3, 2, False)],
)
def test_registry_owned_release_verifies_positive_shared_version_handshake(
    monkeypatch, publication, registry_version, allowed
):
    from ralf_agent import temporal_deployment_release as release
    from ralf_agent.temporal_deployment_release_state import seal

    async def run():
        runtime, client, state, proof, _, _ = environment(
            monkeypatch, publication, registry_version
        )
        certificate = seal(state, {"scope": state.scope, "children": []})
        root = proof["admission_receipt"]["root"]
        value = {
            "mode": "verify",
            "scope": state.scope,
            "root": root,
            "certificate": certificate,
            "manifest": runtime.manifest,
            "registry_execution_epoch": "registry-epoch",
        }
        info = SimpleNamespace(
            workflow_id=client.registry.registry_id,
            workflow_run_id="registry-epoch",
            workflow_namespace=client.namespace,
        )
        if allowed:
            assert await release.execute(runtime, client, value, info) == {
                "root": root,
                "certificate": certificate,
            }
        else:
            with pytest.raises(DefinitionMismatch):
                await release.execute(runtime, client, value, info)
        assert not client.retirements

    asyncio.run(run())


@pytest.mark.parametrize("has_seal", [False, True])
def test_bridge_seal_observation_preserves_live_stop_path_and_never_mutates(monkeypatch, has_seal):
    from ralf_agent import temporal_deployment_coding_bridge as bridge
    from ralf_agent.temporal_bindings import request_release_digest
    from ralf_agent.temporal_deployment_release_state import seal

    from .test_temporal_deployment_execution import sealed

    async def run():
        runtime, client, state, proof, _, _ = environment(monkeypatch)
        if has_seal:
            seal(state, {"scope": state.scope, "children": []})
        else:
            state.state = "running"
        coding = sealed(
            {
                "version": 1,
                **{
                    name: proof[name]
                    for name in (
                        "scope",
                        "run_id",
                        "execution_epoch",
                        "original_execution_epoch",
                        "namespace",
                        "request",
                        "request_digest",
                        "manifest",
                    )
                },
                "release_digest": request_release_digest(proof["request"], proof["manifest"]),
                "revision": 1,
                "state": state.state,
                "physical_stopped": has_seal,
                "action_stops": [],
            }
        )
        assert await bridge.sealed(runtime, client, coding, proof["namespace"]) is has_seal
        assert client.updates == [] and client.retirements == []

    asyncio.run(run())


@pytest.mark.parametrize("publication,registry_version", [(2, 2), (2, 3), (3, 3)])
def test_registry_owned_release_rejects_reset_sdk_epoch(monkeypatch, publication, registry_version):
    from ralf_agent import temporal_deployment_release as release
    from ralf_agent.temporal_deployment_release_state import seal

    async def run():
        runtime, client, state, proof, _, _ = environment(
            monkeypatch, publication, registry_version
        )
        certificate = seal(state, {"scope": state.scope, "children": []})
        client.descriptions[client.registry.registry_id].raw_info.first_run_id = "pre-reset-epoch"
        value = {
            "mode": "verify",
            "scope": state.scope,
            "root": proof["admission_receipt"]["root"],
            "certificate": certificate,
            "manifest": runtime.manifest,
            "registry_execution_epoch": "registry-epoch",
        }
        info = SimpleNamespace(
            workflow_id=client.registry.registry_id,
            workflow_run_id="registry-epoch",
            workflow_namespace=client.namespace,
        )
        with pytest.raises(DefinitionMismatch):
            await release.execute(runtime, client, value, info)
        assert not client.retirements

    asyncio.run(run())
