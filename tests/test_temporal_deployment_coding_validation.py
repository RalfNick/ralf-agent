"""Invocation-local compact SDK reads, never cached phase permission."""

import asyncio
import copy
import importlib
from types import SimpleNamespace

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.governance import DeploymentAdmissionPolicy
from relf_agent.temporal_bindings import request_release_digest
from relf_agent.temporal_deployment_admission import registry_id, root_run_id
from relf_agent.temporal_parent_state import PARENT_WORKFLOW_NAME, child_run_id
from relf_agent.temporal_state import COMMAND_REGISTRY_NAME, WORKFLOW_NAME
from relf_agent.types import digest


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


SCOPE = {"workspace": "validation", "principal": "owner"}
NS = {"name": "original", "id": "11111111-1111-1111-1111-111111111111"}
POLICY = DeploymentAdmissionPolicy("compact-validation", max_active_root_runs=2)
ROOT = root_run_id(POLICY.deployment_id, SCOPE, "accepted")


def identity(name):
    return ROOT if name == "root" else child_run_id(SCOPE, "command-" + name)


def module():
    name = "relf_agent.temporal_deployment_coding_validation"
    assert importlib.util.find_spec(name), "Missing selected3 compact native validator"
    return importlib.import_module(name)


def seal(value):
    value = copy.deepcopy(value)
    value.pop("proof_digest", None)
    return {**value, "proof_digest": digest(value)}


class Handle:
    def __init__(self, client, identity, epoch=None):
        self.client, self.identity, self.epoch = client, identity, epoch

    async def describe(self):
        self.client.calls.append(("describe", self.identity, self.epoch))
        return copy.deepcopy(self.client.descriptions[self.client.key(self.identity)])

    async def query(self, name, request):
        self.client.calls.append(("query", self.identity, self.epoch, copy.deepcopy(request)))
        assert name == "view"
        if request["kind"] == "deployment_coding_validation":
            if self.client.read_hook:
                await self.client.read_hook(self.identity)
            result = copy.deepcopy(self.client.compact[self.client.key(self.identity)])
            if self.client.reply_hook:
                result = self.client.reply_hook(self.client.key(self.identity), result)
            return result
        if request["kind"] == "deployment_configuration":
            return {
                "version": 3,
                "registry_id": self.identity,
                "policy": POLICY.identity,
                "namespace": NS,
            }
        if request["kind"] == "deployment_submission":
            return copy.deepcopy(self.client.record)
        if request["kind"] == "deployment_start":
            return copy.deepcopy(self.client.starts[self.client.key(self.identity)])
        raise AssertionError(request)

    async def execute_update(self, *args, **kwargs):
        raise AssertionError("Validation must never mutate History")


class Client:
    namespace = NS["name"]

    def __init__(self):
        self.calls, self.namespace_reads = [], 0
        self.namespace_uuid = NS["id"]
        self.descriptions, self.compact, self.starts = {}, {}, {}
        self.read_hook = self.reply_hook = None
        self.workflow_service = SimpleNamespace(describe_namespace=self.describe_namespace)

    def key(self, identity):
        return next(
            (key for key, value in self.descriptions.items() if value.id == identity), identity
        )

    def get_workflow_handle(self, identity, **options):
        return Handle(self, identity, options.get("run_id"))

    async def describe_namespace(self, request):
        self.namespace_reads += 1
        return SimpleNamespace(namespace_info=SimpleNamespace(id=self.namespace_uuid))


class Runtime:
    _deployment_admission_policy = _deployment_admission_policy_pin = POLICY
    _deployment_admission_identity = POLICY.identity

    def __init__(self, manifest):
        self.manifest = copy.deepcopy(manifest)
        self.changed = False

    def validate_release(self, manifest=None):
        if self.changed or manifest is not None and manifest != self.manifest:
            raise DefinitionMismatch("Changed original release")
        return copy.deepcopy(self.manifest)


