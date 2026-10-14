"""SDK transport boundaries against original Registry state; no external service."""

import asyncio
import copy
import importlib
from types import SimpleNamespace

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.temporal_deployment_admission import DeploymentAdmissionState, root_run_id
from ralf_agent.types import digest


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


SCOPE = {"workspace": "deployment", "principal": "owner"}
NAMESPACE = {"name": "original", "id": "11111111-1111-1111-1111-111111111111"}
POLICY = DeploymentAdmissionPolicy("sdk-gate", max_active_root_runs=1)


def module():
    name = "ralf_agent.temporal_deployment_execution"
    assert importlib.util.find_spec(name), "Missing actual SDK deployment admission transport"
    return importlib.import_module(name)


def sealed(value):
    value = copy.deepcopy(value)
    value.pop("proof_digest", None)
    return {**value, "proof_digest": digest(value)}


class Runtime:
    def __init__(self, manifest):
        self._deployment_admission_policy = self._deployment_admission_policy_pin = POLICY
        self._deployment_admission_identity = POLICY.identity
        self.manifest = manifest

    def validate_release(self, manifest=None):
        if manifest is not None and manifest != self.manifest:
            raise DefinitionMismatch("Wrong original Worker release")
        if self._deployment_admission_policy is not self._deployment_admission_policy_pin:
            raise DefinitionMismatch("Changed Worker policy")
        return copy.deepcopy(self.manifest)


class Handle:
    def __init__(self, client, run_id, epoch):
        self.client, self.id, self.epoch = client, run_id, epoch

    async def describe(self):
        item = self.client.descriptions[self.id]
        if self.epoch is not None and item.run_id != self.epoch:
            raise DefinitionMismatch("Fake SDK cannot resolve replaced epoch")
        return copy.deepcopy(item)

    async def query(self, name, value):
        assert name == "view"
        if self.id == self.client.registry.registry_id:
            return self.client.registry.deployment_admission(value)
        proof = self.client.proofs[self.id]
        if value["scope"] != proof["scope"]:
            return {"error": "authorization_denied"}
        if value["kind"] == "diagnostics":
            return {"snapshot": {"run_id": self.id, "state": "running"}, "workflow": {}}
        assert value["kind"] == "deployment_admission"
        return copy.deepcopy(proof)

    async def execute_update(self, name, value, **kwargs):
        self.client.updates.append((self.id, self.epoch, name, copy.deepcopy(value)))
        if name == "bind_deployment_root":
            assert self.id == self.client.registry.registry_id
            return self.client.registry.bind_deployment_root(value)
        if name == "deployment_child_epoch":
            parent = self.client.proofs[self.id]
            call = next(c for c in parent["children"] if c["run_id"] == value["child_run_id"])
            assert value["metadata_digest"] == digest(call["deployment_admission"])
            old = call.get("deployment_execution_epoch")
            if old not in (None, value["child_execution_epoch"]):
                raise DefinitionMismatch("Changed child epoch")
            call["deployment_execution_epoch"] = value["child_execution_epoch"]
            self.client.proofs[self.id] = sealed(parent)
            return {"run_id": call["run_id"], "recorded": True}
        assert name == "command"
        return {"command_id": value["command_id"], "apply_state": "applied"}


class Client:
    namespace = NAMESPACE["name"]

    def __init__(self):
        self.proofs, self.descriptions, self.updates = {}, {}, []
        self.registry = DeploymentAdmissionState(POLICY.identity, NAMESPACE, capacity=4096)
        self.workflow_service = SimpleNamespace(describe_namespace=self.describe_namespace)
        self.namespace_uuid = NAMESPACE["id"]

    async def describe_namespace(self, request):
        assert request.namespace == self.namespace
        return SimpleNamespace(namespace_info=SimpleNamespace(id=self.namespace_uuid))

    def get_workflow_handle(self, workflow_id, **kwargs):
        return Handle(self, workflow_id, kwargs.get("run_id"))


