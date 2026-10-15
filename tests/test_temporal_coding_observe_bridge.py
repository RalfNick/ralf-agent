"""Pinned Coding4 observation reuses the real composition reader and original exits."""

import asyncio
import copy

import pytest

from ralf_agent import temporal_coding_composition_control as composition
from ralf_agent import temporal_coding_composition_state as composition_state
from ralf_agent import temporal_deployment_coding_bridge as bridge
from ralf_agent import temporal_deployment_control_transport as transport
from ralf_agent import temporal_deployment_execution as execution
from ralf_agent import temporal_deployment_execution_state as deployment
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_bindings import request_release_digest
from ralf_agent.types import digest
from tests.test_temporal_coding_observe_readset import environment as observe_environment
from tests.test_temporal_deployment_control_transport_projection import setup


def environment(monkeypatch):
    real_activity, real_proof, real_ancestry = (
        execution.validate_activity,
        execution._proof,
        execution._ancestry,
    )
    real_control, real_body, real_composition_proof, real_composition_ancestry = (
        bridge.control,
        composition.control,
        composition._proof,
        composition._ancestry,
    )
    _, _, diagnostics = setup()
    runtime, client, parent, call, info, captured, _ = observe_environment(monkeypatch)
    monkeypatch.setattr(execution, "_proof", real_proof)
    monkeypatch.setattr(execution, "_ancestry", real_ancestry)
    monkeypatch.setattr(bridge, "control", real_control)
    monkeypatch.setattr(composition, "control", real_body)
    monkeypatch.setattr(composition, "_proof", real_composition_proof)
    monkeypatch.setattr(composition, "_ancestry", real_composition_ancestry)
    counts = {"parent_activity": 0, "diagnostics": 0, "updates": 0}

    async def activity(*args, **options):
        counts["parent_activity"] += 1
        return await real_activity(*args, **options)

    monkeypatch.setattr(execution, "validate_activity", activity)
    child_proof = diagnostics["coding_composition_proof"]
    child_proof.update(
        scope=parent.scope,
        run_id=call["run_id"],
        namespace=parent.composition_namespace,
        request=copy.deepcopy(call["request"]),
        request_digest=digest(call["request"]),
        manifest=parent.manifest,
        release_digest=request_release_digest(call["request"], parent.manifest),
    )
    child_proof["proof_digest"] = digest(
        {key: value for key, value in child_proof.items() if key != "proof_digest"}
    )
    diagnostics.update(scope=parent.scope, manifest=parent.manifest)
    diagnostics["snapshot"].update(run_id=call["run_id"], actions=[])
    diagnostics["release_digest"] = child_proof["release_digest"]
    get_handle = client.get_workflow_handle

    class Handle:
        def __init__(self, original):
            self.original = original

        def __getattr__(self, name):
            return getattr(self.original, name)

        async def query(self, name, request):
            assert name == "view" and request["scope"] == parent.scope
            kind = request["kind"]
            identity = self.original.identity
            if kind == "deployment_admission":
                proof = deployment.view(parent)
                if identity == parent.run_id:
                    return proof
                assert identity == proof["admission"]["root"]["registry_id"]
                return {
                    "version": 1,
                    "registry_id": identity,
                    "scope": parent.scope,
                    "namespace": parent.composition_namespace,
                    "policy": runtime._deployment_admission_identity,
                    "held_roots": [proof["admission_receipt"]["root"]],
                }
            if kind == "coding_composition_proof":
                return (
                    composition_state.physical_stop_view(parent)
                    if identity == parent.run_id
                    else copy.deepcopy(child_proof)
                )
            if kind == "coding_composition_children":
                return copy.deepcopy(parent.children)
            if kind == "diagnostics":
                assert identity == call["run_id"]
                counts["diagnostics"] += 1
                result = copy.deepcopy(diagnostics)
                if captured.get("after_diagnostics"):
                    captured["after_diagnostics"]()
                return result
            return await self.original.query(name, request)

        async def execute_update(self, *args, **options):
            counts["updates"] += 1
            raise AssertionError("Read-only observation reached an SDK Update")

    def handle(identity, **options):
        return Handle(get_handle(identity, **options))

    monkeypatch.setattr(client, "get_workflow_handle", handle)
    full = {
        "mode": "observe",
        "scope": parent.scope,
        "child": copy.deepcopy(call),
        "parent_id": parent.run_id,
        "parent_execution_epoch": parent.epoch,
        "parent_request_digest": digest(parent.request),
        "parent_release_digest": request_release_digest(parent.request, parent.manifest),
        "runtime_manifest": parent.manifest,
        "namespace": parent.composition_namespace,
        "task_queue": info.task_queue,
    }
    return runtime, client, parent, call, info, captured, counts, full, real_control


