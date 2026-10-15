"""Original SDK bridge routing and proof boundaries; no native/service I/O."""

import asyncio
import copy
import importlib
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, Scope
from ralf_agent.binding_definitions import AgentDefinition
from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.temporal_deployment_admission import registry_id
from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME, TOOL_ACTIVITY
from ralf_agent.types import canonical, digest


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


SCOPE = asdict(Scope("bridge", "owner"))
POLICY = DeploymentAdmissionPolicy("coding-bridge", max_active_root_runs=2).identity
NAMESPACE = {"name": "original", "id": "11111111-1111-1111-1111-111111111111"}
MANIFEST = {
    "kernel": "temporal-3",
    "binding_protocol": 23,
    "coding_execution_protocol": {"version": 6},
    "coding_composition_protocol": {"version": 7},
    "deployment_admission_protocol": {
        "version": 3,
        "policy": POLICY,
        "registry_id": registry_id(POLICY["deployment_id"]),
        "implementation": {},
    },
}
RUNNER = {"kind": "original-runner", "version": "1"}


def module():
    name = "ralf_agent.temporal_deployment_coding_bridge"
    assert importlib.util.find_spec(name), "Missing original Coding deployment bridge"
    return importlib.import_module(name)


class Handle:
    def __init__(self, client, identity, epoch=None):
        self.client, self.identity, self.epoch = client, identity, epoch

    async def describe(self):
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        if getattr(self.client, "missing_registry", False):
            raise RPCError("Original Registry absent", RPCStatusCode.NOT_FOUND, b"")
        if getattr(self.client, "unavailable", False):
            raise RPCError("Registry temporarily unavailable", RPCStatusCode.UNAVAILABLE, b"")
        return SimpleNamespace(
            id=self.identity,
            namespace=self.client.namespace,
            workflow_type=COMMAND_REGISTRY_NAME,
            run_id=getattr(self.client, "registry_epoch", "registry-epoch"),
            raw_info=SimpleNamespace(first_run_id="registry-epoch"),
            status=getattr(self.client, "registry_status", WorkflowExecutionStatus.RUNNING),
            task_queue="existing-original-queue",
        )

    async def query(self, name, value):
        self.client.calls.append(("query", self.identity, self.epoch, name, copy.deepcopy(value)))
        if value["kind"] == "deployment_configuration":
            if getattr(self.client, "configuration_missing", False):
                from temporalio.service import RPCError, RPCStatusCode

                raise RPCError("Known Registry epoch absent", RPCStatusCode.NOT_FOUND, b"")
            return {
                "version": self.client.version,
                "registry_id": self.identity,
                "policy": POLICY,
                "namespace": NAMESPACE,
            }
        if value["kind"] == "coding_composition_candidates":
            return copy.deepcopy(self.client.candidates)
        if value["kind"] == "coding_composition_admission":
            return {
                **self.client.candidate,
                "admitted": not self.client.candidate["close_requested"],
            }
        if value["kind"] == "deployment_coding_call_candidate":
            return copy.deepcopy(self.client.call_candidate)
        if value["kind"] == "coding_requests":
            return copy.deepcopy(self.client.requests)
        if value["kind"] == "deployment_closure":
            return copy.deepcopy(self.client.closure)
        raise AssertionError(value)

    async def execute_update(self, name, value, **options):
        self.client.calls.append(("update", self.identity, self.epoch, name, copy.deepcopy(value)))
        if name == "close_deployment_coding_submissions":
            for candidate in self.client.candidates:
                candidate["close_requested"] = True
            return {
                "manifest_digest": self.client.candidate["manifest_digest"],
                "close_requested": True,
                "candidates": copy.deepcopy(self.client.candidates),
            }
        assert name == "admit_coding_composition_submission"
        assert value["run_id"] == "root" and value["execution_epoch"] == "root-epoch"
        return {**self.client.candidate, "admitted": not self.client.candidate["close_requested"]}