def setup():
    client = Client()
    manifest = {
        "kernel": "temporal-1",
        "deployment_admission_protocol": {
            "version": 1,
            "policy": POLICY.identity,
            "registry_id": client.registry.registry_id,
            "implementation": {},
        },
    }
    request = {"definition": {"kind": "graph"}, "input": "original", "budget": 8}
    run_id = root_run_id(POLICY.deployment_id, SCOPE, "root-command")
    root = client.registry.reserve(
        {
            "scope": SCOPE,
            "command_id": "root-command",
            "kind": "submit",
            "target": run_id,
            "payload_digest": digest(request),
            "admission_policy": POLICY.identity,
            "namespace": NAMESPACE,
            "root_admission": {"version": 1, "manifest_digest": digest(manifest)},
        }
    )["root_admission"]
    metadata = {"version": 1, "root": root, "lineage": []}
    proof = sealed(
        {
            "version": 1,
            "scope": SCOPE,
            "run_id": run_id,
            "command_id": "root-command",
            "execution_epoch": "root-epoch",
            "original_execution_epoch": "root-epoch",
            "namespace": NAMESPACE,
            "request": request,
            "request_digest": digest(request),
            "manifest": manifest,
            "manifest_digest": digest(manifest),
            "admission": metadata,
            "admission_receipt": None,
            "children": [],
        }
    )
    client.proofs[run_id] = proof
    client.descriptions[run_id] = SimpleNamespace(
        id=run_id,
        run_id="root-epoch",
        namespace=NAMESPACE["name"],
        parent_id=None,
        parent_run_id=None,
    )
    value = {
        "scope": SCOPE,
        "run_id": run_id,
        "execution_epoch": "root-epoch",
        "command_id": "root-command",
        "request": request,
        "runtime_manifest": manifest,
        "deployment_admission": metadata,
    }
    info = SimpleNamespace(
        workflow_id=run_id, workflow_run_id="root-epoch", workflow_namespace=NAMESPACE["name"]
    )
    return Runtime(manifest), client, value, info


async def admitted_setup():
    runtime, client, value, info = setup()
    receipt = await module().admit(runtime, client, value, info)
    client.proofs[value["run_id"]] = sealed(
        {**client.proofs[value["run_id"]], "admission_receipt": receipt}
    )
    return runtime, client, value, info


def child_setup(
    runtime,
    client,
    parent_value,
    *,
    child_id="ralf-temporal-child",
    command_id="child-command",
    kind="agent",
):
    parent = client.proofs[parent_value["run_id"]]
    request = {"definition": {"kind": kind}, "input": "child", "budget": 2}
    link = {
        "parent_run_id": parent["run_id"],
        "parent_execution_epoch": parent["execution_epoch"],
        "parent_request_digest": parent["request_digest"],
        "parent_manifest_digest": parent["manifest_digest"],
        "call_id": "0:worker",
        "child_run_id": child_id,
        "child_command_id": command_id,
        "child_request_digest": digest(request),
    }
    metadata = {
        **copy.deepcopy(parent["admission"]),
        "lineage": [*parent["admission"]["lineage"], link],
    }
    call = {
        "id": "0:worker",
        "command_id": command_id,
        "run_id": child_id,
        "request": request,
        "dispatch_started": True,
        "deployment_admission": metadata,
        "deployment_execution_epoch": None,
    }
    client.proofs[parent["run_id"]] = sealed({**parent, "children": [call]})
    client.proofs[child_id] = sealed(
        {
            **parent,
            "run_id": child_id,
            "command_id": command_id,
            "execution_epoch": "child-epoch",
            "original_execution_epoch": "child-epoch",
            "request": request,
            "request_digest": digest(request),
            "admission": metadata,
            "admission_receipt": None,
            "children": [],
        }
    )
    client.descriptions[child_id] = SimpleNamespace(
        id=child_id,
        run_id="child-epoch",
        namespace=NAMESPACE["name"],
        parent_id=parent["run_id"],
        parent_run_id=parent["execution_epoch"],
    )
    value = {
        "scope": SCOPE,
        "run_id": child_id,
        "execution_epoch": "child-epoch",
        "command_id": command_id,
        "request": request,
        "runtime_manifest": runtime.manifest,
        "deployment_admission": metadata,
    }
    info = SimpleNamespace(
        workflow_id=child_id, workflow_run_id="child-epoch", workflow_namespace=NAMESPACE["name"]
    )
    return value, info, call