def environment(monkeypatch, depth=0):
    """SDK proofs are injected; all compact DTOs and actual RPC checks are real."""
    from temporalio.client import WorkflowExecutionStatus

    from relf_agent import temporal_coding_composition_control as composition
    from relf_agent import temporal_deployment_execution as execution
    from relf_agent.temporal_deployment_control_projection import (
        edge_identity_digest,
        node_identity_digest,
        root_identity_digest,
        submission_identity_digest,
    )

    client = Client()
    from tests.test_temporal_deployment_coding_registry import coding_request

    manifest = copy.deepcopy(coding_request()["root_admission"]["submission"]["manifest"])
    if depth:
        from relf_agent.temporal_coding_composition_protocol import publish

        manifest = publish(
            manifest, SimpleNamespace(coding_execution=True, coding_composition=True)
        )
    manifest["deployment_admission_protocol"].update(
        policy=POLICY.identity, registry_id=registry_id(POLICY.deployment_id)
    )
    requests = {}
    proofs, coding, calls = {}, {}, {}
    root = {
        "version": 1,
        "registry_id": registry_id(POLICY.deployment_id),
        "scope": SCOPE,
        "command_id": "accepted",
        "run_id": ROOT,
        "request_digest": "",
        "manifest_digest": digest(manifest),
        "namespace": NS,
        "state": "held-unbound",
        "execution_epoch": None,
    }
    for index in range(depth + 1):
        name = "root" if index == 0 else f"child-{index}"
        request = {
            "definition": {"kind": "agent" if index == depth else "graph"},
            "input": None,
            "budget": 8,
        }
        if index:
            parent = "root" if index == 1 else f"child-{index - 1}"
            request["coding_parent"] = {
                "version": 1,
                "scope": SCOPE,
                "namespace": NS,
                "parent_run_id": identity(parent) if parent is not None else None,
                "parent_execution_epoch": parent + "-epoch",
                "parent_request_digest": digest(requests[parent]),
                "parent_release_digest": request_release_digest(requests[parent], manifest),
                "call_id": "intent-" + name,
                "command_id": "command-" + name,
                "member": "member",
                "planning_revision": 0,
                "child_run_id": identity(name),
                "child_projection_digest": digest(request),
                "cap": 8,
                "depth": index,
            }
        requests[name] = request
    root["request_digest"] = digest(requests["root"])
    root["proof_digest"] = digest(
        {k: v for k, v in root.items() if k not in {"state", "execution_epoch"}}
    )
    bound = {**root, "state": "held-bound", "execution_epoch": "root-epoch"}
    lineage = []
    for index, (name, request) in enumerate(requests.items()):
        if index:
            parent = "root" if index == 1 else f"child-{index - 1}"
            lineage.append(
                {
                    "parent_run_id": identity(parent) if parent is not None else None,
                    "parent_execution_epoch": parent + "-epoch",
                    "parent_request_digest": digest(requests[parent]),
                    "parent_manifest_digest": digest(manifest),
                    "call_id": "intent-" + name,
                    "child_run_id": identity(name),
                    "child_command_id": "command-" + name,
                    "child_request_digest": digest(request),
                }
            )
        admission = {"version": 1, "root": root, "lineage": copy.deepcopy(lineage)}
        receipt = seal(
            {
                "version": 1,
                "run_id": identity(name),
                "execution_epoch": name + "-epoch",
                "root": bound,
                "metadata_digest": digest(admission),
            }
        )
        proofs[name] = seal(
            {
                "version": 1,
                "scope": SCOPE,
                "run_id": identity(name),
                "command_id": "accepted" if not index else "command-" + name,
                "execution_epoch": name + "-epoch",
                "original_execution_epoch": name + "-epoch",
                "namespace": NS,
                "request": request,
                "request_digest": digest(request),
                "manifest": manifest,
                "manifest_digest": digest(manifest),
                "admission": admission,
                "admission_receipt": receipt,
                "children": [],
            }
        )
        coding[name] = seal(
            {
                "version": 1,
                "scope": SCOPE,
                "run_id": identity(name),
                "execution_epoch": name + "-epoch",
                "original_execution_epoch": name + "-epoch",
                "namespace": NS,
                "request": request,
                "request_digest": digest(request),
                "manifest": manifest,
                "release_digest": request_release_digest(request, manifest),
                "revision": 0,
                "state": "running",
                "physical_stopped": False,
                "action_stops": [],
            }
        )
        client.starts[name] = {
            "scope": SCOPE,
            "run_id": identity(name),
            "execution_epoch": name + "-epoch",
            "activity_timeout": 80,
            "task_queue": "original-queue",
            "request_digest": digest(request),
            "manifest_digest": digest(manifest),
        }
        parent = None if not index else "root" if index == 1 else f"child-{index - 1}"
        client.descriptions[name] = SimpleNamespace(
            id=identity(name),
            run_id=name + "-epoch",
            raw_info=SimpleNamespace(first_run_id=name + "-epoch"),
            namespace=NS["name"],
            status=WorkflowExecutionStatus.RUNNING,
            workflow_type=WORKFLOW_NAME if index == depth else PARENT_WORKFLOW_NAME,
            task_queue="original-queue",
            parent_id=None if parent is None else identity(parent),
            parent_run_id=None if parent is None else parent + "-epoch",
        )
    for index in range(depth):
        parent, child = ("root" if index == 0 else f"child-{index}"), f"child-{index + 1}"
        call = {
            "id": "intent-" + child,
            "call_id": "semantic-call",
            "member": "member",
            "input": None,
            "command_id": "command-" + child,
            "run_id": identity(child),
            "request": requests[child],
            "child_request_digest": digest(requests[child]),
            "cap": 8,
            "depth": index + 1,
            "planning_revision": 0,
            "deployment_admission": proofs[child]["admission"],
            "deployment_execution_epoch": child + "-epoch",
            "dispatch_started": True,
            "child_execution": {
                "namespace": NS,
                "execution_epoch": child + "-epoch",
                "original_execution_epoch": child + "-epoch",
            },
        }
        calls[parent] = call
        proofs[parent]["children"] = [call]
        proofs[parent] = seal(proofs[parent])
    for name in requests:
        call = calls.get(name)
        edge = (
            None
            if call is None
            else {
                "call_id": call["id"],
                "child_run_id": call["run_id"],
                "child_execution_epoch": call["deployment_execution_epoch"],
                "identity_digest": edge_identity_digest(call),
                "dispatch_started": True,
                "owned": True,
            }
        )
        client.compact[name] = seal(
            {
                "version": 1,
                "scope": SCOPE,
                "namespace": NS,
                "run_id": identity(name),
                "execution_epoch": name + "-epoch",
                "original_execution_epoch": name + "-epoch",
                "identity_digest": node_identity_digest(
                    proofs[name], client.starts[name], coding[name] if depth else None
                ),
                "revision": 0,
                "state": "running",
                "stop_requested": False,
                "sealed": False,
                "edge": edge,
            }
        )
    rid = root["registry_id"]
    envelope = {
        "version": 1,
        "request": requests["root"],
        "manifest": manifest,
        "activity_timeout": 80,
        "task_queue": "original-queue",
    }
    client.record = {
        "reservation": {
            "command_id": "accepted",
            "target": ROOT,
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
            "root_admission": root,
        },
        "submission": envelope,
        "run_receipt": None,
        "execution_epoch": "root-epoch",
    }
    client.descriptions[rid] = SimpleNamespace(
        id=rid,
        run_id="registry-epoch",
        raw_info=SimpleNamespace(first_run_id="registry-epoch"),
        namespace=NS["name"],
        status=WorkflowExecutionStatus.RUNNING,
        workflow_type=COMMAND_REGISTRY_NAME,
        task_queue="registry-first-queue",
        parent_id=None,
        parent_run_id=None,
    )
    client.compact[rid] = seal(
        {
            "version": 1,
            "registry_id": rid,
            "registry_execution_epoch": "registry-epoch",
            "configuration_version": 3,
            "policy": POLICY.identity,
            "scope": SCOPE,
            "namespace": NS,
            "root_identity_digest": root_identity_digest(bound),
            "submission_digest": submission_identity_digest(envelope),
            "held": True,
            "retired": False,
            "close_requested": False,
            "admitted": True,
        }
    )
    bootstrap_reads = []

    async def proof(*args, **kwargs):
        name = client.key(args[4])
        bootstrap_reads.append(name)
        return copy.deepcopy(proofs[name])

    async def ancestry(*args, **kwargs):
        assert kwargs["read_only"] is True
        return copy.deepcopy(proofs["root"])

    async def coding_proof(*args, **kwargs):
        return copy.deepcopy(coding[client.key(args[2])])

    async def coding_ancestry(*args):
        return [
            (
                copy.deepcopy(coding["root" if i == 0 else f"child-{i}"]),
                copy.deepcopy(calls["root" if i == 0 else f"child-{i}"]),
            )
            for i in reversed(range(depth))
        ]

    monkeypatch.setattr(execution, "_proof", proof)
    monkeypatch.setattr(execution, "_ancestry", ancestry)
    monkeypatch.setattr(composition, "_proof", coding_proof)
    monkeypatch.setattr(composition, "_ancestry", coding_ancestry)
    leaf = "root" if not depth else f"child-{depth}"
    request = {
        "scope": SCOPE,
        "run_id": identity(leaf),
        "execution_epoch": leaf + "-epoch",
        "runtime_manifest": manifest,
        "coding_request": {"request_digest": digest("native")},
    }
    info = SimpleNamespace(
        workflow_id=identity(leaf),
        workflow_run_id=leaf + "-epoch",
        workflow_namespace=NS["name"],
        activity_id="original-tool",
        attempt=1,
    )
    return Runtime(manifest), client, request, info, bootstrap_reads