class Client:
    namespace = NAMESPACE["name"]

    def __init__(self):
        self.version, self.calls = 3, []
        self.starts = []
        self.namespace_uuid = NAMESPACE["id"]
        self.workflow_service = SimpleNamespace(describe_namespace=self.describe_namespace)
        self.candidate = {
            "command_id": "accepted",
            "run_id": "root",
            "request_digest": digest({"task": "original"}),
            "manifest_digest": digest(MANIFEST),
            "close_requested": False,
            "execution_epoch": "root-epoch",
            "namespace": NAMESPACE,
        }
        self.candidates = [self.candidate]

    async def describe_namespace(self, request):
        assert request.namespace == self.namespace
        return SimpleNamespace(namespace_info=SimpleNamespace(id=self.namespace_uuid))

    def get_workflow_handle(self, identity, **options):
        return Handle(self, identity, options.get("run_id"))

    async def start_workflow(self, name, accepted, **options):
        self.starts.append((name, copy.deepcopy(accepted), options))
        self.missing_registry = False
        self.version = getattr(self, "created_version", accepted["deployment_admission"]["version"])
        if getattr(self, "namespace_drift", False):
            self.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        if getattr(self, "lost_start", False):
            self.lost_start = False
            raise TimeoutError("Original Registry start response lost")
        if getattr(self, "racing_start", False):
            from temporalio.exceptions import WorkflowAlreadyStartedError

            raise WorkflowAlreadyStartedError(options["id"], name)
        return self.get_workflow_handle(options["id"])


class Runtime:
    manifest = orchestration_release = MANIFEST
    _deployment_admission_policy = _deployment_admission_policy_pin = (
        DeploymentAdmissionPolicy.from_identity(POLICY)
    )
    _deployment_admission_identity = POLICY

    def validate_release(self, manifest=None):
        if manifest is not None and manifest != MANIFEST:
            raise DefinitionMismatch("Original release changed")
        return copy.deepcopy(MANIFEST)


def proof(run_id="root", epoch="root-epoch"):
    return {
        "scope": SCOPE,
        "run_id": run_id,
        "command_id": "accepted",
        "execution_epoch": epoch,
        "namespace": NAMESPACE,
        "request": {"task": "original"},
        "manifest": MANIFEST,
        "admission": {"root": {"run_id": "root"}},
        "children": [],
    }


def install_proofs(monkeypatch, original=None):
    from ralf_agent import temporal_deployment_execution as execution

    original = proof() if original is None else original

    async def read(*args, **kwargs):
        return copy.deepcopy(original)

    async def ancestry(*args):
        return proof()

    monkeypatch.setattr(execution, "_proof", read)
    monkeypatch.setattr(execution, "_ancestry", ancestry)
    return original


def test_structural_runner_binding_keeps_original_logical_request_without_alias_authorization():
    bound = AgentDefinition(
        AgentSpec("answer", "Answer", tools=("coding",)),
        AgentBindingDescriptor(runner=BindingSelection.ref("original", "1")),
    )
    request = module().logical_request(bound, {"items": (1, 2)}, budget=7, session_id=None)
    assert request["definition"]["kind"] == "agent"
    assert request["agent_bindings"]["agent"]["runner"]["component_id"] == "original"
    assert request["definition"]["steps"][0]["tools"] == ["coding"]
    assert request["input"]["items"] == [1, 2]


def test_registry_proxy_routes_existing_shapes_to_scoped_original_registry3():
    async def run():
        client = Client()
        handle = module().registry(client, SCOPE, MANIFEST)
        assert await handle.query(
            "view",
            {
                "scope": SCOPE,
                "kind": "coding_composition_candidates",
                "manifest_digest": digest(MANIFEST),
            },
        ) == [client.candidate]
        result = await handle.execute_update(
            "close_coding_composition_submissions",
            {"scope": SCOPE, "manifest_digest": digest(MANIFEST)},
            id="old-close",
        )
        assert result["close_requested"] is True
        calls = [c for c in client.calls if c[4].get("kind") != "deployment_configuration"]
        assert all(c[1] == registry_id(POLICY["deployment_id"]) for c in calls)
        assert all(c[2] == "registry-epoch" for c in client.calls)
        assert calls[-1][3] == "close_deployment_coding_submissions"
        assert all(
            c[4]["scope"] == SCOPE
            and c[4]["admission_policy"] == POLICY
            and c[4]["namespace"] == NAMESPACE
            for c in calls
        )

    asyncio.run(run())