def test_root_admission_binds_original_registry_and_detaches_result():
    async def run():
        runtime, client, value, info = setup()
        original = copy.deepcopy(value)
        result = await module().admit(runtime, client, value, info)
        assert result["root"]["state"] == "held-bound"
        assert result["root"]["execution_epoch"] == "root-epoch"
        assert result["metadata_digest"] == digest(original["deployment_admission"])
        assert value == original
        result["root"]["state"] = "released"
        assert next(iter(client.registry.roots.values()))["state"] == "held-bound"

    asyncio.run(run())


@pytest.mark.parametrize(
    "changed",
    ["sdk_epoch", "namespace_uuid", "orphan", "proof_digest", "request", "manifest", "root"],
)
def test_root_refuses_forged_sdk_or_original_proof_before_registry_binding(changed):
    async def run():
        runtime, client, value, info = setup()
        run_id = value["run_id"]
        if changed == "sdk_epoch":
            info.workflow_run_id = "replacement"
        elif changed == "namespace_uuid":
            client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        elif changed == "orphan":
            client.descriptions[run_id].parent_id = "foreign"
            client.descriptions[run_id].parent_run_id = "foreign-epoch"
        elif changed == "proof_digest":
            client.proofs[run_id]["proof_digest"] = "0" * 64
        elif changed == "request":
            value["request"] = {**value["request"], "input": "changed"}
        elif changed == "manifest":
            value["runtime_manifest"] = {**runtime.manifest, "foreign": True}
        else:
            value["deployment_admission"] = {**value["deployment_admission"], "root": {}}
        with pytest.raises(DefinitionMismatch):
            await module().admit(runtime, client, value, info)
        assert not client.updates
        assert next(iter(client.registry.roots.values()))["state"] == "held-unbound"

    asyncio.run(run())


def test_child_admission_inherits_one_root_and_pins_actual_parent_history():
    async def run():
        runtime, client, parent_value, _ = await admitted_setup()
        value, info, _ = child_setup(runtime, client, parent_value)
        result = await module().admit(runtime, client, value, info)
        assert result["root"]["execution_epoch"] == "root-epoch"
        assert len(client.registry.roots) == 1
        parent = client.proofs[parent_value["run_id"]]
        assert parent["children"][0]["deployment_execution_epoch"] == "child-epoch"
        assert not any(v[2] == "reserve" for v in client.updates)

    asyncio.run(run())


@pytest.mark.parametrize(
    "changed",
    ["sdk_parent", "parent_intent", "parent_metadata", "parent_unadmitted", "pinned_epoch"],
)
def test_child_refuses_foreign_parent_or_changed_original_intent(changed):
    async def run():
        runtime, client, parent_value, _ = await admitted_setup()
        value, info, _ = child_setup(runtime, client, parent_value)
        parent = client.proofs[parent_value["run_id"]]
        if changed == "sdk_parent":
            client.descriptions[value["run_id"]].parent_run_id = "foreign"
        elif changed == "parent_intent":
            parent["children"][0]["request"]["input"] = "changed"
        elif changed == "parent_metadata":
            parent["children"][0]["deployment_admission"]["lineage"] = []
        elif changed == "parent_unadmitted":
            parent["admission_receipt"] = None
        else:
            parent["children"][0]["deployment_execution_epoch"] = "foreign"
        client.proofs[parent["run_id"]] = sealed(parent)
        with pytest.raises(DefinitionMismatch):
            await module().admit(runtime, client, value, info)

    asyncio.run(run())


