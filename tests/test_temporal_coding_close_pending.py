"""A same-pass physical close must distinguish pending facts from hard failures."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent import temporal_coding_composition_control as control
from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.types import Scope, digest
from tests import test_temporal_coding_composition_control as fixture
from tests.test_temporal_session_deployment_coding_configuration import coding_session_manifest


def environment(monkeypatch, *, publication=4):
    manifest = coding_session_manifest(composition=True)
    if publication == 3:
        from tests.test_temporal_deployment_coding_registry import coding_request

        original = coding_request()["root_admission"]["submission"]["manifest"]
        manifest = copy.deepcopy(original) | {
            "binding_protocol": 23,
            "coding_composition_protocol": manifest["coding_composition_protocol"],
        }
    monkeypatch.setattr(fixture, "MANIFEST", manifest)
    client, child_id = fixture.linked_client()
    # The original close fixture still owns all proof mutations and injected
    # Update faults. Expose its command port through the current transport.
    from ralf_agent.temporal_command_transport import accept, observe
    from ralf_agent.temporal_state import TemporalRunState

    hosts = {}

    def host(run_id):
        if run_id not in hosts:
            epoch = client.epochs[run_id]
            state = SimpleNamespace(
                scope=fixture.SCOPE, run_id=run_id, epoch=epoch, manifest=manifest
            )
            state.authorize = lambda scope: TemporalRunState.authorize(state, scope)

            async def command(request):
                await fixture.Handle(client, run_id, epoch).execute_update("command", request)
                return {
                    "command_id": request["command_id"],
                    "run_id": run_id,
                    "kind": request["payload"]["kind"],
                    "record_state": "durably_recorded",
                    "apply_state": "applied",
                    "outcome": {},
                }

            hosts[run_id] = SimpleNamespace(state=state, command=command)
        return hosts[run_id]

    def info(run_id):
        epoch = client.epochs[run_id]
        return SimpleNamespace(
            workflow_id=run_id,
            namespace=client.namespace,
            run_id=epoch,
            first_execution_run_id=epoch,
            original_execution_run_id=epoch,
        )

    class Handle(fixture.Handle):
        async def query(self, name, request):
            if request.get("kind") == "status" and "command_observation" in request:
                client.calls.append(("query", self.run_id, self.epoch, request))
                return {
                    "command_observation": observe(
                        host(self.run_id), request["command_observation"], info(self.run_id)
                    )
                }
            return await super().query(name, request)

        async def signal(self, name, request):
            assert name == "control_command"
            client.calls.append(("signal", self.run_id, self.epoch, name, request))
            await accept(host(self.run_id), request, info(self.run_id))

    client.get_workflow_handle = lambda workflow_id, **kwargs: Handle(
        client, workflow_id, kwargs.get("run_id")
    )
    client.live_owner = True
    client.candidate.update(
        execution_epoch="root-epoch", namespace=fixture.NAMESPACE, close_requested=True
    )
    client.children[0]["child_execution"] = {
        "namespace": fixture.NAMESPACE,
        "execution_epoch": "child-epoch",
        "original_execution_epoch": "child-epoch",
    }
    client.children[0]["planning_revision"] = 0
    runtime = fixture.runtime()

    async def namespace(*args):
        return copy.deepcopy(fixture.NAMESPACE)

    async def unsealed(*args):
        return False

    def registry(sdk, scope, release=None):
        return sdk.get_workflow_handle("ralf-temporal-commands-original")

    monkeypatch.setattr(control, "_namespace", namespace)
    monkeypatch.setattr(control, "_deployment_sealed", unsealed)
    monkeypatch.setattr(control, "_registry", registry)

    def completed(*, child=True):
        for identity, proof in client.proofs.items():
            proof.update(state="cancelled", physical_stopped=identity == "root" or child)
            proof["revision"] += 1
            proof["proof_digest"] = digest({k: v for k, v in proof.items() if k != "proof_digest"})

    return runtime, client, child_id, manifest, completed


def native_inventory(monkeypatch, runtime, client, child_id, finish):
    """Real native row/request producer and real journal inventory port."""
    from ralf_agent import delegated_coding, temporal_bindings
    from ralf_agent.postgres_coding_resources import receive_resource

    resource = fixture.native_resource(client, child_id)
    state = {"resource": resource, "scans": 0}

    async def resources(scope):
        assert scope == Scope(**fixture.SCOPE)
        state["scans"] += 1
        if state["scans"] == 2:
            state["resource"] = receive_resource(
                state["resource"],
                "unprepared",
                {
                    "namespace_binding": resource["namespace_binding"],
                    "prepare_granted": False,
                },
            )
            finish(state)
        return () if state.get("missing") else (copy.deepcopy(state["resource"]),)

    handler = SimpleNamespace(
        identity=resource["runner"],
        runner=SimpleNamespace(_journal=SimpleNamespace(composition_resources=resources)),
    )
    monkeypatch.setattr(delegated_coding, "registered_coding_tool", lambda tool: handler)
    monkeypatch.setattr(temporal_bindings, "selected_runtime", lambda runtime, request: runtime)
    runtime.tools = SimpleNamespace(_tools=["coding"], get=lambda name: object())

    async def fence(*args):
        # The real native body remains live until the final journal scan.
        pass

    monkeypatch.setattr(control, "_fence_leaf", fence)
    return state


def seal(proof):
    proof["proof_digest"] = digest({k: v for k, v in proof.items() if k != "proof_digest"})


def test_real_close_consumes_same_pass_late_physical_closure_without_another_attempt(monkeypatch):
    async def run():
        runtime, client, child_id, _, completed = environment(monkeypatch)
        scans = []
        final_start = []

        async def resources(*args):
            scans.append(True)
            if len(scans) == 2:
                # Original handlers/ACKs finish during this pass's final journal
                # scan. These mutable SDK facts must now be freshly verified.
                completed()
                final_start.append(len(client.calls))
            return {}, ()

        monkeypatch.setattr(control, "_resources", resources)
        await control.close(
            runtime, client=client, scope=Scope(**fixture.SCOPE), candidates=[client.candidate]
        )
        assert scans == [True, True]
        assert client.proofs[child_id]["physical_stopped"] is True
        assert client.proofs["root"]["physical_stopped"] is True
        assert not any(call[0] == "update" for call in client.calls[final_start[0] :])

    asyncio.run(run())


def test_final_real_native_receipt_and_original_ancestor_adoption_close_same_pass(monkeypatch):
    async def run():
        runtime, client, child_id, _, completed = environment(monkeypatch)
        inventory = native_inventory(
            monkeypatch, runtime, client, child_id, lambda state: completed()
        )
        await control.close(
            runtime, client=client, scope=Scope(**fixture.SCOPE), candidates=[client.candidate]
        )
        assert inventory["scans"] == 2
        assert inventory["resource"]["pending_stop"] is False
        assert any(
            call[0] == "update" and call[3] == "coding_composition_child_stopped"
            for call in client.calls
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        "child_live",
        "root_live",
        "resource_missing",
        "pending_stop",
        "bad_resource",
        "unknown_owner",
        "missing_owner",
        "child_missing",
        "epoch_changed",
    ],
)
def test_final_positive_root_cannot_hide_original_tree_or_native_debt(monkeypatch, fault):
    async def run():
        runtime, client, child_id, _, completed = environment(monkeypatch)

        def finish(state):
            completed()
            if fault == "child_live":
                client.proofs[child_id]["physical_stopped"] = False
            elif fault == "root_live":
                client.proofs["root"]["physical_stopped"] = False
            elif fault == "resource_missing":
                state["missing"] = True
            elif fault == "pending_stop":
                state["resource"] = copy.deepcopy(initial)
            elif fault == "bad_resource":
                state["resource"]["unprepared"]["prepare_granted"] = True
            elif fault in {"unknown_owner", "missing_owner"}:
                client.proofs[child_id]["action_stops"] = [
                    {
                        "action_id": "tool",
                        "attempts": [{"status": "outcome_unknown"}],
                        "effect_key": None,
                        "native_request_digest": None,
                        "native_fenced": None,
                        "pending_stop": None,
                        "owner": {"execution_stopped": False} if fault == "unknown_owner" else None,
                    }
                ]
            elif fault == "child_missing":
                client.children.clear()
            elif fault == "epoch_changed":
                client.children[0]["child_execution"]["execution_epoch"] = "replacement"
                client.children[0]["child_execution"]["original_execution_epoch"] = "replacement"
            for proof in client.proofs.values():
                seal(proof)

        inventory = native_inventory(monkeypatch, runtime, client, child_id, finish)
        initial = copy.deepcopy(inventory["resource"])
        with pytest.raises(CloseIncomplete):
            await control.close(
                runtime, client=client, scope=Scope(**fixture.SCOPE), candidates=[client.candidate]
            )
        assert inventory["scans"] == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "error",
    [
        OSError("SDK failed"),
        DefinitionMismatch("identity changed"),
        CloseIncomplete({"ack": "unknown"}),
        "missing_ack",
    ],
)
def test_early_hard_error_is_never_erased_by_later_physical_success(monkeypatch, error):
    async def run():
        runtime, client, child_id, _, completed = environment(monkeypatch)
        native_inventory(monkeypatch, runtime, client, child_id, lambda state: completed())
        original = fixture.Handle.execute_update
        failed = []

        async def update(handle, name, value, **kwargs):
            if name == "coding_composition_child_stopped" and not failed:
                failed.append(True)
                if error == "missing_ack":
                    return {"run_id": child_id, "recorded": False}
                raise error
            return await original(handle, name, value, **kwargs)

        monkeypatch.setattr(fixture.Handle, "execute_update", update)
        with pytest.raises(CloseIncomplete):
            await control.close(
                runtime, client=client, scope=Scope(**fixture.SCOPE), candidates=[client.candidate]
            )
        assert failed and all(proof["physical_stopped"] for proof in client.proofs.values())

    asyncio.run(run())


def test_publication_three_retains_original_pending_behavior(monkeypatch):
    async def run():
        runtime, client, child_id, _, completed = environment(monkeypatch, publication=3)
        native_inventory(monkeypatch, runtime, client, child_id, lambda state: completed())
        with pytest.raises(CloseIncomplete):
            await control.close(
                runtime, client=client, scope=Scope(**fixture.SCOPE), candidates=[client.candidate]
            )
        assert all(proof["physical_stopped"] for proof in client.proofs.values())

    asyncio.run(run())


@pytest.mark.parametrize("no_start", [True, False])
def test_undispatched_child_requires_original_no_start_without_sdk_discovery(monkeypatch, no_start):
    async def run():
        runtime, client, child_id, _, completed = environment(monkeypatch)
        client.children[0].update(dispatch_started=False, physical_no_start=no_start)
        client.children[0].pop("child_execution")
        scans = []

        async def resources(*args):
            scans.append(True)
            if len(scans) == 2:
                completed()
            return {}, ()

        monkeypatch.setattr(control, "_resources", resources)
        operation = control.close(
            runtime, client=client, scope=Scope(**fixture.SCOPE), candidates=[client.candidate]
        )
        if no_start:
            await operation
        else:
            with pytest.raises(CloseIncomplete):
                await operation
        assert not any(call[1] == child_id for call in client.calls)
        assert not any(call[0] == "describe" for call in client.calls)

    asyncio.run(run())