@pytest.mark.parametrize("changed", ["old-registry", "scope", "namespace", "reset"])
def test_registry_proxy_refuses_without_coding_update(changed):
    async def run():
        client = Client()
        if changed == "old-registry":
            client.version = 2
        elif changed == "namespace":
            client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        elif changed == "reset":
            client.registry_epoch = "reset-epoch"
        request = {
            "scope": {**SCOPE, "principal": "foreign"} if changed == "scope" else SCOPE,
            "manifest_digest": digest(MANIFEST),
        }
        with pytest.raises(DefinitionMismatch):
            await (
                module()
                .registry(client, SCOPE, MANIFEST)
                .execute_update("close_coding_composition_submissions", request)
            )
        assert not any(c[0] == "update" for c in client.calls)

    asyncio.run(run())


@pytest.mark.parametrize("closed", [False, True])
def test_sideband_descendant_binds_only_original_root_and_preserves_closed_stop_only(
    monkeypatch, closed
):
    async def run():
        client, runtime = Client(), Runtime()
        client.candidate["close_requested"] = closed
        original = install_proofs(monkeypatch, proof("child", "child-epoch"))
        value = {
            "scope": SCOPE,
            "run_id": "child",
            "execution_epoch": "child-epoch",
            "runtime_manifest": MANIFEST,
            "request": original["request"],
        }
        info = SimpleNamespace(
            workflow_id="child", workflow_run_id="child-epoch", workflow_namespace=client.namespace
        )
        assert await module().admission(runtime, client, value, info) == {
            "namespace": NAMESPACE,
            "execution_epoch": "child-epoch",
            "admitted": not closed,
        }
        updates = [c for c in client.calls if c[0] == "update"]
        assert len(updates) == 1 and updates[0][4]["run_id"] == "root"

    asyncio.run(run())


def test_combined_control_validates_both_edges_then_executes_original_operation_once(monkeypatch):
    from ralf_agent import temporal_coding_composition_control as coding
    from ralf_agent import temporal_deployment_execution as execution

    async def run():
        calls = []
        original = proof()
        child = {
            "id": "old-intent",
            "run_id": "child",
            "request": {"coding_parent": "original"},
            "deployment_admission": {"root": "original"},
            "command_id": "child-command",
        }
        original["children"] = [child]

        async def validate(*args):
            calls.append("deployment")
            return copy.deepcopy(original)

        async def control(*args):
            calls.append("coding-once")
            return {"coding_composition_proof": {"physical_stopped": False}}

        monkeypatch.setattr(execution, "validate_activity", validate)
        monkeypatch.setattr(coding, "control", control)
        result = await module().control(
            Runtime(),
            Client(),
            {
                "scope": SCOPE,
                "parent_id": "root",
                "runtime_manifest": MANIFEST,
                "mode": "observe",
                "child": child,
            },
            object(),
        )
        assert result["coding_composition_proof"]["physical_stopped"] is False
        assert calls == ["deployment", "coding-once"]
        with pytest.raises(DefinitionMismatch):
            await module().control(
                Runtime(),
                Client(),
                {
                    "scope": SCOPE,
                    "parent_id": "root",
                    "runtime_manifest": MANIFEST,
                    "mode": "observe",
                    "child": {**child, "deployment_admission": {}},
                },
                object(),
            )
        assert calls.count("coding-once") == 1

    asyncio.run(run())


@pytest.mark.parametrize("closed", [False, True])
def test_native_grant_guard_only_reads_original_root_index(monkeypatch, closed):
    async def run():
        client, runtime = Client(), Runtime()
        original = install_proofs(monkeypatch)
        runtime.manifest = copy.deepcopy(MANIFEST)
        runtime.manifest["binding_protocol"] = 22
        runtime.manifest.pop("coding_composition_protocol")
        manifest = runtime.manifest
        original["manifest"] = manifest
        client.candidate["manifest_digest"] = digest(manifest)
        client.candidate["close_requested"] = closed
        from ralf_agent import temporal_deployment_execution as execution

        async def read(*args, **kwargs):
            return copy.deepcopy(original)

        monkeypatch.setattr(execution, "_proof", read)
        monkeypatch.setattr(execution, "_ancestry", read)
        runtime.validate_release = lambda expected=None: copy.deepcopy(manifest)
        request = {
            "scope": SCOPE,
            "run_id": "root",
            "execution_epoch": "root-epoch",
            "runtime_manifest": manifest,
        }
        info = SimpleNamespace(
            workflow_id="root", workflow_run_id="root-epoch", workflow_namespace=client.namespace
        )
        assert await module().grant_allowed(runtime, client, request, info) is not closed
        assert not any(c[0] == "update" for c in client.calls)

    asyncio.run(run())