@pytest.mark.parametrize(
    "category",
    [
        "model",
        "tool",
        "context",
        "evidence",
        "reconcile",
        "limits",
        "completion",
        "selection",
        "control",
        "session",
    ],
)
def test_every_selected_activity_requires_adopted_original_history_despite_dropped_flags(
    monkeypatch, category
):
    async def run():
        from temporalio import activity

        runtime, client, value, info = setup()
        monkeypatch.setattr(activity, "info", lambda: info)
        calls = []

        @activity.defn(name="test." + category)
        async def body(request: dict) -> dict:
            calls.append(request)
            return {"done": True}

        wrapped = module().wrap_activities(runtime, client, [body])[0]
        with pytest.raises(DefinitionMismatch):
            await wrapped({"scope": SCOPE})
        assert calls == []
        receipt = await module().admit(runtime, client, value, info)
        client.proofs[value["run_id"]] = sealed(
            {**client.proofs[value["run_id"]], "admission_receipt": receipt}
        )
        assert await wrapped({"scope": SCOPE}) == {"done": True}

    asyncio.run(run())


def test_model_adoption_scope_and_input_detachment(monkeypatch):
    async def run():
        from temporalio import activity

        runtime, client, _, info = await admitted_setup()
        monkeypatch.setattr(activity, "info", lambda: info)

        @activity.defn(name="test.adoption")
        async def body(request: dict) -> dict:
            request["original_request"]["scope"]["workspace"] = "mutated"
            return {"done": True}

        payload = {"original_request": {"scope": copy.deepcopy(SCOPE)}}
        assert await module().wrap_activities(runtime, client, [body])[0](payload) == {"done": True}
        assert payload["original_request"]["scope"] == SCOPE

    asyncio.run(run())


def test_control_register_observe_and_cancel_use_original_parent_intent_and_child_epoch():
    async def run():
        runtime, client, parent_value, parent_info = await admitted_setup()
        child_value, child_info, call = child_setup(runtime, client, parent_value)
        result = await module().admit(runtime, client, child_value, child_info)
        client.proofs[child_value["run_id"]] = sealed(
            {**client.proofs[child_value["run_id"]], "admission_receipt": result}
        )
        value = {
            "mode": "register",
            "scope": SCOPE,
            "parent_id": parent_value["run_id"],
            "child": call,
            "runtime_manifest": runtime.manifest,
        }
        assert await module().control(runtime, client, value, parent_info) == {
            "run_id": child_value["run_id"],
            "registered": True,
        }
        observed = await module().control(
            runtime, client, {**value, "mode": "observe"}, parent_info
        )
        assert observed["scope"] == SCOPE
        await module().control(runtime, client, {**value, "mode": "cancel"}, parent_info)
        command = client.updates[-1]
        assert command[0:3] == (child_value["run_id"], "child-epoch", "command")
        assert command[3]["payload"]["kind"] == "cancel"

    asyncio.run(run())


def test_only_original_admission_activity_is_exempt_and_returns_sanitized_failure(monkeypatch):
    async def run():
        from temporalio import activity

        runtime, client, value, info = setup()
        monkeypatch.setattr(activity, "info", lambda: info)
        original = module().registered_activity(runtime, client)
        assert module().wrap_activities(runtime, client, [original])[0] is original
        assert (await original(value))["ok"] is True
        malformed = await original({})
        assert malformed == {"ok": False, "code": "definition_mismatch"}

        @activity.defn(name=module().ACTIVITY)
        async def forged(request: dict) -> dict:
            return {"done": True}

        with pytest.raises(DefinitionMismatch):
            module().wrap_activities(runtime, client, [forged])

    asyncio.run(run())


def test_wrapper_rechecks_actual_namespace_after_body(monkeypatch):
    async def run():
        from temporalio import activity

        runtime, client, _, info = await admitted_setup()
        monkeypatch.setattr(activity, "info", lambda: info)

        @activity.defn(name="test.namespace-drift")
        async def body(request: dict) -> dict:
            client.namespace = "changed"
            return {"done": True}

        with pytest.raises(DefinitionMismatch):
            await module().wrap_activities(runtime, client, [body])[0]({"scope": SCOPE})

    asyncio.run(run())