def test_pinned_coding_four_observe_avoids_duplicate_parent_validation_with_same_real_result(
    monkeypatch,
):
    async def run():
        runtime, client, parent, call, info, _, counts, full, original = environment(monkeypatch)
        expected = await original(runtime, client, full, info)
        assert counts["parent_activity"] == 1
        counts["parent_activity"] = 0
        result = await transport.execute(
            runtime, client, transport.request(parent, call, "observe"), info
        )
        assert counts["parent_activity"] == 1
        assert result == transport.pack_response(parent, call, expected)
        expanded = transport.expand_response(parent, call, {"ok": True, "result": result})
        assert expanded["result"]["snapshot"] == expected["snapshot"]
        assert (
            expanded["result"]["coding_composition_proof"] == expected["coding_composition_proof"]
        )
        assert counts["diagnostics"] == 2 and counts["updates"] == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["runtime", "namespace", "parent-reset", "child-parent", "child-pin", "source"]
)
def test_real_observe_body_cannot_publish_after_original_exit_drift(monkeypatch, fault):
    async def run():
        runtime, client, parent, call, info, captured, counts, _, _ = environment(monkeypatch)

        def changed():
            if fault == "runtime":
                runtime.changed = True
            elif fault == "namespace":
                client.namespace_uuid = "22222222-2222-4222-8222-222222222222"
            elif fault == "parent-reset":
                client.descriptions["root"].run_id = "reset-parent"
            elif fault == "child-parent":
                client.descriptions["child"].parent_id = "foreign-parent"
            elif fault == "child-pin":
                call["deployment_execution_epoch"] = "reset-child"
            else:
                monkeypatch.setattr(composition, "control", lambda *args: None)

        captured["after_diagnostics"] = changed
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                runtime, client, transport.request(parent, call, "observe"), info
            )
        assert counts == {"parent_activity": 1, "diagnostics": 1, "updates": 0}

    asyncio.run(run())


def test_missing_original_child_pin_keeps_bridge_and_refuses_adoption(monkeypatch):
    async def run():
        runtime, client, parent, call, info, _, counts, _, _ = environment(monkeypatch)
        call["child_execution"] = None
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                runtime, client, transport.request(parent, call, "observe"), info
            )
        assert counts == {"parent_activity": 2, "diagnostics": 1, "updates": 0}

    asyncio.run(run())


def test_readonly_cold_discovery_cannot_turn_original_proof_into_command_authority(monkeypatch):
    async def run():
        _, client, parent, call, _, _, counts, _, _ = environment(monkeypatch)
        readonly = bridge._ReadOnlyClient(client)
        original = composition_state.physical_stop_view(parent)
        proof = await composition._discover(
            readonly,
            parent.scope,
            call["run_id"],
            parent.manifest,
            parent.composition_namespace,
            request=call["request"],
            parent=original,
        )
        assert proof["execution_epoch"] == "child-epoch"
        with pytest.raises(DefinitionMismatch):
            await composition._command(readonly, proof, "cancel", owner_id=parent.run_id)
        with pytest.raises(DefinitionMismatch):
            await readonly.start_workflow("unexpected-business", id=call["run_id"])
        assert counts["updates"] == 0

    asyncio.run(run())