def test_readonly_grant_guard_refuses_hidden_ancestry_pin_before_sdk_mutation(monkeypatch):
    from ralf_agent import temporal_deployment_execution as execution

    async def run():
        client, runtime = Client(), Runtime()
        original = install_proofs(monkeypatch)

        async def pin(runtime, sdk_client, policy, proof):
            await sdk_client.get_workflow_handle(
                proof["run_id"], run_id=proof["execution_epoch"]
            ).execute_update("deployment_child_epoch", {"scope": SCOPE})
            return proof

        monkeypatch.setattr(execution, "_ancestry", pin)
        request = {
            "scope": SCOPE,
            "run_id": original["run_id"],
            "execution_epoch": original["execution_epoch"],
            "runtime_manifest": MANIFEST,
        }
        info = SimpleNamespace(
            workflow_id="root", workflow_run_id="root-epoch", workflow_namespace=client.namespace
        )
        with pytest.raises(DefinitionMismatch):
            await module().grant_allowed(runtime, client, request, info)
        assert not any(c[0] == "update" for c in client.calls)

    asyncio.run(run())


def stopped_call(client):
    request = {
        "scope": SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "action_id": "tool-action",
        "tool": "coding",
        "runtime_manifest": MANIFEST,
        "tool_manifest": {"config": {"delegated_runner": {"runner": RUNNER}}},
    }
    identity = {
        "version": 1,
        "scope": SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "activity_id": "tool-call",
        "activity_name": TOOL_ACTIVITY,
        "attempt": 1,
        "invocation_id": "call-owner",
        "request_digest": digest({"scope": SCOPE, "_deployment_activity_request": request}),
        "manifest_digest": digest(MANIFEST),
    }
    owner = {
        "version": 1,
        "pid": 123,
        "start": "original-birth",
        "deployment": "a" * 64,
        "invocation_id": "native-owner",
    }
    candidate = {
        "version": 1,
        "identity": identity,
        "action_id": request["action_id"],
        "tool_request_digest": digest(request),
        "owner": owner,
        "owner_stop_proof": {
            "scope": SCOPE,
            "run_id": "root",
            "action_id": request["action_id"],
            "release_digest": "a" * 64,
            "request_digest": digest(request),
            "execution_epoch": "root-epoch",
            "invocation_id": "stop-owner",
            "evidence": {"owner": owner, "process_present": False, "native_fenced": True},
        },
        "runner": RUNNER,
        "namespace": NAMESPACE,
        "execution_epoch": "root-epoch",
    }
    client.call_candidate, client.requests = copy.deepcopy(candidate), [copy.deepcopy(request)]
    return identity, candidate


@pytest.mark.parametrize(
    "changed",
    [None, "live", "candidate", "carrier", "namespace", "runner", "caller-proof", "stop-handler"],
)
def test_call_stop_verifier_reads_original_candidate_before_original_birth_check(
    monkeypatch, changed
):
    from ralf_agent import delegated_coding, temporal_coding_runtime

    async def run():
        client, runtime = Client(), Runtime()
        install_proofs(monkeypatch)
        identity, candidate = stopped_call(client)
        runtime.tools = SimpleNamespace(_tools={"coding": object()}, get=lambda name: object())
        handler = SimpleNamespace(identity=RUNNER, runner=object(), check=lambda: None)
        monkeypatch.setattr(delegated_coding, "registered_coding_tool", lambda tool: handler)
        seen = []

        async def stopped(runner, owner):
            seen.append(copy.deepcopy(owner))
            return changed != "live"

        monkeypatch.setattr(temporal_coding_runtime, "original_owner_stopped", stopped)
        value = {"scope": SCOPE, "identity": identity}
        if changed == "candidate":
            client.call_candidate["identity"]["execution_epoch"] = "replacement"
        elif changed == "carrier":
            client.requests[0]["action_id"] = "foreign"
        elif changed == "namespace":
            client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        elif changed == "runner":
            handler.identity = {"kind": "foreign"}
        elif changed == "caller-proof":
            value["attestation"] = candidate
        elif changed == "stop-handler":
            from ralf_agent.temporal_coding_state import CODING_STOP_ACTIVITY

            identity["activity_name"] = CODING_STOP_ACTIVITY
        info = SimpleNamespace(
            workflow_id="root", workflow_run_id="root-epoch", workflow_namespace=client.namespace
        )
        if changed is None:
            assert await module().verify_call_stop(runtime, client, value, info) == {
                **candidate,
                "process_present": False,
                "native_fenced": True,
            }
            assert seen == [candidate["owner"]]
        else:
            with pytest.raises(DefinitionMismatch):
                await module().verify_call_stop(runtime, client, value, info)

    asyncio.run(run())


