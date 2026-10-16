"""Fixed SDK transport boundaries; no service/native execution evidence."""

import asyncio
import copy
import importlib
from types import SimpleNamespace

import pytest

from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.types import Scope, digest

SCOPE = {"workspace": "composition", "principal": "original"}
MANIFEST = {
    "kernel": "temporal-3",
    "binding_protocol": 13,
    "coding_composition_protocol": {"version": 2, "topology": "bounded-agent-graph"},
}
NAMESPACE = {"name": "original", "id": "11111111-1111-1111-1111-111111111111"}


def test_close_adopts_sealed_child_without_sending_new_cancel(monkeypatch):
    from tests.test_temporal_deployment_coding_guards import sealed_native

    state, _, _ = sealed_native(monkeypatch)
    leaf = {
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "request": copy.deepcopy(state.request),
        "state": state.state,
        "physical_stopped": True,
        "manifest": state.manifest,
        "namespace": NAMESPACE,
    }
    root = {
        "scope": state.scope,
        "run_id": "unsealed-parent",
        "request": {"definition": {"kind": "graph"}},
        "execution_epoch": "parent-epoch",
    }
    call = {"request": copy.deepcopy(state.request), "run_id": state.run_id}
    events = []
    before = copy.deepcopy((state.deployment_seal, state.event_log, state.revision))

    async def read(*args, **kwargs):
        return copy.deepcopy(leaf)

    async def adopt(*args, **kwargs):
        events.append("epoch" if kwargs.get("epoch") else "physical")

    async def namespace(*args):
        pass

    async def sealed(*args):
        events.append("positive-seal")
        return True

    class OriginalHandle:
        async def execute_update(self, name, value, **kwargs):
            events.append("new-command")
            return state.command(value["command_id"], value["payload"])

    class OriginalClient:
        def get_workflow_handle(self, *args, **kwargs):
            return OriginalHandle()

    control = module()
    monkeypatch.setattr(control, "_child_proof", read)
    monkeypatch.setattr(control, "_proof", read)
    monkeypatch.setattr(control, "_adopt", adopt)
    monkeypatch.setattr(control, "_namespace", namespace)
    monkeypatch.setattr(control, "_deployment_sealed", sealed)
    asyncio.run(
        control._close_child(
            object(), OriginalClient(), root, call, {"binding_protocol": 23}, NAMESPACE
        )
    )
    assert events == ["epoch", "positive-seal", "positive-seal", "physical"]
    assert (state.deployment_seal, state.event_log, state.revision) == before


def module():
    name = "ralf_agent.temporal_coding_composition_control"
    assert importlib.util.find_spec(name), "Missing original composition control"
    return importlib.import_module(name)


def proof(run_id="child", *, request=None, epoch="child-epoch", stopped=False):
    request = (
        {"definition": {"kind": "agent"}, "input": "original", "budget": 8}
        if request is None
        else request
    )
    value = {
        "version": 1,
        "scope": SCOPE,
        "run_id": run_id,
        "execution_epoch": epoch,
        "original_execution_epoch": epoch,
        "namespace": NAMESPACE,
        "request": request,
        "request_digest": digest(request),
        "manifest": MANIFEST,
        "release_digest": digest({"definition": request["definition"], "manifest": MANIFEST}),
        "revision": 1,
        "state": "cancelled" if stopped else "running",
        "physical_stopped": stopped,
        "action_stops": [],
    }
    value["proof_digest"] = digest(value)
    return value