def test_activity_payload_identity_and_metadata_cannot_replace_original_history():
    async def run():
        runtime, client, value, info = await admitted_setup()
        for payload in (
            {"scope": SCOPE, "run_id": "foreign"},
            {"scope": SCOPE, "execution_epoch": "foreign"},
            {"scope": SCOPE, "deployment_admission": {}},
            {
                "scope": SCOPE,
                "original_request": {"scope": {"workspace": "foreign", "principal": "owner"}},
            },
        ):
            with pytest.raises(DefinitionMismatch):
                await module().validate_activity(runtime, client, payload, info)

    asyncio.run(run())


def test_selected_worker_policy_pin_cannot_be_removed_to_disable_guard(monkeypatch):
    async def run():
        from temporalio import activity

        runtime, client, _, info = setup()
        monkeypatch.setattr(activity, "info", lambda: info)
        called = []

        @activity.defn(name="test.policy-drift")
        async def body(request: dict) -> dict:
            called.append(True)
            return {"done": True}

        wrapped = module().wrap_activities(runtime, client, [body])[0]
        runtime._deployment_admission_policy_pin = None
        with pytest.raises(DefinitionMismatch):
            await wrapped({"scope": SCOPE})
        assert called == []

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value", [("admission", {}), ("namespace", "original"), ("manifest", [])]
)
def test_malformed_original_proof_refuses_as_typed_identity_mismatch(field, value):
    async def run():
        runtime, client, request, info = setup()
        run_id = request["run_id"]
        client.proofs[run_id] = sealed({**client.proofs[run_id], field: value})
        with pytest.raises(DefinitionMismatch):
            await module().admit(runtime, client, request, info)
        assert client.updates == []

    asyncio.run(run())


def test_nested_parent_ancestry_pins_each_original_edge_and_keeps_one_root():
    async def run():
        runtime, client, root_value, _ = await admitted_setup()
        parent_value, parent_info, _ = child_setup(runtime, client, root_value, kind="graph")
        receipt = await module().admit(runtime, client, parent_value, parent_info)
        parent = client.proofs[parent_value["run_id"]]
        client.proofs[parent["run_id"]] = sealed({**parent, "admission_receipt": receipt})
        leaf_value, leaf_info, _ = child_setup(
            runtime, client, parent_value, child_id="nested-leaf", command_id="nested-command"
        )
        # Distinct original epochs must remain fixed at each SDK edge.
        leaf_info.workflow_run_id = "nested-epoch"
        leaf_value["execution_epoch"] = "nested-epoch"
        client.descriptions[leaf_value["run_id"]].run_id = "nested-epoch"
        leaf = client.proofs[leaf_value["run_id"]]
        client.proofs[leaf_value["run_id"]] = sealed(
            {**leaf, "execution_epoch": "nested-epoch", "original_execution_epoch": "nested-epoch"}
        )
        result = await module().admit(runtime, client, leaf_value, leaf_info)
        assert result["root"]["execution_epoch"] == "root-epoch"
        assert (
            client.proofs[parent["run_id"]]["children"][0]["deployment_execution_epoch"]
            == "nested-epoch"
        )
        assert len(client.registry.roots) == len(client.registry.commands) == 1

    asyncio.run(run())


def test_default_worker_wrapper_keeps_body_behavior_without_deployment_io(monkeypatch):
    async def run():
        from temporalio import activity

        runtime, client, _, _ = setup()
        runtime._deployment_admission_policy = runtime._deployment_admission_policy_pin = None
        runtime._deployment_admission_identity = None
        runtime.manifest = {"kernel": "temporal-1"}
        monkeypatch.setattr(activity, "info", lambda: None)

        @activity.defn(name="test.default")
        async def body(request: dict) -> dict:
            return {"output": request["input"]}

        result = await module().wrap_activities(runtime, client, [body])[0]({"input": "original"})
        assert result == {"output": "original"}
        assert client.updates == []

    asyncio.run(run())