def test_stop_activity_registration_marker_is_exact_and_runtime_bound():
    api, runtime, client = module(), Runtime(), Client()
    function = api.registered_stop_activity(runtime, client)
    assert api.is_registered_stop_activity(runtime, client, function)
    assert not api.is_registered_stop_activity(runtime, Client(), function)

    async def forged(value):
        return value

    assert not api.is_registered_stop_activity(runtime, client, forged)
    forged.__ralf_deployment_coding_stop__ = function.__ralf_deployment_coding_stop__
    assert not api.is_registered_stop_activity(runtime, client, forged)


def test_verifier_consumes_real_original_history_cold_candidate(monkeypatch):
    from ralf_agent import delegated_coding, temporal_coding_runtime
    from ralf_agent import temporal_deployment_execution as execution
    from ralf_agent import temporal_deployment_execution_state as admission_state
    from ralf_agent.temporal_deployment_coding_state import coding_call_candidate

    from .test_temporal_deployment_coding_state import cold

    async def run():
        state, _, request, identity = cold(monkeypatch)
        candidate = coding_call_candidate(state, identity)
        client = Client()
        client.namespace_uuid = candidate["namespace"]["id"]
        client.call_candidate, client.requests = candidate, [request]
        original = admission_state.view(state)

        class OriginalRuntime(Runtime):
            manifest = orchestration_release = state.manifest

            def validate_release(self, manifest=None):
                assert manifest is None or manifest == state.manifest
                return copy.deepcopy(state.manifest)

        async def read(*args, **kwargs):
            return copy.deepcopy(original)

        async def ancestry(*args):
            return copy.deepcopy(original)

        async def absent(runner, owner):
            assert owner == candidate["owner"]
            return True

        monkeypatch.setattr(execution, "_proof", read)
        monkeypatch.setattr(execution, "_ancestry", ancestry)
        monkeypatch.setattr(execution, "_policy", lambda runtime: POLICY)
        monkeypatch.setattr(temporal_coding_runtime, "original_owner_stopped", absent)
        handler = SimpleNamespace(identity=candidate["runner"], runner=object(), check=lambda: None)
        monkeypatch.setattr(delegated_coding, "registered_coding_tool", lambda tool: handler)
        runtime = OriginalRuntime()
        runtime.tools = SimpleNamespace(get=lambda name: object())
        info = SimpleNamespace(
            workflow_id=state.run_id,
            workflow_run_id=state.epoch,
            workflow_namespace=client.namespace,
        )
        assert await module().verify_call_stop(
            runtime, client, {"scope": state.scope, "identity": identity}, info
        ) == {**candidate, "process_present": False, "native_fenced": True}

    asyncio.run(run())


@pytest.mark.parametrize("missing", [False, True])
def test_close_scans_native_candidates_without_pg_rows_and_never_infers_missing_root(
    monkeypatch, missing
):
    from ralf_agent import temporal_coding_composition_control as coding
    from ralf_agent import temporal_deployment_execution as execution

    async def run():
        runtime, client, events = Runtime(), Client(), []
        original = proof()
        original["request"] = {"definition": {"kind": "agent"}}
        client.closure = {
            "version": 1,
            "deployment": original,
            "ready": False,
            "reasons": ["business_not_terminal"],
            "calls": {},
            "seal": None,
        }
        client.candidate["request_digest"] = digest(original["request"])
        install_proofs(monkeypatch, original)

        async def read(*args, **kwargs):
            if missing:
                from temporalio.service import RPCError, RPCStatusCode

                raise RPCError("Original accepted root absent", RPCStatusCode.NOT_FOUND, b"")
            return copy.deepcopy(original)

        async def command(client, proof, kind, **options):
            events.append(("original-stop", proof["run_id"], kind))

        async def close(runtime, *, client, scope, candidates):
            events.append(("existing-close", copy.deepcopy(candidates)))

        monkeypatch.setattr(execution, "_proof", read)
        monkeypatch.setattr(coding, "_command", command)
        monkeypatch.setattr(coding, "close", close)
        if missing:
            with pytest.raises(CloseIncomplete):
                await module().close(runtime, client=client, scope=Scope(**SCOPE))
            assert not any(e[0] == "original-stop" for e in events)
            assert ("existing-close", []) in events
        else:
            await module().close(runtime, client=client, scope=Scope(**SCOPE))
            assert events == [("original-stop", "root", "cancel"), ("existing-close", [])]
        assert client.candidate["close_requested"] is True
        assert runtime._tool_execution_closing is True
        assert all(
            c[1] == registry_id(POLICY["deployment_id"]) for c in client.calls if c[0] == "update"
        )

    asyncio.run(run())