class Handle:
    def __init__(self, client, run_id, epoch):
        self.client, self.run_id, self.epoch = client, run_id, epoch

    async def describe(self):
        self.client.calls.append(("describe", self.run_id, self.epoch))
        return SimpleNamespace(
            run_id=self.client.epochs[self.run_id],
            parent_id=None if self.run_id == "root" else "root",
            parent_run_id=None if self.run_id == "root" else "root-epoch",
        )

    async def query(self, name, value):
        self.client.calls.append(("query", self.run_id, self.epoch, value))
        if self.run_id.startswith("ralf-temporal-commands-"):
            if value["kind"] == "coding_composition_admission":
                return self.client.candidate | {
                    "admitted": not self.client.candidate["close_requested"]
                }
            return [self.client.candidate]
        if value["kind"] == "coding_composition_children":
            return copy.deepcopy(self.client.children)
        if value["kind"] == "coding_composition_proof":
            return copy.deepcopy(self.client.proofs[self.run_id])
        if value["kind"] == "coding_requests":
            return copy.deepcopy(self.client.requests.get(self.run_id, []))
        return {"snapshot": {"run_id": self.run_id}, "workflow": {}}

    async def execute_update(self, name, value, **kwargs):
        self.client.calls.append(("update", self.run_id, self.epoch, name, value))
        if name == "admit_coding_composition_submission":
            self.client.candidate.update(
                execution_epoch=value["execution_epoch"], namespace=value["namespace"]
            )
            return self.client.candidate | {
                "admitted": not self.client.candidate["close_requested"]
            }
        if name == "close_coding_composition_submissions":
            self.client.candidate["close_requested"] = True
            return {
                "manifest_digest": digest(MANIFEST),
                "close_requested": True,
                "candidates": [self.client.candidate],
            }
        if name == "coding_composition_namespace":
            self.client.proofs[self.run_id]["namespace"] = value["namespace"]
            self.client.proofs[self.run_id]["proof_digest"] = digest(
                {k: v for k, v in self.client.proofs[self.run_id].items() if k != "proof_digest"}
            )
            return {"run_id": self.run_id, "recorded": True}
        if name == "coding_composition_child_epoch":
            call = next(
                item for item in self.client.children if item["run_id"] == value["child_run_id"]
            )
            evidence = value["evidence"]
            call["child_execution"] = {
                key: evidence[key]
                for key in ("namespace", "execution_epoch", "original_execution_epoch")
            }
            return {"run_id": value["child_run_id"], "recorded": True}
        if name == "command":
            current = self.client.proofs[self.run_id]
            current.update(state="cancelled", physical_stopped=not self.client.live_owner)
            current["proof_digest"] = digest(
                {k: v for k, v in current.items() if k != "proof_digest"}
            )
            return {"run_id": self.run_id}
        return {"run_id": value.get("child_run_id", self.run_id), "recorded": True}


class Client:
    namespace = "original"

    def __init__(self, root_request=None):
        root_request = (
            {"definition": {"kind": "graph"}, "input": None, "budget": 8}
            if root_request is None
            else root_request
        )
        self.calls, self.live_owner, self.children = [], False, []
        self.requests = {}
        self.epochs = {"root": "root-epoch", "child": "child-epoch"}
        self.proofs = {"root": proof("root", request=root_request, epoch="root-epoch")}
        payload = root_request
        self.candidate = {
            "command_id": "root-command",
            "run_id": "root",
            "request_digest": digest(payload),
            "manifest_digest": digest(MANIFEST),
            "close_requested": False,
            "execution_epoch": None,
            "namespace": None,
        }

    def get_workflow_handle(self, workflow_id, **kwargs):
        return Handle(self, workflow_id, kwargs.get("run_id"))


def runtime():
    def validate(value=None):
        if value is not None and value != MANIFEST:
            raise DefinitionMismatch("release changed")

    return SimpleNamespace(
        orchestration_release=MANIFEST, validate_release=validate, tools=SimpleNamespace(_tools=[])
    )


@pytest.fixture
def namespace(monkeypatch):
    from ralf_agent import temporal_session_activities

    async def identity(client):
        return "11111111-1111-1111-1111-111111111111"

    monkeypatch.setattr(temporal_session_activities, "namespace_id", identity)


def test_root_admission_checks_actual_epoch_before_registry_io(namespace):
    client = Client()
    value = {
        "scope": SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "command_id": "root-command",
        "request": client.proofs["root"]["request"],
        "runtime_manifest": MANIFEST,
    }
    wrong = SimpleNamespace(
        workflow_id="root", workflow_run_id="foreign", workflow_namespace="original"
    )
    with pytest.raises(DefinitionMismatch):
        asyncio.run(module().root_admission(runtime(), client, value, wrong))
    assert not client.calls


def test_closed_root_admission_has_namespace_but_no_business_permission(namespace):
    client = Client()
    client.candidate["close_requested"] = True
    value = {
        "scope": SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "command_id": "root-command",
        "request": client.proofs["root"]["request"],
        "runtime_manifest": MANIFEST,
    }
    info = SimpleNamespace(
        workflow_id="root", workflow_run_id="root-epoch", workflow_namespace="original"
    )
    result = asyncio.run(module().root_admission(runtime(), client, value, info))
    assert result == {"namespace": NAMESPACE, "admitted": False, "execution_epoch": "root-epoch"}


