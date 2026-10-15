"""The owned poller remains available for queued original retirement Activities."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent import Scope, TemporalProfile
from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.runtime_lifecycle import BuildContext
from ralf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly
from ralf_agent.types import digest


@pytest.fixture(autouse=True)
def sdk():
    pytest.importorskip("temporalio")


def test_actual_owners_drain_before_retirement_and_poller_stops_last(tmp_path, monkeypatch):
    from ralf_agent import temporal_deployment_coding_bridge as bridge
    from ralf_agent import temporal_deployment_release as release

    async def run():
        events = []
        scope = Scope()

        class ActualOwner:
            closed = False

            async def wait(self, **kwargs):
                events.append("actual-and-end-ack")
                return True

        actual_owner = ActualOwner()

        async def public(**kwargs):
            actual_owner.closed = True
            events.append("public-owner-close")

        async def contexts(**kwargs):
            events.append("contexts")

        runtime = SimpleNamespace(
            orchestration_release={
                "binding_protocol": 22,
                "deployment_admission_protocol": {"version": 3},
            },
            coding_execution=True,
            _deployment_public_execution=True,
            close_deployment_execution=public,
            close_context_execution=contexts,
            close_session_execution=contexts,
        )
        context = BuildContext(None, tmp_path / "unused", scope, tmp_path, allow_async=True)
        profile = TemporalProfile("original", "1", {"default": {"adapter": "echo"}})
        assembly = TemporalRuntimeAssembly(runtime, context, profile, scope)
        assembly._bind_client(SimpleNamespace(namespace="original"), "original-queue")
        # A hosted Worker is present; the test controls only its finish boundary.
        assembly._worker = object()

        async def close(*args, **kwargs):
            events.append("original-cancel")

        async def settle(runtime, *, client, scope, wait_timeout):
            assert "actual-and-end-ack" in events
            assert not assembly._calls._execution._closed
            assert actual_owner.closed is False
            assert assembly._worker is not None
            events.append("queued-release-and-registry-verify")

        async def finish(wait_timeout):
            assert assembly._calls._execution._closed
            events.append("worker-stop")

        monkeypatch.setattr(bridge, "close", close)
        monkeypatch.setattr(release, "check_owner", lambda runtime: actual_owner)
        monkeypatch.setattr(bridge, "wait_retirement", settle, raising=False)
        monkeypatch.setattr(assembly, "_finish_worker", finish)
        await assembly.aclose()
        assert events == [
            "original-cancel",
            "actual-and-end-ack",
            "contexts",
            "contexts",
            "queued-release-and-registry-verify",
            "public-owner-close",
            "worker-stop",
        ]

    asyncio.run(run())


def environment(monkeypatch, *, ready=True):
    from ralf_agent import temporal_deployment_coding_bridge as bridge
    from ralf_agent import temporal_deployment_execution as execution
    from ralf_agent import temporal_deployment_release as release
    from ralf_agent.temporal_bindings import request_release_digest
    from tests.test_temporal_deployment_coding_bridge import MANIFEST, NAMESPACE, SCOPE

    proof = {
        "scope": SCOPE,
        "run_id": "original",
        "execution_epoch": "original-epoch",
        "command_id": "original-command",
        "request": {
            "definition": {"kind": "agent", "id": "original"},
            "input": "original",
            "budget": 32,
        },
        "manifest": MANIFEST,
        "children": [],
        "namespace": NAMESPACE,
        "admission_receipt": {"root": {"run_id": "original", "execution_epoch": "original-epoch"}},
    }
    proof.update(
        version=1,
        original_execution_epoch=proof["execution_epoch"],
        request_digest=digest(proof["request"]),
        manifest_digest=digest(MANIFEST),
        admission={"root": proof["admission_receipt"]["root"], "lineage": []},
    )
    proof["proof_digest"] = digest(proof)
    assert set(proof) == execution._PROOF_FIELDS  # actual deployment proof has no release_digest
    candidate = {
        "command_id": proof["command_id"],
        "run_id": proof["run_id"],
        "execution_epoch": proof["execution_epoch"],
        "namespace": NAMESPACE,
        "request_digest": digest(proof["request"]),
        "manifest_digest": digest(MANIFEST),
        "close_requested": True,
    }
    closure = {
        "version": 1,
        "deployment": proof,
        "ready": ready,
        "reasons": [] if ready else ["unfinished_action"],
        "calls": {},
        "seal": None,
    }
    certificate = {"original": "certificate"}
    records = []
    events = []

    class Handle:
        async def query(self, name, request):
            assert name == "view"
            events.append(request["kind"])
            if request["kind"] == "deployment_closure":
                return copy.deepcopy(closure)
            if request["kind"] == "diagnostics":
                return {
                    "snapshot": {
                        "run_id": proof["run_id"],
                        "state_revision": 1,
                        "state": "cancelled",
                        "actions": [{"status": "outcome_unknown"}],
                    },
                    "manifest": MANIFEST,
                    "release_digest": request_release_digest(proof["request"], proof["manifest"]),
                    "budget": {"unknown": 0},
                }
            assert request["kind"] == "deployment_retirement"
            return copy.deepcopy(records[-1]) if records else None

        async def execute_update(self, *args, **kwargs):
            pytest.fail("drain must never mutate Registry or original History")

    class Registry:
        namespace = NAMESPACE
        policy = MANIFEST["deployment_admission_protocol"]["policy"]
        handle = Handle()

        async def query(self, name, request):
            return [copy.deepcopy(candidate)]

        async def _authority(self):
            events.append("original-registry-authority")
            return self.namespace

        def _payload(self, value, namespace):
            return value

        async def _result(self, value, namespace):
            return value

    client = SimpleNamespace(get_workflow_handle=lambda *args, **kwargs: Handle())
    runtime = SimpleNamespace(
        orchestration_release=MANIFEST, validate_release=lambda *args: MANIFEST
    )

    async def read(*args, **kwargs):
        events.append("actual-original-proof")
        return copy.deepcopy(proof)

    async def read_closure(*args):
        assert closure["ready"]
        return copy.deepcopy(closure)

    async def namespace(*args):
        events.append("namespace")

    monkeypatch.setattr(bridge, "registry", lambda *args: Registry())
    monkeypatch.setattr(execution, "_proof", read)
    monkeypatch.setattr(execution, "_policy", lambda *args: Registry.policy)
    monkeypatch.setattr(execution, "_sealed", lambda value: None)
    monkeypatch.setattr(execution, "_namespace", namespace)
    monkeypatch.setattr(release, "_closure", read_closure)
    monkeypatch.setattr(release, "_certificate", lambda value, proof: None)
    monkeypatch.setattr(release, "_binding", lambda *args: {})
    return runtime, client, Scope(**SCOPE), closure, certificate, records, events


def test_queued_release_and_verify_must_finish_before_drain_returns(monkeypatch):
    from ralf_agent import temporal_deployment_coding_bridge as bridge

    async def run():
        runtime, client, scope, closure, certificate, records, events = environment(monkeypatch)
        task = asyncio.create_task(
            bridge.wait_retirement(runtime, client=client, scope=scope, wait_timeout=2)
        )
        await asyncio.sleep(0)
        assert not task.done()
        # Activity is queued, then the original History adopts its seal.
        closure["seal"] = certificate
        await asyncio.sleep(0.02)
        assert not task.done()  # seal alone never means quota released
        records.append(
            {
                "root": closure["deployment"]["admission_receipt"]["root"],
                "certificate": certificate,
                "released": True,
            }
        )
        await task
        assert "deployment_retirement" in events
        assert events[-1] == "namespace"

    asyncio.run(run())


def test_unknown_effect_remains_held_without_manufacturing_retirement(monkeypatch):
    from ralf_agent import temporal_deployment_coding_bridge as bridge

    async def run():
        runtime, client, scope, _, _, _, events = environment(monkeypatch, ready=False)
        await bridge.wait_retirement(runtime, client=client, scope=scope, wait_timeout=0)
        assert "deployment_retirement" not in events

    asyncio.run(run())


def test_not_ready_without_unknown_waits_for_original_sdk_adoption(monkeypatch):
    from ralf_agent import temporal_deployment_coding_bridge as bridge

    async def run():
        runtime, client, scope, closure, certificate, records, _ = environment(
            monkeypatch, ready=False
        )
        handle_type = type(client.get_workflow_handle("original"))
        query = handle_type.query

        async def read(self, name, request):
            value = await query(self, name, request)
            if request["kind"] == "diagnostics":
                value["snapshot"]["actions"] = [{"status": "executing"}]
            return value

        monkeypatch.setattr(handle_type, "query", read)
        task = asyncio.create_task(
            bridge.wait_retirement(runtime, client=client, scope=scope, wait_timeout=2)
        )
        await asyncio.sleep(0.02)
        assert not task.done()  # empty actual tracker does not mean SDK completion adopted
        closure.update(ready=True, reasons=[], seal=certificate)
        records.append(
            {
                "root": closure["deployment"]["admission_receipt"]["root"],
                "certificate": certificate,
                "released": True,
            }
        )
        await task

    asyncio.run(run())


def test_recursive_root_waits_for_queued_child_completion_with_empty_tracker(monkeypatch):
    from ralf_agent import temporal_deployment_coding_bridge as bridge
    from ralf_agent import temporal_deployment_execution as execution

    async def run():
        runtime, client, scope, root, certificate, records, events = environment(
            monkeypatch, ready=False
        )
        parent = root["deployment"]
        child = copy.deepcopy(parent)
        child.update(run_id="child", command_id="child-command", execution_epoch="child-epoch")
        child["admission"] = {"original": "child-metadata"}
        parent["children"] = [
            {
                "id": "original-intent",
                "run_id": "child",
                "command_id": "child-command",
                "request": child["request"],
                "deployment_admission": child["admission"],
                "dispatch_started": True,
                "deployment_execution_epoch": "child-epoch",
            }
        ]
        root["reasons"] = ["child_unfinished"]
        leaf = {**copy.deepcopy(root), "deployment": child, "reasons": ["actual_call_not_stopped"]}
        get_handle = client.get_workflow_handle

        class Handle:
            def __init__(self, run_id):
                self.run_id = run_id

            async def query(self, name, request):
                events.append((self.run_id, request["kind"]))
                if self.run_id == "child" and request["kind"] == "deployment_closure":
                    return copy.deepcopy(leaf)
                value = await get_handle(self.run_id).query(name, request)
                if request["kind"] == "diagnostics":
                    value["snapshot"].update(run_id=self.run_id, actions=[])
                return value

        client.get_workflow_handle = lambda identity, **kwargs: Handle(identity)

        async def read(*args, **kwargs):
            return copy.deepcopy(child if args[4] == "child" else parent)

        async def ancestry(*args, **kwargs):
            assert kwargs == {"read_only": True}
            return parent

        monkeypatch.setattr(execution, "_proof", read)
        monkeypatch.setattr(execution, "_ancestry", ancestry)
        task = asyncio.create_task(
            bridge.wait_retirement(runtime, client=client, scope=scope, wait_timeout=2)
        )
        await asyncio.sleep(0.02)
        assert not task.done()
        assert ("child", "deployment_closure") in events
        leaf.update(ready=True, reasons=[], seal={"original": "child-seal"})
        root.update(ready=True, reasons=[], seal=certificate)
        records.append(
            {
                "root": parent["admission_receipt"]["root"],
                "certificate": certificate,
                "released": True,
            }
        )
        await task

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["timeout", "wrong-retirement"])
def test_ready_original_root_needs_positive_exact_retirement(monkeypatch, fault):
    from ralf_agent import temporal_deployment_coding_bridge as bridge

    async def run():
        runtime, client, scope, closure, certificate, records, _ = environment(monkeypatch)
        if fault == "wrong-retirement":
            closure["seal"] = certificate
            records.append({"root": {}, "certificate": certificate, "released": True})
        with pytest.raises(CloseIncomplete if fault == "timeout" else DefinitionMismatch):
            await bridge.wait_retirement(runtime, client=client, scope=scope, wait_timeout=0.01)

    asyncio.run(run())


@pytest.mark.parametrize("root_unknown", [False, True])
def test_unknown_never_hides_sibling_queued_cleanup(monkeypatch, root_unknown):
    from ralf_agent import temporal_deployment_coding_bridge as bridge
    from ralf_agent import temporal_deployment_execution as execution

    async def run():
        runtime, client, scope, root, _, _, events = environment(monkeypatch, ready=False)
        parent = root["deployment"]
        parent["children"] = []
        leaves = {}
        for identity in ("unknown-child", "queued-child"):
            child = copy.deepcopy(parent)
            child.update(
                run_id=identity,
                command_id=identity,
                execution_epoch=identity + "-epoch",
                children=[],
            )
            child["admission"] = {"original": identity}
            leaves[identity] = {
                **copy.deepcopy(root),
                "deployment": child,
                "reasons": ["unfinished_action"],
            }
            parent["children"].append(
                {
                    "id": identity,
                    "run_id": identity,
                    "command_id": identity,
                    "request": child["request"],
                    "deployment_admission": child["admission"],
                    "dispatch_started": True,
                    "deployment_execution_epoch": child["execution_epoch"],
                }
            )
        root["reasons"] = ["child_unfinished"]
        get_handle = client.get_workflow_handle

        class Handle:
            def __init__(self, identity):
                self.identity = identity

            async def query(self, name, request):
                events.append((self.identity, request["kind"]))
                if self.identity in leaves and request["kind"] == "deployment_closure":
                    return copy.deepcopy(leaves[self.identity])
                value = await get_handle(self.identity).query(name, request)
                if request["kind"] == "diagnostics":
                    unknown = self.identity == "unknown-child" or (
                        self.identity == "original" and root_unknown
                    )
                    value["snapshot"].update(
                        run_id=self.identity,
                        actions=[{"status": "outcome_unknown" if unknown else "executing"}]
                        if self.identity != "original" or unknown
                        else [],
                    )
                return value

        client.get_workflow_handle = lambda identity, **kwargs: Handle(identity)

        async def read(*args, **kwargs):
            return copy.deepcopy(parent if args[4] == "original" else leaves[args[4]]["deployment"])

        async def ancestry(*args, **kwargs):
            assert kwargs == {"read_only": True}
            return parent

        monkeypatch.setattr(execution, "_proof", read)
        monkeypatch.setattr(execution, "_ancestry", ancestry)
        task = asyncio.create_task(
            bridge.wait_retirement(runtime, client=client, scope=scope, wait_timeout=2)
        )
        await asyncio.sleep(0.02)
        assert not task.done()
        assert ("queued-child", "deployment_closure") in events
        leaves["queued-child"].update(ready=True, reasons=[])
        await asyncio.sleep(0.06)
        assert not task.done()  # its parent has not adopted this ready child yet
        parent["children"][1]["settled"] = True
        await task
        assert "deployment_retirement" not in events  # unknown remains held

    asyncio.run(run())