@pytest.mark.parametrize("binding", [22, 23])
@pytest.mark.parametrize("changed", [False, True])
def test_v3_close_accepts_original_sdk_planner_arrays_but_refuses_changed_manifest(
    monkeypatch, binding, changed
):
    from ralf_agent import temporal_coding_composition_control as coding
    from ralf_agent import temporal_coding_runtime as native

    async def run():
        runtime, client, events = Runtime(), Client(), []
        local = copy.deepcopy(MANIFEST)
        local["binding_protocol"] = binding
        local["orchestration"] = {
            "planners": {
                name: {"agent": {"tools": ()}, "identity": {"agent": {"tools": ()}}}
                for name in ("dag-model", "model")
            }
        }
        original = proof()
        original["manifest"] = json.loads(canonical(local))
        original["request"] = {"definition": {"kind": "agent"}}
        assert original["manifest"] != local
        assert digest(original["manifest"]) == digest(local)
        if changed:
            original["manifest"]["orchestration"]["planners"]["model"]["agent"]["tools"] = [
                "replacement-tool"
            ]
        runtime.manifest = runtime.orchestration_release = local

        def validate_release(value=None):
            if value is not None and canonical(value) != canonical(local):
                raise DefinitionMismatch("Original release changed")
            return copy.deepcopy(local)

        runtime.validate_release = validate_release
        client.candidate["request_digest"] = digest(original["request"])
        client.candidate["manifest_digest"] = digest(local)
        client.closure = {
            "version": 1,
            "deployment": original,
            "ready": False,
            "reasons": ["business_not_terminal"],
            "calls": {},
            "seal": None,
        }
        install_proofs(monkeypatch, original)

        async def command(client, proof, kind, **options):
            events.append(("original-stop", proof["run_id"], kind))

        async def close(runtime, *, client, scope, **options):
            events.append(("existing-close", binding))

        monkeypatch.setattr(coding, "_command", command)
        monkeypatch.setattr(coding, "close", close)
        monkeypatch.setattr(native, "close", close)
        if changed:
            with pytest.raises(CloseIncomplete):
                await module().close(runtime, client=client, scope=Scope(**SCOPE))
            assert events == [("existing-close", binding)]
        else:
            await module().close(runtime, client=client, scope=Scope(**SCOPE))
            assert events == [("original-stop", "root", "cancel"), ("existing-close", binding)]
        assert runtime.orchestration_release is local
        assert isinstance(local["orchestration"]["planners"]["model"]["agent"]["tools"], tuple)

    asyncio.run(run())