def test_root_admission_rejects_replaced_original_registry_request(namespace):
    client = Client()
    client.candidate["request_digest"] = "foreign"
    value = {
        "scope": SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "command_id": "root-command",
        "request": client.proofs["root"]["request"],
        "runtime_manifest": MANIFEST,
    }
    info = SimpleNamespace(
        workflow_id="root", workflow_run_id="root-epoch", workflow_namespace="original"
    )
    with pytest.raises(DefinitionMismatch):
        asyncio.run(module().root_admission(runtime(), client, value, info))


def test_close_records_admission_stop_before_reading_original_root(namespace):
    client = Client()
    asyncio.run(module().close(runtime(), client=client, scope=Scope(**SCOPE)))
    assert (
        client.calls[0][0] == "update"
        and client.calls[0][3] == "close_coding_composition_submissions"
    )
    assert client.candidate["close_requested"] is True
    commands = [call for call in client.calls if call[0] == "update" and call[3] == "command"]
    assert commands and all(call[2] == "root-epoch" for call in commands)


def test_close_live_original_owner_retains_obligation(namespace):
    client = Client()
    client.live_owner = True
    with pytest.raises(CloseIncomplete):
        asyncio.run(module().close(runtime(), client=client, scope=Scope(**SCOPE)))
    assert client.candidate["close_requested"] is True


def test_validation_refuses_reset_original_leaf_before_business(namespace):
    client = Client()
    child = proof()
    child["original_execution_epoch"] = "replaced-epoch"
    child["proof_digest"] = digest({k: v for k, v in child.items() if k != "proof_digest"})
    client.proofs["child"] = child
    request = {
        "scope": SCOPE,
        "run_id": "child",
        "execution_epoch": "child-epoch",
        "runtime_manifest": MANIFEST,
    }
    with pytest.raises(DefinitionMismatch):
        asyncio.run(module().validate_activity(client, request, workflow_id="child"))
    assert all(call[2] == "child-epoch" for call in client.calls)


def test_tree_validator_checks_composition_without_session_lineage(namespace):
    from ralf_agent.temporal_session_activities import validate_tree_activity

    client = Client()
    child = proof()
    child["original_execution_epoch"] = "foreign"
    child["proof_digest"] = digest({k: v for k, v in child.items() if k != "proof_digest"})
    client.proofs["child"] = child
    request = {
        "scope": SCOPE,
        "run_id": "child",
        "execution_epoch": "child-epoch",
        "runtime_manifest": MANIFEST,
    }
    with pytest.raises(DefinitionMismatch):
        asyncio.run(validate_tree_activity(client, request, workflow_id="child"))


def test_selected_assembly_drain_uses_composition_close_not_native_only(monkeypatch):
    from ralf_agent import temporal_coding_runtime
    from ralf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly, WorkerExecutionOwner

    calls = []

    async def selected_close(runtime, **kwargs):
        calls.append("composition")

    async def old_close(runtime, **kwargs):
        calls.append("native-only")

    async def end(**kwargs):
        pass

    monkeypatch.setattr(module(), "close", selected_close)
    monkeypatch.setattr(temporal_coding_runtime, "close", old_close)
    owner = SimpleNamespace(
        release=MANIFEST,
        _worker_start=None,
        _worker=None,
        _runtime=SimpleNamespace(
            coding_execution=True,
            orchestration_release=MANIFEST,
            close_context_execution=end,
            close_session_execution=end,
        ),
        _coding_stop_task=None,
        _client=Client(),
        _scope=Scope(**SCOPE),
        _calls=WorkerExecutionOwner(scope=Scope(**SCOPE), release=MANIFEST),
    )

    async def run():
        await TemporalRuntimeAssembly._drain_execution(owner, 1)

    asyncio.run(run())
    assert calls == ["composition"]