def test_carrier_preserves_actual_registered_limits_request_digest(monkeypatch):
    """Adding SDK headers to a frozen limits intent must not change its response digest."""

    async def run():
        from temporalio import activity

        from ralf_agent import AgentSpec, FixedAgentLimits, ModelResponse, ToolRegistry
        from ralf_agent.temporal_activities import TemporalRuntime, registered_activities
        from ralf_agent.temporal_bindings import normalize_request
        from ralf_agent.temporal_deployment_execution_state import adopt, initialize, view
        from ralf_agent.temporal_state import TemporalRunState
        from ralf_agent.types import submission_request

        class Provider:
            identity = {"kind": "carrier-limits", "version": "1"}

            async def complete(self, messages, tools):
                return ModelResponse(output="answer")

        runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            limits=FixedAgentLimits(max_decisions=2),
            _deployment_admission_policy=POLICY,
        )
        client = Client()
        run_id = root_run_id(POLICY.deployment_id, SCOPE, "limits-command")
        request = normalize_request(
            submission_request(AgentSpec("limited", "answer"), "task"), runtime.manifest
        )
        root = client.registry.reserve(
            {
                "scope": SCOPE,
                "command_id": "limits-command",
                "kind": "submit",
                "target": run_id,
                "payload_digest": digest(request),
                "admission_policy": POLICY.identity,
                "namespace": NAMESPACE,
                "root_admission": {"version": 1, "manifest_digest": digest(runtime.manifest)},
            }
        )["root_admission"]
        state = TemporalRunState(
            run_id, SCOPE, "limits-command", request, runtime.manifest, "limits-epoch"
        )
        initialize(
            state,
            {"version": 1, "root": root, "lineage": []},
            namespace=NAMESPACE["name"],
            epoch="limits-epoch",
            original_epoch="limits-epoch",
            parent=None,
        )
        client.proofs[run_id] = view(state)
        client.descriptions[run_id] = SimpleNamespace(
            id=run_id,
            run_id="limits-epoch",
            namespace=NAMESPACE["name"],
            parent_id=None,
            parent_run_id=None,
        )
        info = SimpleNamespace(
            workflow_id=run_id, workflow_run_id="limits-epoch", workflow_namespace=NAMESPACE["name"]
        )
        value = {
            "scope": SCOPE,
            "run_id": run_id,
            "execution_epoch": "limits-epoch",
            "command_id": "limits-command",
            "request": request,
            "runtime_manifest": runtime.manifest,
            "deployment_admission": state.deployment_admission,
        }
        adopt(state, await module().admit(runtime, client, value, info))
        client.proofs[run_id] = view(state)
        monkeypatch.setattr(activity, "info", lambda: info)
        action, original = state.next_operation()
        assert action["kind"] == "agent_limits"
        frozen_digest = digest(original)
        from ralf_agent.temporal_limits_state import ACTIVITY as LIMITS_ACTIVITY

        limits_activity = next(
            fn
            for fn in registered_activities(runtime, client)
            if activity._Definition.from_callable(fn).name == LIMITS_ACTIVITY
        )
        wrapped = module().wrap_activities(runtime, client, [limits_activity])[0]
        result = await wrapped({"scope": SCOPE, "_deployment_activity_request": original})
        assert result["ok"] is True
        assert result["request_digest"] == frozen_digest
        assert digest(original) == frozen_digest
        state.accept_limits(action["id"], result)
        assert state.next_operation()[0]["kind"] == "model"

    asyncio.run(run())