@pytest.mark.parametrize("present", [False, True])
def test_owned_close_uses_original_registry3_authority_without_business_acceptance(
    monkeypatch, present
):
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

    from ralf_agent import temporal_coding_composition_control as coding

    async def run():
        runtime, client, closed = Runtime(), Client(), []
        client.missing_registry, client.candidates = not present, []

        async def close(runtime, *, client, scope, candidates):
            closed.append(candidates)

        monkeypatch.setattr(coding, "close", close)
        await module().close(
            runtime, client=client, scope=Scope(**SCOPE), task_queue="fixed-owned-queue"
        )
        assert closed == [[]]
        assert len(client.starts) == (0 if present else 1)
        if not present:
            name, accepted, options = client.starts[0]
            assert name == COMMAND_REGISTRY_NAME
            assert accepted == {
                "deployment_admission": {"version": 3, "policy": POLICY, "namespace": NAMESPACE}
            }
            assert options == {
                "id": registry_id(POLICY["deployment_id"]),
                "task_queue": "fixed-owned-queue",
                "id_reuse_policy": WorkflowIDReusePolicy.REJECT_DUPLICATE,
                "id_conflict_policy": WorkflowIDConflictPolicy.FAIL,
                "retry_policy": None,
            }
        updates = [c for c in client.calls if c[0] == "update"]
        assert len(updates) == 1 and updates[0][2:4] == (
            "registry-epoch",
            "close_deployment_coding_submissions",
        )
        assert updates[0][4] == {
            "scope": SCOPE,
            "admission_policy": POLICY,
            "namespace": NAMESPACE,
            "manifest_digest": digest(MANIFEST),
        }

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        "registry2",
        "reset",
        "terminated",
        "unavailable",
        "known-epoch-missing",
        "namespace-drift",
        "created-misconfig",
    ],
)
def test_owned_close_refuses_old_reset_terminated_or_uncertain_registry_without_scoped_close(fault):
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.service import RPCError

    async def run():
        client = Client()
        client.candidates = []
        if fault == "registry2":
            client.version = 2
        elif fault == "reset":
            client.registry_epoch = "reset-epoch"
        elif fault == "terminated":
            client.registry_status = WorkflowExecutionStatus.TERMINATED
        elif fault == "unavailable":
            client.unavailable = True
        elif fault == "known-epoch-missing":
            client.configuration_missing = True
        elif fault in {"namespace-drift", "created-misconfig"}:
            client.missing_registry = True
            if fault == "namespace-drift":
                client.namespace_drift = True
            else:
                client.created_version = 2
        error = RPCError if fault in {"unavailable", "known-epoch-missing"} else DefinitionMismatch
        with pytest.raises(error):
            await module().close(
                Runtime(), client=client, scope=Scope(**SCOPE), task_queue="fixed-owned-queue"
            )
        assert len(client.starts) == (1 if fault in {"namespace-drift", "created-misconfig"} else 0)
        assert not any(c[0] == "update" for c in client.calls)

    asyncio.run(run())


def test_borrowed_close_and_proxy_diagnostics_never_create_missing_registry():
    from temporalio.service import RPCError

    async def run():
        client = Client()
        client.missing_registry, client.candidates = True, []
        with pytest.raises(RPCError):
            await module().close(Runtime(), client=client, scope=Scope(**SCOPE))
        with pytest.raises(RPCError):
            await (
                module()
                .registry(client, SCOPE, MANIFEST)
                .query(
                    "view",
                    {
                        "kind": "coding_composition_candidates",
                        "scope": SCOPE,
                        "manifest_digest": digest(MANIFEST),
                    },
                )
            )
        assert not client.starts and not any(c[0] == "update" for c in client.calls)

    asyncio.run(run())


@pytest.mark.parametrize("lost", [False, True])
def test_owned_close_racing_or_lost_registry_start_keeps_same_authority(monkeypatch, lost):
    from ralf_agent import temporal_coding_composition_control as coding

    async def run():
        client, closed = Client(), []
        client.missing_registry, client.candidates = True, []
        client.lost_start, client.racing_start = lost, not lost

        async def close(runtime, *, client, scope, candidates):
            closed.append(candidates)

        monkeypatch.setattr(coding, "close", close)
        if lost:
            with pytest.raises(TimeoutError):
                await module().close(
                    Runtime(), client=client, scope=Scope(**SCOPE), task_queue="fixed-owned-queue"
                )
            assert not closed and not any(c[0] == "update" for c in client.calls)
        await module().close(
            Runtime(), client=client, scope=Scope(**SCOPE), task_queue="fixed-owned-queue"
        )
        assert len(client.starts) == 1
        assert client.starts[0][2]["id"] == registry_id(POLICY["deployment_id"])
        assert closed == [[]]

    asyncio.run(run())


@pytest.mark.parametrize("queue", ["", 1])
def test_owned_close_requires_nonempty_fixed_queue_before_sdk_io(queue):
    async def run():
        client = Client()
        client.missing_registry = True
        with pytest.raises(DefinitionMismatch):
            await module().close(Runtime(), client=client, scope=Scope(**SCOPE), task_queue=queue)
        assert not client.starts and not client.calls

    asyncio.run(run())