def test_registered_admission_activity_uses_actual_sdk_identity(namespace, monkeypatch):
    from temporalio import activity

    from ralf_agent.temporal_control_activities import registered_parent_activities

    client, worker_runtime = Client(), runtime()
    worker_runtime.parent_completion_policies = {}
    registrations = registered_parent_activities(worker_runtime, client)
    found = [
        fn
        for fn in registrations
        if activity._Definition.from_callable(fn).name
        == "ralf.temporal.coding-composition-admission.v1"
    ]
    assert len(found) == 1, "Missing fixed original root admission Activity"
    monkeypatch.setattr(
        activity,
        "info",
        lambda: SimpleNamespace(
            workflow_id="root", workflow_run_id="root-epoch", workflow_namespace="original"
        ),
    )
    request = {
        "scope": SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "command_id": "root-command",
        "request": client.proofs["root"]["request"],
        "runtime_manifest": MANIFEST,
    }
    result = asyncio.run(found[0](request))
    assert result == {
        "ok": True,
        "result": {"namespace": NAMESPACE, "admitted": True, "execution_epoch": "root-epoch"},
    }


def test_assembly_drain_retains_resources_before_inflight_submit_response(monkeypatch):
    from ralf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly

    calls = []

    async def unresolved(**kwargs):
        raise CloseIncomplete("Original submit response remains owned")

    async def selected_close(runtime, **kwargs):
        calls.append("close")

    async def end(**kwargs):
        pass

    monkeypatch.setattr(module(), "close", selected_close)
    owner = SimpleNamespace(
        _worker_start=None,
        _runtime=SimpleNamespace(
            coding_execution=True,
            orchestration_release=MANIFEST,
            close_context_execution=end,
            close_session_execution=end,
        ),
        _coding_stop_task=None,
        _client=Client(),
        _scope=Scope(**SCOPE),
        _calls=SimpleNamespace(aclose=end),
        _coding_submissions=SimpleNamespace(aclose=unresolved),
    )
    with pytest.raises(CloseIncomplete):
        asyncio.run(TemporalRuntimeAssembly._drain_execution(owner, 0))
    assert calls == []


def test_root_close_uses_saved_epoch_without_discovering_latest(namespace):
    client = Client()
    client.candidate.update(execution_epoch="root-epoch", namespace=NAMESPACE)
    client.epochs["root"] = "foreign-latest"
    asyncio.run(module().close(runtime(), client=client, scope=Scope(**SCOPE)))
    assert not any(call[0] == "describe" for call in client.calls)
    assert all(call[2] == "root-epoch" for call in client.calls if call[1] == "root")


def linked_client():
    from ralf_agent.temporal_parent_state import child_run_id

    client = Client()
    run_id = child_run_id(SCOPE, "child-command")
    base = {"definition": {"kind": "agent"}, "input": "original", "budget": 8}
    parent = client.proofs["root"]
    request = base | {
        "coding_parent": {
            "version": 1,
            "scope": SCOPE,
            "namespace": NAMESPACE,
            "parent_run_id": "root",
            "parent_execution_epoch": "root-epoch",
            "parent_request_digest": parent["request_digest"],
            "parent_release_digest": parent["release_digest"],
            "call_id": "0:a",
            "command_id": "child-command",
            "member": "a",
            "planning_revision": 0,
            "child_run_id": run_id,
            "child_projection_digest": digest(base),
            "cap": 8,
            "depth": 1,
        }
    }
    client.proofs[run_id] = proof(run_id, request=request)
    client.epochs[run_id] = "child-epoch"
    client.children = [
        {
            "id": "0:a",
            "run_id": run_id,
            "request": request,
            "cap": 8,
            "command_id": "child-command",
            "dispatch_started": True,
            "call_id": "a",
            "member": "a",
            "input": "original",
            "depth": 1,
            "child_request_digest": digest(request),
        }
    ]
    return client, run_id


def test_activity_startup_pins_actual_child_epoch_before_business(namespace):
    client, run_id = linked_client()
    request = {
        "scope": SCOPE,
        "run_id": run_id,
        "execution_epoch": "child-epoch",
        "runtime_manifest": MANIFEST,
    }
    asyncio.run(module().validate_activity(client, request, workflow_id=run_id))
    assert client.children[0].get("child_execution") == {
        "namespace": NAMESPACE,
        "execution_epoch": "child-epoch",
        "original_execution_epoch": "child-epoch",
    }