@pytest.mark.parametrize(
    "category",
    [
        "model",
        "tool",
        "context",
        "evidence",
        "reconcile",
        "limits",
        "completion",
        "selection",
        "control",
        "session",
    ],
)
def test_carrier_hands_each_activity_unchanged_inner_bytes_after_history_guard(
    monkeypatch, category
):
    async def run():
        from temporalio import activity

        runtime, client, _, info = await admitted_setup()
        monkeypatch.setattr(activity, "info", lambda: info)
        original = {"frozen_intent": {"category": category, "input": "original"}}
        frozen = digest(original)

        @activity.defn(name="test.carrier." + category)
        async def body(request: dict) -> dict:
            assert digest(request) == frozen
            return {"request_digest": digest(request)}

        wrapped = module().wrap_activities(runtime, client, [body])[0]
        assert await wrapped({"scope": SCOPE, "_deployment_activity_request": original}) == {
            "request_digest": frozen
        }
        assert digest(original) == frozen

    asyncio.run(run())


@pytest.mark.parametrize(
    "changed",
    [
        "scope",
        "extra",
        "non_dict",
        "inner_scope",
        "inner_run",
        "inner_epoch",
        "inner_manifest",
        "inner_admission",
        "original_scope",
        "original_run",
        "original_epoch",
        "original_manifest",
        "original_admission",
    ],
)
def test_carrier_refuses_outer_schema_and_any_supplied_inner_original_identity(
    monkeypatch, changed
):
    async def run():
        from temporalio import activity

        runtime, client, value, info = await admitted_setup()
        monkeypatch.setattr(activity, "info", lambda: info)
        carrier = {
            "scope": copy.deepcopy(SCOPE),
            "_deployment_activity_request": {"original_request": {}},
        }
        if changed == "scope":
            carrier["scope"] = {"workspace": "foreign", "principal": "owner"}
        elif changed == "extra":
            carrier["exemption"] = True
        elif changed == "non_dict":
            carrier["_deployment_activity_request"] = None
        else:
            layer, field = changed.split("_", 1)
            target = carrier["_deployment_activity_request"]
            if layer == "original":
                target = target["original_request"]
            field = {
                "run": "run_id",
                "epoch": "execution_epoch",
                "manifest": "runtime_manifest",
                "admission": "deployment_admission",
            }.get(field, field)
            target[field] = (
                {} if field in {"runtime_manifest", "deployment_admission"} else "foreign"
            )
        calls = []

        @activity.defn(name="test.carrier.refusal")
        async def body(request: dict) -> dict:
            calls.append(request)
            return {"done": True}

        with pytest.raises(DefinitionMismatch):
            await module().wrap_activities(runtime, client, [body])[0](carrier)
        assert not calls

    asyncio.run(run())


def test_carrier_cannot_use_reserved_key_or_dropped_flags_to_bypass_adoption(monkeypatch):
    async def run():
        from temporalio import activity

        runtime, client, _, info = setup()
        monkeypatch.setattr(activity, "info", lambda: info)
        calls = []

        @activity.defn(name="test.carrier.no-exemption")
        async def body(request: dict) -> dict:
            calls.append(request)
            return {"done": True}

        for request in (
            {"scope": SCOPE, "_deployment_activity_request": {}},
            {"_deployment_activity_request": {}},
        ):
            with pytest.raises(DefinitionMismatch):
                await module().wrap_activities(runtime, client, [body])[0](request)
        assert not calls

    asyncio.run(run())


def test_carrier_preserves_nested_model_adoption_payload_and_detaches_caller(monkeypatch):
    async def run():
        from temporalio import activity

        runtime, client, _, info = await admitted_setup()
        monkeypatch.setattr(activity, "info", lambda: info)
        original = {
            "original_request": {
                "runtime_manifest": runtime.manifest,
                "scope": copy.deepcopy(SCOPE),
            },
            "response": {"received": True},
        }
        frozen = digest(original)

        @activity.defn(name="test.carrier.adoption")
        async def body(request: dict) -> dict:
            assert digest(request) == frozen
            request["response"]["received"] = False
            return {"done": True}

        assert await module().wrap_activities(runtime, client, [body])[0](
            {"scope": SCOPE, "_deployment_activity_request": original}
        ) == {"done": True}
        assert digest(original) == frozen

    asyncio.run(run())