@pytest.mark.parametrize("depth", [0, 1, 2])
def test_full_bootstrap_once_then_only_fresh_compact_reads(monkeypatch, depth):
    cls = module().CodingValidation
    runtime, client, request, info, reads = environment(monkeypatch, depth)
    validator = cls(runtime, client, request, info)
    assert not client.calls

    async def scenario():
        assert await validator.validate() is None
        assert await validator.permission() is True
        before = len(reads)
        client.calls.clear()
        assert await validator.validate() is None
        assert len(reads) == before
        queries = [c for c in client.calls if c[0] == "query"]
        assert len(queries) == depth + 2
        assert all(c[3]["kind"] == "deployment_coding_validation" for c in queries)
        assert all("request" not in c[3] and "manifest" not in c[3] for c in queries)
        assert len([c for c in client.calls if c[0] == "describe"]) == depth + 2

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["close", "retire", "stop", "seal", "cancel"])
def test_cleanup_validation_survives_close_but_permission_is_fresh(monkeypatch, change):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = cls(runtime, client, request, info)

    async def scenario():
        assert await validator.permission()
        rid = registry_id(POLICY.deployment_id)
        if change in {"close", "retire"}:
            v = client.compact[rid]
            v.update(admitted=False)
            if change == "close":
                v["close_requested"] = True
            else:
                v.update(held=False, retired=True)
            client.compact[rid] = seal(v)
        else:
            v = client.compact["root"]
            v[{"stop": "stop_requested", "seal": "sealed", "cancel": "state"}[change]] = (
                "cancelling" if change == "cancel" else True
            )
            client.compact["root"] = seal(v)
        assert await validator.validate() is None
        assert await validator.permission() is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "intent",
    [
        None,
        "cancel",
        "stop_needed",
        "stop_active",
        "cancelling",
        "cancelled",
        "failed",
        "succeeded",
        "seal",
    ],
)
def test_real_native_grants_keep_fresh_permission_until_actual_stop(monkeypatch, intent):
    from relf_agent import temporal_deployment_execution_state as deployment
    from relf_agent.temporal_deployment_control_projection import node
    from tests.test_temporal_deployment_control_projection import granted_native_phases

    runtime, client, request, info, _ = environment(monkeypatch)
    envelope = client.record["submission"]
    root = copy.deepcopy(client.record["reservation"]["root_admission"])
    metadata = {"version": 1, "root": root, "lineage": []}
    state = SimpleNamespace(
        scope=SCOPE,
        run_id=ROOT,
        epoch="root-epoch",
        request=envelope["request"],
        manifest=runtime.manifest,
        receipts={"accepted": {"kind": "submit"}},
        release_digest=request_release_digest(envelope["request"], runtime.manifest),
        state="running",
        revision=0,
        actions=[],
        deployment_activity_timeout=80,
        deployment_task_queue="original-queue",
    )
    deployment.initialize(
        state,
        metadata,
        namespace=NS["name"],
        epoch=state.epoch,
        original_epoch=state.epoch,
        parent=None,
    )
    deployment.adopt(
        state,
        seal(
            {
                "version": 1,
                "run_id": ROOT,
                "execution_epoch": state.epoch,
                "root": {**root, "state": "held-bound", "execution_epoch": state.epoch},
                "metadata_digest": digest(metadata),
            }
        ),
    )

    def fresh():
        return node(
            state,
            {
                "kind": "deployment_coding_validation",
                "scope": SCOPE,
                "run_id": ROOT,
                "execution_epoch": state.epoch,
                "child_call_id": None,
            },
        )

    assert fresh() == client.compact["root"]
    validator = module().CodingValidation(runtime, client, request, info)

    async def scenario():
        assert await validator.permission() is True
        for native in granted_native_phases():
            assert native["pending_stop"] is True
            state.actions = [{"delegated_execution": native}]
            client.compact["root"] = fresh()
            assert await validator.permission() is True
        if intent is None:
            return
        if intent == "cancel":
            native["cancel"] = {"code": "original_stop_requested"}
        elif intent in {"stop_needed", "stop_active"}:
            native[intent] = True
        elif intent == "seal":
            state.deployment_seal = {"original": "seal"}
        else:
            state.state = intent
        client.compact["root"] = fresh()
        assert await validator.permission() is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        "reset",
        "first",
        "terminated",
        "parent",
        "queue",
        "type",
        "namespace",
        "identity",
        "edge",
        "registry_epoch",
        "registry_policy",
        "registry_absent",
    ],
)
def test_fresh_reads_reject_original_authority_replacement(monkeypatch, change):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = cls(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        rid = registry_id(POLICY.deployment_id)
        desc = client.descriptions[client.key(request["run_id"])]
        if change == "reset":
            desc.run_id = "new-epoch"
        elif change == "first":
            desc.raw_info.first_run_id = "old-epoch"
        elif change == "terminated":
            from temporalio.client import WorkflowExecutionStatus

            desc.status = WorkflowExecutionStatus.TERMINATED
        elif change == "parent":
            desc.parent_run_id = "foreign-parent-epoch"
        elif change == "queue":
            desc.task_queue = "alias-queue"
        elif change == "type":
            desc.workflow_type = COMMAND_REGISTRY_NAME
        elif change == "namespace":
            client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        else:
            node = client.compact["root" if change in {"identity", "edge"} else rid]
            if change == "identity":
                node["identity_digest"] = digest("forged")
            elif change == "edge":
                node["edge"]["child_execution_epoch"] = "foreign"
            elif change == "registry_epoch":
                node["registry_execution_epoch"] = "new-registry"
            elif change == "registry_policy":
                node["policy"] = {**POLICY.identity, "deployment_id": "other"}
            elif change == "registry_absent":
                node.update(held=False, retired=False, admitted=False)
            client.compact["root" if change in {"identity", "edge"} else rid] = seal(node)
        with pytest.raises(DefinitionMismatch):
            await validator.validate()

    asyncio.run(scenario())


def test_parallel_failure_drains_other_original_sdk_reads(monkeypatch):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch, 1)
    validator = cls(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        entered, finish = asyncio.Event(), asyncio.Event()
        failure = RuntimeError("original SDK query failed")

        async def read(identity):
            if identity == request["run_id"]:
                raise failure
            if identity == ROOT:
                entered.set()
                await finish.wait()

        client.read_hook = read
        task = asyncio.create_task(validator.validate())
        await entered.wait()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(RuntimeError) as exc:
            await task
        assert exc.value is failure

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["runtime", "attempt", "activity", "request"])
def test_callback_resources_and_original_claim_remain_fixed(monkeypatch, change):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch)
    validator = cls(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        if change == "runtime":
            runtime.changed = True
        elif change == "attempt":
            info.attempt = 2
        elif change == "activity":
            info.activity_id = "other-tool"
        else:
            request["run_id"] = "caller-mutated"
        if change == "request":
            # Caller ownership ended at construction; its later mutation is irrelevant.
            assert await validator.validate() is None
        else:
            with pytest.raises(DefinitionMismatch):
                await validator.validate()

    asyncio.run(scenario())


@pytest.mark.parametrize("state", ["succeeded", "invalid_state"])
def test_terminal_or_invalid_node_never_permits_new_native_grant(monkeypatch, state):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch)
    validator = cls(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        value = client.compact["root"]
        value["state"] = state
        client.compact["root"] = seal(value)
        if state == "invalid_state":
            with pytest.raises(DefinitionMismatch):
                await validator.permission()
        else:
            assert await validator.validate() is None
            assert await validator.permission() is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "namespace",
        "version_bool",
        "revision_bool",
        "full_payload",
        "proof_digest",
        "registry_reset",
        "registry_terminated",
        "runtime_port",
        "helper_port",
    ],
)
def test_compact_wire_and_helper_source_checks_remain_strict(monkeypatch, change):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch)
    validator = cls(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        value = copy.deepcopy(client.compact["root"])
        rid = registry_id(POLICY.deployment_id)
        if change == "scope":
            value["scope"] = {**SCOPE, "principal": "foreign"}
        elif change == "namespace":
            value["namespace"] = {**NS, "id": "22222222-2222-2222-2222-222222222222"}
        elif change == "version_bool":
            value["version"] = True
        elif change == "revision_bool":
            value["revision"] = True
        elif change == "full_payload":
            value["request"] = {"definition": "unexpected full body"}
        elif change == "registry_reset":
            client.descriptions[rid].run_id = "replacement"
        elif change == "registry_terminated":
            from temporalio.client import WorkflowExecutionStatus

            client.descriptions[rid].status = WorkflowExecutionStatus.TERMINATED
        elif change == "runtime_port":
            monkeypatch.setattr(
                runtime, "validate_release", lambda manifest=None: copy.deepcopy(runtime.manifest)
            )
        elif change == "helper_port":
            from relf_agent import temporal_deployment_control_projection as projection

            monkeypatch.setattr(
                projection, "node_identity_digest", lambda *args: digest("new code")
            )
        client.compact["root"] = seal(value)
        if change == "proof_digest":
            client.compact["root"]["proof_digest"] = digest("forged")
        with pytest.raises(DefinitionMismatch):
            await validator.validate()

    asyncio.run(scenario())


def test_namespace_change_while_compact_reads_are_pending_refuses(monkeypatch):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch)
    validator = cls(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        entered, finish = asyncio.Event(), asyncio.Event()

        async def held(identity):
            if identity == ROOT:
                entered.set()
                await finish.wait()

        client.read_hook = held
        task = asyncio.create_task(validator.permission())
        await entered.wait()
        client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        finish.set()
        with pytest.raises(DefinitionMismatch):
            await task

    asyncio.run(scenario())


def test_cancellation_waits_for_all_original_read_finalizers(monkeypatch):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch)
    validator = cls(runtime, client, request, info)

    async def scenario():
        await validator.validate()
        entered, cleanup, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def held(identity):
            if identity == ROOT:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleanup.set()
                    await finish.wait()

        client.read_hook = held
        task = asyncio.create_task(validator.validate())
        await entered.wait()
        task.cancel()
        await cleanup.wait()
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


@pytest.mark.parametrize("depth", [0, 1])
def test_original_worker_can_bootstrap_before_facade_records_start_receipt(monkeypatch, depth):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch, depth)
    # Admission has already bound the original root and SDK epoch; only the
    # Facade's original start acknowledgement has not yet reached Registry.
    client.record.update(execution_epoch=None, run_receipt=None)
    validator = cls(runtime, client, request, info)

    async def scenario():
        assert await validator.validate() is None
        assert await validator.permission() is True

    asyncio.run(scenario())


@pytest.mark.parametrize("epoch,receipt", [(None, {}), ("foreign-epoch", None)])
def test_pre_record_window_never_accepts_a_receipt_without_original_epoch(
    monkeypatch, epoch, receipt
):
    cls = module().CodingValidation
    runtime, client, request, info, _ = environment(monkeypatch)
    client.record.update(execution_epoch=epoch, run_receipt=receipt)
    validator = cls(runtime, client, request, info)

    async def scenario():
        with pytest.raises(DefinitionMismatch):
            await validator.validate()

    asyncio.run(scenario())