def test_activity_observing_original_parent_stop_cancels_leaf_before_cleanup_validation(namespace):
    client, run_id = linked_client()
    client.proofs["root"].update(state="cancelling")
    client.proofs["root"]["proof_digest"] = digest(
        {k: v for k, v in client.proofs["root"].items() if k != "proof_digest"}
    )
    request = {
        "scope": SCOPE,
        "run_id": run_id,
        "execution_epoch": "child-epoch",
        "runtime_manifest": MANIFEST,
    }
    asyncio.run(module().validate_activity(client, request, workflow_id=run_id))
    assert client.proofs[run_id]["state"] == "cancelled"


def test_original_control_accepts_stale_child_bookkeeping_but_not_changed_intent(namespace):
    client, run_id = linked_client()
    original_call = copy.deepcopy(client.children[0])
    client.children[0]["observed_revision"] = 2
    parent = client.proofs["root"]
    value = {
        "mode": "observe",
        "child": original_call,
        "parent_id": "root",
        "scope": SCOPE,
        "task_queue": "original",
        "runtime_manifest": MANIFEST,
        "parent_execution_epoch": "root-epoch",
        "namespace": NAMESPACE,
        "parent_request_digest": parent["request_digest"],
        "parent_release_digest": parent["release_digest"],
    }
    info = SimpleNamespace(
        workflow_id="root", workflow_run_id="root-epoch", workflow_namespace="original"
    )
    result = asyncio.run(module().control(runtime(), client, value, info))
    assert result["coding_composition_proof"]["run_id"] == run_id
    value["child"]["request"]["input"] = "replaced"
    with pytest.raises(DefinitionMismatch):
        asyncio.run(module().control(runtime(), client, value, info))


def test_activity_refuses_foreign_saved_child_epoch_before_native_business(namespace):
    client, run_id = linked_client()
    client.children[0]["child_execution"] = {
        "namespace": NAMESPACE,
        "execution_epoch": "foreign",
        "original_execution_epoch": "foreign",
    }
    request = {
        "scope": SCOPE,
        "run_id": run_id,
        "execution_epoch": "child-epoch",
        "runtime_manifest": MANIFEST,
    }
    with pytest.raises(DefinitionMismatch):
        asyncio.run(module().validate_activity(client, request, workflow_id=run_id))


def test_fenced_resource_survives_failed_ancestor_adoption_on_close_retry(namespace, monkeypatch):
    from ralf_agent import delegated_coding, temporal_bindings
    from ralf_agent.postgres_coding_resources import receive_resource

    client, run_id = linked_client()
    client.fault = True
    original_update = Handle.execute_update
    resource = native_resource(client, run_id)
    scans = []

    async def resources(scope):
        assert scope == Scope(**SCOPE)
        scans.append(resource["pending_stop"])
        return (copy.deepcopy(resource),)

    async def update(handle, name, value, **kwargs):
        if name == "coding_composition_child_stopped":
            if client.fault:
                raise OSError("controlled original ancestor adoption fault")
            current = client.proofs["root"]
            current["physical_stopped"] = value["evidence"]["physical_stopped"]
            current["proof_digest"] = digest(
                {k: v for k, v in current.items() if k != "proof_digest"}
            )
        return await original_update(handle, name, value, **kwargs)

    async def fence(runtime, sdk, leaf, namespace):
        nonlocal resource
        assert leaf["run_id"] == run_id and leaf["execution_epoch"] == "child-epoch"
        resource = receive_resource(
            resource,
            "unprepared",
            {
                "namespace_binding": resource["namespace_binding"],
                "prepare_granted": False,
            },
        )

    monkeypatch.setattr(Handle, "execute_update", update)
    monkeypatch.setattr(module(), "_fence_leaf", fence)
    journal = SimpleNamespace(composition_resources=resources)
    handler = SimpleNamespace(identity=resource["runner"], runner=SimpleNamespace(_journal=journal))
    monkeypatch.setattr(delegated_coding, "registered_coding_tool", lambda tool: handler)
    monkeypatch.setattr(temporal_bindings, "selected_runtime", lambda runtime, request: runtime)
    worker_runtime = runtime()
    worker_runtime.tools = SimpleNamespace(_tools=["coding"], get=lambda name: object())

    async def run():
        with pytest.raises(CloseIncomplete) as error:
            await module().close(worker_runtime, client=client, scope=Scope(**SCOPE))
        assert resource["pending_stop"] is False
        assert any(item.get("child") == run_id for item in error.value.report["coding_composition"])
        client.fault = False
        await module().close(worker_runtime, client=client, scope=Scope(**SCOPE))
        assert client.proofs["root"]["physical_stopped"] is True
        assert scans == [True, False, False, False]

    asyncio.run(run())


def native_resource(client, run_id, *, fenced=False):
    """Complete legal PG row based on the actual History native-intent producer."""
    from ralf_agent.postgres_coding_resources import (
        new_resource,
        receive_resource,
        validate_resource,
    )
    from ralf_agent.types import canonical
    from tests.test_temporal_coding_state import RUNNER, ready

    _, _, request = ready()
    request = copy.deepcopy(request)
    epoch = client.proofs[run_id]["execution_epoch"]
    request.update(scope=SCOPE, run_id=run_id, execution_epoch=epoch, runtime_manifest=MANIFEST)
    native = request["coding_request"]
    native["dispatch"].update(scope=SCOPE, run_id=run_id, execution_epoch=epoch)
    native["release_digest"] = client.proofs[run_id]["release_digest"]
    native["request_digest"] = digest({k: v for k, v in native.items() if k != "request_digest"})
    client.requests[run_id] = [request]
    binding = {
        "request": native,
        "runner": RUNNER,
        "dispatch": native["dispatch"],
        "environment": {
            "version": "2",
            "expected_generation": "a" * 32,
            "resource_id": "original-resource",
            "retire_on_stop": True,
        },
    }
    key = (SCOPE["workspace"], SCOPE["principal"], native["dispatch"]["effect_key"])
    record = new_resource(key, native, RUNNER, binding)
    if fenced:
        record = receive_resource(
            record,
            "unprepared",
            {
                "namespace_binding": binding,
                "prepare_granted": False,
            },
        )
    return validate_resource(canonical(record), key)


def test_registry_absence_is_not_a_root_creation_permission(namespace, monkeypatch):
    from temporalio.service import RPCError, RPCStatusCode

    client = Client()

    async def absent(handle, name, value, **kwargs):
        raise RPCError("original Registry not found", RPCStatusCode.NOT_FOUND, b"")

    monkeypatch.setattr(Handle, "execute_update", absent)
    asyncio.run(module().close(runtime(), client=client, scope=Scope(**SCOPE)))
    assert not client.calls


def test_registry_absence_with_fenced_native_rows_retains_original_obligation(
    namespace, monkeypatch
):
    from temporalio.service import RPCError, RPCStatusCode

    from ralf_agent import delegated_coding

    client = Client()
    resource = native_resource(client, "root", fenced=True)

    async def absent(handle, name, value, **kwargs):
        raise RPCError("original Registry not found", RPCStatusCode.NOT_FOUND, b"")

    async def rows(scope):
        return (copy.deepcopy(resource),)

    handler = SimpleNamespace(
        identity=resource["runner"],
        runner=SimpleNamespace(_journal=SimpleNamespace(composition_resources=rows)),
    )
    monkeypatch.setattr(Handle, "execute_update", absent)
    monkeypatch.setattr(delegated_coding, "registered_coding_tool", lambda tool: handler)
    worker_runtime = runtime()
    worker_runtime.tools = SimpleNamespace(_tools=["coding"], get=lambda name: object())
    with pytest.raises(CloseIncomplete):
        asyncio.run(module().close(worker_runtime, client=client, scope=Scope(**SCOPE)))


def test_original_parent_context_uses_actual_sdk_epoch_when_legacy_payload_omits_it(
    namespace, monkeypatch
):
    from temporalio import activity

    client = Client()
    monkeypatch.setattr(
        activity,
        "info",
        lambda: SimpleNamespace(
            workflow_id="root", workflow_run_id="root-epoch", workflow_namespace="original"
        ),
    )
    request = {"scope": SCOPE, "run_id": "root", "runtime_manifest": MANIFEST}
    asyncio.run(module().validate_activity(client, request, workflow_id="root"))
    assert all(call[2] == "root-epoch" for call in client.calls)
    assert not any(call[0] == "describe" for call in client.calls)


def test_root_admission_consumes_actual_engine_guard_metadata(namespace):
    from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec
    from ralf_agent.temporal import TemporalEngine
    from ralf_agent.temporal_state import TemporalCommandRegistryState
    from ralf_agent.types import submission_request

    request = submission_request(
        GraphWorkflowSpec("original", [GraphNode("a", agent=AgentSpec("a", "Answer"))]),
        "task",
        budget=8,
    )
    registry = TemporalCommandRegistryState(SCOPE)

    class RegistryTransport:
        async def execute_update(self, name, payload, **kwargs):
            arguments = {key: value for key, value in payload.items() if key != "scope"}
            if name == "reserve":
                return registry.reserve(payload)
            return registry.bind_composition_submission(**arguments)

        async def query(self, name, payload):
            if payload.get("kind") == "scoped_reserve_receipt":
                return {
                    "scope": SCOPE,
                    "capacity": registry.capacity,
                    "accepted_commands": len(registry.identities),
                }
            return registry.composition_admission(
                *(
                    payload[key]
                    for key in ("command_id", "run_id", "request_digest", "manifest_digest")
                )
            )

    transport = RegistryTransport()
    client = SimpleNamespace(
        namespace="original", get_workflow_handle=lambda workflow_id, **kwargs: transport
    )
    engine = SimpleNamespace(
        _closed=False,
        _registry=transport,
        _release=MANIFEST,
        release=MANIFEST,
        scope=Scope(**SCOPE),
        client=client,
    )
    value = {
        "scope": SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "command_id": "root-command",
        "request": request,
        "runtime_manifest": MANIFEST,
    }
    info = SimpleNamespace(
        workflow_id="root", workflow_run_id="root-epoch", workflow_namespace="original"
    )

    async def run():
        await TemporalEngine._guard(engine, "submit", "root-command", "root", request)
        result = await module().root_admission(runtime(), client, value, info)
        assert result["admitted"] is True

    asyncio.run(run())


def test_standalone_leaf13_initializes_uuid_at_original_epoch_without_parent_admission(namespace):
    request = {"definition": {"kind": "agent"}, "input": "original", "budget": 8}
    client = Client(root_request=request)
    client.proofs["root"]["namespace"] = {"name": "original", "id": None}
    client.proofs["root"]["proof_digest"] = digest(
        {k: v for k, v in client.proofs["root"].items() if k != "proof_digest"}
    )
    activity_request = {
        "scope": SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "runtime_manifest": MANIFEST,
    }
    asyncio.run(module().validate_activity(client, activity_request, workflow_id="root"))
    assert client.proofs["root"]["namespace"] == NAMESPACE
    assert not any(call[0] == "describe" for call in client.calls)
    assert all(call[2] == "root-epoch" for call in client.calls)


def test_recreated_same_manifest_close_does_not_reuse_prior_registry_receipt(
    namespace, monkeypatch
):
    client = Client()
    original = Handle.execute_update
    cached = {}
    original_candidates = {"root-command": client.candidate}

    async def update(handle, name, value, **kwargs):
        if name == "admit_coding_composition_submission":
            item = original_candidates[value["command_id"]]
            item.update(execution_epoch=value["execution_epoch"], namespace=value["namespace"])
            return copy.deepcopy(item) | {"admitted": not item["close_requested"]}
        if name == "close_coding_composition_submissions":
            key = kwargs["id"]
            if key not in cached:
                cached[key] = copy.deepcopy(await original(handle, name, value, **kwargs))
            return copy.deepcopy(cached[key])
        return await original(handle, name, value, **kwargs)

    monkeypatch.setattr(Handle, "execute_update", update)

    async def run():
        await module().close(runtime(), client=client, scope=Scope(**SCOPE))
        request = {"definition": {"kind": "graph"}, "input": "new accepted root", "budget": 8}
        client.proofs["second-root"] = proof("second-root", request=request, epoch="second-epoch")
        client.candidate = {
            "command_id": "second-command",
            "run_id": "second-root",
            "request_digest": digest(request),
            "manifest_digest": digest(MANIFEST),
            "close_requested": False,
            "execution_epoch": "second-epoch",
            "namespace": NAMESPACE,
        }
        original_candidates["second-command"] = client.candidate
        await module().close(runtime(), client=client, scope=Scope(**SCOPE))
        assert client.proofs["second-root"]["state"] == "cancelled"

    asyncio.run(run())
