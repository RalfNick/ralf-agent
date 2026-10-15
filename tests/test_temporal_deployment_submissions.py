"""Public submission transport retains original History envelopes under SDK uncertainty."""

import asyncio
import copy
import importlib
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, Scope
from ralf_agent.errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.temporal_deployment_admission import DeploymentAdmissionState
from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME
from ralf_agent.types import digest, submission_request


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


POLICY = DeploymentAdmissionPolicy("public-transport", max_active_root_runs=1)
SCOPE = Scope("public", "owner")
NAMESPACE = {"name": "original", "id": "11111111-1111-1111-1111-111111111111"}


def module():
    name = "ralf_agent.temporal_deployment_submissions"
    assert importlib.util.find_spec(name), "Missing original first-acceptance transport"
    return importlib.import_module(name)


def sealed(value):
    value = copy.deepcopy(value)
    value.pop("proof_digest", None)
    return {**value, "proof_digest": digest(value)}


class Registry:
    """Only the SDK is simulated; original public Registry state stays real."""

    def __init__(self, version=2):
        from ralf_agent.temporal_deployment_registry import PublicDeploymentAdmissionState

        if version == 3:
            from ralf_agent.temporal_deployment_coding_registry import (
                CodingDeploymentAdmissionState,
            )

            state_type = CodingDeploymentAdmissionState
        else:
            state_type = (
                PublicDeploymentAdmissionState if version == 2 else DeploymentAdmissionState
            )
        self.state = state_type(POLICY.identity, NAMESPACE, capacity=4096)
        self.version = version

    @property
    def submissions(self):
        return {
            r["reservation"]["command_id"]: r
            for r in getattr(self.state, "submissions", {}).values()
        }

    def configuration(self, value):
        self.state._authority(value)
        return {
            "version": self.version,
            "registry_id": self.state.registry_id,
            "policy": POLICY.identity,
            "namespace": NAMESPACE,
        }

    def lookup(self, value):
        return self.state.deployment_submission(value)

    def reserve(self, value):
        return self.state.reserve(value)

    def record(self, value):
        return self.state.record_deployment_submission(value)


class Handle:
    def __init__(self, client, identity, epoch):
        self.client, self.id, self.epoch = client, identity, epoch

    async def describe(self):
        if self.id == self.client.registry_id and self.client.registry is not None:
            return SimpleNamespace(
                id=self.id,
                run_id=getattr(self.client, "registry_epoch", "registry-epoch"),
                raw_info=SimpleNamespace(first_run_id="registry-epoch"),
                namespace=self.client.namespace,
                workflow_type=COMMAND_REGISTRY_NAME,
                task_queue=self.client.registry_queue,
                parent_id=None,
                parent_run_id=None,
            )
        if self.id not in self.client.runs:
            from temporalio.service import RPCError, RPCStatusCode

            raise RPCError("missing", RPCStatusCode.NOT_FOUND, b"")
        run = self.client.runs[self.id]
        if self.epoch is not None and self.epoch != run["epoch"]:
            raise DefinitionMismatch("Changed SDK epoch")
        return SimpleNamespace(
            id=self.id,
            run_id=run["epoch"],
            raw_info=SimpleNamespace(first_run_id=run.get("original_epoch", run["epoch"])),
            namespace=self.client.namespace,
            workflow_type=run["workflow"],
            task_queue=run["queue"],
            parent_id=run.get("parent_id"),
            parent_run_id=run.get("parent_run_id"),
        )

    async def query(self, name, value):
        assert name == "view"
        if self.id == self.client.registry_id:
            if value["kind"] == "deployment_control":
                return self.client.registry.state.deployment_control(value)
            if value["kind"] == "deployment_configuration":
                return self.client.registry.configuration(value)
            if value["kind"] == "deployment_submission":
                return self.client.registry.lookup(value)
            return self.client.registry.state.deployment_admission(value)
        await self.describe()
        run = self.client.runs[self.id]
        if value["scope"] != run["accepted"]["scope"]:
            return {"error": "authorization_denied"}
        if value["kind"] == "submission":
            if (
                value["request"] != run["accepted"]["request"]
                or value["command_id"] != run["accepted"]["command_id"]
            ):
                return {"error": "idempotency_conflict"}
            return copy.deepcopy(run["receipt"])
        accepted = run["accepted"]
        if value["kind"] == "deployment_start":
            return {
                "scope": accepted["scope"],
                "run_id": self.id,
                "execution_epoch": run["epoch"],
                "activity_timeout": accepted["activity_timeout"],
                "task_queue": run["queue"],
                "request_digest": digest(accepted["request"]),
                "manifest_digest": digest(accepted["manifest"]),
            }
        assert value["kind"] == "deployment_admission"
        proof = {
            "version": 1,
            "scope": accepted["scope"],
            "run_id": self.id,
            "command_id": accepted["command_id"],
            "execution_epoch": run["epoch"],
            "original_execution_epoch": run.get("original_epoch", run["epoch"]),
            "namespace": NAMESPACE,
            "request": accepted["request"],
            "request_digest": digest(accepted["request"]),
            "manifest": accepted["manifest"],
            "manifest_digest": digest(accepted["manifest"]),
            "admission": accepted["deployment_admission"],
            "admission_receipt": None,
            "children": [],
        }
        return sealed(proof)

    async def execute_update(self, name, value, **options):
        assert self.id == self.client.registry_id
        self.client.updates.append(name)
        if name == "reserve":
            result = self.client.registry.reserve(value)
            if self.client.lose_reserve:
                self.client.lose_reserve = False
                raise TimeoutError("Lost reserve reply after actual acceptance")
            return result
        assert name == "record_deployment_submission"
        return self.client.registry.record(value)


class Client:
    namespace = NAMESPACE["name"]
    service_client = SimpleNamespace(config=SimpleNamespace(target_host="fixture:7233"))

    def __init__(self):
        self.registry_id = DeploymentAdmissionState(
            POLICY.identity, NAMESPACE, capacity=4096
        ).registry_id
        self.registry, self.registry_queue, self.runs = None, None, {}
        self.starts, self.updates = [], []
        self.lose_reserve = self.lose_start = False
        self.namespace_uuid = NAMESPACE["id"]
        self.workflow_service = SimpleNamespace(describe_namespace=self.describe_namespace)

    async def describe_namespace(self, value):
        assert value.namespace == self.namespace
        return SimpleNamespace(namespace_info=SimpleNamespace(id=self.namespace_uuid))

    def get_workflow_handle(self, identity, **options):
        return Handle(self, identity, options.get("run_id"))

    async def start_workflow(self, workflow, accepted, **options):
        from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError

        assert options["id_reuse_policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE
        assert options["id_conflict_policy"] == WorkflowIDConflictPolicy.FAIL
        if workflow == COMMAND_REGISTRY_NAME:
            if self.registry is not None:
                raise WorkflowAlreadyStartedError(options["id"], workflow)
            assert accepted["deployment_admission"]["version"] in (2, 3)
            self.registry = Registry(accepted["deployment_admission"]["version"])
            self.registry_queue = options["task_queue"]
        else:
            if options["id"] in self.runs:
                raise WorkflowAlreadyStartedError(options["id"], workflow)
            assert options["retry_policy"] is None
            receipt = {
                "command_id": accepted["command_id"],
                "run_id": options["id"],
                "kind": "submit",
                "record_state": "durably_recorded",
                "apply_state": "applied",
                "outcome": {"state_revision": 0},
            }
            self.runs[options["id"]] = {
                "accepted": copy.deepcopy(accepted),
                "queue": options["task_queue"],
                "workflow": workflow,
                "epoch": "root-epoch",
                "receipt": receipt,
            }
        self.starts.append((workflow, copy.deepcopy(accepted), copy.deepcopy(options)))
        if workflow != COMMAND_REGISTRY_NAME and self.lose_start:
            self.lose_start = False
            raise TimeoutError("Lost start response after actual acceptance")
        return self.get_workflow_handle(options["id"])


class Engine:
    def __init__(self, client=None):
        self.client = client or Client()
        self.scope, self.namespace = SCOPE, NAMESPACE["name"]
        self.task_queue, self.activity_timeout, self._closed = "first-queue", 17, False
        self._registry = None
        from ralf_agent.temporal_deployment_protocol import PUBLIC_SOURCE_FILES

        self.release = {
            "kernel": "temporal-1",
            "providers": {"default": {"kind": "fixture", "version": "1"}},
            "tools": {},
            "harness": {},
            "context_builder": {},
            "tool_executor": {},
            "policy": {},
            "effect_journal": None,
            "deployment_admission_protocol": {
                "version": 2,
                "policy": POLICY.identity,
                "registry_id": self.client.registry_id,
                "implementation": {name: "a" * 64 for name in PUBLIC_SOURCE_FILES},
            },
        }


def spec():
    return AgentSpec("answer", "Answer")


@pytest.mark.parametrize(
    "publication,registry_version,allowed",
    [(2, 2, True), (2, 3, True), (3, 3, True), (3, 2, False)],
)
def test_public_registry_version_negotiation_is_positive_and_shares_address(
    publication, registry_version, allowed
):
    async def run():
        api, client = module(), Client()
        client.registry, client.registry_queue = Registry(registry_version), "first-queue"
        engine = Engine(client)
        engine.release["deployment_admission_protocol"]["version"] = publication
        if publication == 3:
            engine.release["coding_execution_protocol"] = {"version": 6}
        if allowed:
            policy = api._policy(engine)
            handle = await api._registry(engine, client, asdict(SCOPE), NAMESPACE, policy)
            assert handle.id == client.registry_id
        else:
            with pytest.raises(DefinitionMismatch):
                await api._registry(engine, client, asdict(SCOPE), NAMESPACE, api._policy(engine))
        assert not client.updates and not client.runs

    asyncio.run(run())


def test_public_diagnostics_are_read_only_and_never_create_missing_registry():
    from temporalio.service import RPCError, RPCStatusCode

    async def run():
        engine = Engine()
        with pytest.raises(RPCError) as error:
            await module().diagnostics(engine)
        assert error.value.status == RPCStatusCode.NOT_FOUND
        assert engine.client.starts == [] and engine.client.registry is None

    asyncio.run(run())


def test_mixed_host_can_start_registry_three_from_ordinary_two_first():
    async def run():
        engine = Engine()
        engine._deployment_registry_protocol = 3
        await module().submit(engine, spec(), "task", command_id="ordinary-first")
        assert engine.client.starts[0][1]["deployment_admission"]["version"] == 3
        assert engine.client.registry.version == 3
        assert len(engine.client.registry.state.roots) == 1

    asyncio.run(run())


@pytest.mark.parametrize("lost", ["reserve", "start"])
def test_bound_coding_first_acceptance_recovers_original_runner_after_alias_move(lost):
    from ralf_agent.binding_definitions import AgentDefinition
    from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection

    from .test_temporal_deployment_coding_registry import coding_request

    async def run():
        engine = Engine()
        engine.client.registry, engine.client.registry_queue = Registry(3), "first-queue"
        release = copy.deepcopy(coding_request()["root_admission"]["submission"]["manifest"])
        release["deployment_admission_protocol"].update(
            policy=POLICY.identity, registry_id=engine.client.registry_id
        )
        for record in release["binding_catalog"]["records"].values():
            record["scope"] = asdict(SCOPE)
        engine.release = release
        bound = AgentDefinition(
            AgentSpec("answer", "Answer", tools=("coding",)),
            AgentBindingDescriptor(runner=BindingSelection.ref("native", "1")),
        )
        setattr(engine.client, "lose_" + lost, True)
        with pytest.raises(TimeoutError):
            await module().submit(engine, bound, {"items": (1, 2)}, command_id="coding-original")
        engine.release = {
            **release,
            "providers": {"moved": {"kind": "other"}},
            "binding_catalog": {"records": {}},
        }
        engine.task_queue, engine.activity_timeout = "moved-queue", 99
        handle = await module().submit(
            engine, bound, {"items": (1, 2)}, command_id="coding-original"
        )
        accepted = engine.client.runs[handle.run_id]["accepted"]
        assert accepted["manifest"] == release
        assert accepted["request"]["agent_bindings"]["agent"]["runner"]["component_id"] == "native"
        assert engine.client.runs[handle.run_id]["queue"] == "first-queue"
        assert len(engine.client.registry.state.roots) == 1
        assert len(engine.client.registry.state.coding_index) == 1

    asyncio.run(run())


class RecoveryHandle(Handle):
    async def query(self, name, value):
        if self.id == self.client.registry_id and value["kind"] == "deployment_retirement":
            return self.client.registry.state.deployment_retirement(
                {k: v for k, v in value.items() if k != "kind"}
            )
        if self.id != self.client.registry_id and value["kind"] == "deployment_closure":
            await self.describe()
            return copy.deepcopy(self.client.closure)
        return await super().query(name, value)

    async def execute_update(self, name, value, **options):
        if self.id != self.client.registry_id:
            assert name == "deployment_seal", "Recovery must never send a business command"
            assert self.epoch == "root-epoch"
            assert value == {
                "scope": asdict(SCOPE),
                "children": self.client.closure["seal"]["children"],
            }
            self.client.wakes.append((self.id, self.epoch, copy.deepcopy(value), options["id"]))
            if self.client.drift_on_wake:
                self.client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
            certificate = copy.deepcopy(self.client.closure["seal"])
            if self.client.change_seal_reply:
                certificate = sealed({**certificate, "closure_digest": "b" * 64})
            return certificate
        return await super().execute_update(name, value, **options)


class RecoveryClient(Client):
    def __init__(self):
        super().__init__()
        self.wakes = []
        self.drift_on_wake = self.change_seal_reply = False

    def get_workflow_handle(self, identity, **options):
        return RecoveryHandle(self, identity, options.get("run_id"))


async def sealed_root():
    engine = Engine(RecoveryClient())
    handle = await module().submit(engine, spec(), "task", command_id="sealed-root")
    proof = await engine.client.get_workflow_handle(handle.run_id, run_id="root-epoch").query(
        "view", {"scope": asdict(SCOPE), "kind": "deployment_admission"}
    )
    certificate = sealed(
        {
            "version": 1,
            **{
                name: proof[name]
                for name in (
                    "scope",
                    "run_id",
                    "command_id",
                    "namespace",
                    "execution_epoch",
                    "original_execution_epoch",
                    "request_digest",
                    "manifest_digest",
                )
            },
            "admission_digest": digest(proof["admission"]),
            "receipt_digest": digest(proof["admission_receipt"]),
            "terminal_state": "succeeded",
            "closure_digest": "a" * 64,
            "children": [],
        }
    )
    engine.client.closure = {
        "version": 1,
        "deployment": proof,
        "ready": True,
        "reasons": [],
        "calls": {},
        "seal": certificate,
    }
    return engine, handle, copy.deepcopy(engine.client.closure)


def test_sealed_held_root_recovery_wakes_only_original_history_after_alias_move():
    async def run():
        engine, handle, closure = await sealed_root()
        engine.release = {**engine.release, "providers": {"different": {"kind": "other"}}}
        engine.task_queue, engine.activity_timeout = "changed-queue", 99
        registry_updates = list(engine.client.updates)
        for _ in range(2):
            assert (
                await module().recover_retirement(engine, handle.run_id, closure) == closure["seal"]
            )
        assert engine.client.updates == registry_updates
        assert len(engine.client.wakes) == 2
        assert engine.client.wakes[0][3] != engine.client.wakes[1][3]
        assert engine.client.closure == closure
        assert len(engine.client.runs) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "changed", ["scope", "epoch", "seal", "request", "namespace", "reply", "after-await"]
)
def test_sealed_retirement_recovery_refuses_changed_original_proof(changed):
    async def run():
        engine, handle, closure = await sealed_root()
        if changed == "scope":
            engine.scope = Scope("public", "other")
        elif changed == "epoch":
            engine.client.runs[handle.run_id]["epoch"] = "replacement-epoch"
        elif changed == "seal":
            closure["seal"] = sealed({**closure["seal"], "closure_digest": "b" * 64})
        elif changed == "request":
            closure["deployment"]["request"]["input"] = "forged"
        elif changed == "namespace":
            engine.client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        elif changed == "reply":
            engine.client.change_seal_reply = True
        else:
            engine.client.drift_on_wake = True
        with pytest.raises(DefinitionMismatch):
            await module().recover_retirement(engine, handle.run_id, closure)
        assert len(engine.client.wakes) == (1 if changed in {"reply", "after-await"} else 0)

    asyncio.run(run())


def test_retired_root_recovery_is_read_only_without_business_poller():
    async def run():
        engine, handle, closure = await sealed_root()
        state = engine.client.registry.state
        root = next(iter(state.roots.values()))
        payload = {
            "scope": asdict(SCOPE),
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
                    "execution_epoch",
                )
            },
            "certificate": closure["seal"],
        }
        state.commit_deployment_release(payload, {"root": root, "certificate": closure["seal"]})
        starts, updates = list(engine.client.starts), list(engine.client.updates)
        engine.client.runs.clear()
        assert await module().recover_retirement(engine, handle.run_id, closure) == closure["seal"]
        assert engine.client.starts == starts
        assert engine.client.updates == updates
        assert engine.client.wakes == []

    asyncio.run(run())


def test_public_fresh_submission_records_actual_sdk_receipt_and_original_envelope():
    async def run():
        api = module()
        engine = Engine()
        handle = await api.submit(
            engine, spec(), "task", command_id="original", budget=8, session_id=None
        )
        assert handle.receipt.apply_state == "applied"
        record = engine.client.registry.submissions["original"]
        assert record["submission"]["activity_timeout"] == 17
        assert record["submission"]["task_queue"] == "first-queue"
        assert record["execution_epoch"] == "root-epoch"
        assert record["run_receipt"] == asdict(handle.receipt)
        assert len(engine.client.registry.state.roots) == 1

    asyncio.run(run())


@pytest.mark.parametrize("with_tools", [False, True])
def test_public_request_matches_original_registry_after_default_sdk_json_roundtrip(with_tools):
    from temporalio.converter import DataConverter

    from ralf_agent.temporal_bindings import normalize_request
    from ralf_agent.tools import ToolRegistry, ToolSpec

    async def wire(value):
        payloads = await DataConverter.default.encode([value])
        return (await DataConverter.default.decode(payloads))[0]

    class WireHandle(Handle):
        async def query(self, name, value):
            return await wire(await super().query(name, await wire(value)))

        async def execute_update(self, name, value, **options):
            # Actual public Registry state accepts the decoded SDK input before
            # its Update response crosses the JSON payload boundary.
            result = await super().execute_update(name, await wire(value), **options)
            return await wire(result)

    class WireClient(Client):
        def get_workflow_handle(self, identity, **options):
            return WireHandle(self, identity, options.get("run_id"))

        async def start_workflow(self, workflow, accepted, **options):
            return await super().start_workflow(workflow, await wire(accepted), **options)

    async def read(arguments, context):
        return arguments

    async def run():
        engine = Engine(WireClient())
        definition = AgentSpec("answer", "Answer", tools=("read",) if with_tools else ())
        if with_tools:
            tools = ToolRegistry()
            tools.register(ToolSpec("read", "Read", {"type": "object"}), read)
            engine.release["tools"] = tools.manifests(definition.tools)
        input_value = {"items": (1, {"pair": ("a", "b")})}
        logical = normalize_request(submission_request(definition, input_value, budget=8), None)
        decoded = await wire(logical)
        assert logical != decoded
        assert digest(logical) == digest(decoded)
        handle = await module().submit(
            engine, definition, input_value, command_id="sdk-wire", budget=8
        )
        record = engine.client.registry.submissions["sdk-wire"]
        assert record["submission"]["request"] == decoded
        assert record["reservation"]["root_admission"]["request_digest"] == digest(logical)
        assert record["run_receipt"] == asdict(handle.receipt)
        assert record["execution_epoch"] == "root-epoch"
        assert (
            await module().submit(engine, definition, input_value, command_id="sdk-wire", budget=8)
        ) == handle
        assert len(engine.client.runs) == 1
        assert engine.client.updates.count("reserve") == 1
        assert definition.tools == (("read",) if with_tools else ())
        assert input_value == {"items": (1, {"pair": ("a", "b")})}

    asyncio.run(run())


@pytest.mark.parametrize("lost", ["reserve", "start"])
def test_uncertain_acceptance_recovers_first_queue_manifest_timeout_after_alias_move(lost):
    async def run():
        api = module()
        engine = Engine()
        setattr(engine.client, "lose_" + lost, True)
        with pytest.raises(TimeoutError):
            await api.submit(
                engine, spec(), "task", command_id="original", budget=8, session_id=None
            )
        engine.task_queue, engine.activity_timeout = "new-queue", 99
        engine.release = {**engine.release, "providers": {"different": {"kind": "other"}}}
        handle = await api.submit(
            engine, spec(), "task", command_id="original", budget=8, session_id=None
        )
        run = engine.client.runs[handle.run_id]
        assert run["queue"] == "first-queue"
        assert run["accepted"]["activity_timeout"] == 17
        assert "default" in run["accepted"]["manifest"]["providers"]
        assert len(engine.client.registry.state.roots) == 1
        assert len([s for s in engine.client.starts if s[0] != COMMAND_REGISTRY_NAME]) == 1

    asyncio.run(run())


def test_recorded_duplicate_needs_no_business_workflow_poller_and_conflict_still_refuses():
    async def run():
        api = module()
        engine = Engine()
        first = await api.submit(
            engine, spec(), "task", command_id="original", budget=8, session_id=None
        )
        engine.client.runs.clear()
        engine.release = {**engine.release, "providers": {"different": {"kind": "other"}}}
        assert (
            await api.submit(
                engine, spec(), "task", command_id="original", budget=8, session_id=None
            )
            == first
        )
        with pytest.raises(IdempotencyConflict):
            await api.submit(
                engine, spec(), "changed", command_id="original", budget=8, session_id=None
            )

    asyncio.run(run())


def test_original_v1_registry_and_changed_namespace_refuse_without_replacement():
    async def run():
        api = module()
        engine = Engine()
        engine.client.registry, engine.client.registry_queue = Registry(version=1), "first-queue"
        with pytest.raises(DefinitionMismatch):
            await api.submit(
                engine, spec(), "task", command_id="original", budget=8, session_id=None
            )
        assert engine.client.starts == []
        assert not engine.client.registry.submissions
        engine = Engine()
        await api.submit(engine, spec(), "task", command_id="original", budget=8, session_id=None)
        engine.client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        with pytest.raises(DefinitionMismatch):
            await api.submit(
                engine, spec(), "task", command_id="original", budget=8, session_id=None
            )
        assert len(engine.client.starts) == 2

    asyncio.run(run())


@pytest.mark.parametrize("field", ["original_epoch", "parent_id", "receipt"])
def test_start_recovery_refuses_replacement_epoch_foreign_parent_or_receipt(field):
    async def run():
        api = module()
        engine = Engine()
        engine.client.lose_start = True
        with pytest.raises(TimeoutError):
            await api.submit(
                engine, spec(), "task", command_id="original", budget=8, session_id=None
            )
        run = next(iter(engine.client.runs.values()))
        if field == "receipt":
            run["receipt"]["command_id"] = "forged"
        else:
            run[field] = "foreign"
        with pytest.raises(DefinitionMismatch):
            await api.submit(
                engine, spec(), "task", command_id="original", budget=8, session_id=None
            )
        assert engine.client.registry.submissions["original"]["run_receipt"] is None

    asyncio.run(run())


def test_guard_controls_and_diagnostics_use_scoped_deployment_registry():
    async def run():
        api = module()
        engine = Engine()
        # Creation and first root use the same original Registry handshake.
        handle = await api.submit(
            engine, spec(), "task", command_id="original", budget=8, session_id=None
        )
        await api.guard(
            engine,
            "cancel",
            "cancel-one",
            handle.run_id,
            {"kind": "cancel", "scope": asdict(SCOPE)},
        )
        result = await api.diagnostics(engine)
        assert result["registry_id"] == engine.client.registry_id
        assert result["counts"]["held_root_runs_for_scope"] == 1

    asyncio.run(run())


def test_namespace_drift_after_missing_root_refuses_before_sdk_start():
    async def run():
        api = module()
        engine = Engine()
        original_describe = Handle.describe

        async def drifting_describe(handle):
            try:
                return await original_describe(handle)
            except Exception:
                if handle.id != handle.client.registry_id:
                    handle.client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
                raise

        from unittest.mock import patch

        with patch.object(Handle, "describe", drifting_describe):
            with pytest.raises(DefinitionMismatch):
                await api.submit(
                    engine, spec(), "task", command_id="original", budget=8, session_id=None
                )
        assert not engine.client.runs
        assert len(engine.client.registry.state.roots) == 1

    asyncio.run(run())


def test_public_facade_reaches_original_lookup_before_current_composite_capability_preflight():
    async def run():
        from types import MethodType

        from ralf_agent import TeamSpec
        from ralf_agent.temporal import TemporalEngine
        from ralf_agent.temporal_agent_runtime import TemporalClientRuntime

        fixture = Engine()
        engine = object.__new__(TemporalEngine)
        engine.__dict__.update(fixture.__dict__)
        engine._release = engine.__dict__.pop("release")

        class LookupReached(Exception):
            pass

        async def original_lookup(self, *args, **kwargs):
            raise LookupReached()

        engine.submit = MethodType(original_lookup, engine)
        runtime = TemporalClientRuntime(engine)
        with pytest.raises(LookupReached):
            await runtime.submit(TeamSpec("original", {"a": spec()}), "task", command_id="original")
        first = runtime._dispatch_engine()
        second = runtime._dispatch_engine()
        assert first._deployment_namespace_binding is second._deployment_namespace_binding

    asyncio.run(run())


def test_hosted_deployment_registry_uses_original_known_queue_not_current_alias():
    async def run():
        from ralf_agent.temporal_host_runtime import HostedHandle

        host = SimpleNamespace(
            _route=("fixture:7233", NAMESPACE["name"]),
            _queues={"original-queue": object(), "new-queue": object()},
        )
        transport = SimpleNamespace(runtime=SimpleNamespace(_host=host))

        async def check():
            pass

        transport.check = check

        async def describe():
            return SimpleNamespace(
                id="ralf-temporal-deployment-original",
                namespace=NAMESPACE["name"],
                workflow_type=COMMAND_REGISTRY_NAME,
                task_queue="original-queue",
            )

        value = await HostedHandle(
            transport, "ralf-temporal-deployment-original", SimpleNamespace(describe=describe)
        ).describe()
        assert value.task_queue == "original-queue"

    asyncio.run(run())


def test_public_facade_refuses_sdk_session_coordinator_before_service_io():
    async def run():
        from ralf_agent.temporal import TemporalEngine
        from ralf_agent.temporal_agent_runtime import TemporalClientRuntime

        fixture = Engine()
        engine = object.__new__(TemporalEngine)
        engine.__dict__.update(fixture.__dict__)
        engine._release = {**engine.__dict__.pop("release"), "session_protocol": 1}
        runtime = TemporalClientRuntime(engine)
        with pytest.raises(ValidationError, match="coordinator"):
            await runtime._session_client()
        assert runtime.capabilities["shared_sessions"] is False
        assert not fixture.client.starts

    asyncio.run(run())


def test_host_start_checks_each_selected_registry_and_allows_shared_original_queue(monkeypatch):
    async def run():
        from ralf_agent.temporal_deployment_admission import registry_id
        from ralf_agent.temporal_profile_host import TemporalProfileHost

        client = Client()
        descriptions, checked = {}, []

        class ExistingHandle:
            def __init__(self, identity):
                self.identity = identity

            async def describe(self):
                checked.append(self.identity)
                return descriptions[self.identity]

        client.get_workflow_handle = lambda identity: ExistingHandle(identity)

        async def namespace(_):
            return NAMESPACE["id"]

        monkeypatch.setattr("ralf_agent.temporal_session_activities.namespace_id", namespace)

        class Assembly:
            def __init__(self, index, deployment):
                self.profile = SimpleNamespace(
                    identity={
                        "kind": "runtime-profile",
                        "name": str(index),
                        "version": "1",
                        "digest": str(index) * 64,
                    }
                )
                self.release = {
                    "kernel": "temporal-1",
                    "deployment_admission_protocol": {
                        "version": 2,
                        "policy": {"deployment_id": deployment},
                    },
                }
                self.identity = registry_id(deployment)
                self._worker_start = asyncio.get_running_loop().create_future()
                self._worker_lifetime = asyncio.Event()

            def create_engine(self, client, *, task_queue, **kwargs):
                descriptions.setdefault(
                    self.identity,
                    SimpleNamespace(
                        id=self.identity,
                        namespace=client.namespace,
                        workflow_type=COMMAND_REGISTRY_NAME,
                        task_queue=task_queue,
                    ),
                )
                return SimpleNamespace(command_registry_id=self.identity, release=self.release)

            async def start_worker(self, *args, **kwargs):
                return self

            def _begin_close(self):
                pass

        assemblies = [Assembly(1, "first"), Assembly(2, "first"), Assembly(3, "other")]
        host = TemporalProfileHost(assemblies, None, [], assemblies[0].profile.identity, SCOPE)
        await host.start_workers(client, queue_prefix="public-host")
        assert set(checked) == {registry_id("first"), registry_id("other")}
        assert len(checked) == 2

    asyncio.run(run())


def test_actual_start_timeout_must_match_original_registry_envelope_before_record():
    async def run():
        api = module()
        engine = Engine()
        engine.client.lose_start = True
        with pytest.raises(TimeoutError):
            await api.submit(
                engine, spec(), "task", command_id="original", budget=8, session_id=None
            )
        next(iter(engine.client.runs.values()))["accepted"]["activity_timeout"] = 99
        with pytest.raises(DefinitionMismatch):
            await api.submit(
                engine, spec(), "task", command_id="original", budget=8, session_id=None
            )
        assert engine.client.registry.submissions["original"]["run_receipt"] is None

    asyncio.run(run())


def test_racing_aliases_share_first_envelope_and_one_original_sdk_root():
    async def run():
        from unittest.mock import patch

        api = module()
        client = Client()
        first, second = Engine(client), Engine(client)
        second.task_queue, second.activity_timeout = "second-queue", 41
        second.release = {**second.release, "providers": {"default": {"kind": "changed"}}}
        barrier, arrived = asyncio.Event(), 0
        original_query = Handle.query

        async def racing_query(handle, name, value):
            nonlocal arrived
            if value.get("kind") == "deployment_submission" and not client.registry.submissions:
                arrived += 1
                if arrived == 2:
                    barrier.set()
                await barrier.wait()
                return None
            return await original_query(handle, name, value)

        with patch.object(Handle, "query", racing_query):
            handles = await asyncio.gather(
                *[
                    api.submit(
                        engine, spec(), "task", command_id="original", budget=8, session_id=None
                    )
                    for engine in (first, second)
                ]
            )
        assert handles[0] == handles[1]
        record = client.registry.submissions["original"]
        run = client.runs[handles[0].run_id]
        assert run["queue"] == record["submission"]["task_queue"]
        assert run["accepted"]["activity_timeout"] == record["submission"]["activity_timeout"]
        assert run["accepted"]["manifest"] == record["submission"]["manifest"]
        assert len(client.registry.state.roots) == len(client.runs) == 1

    asyncio.run(run())


def test_lost_record_reply_returns_original_receipt_on_retry_without_sdk_business_lookup():
    async def run():
        from unittest.mock import patch

        api = module()
        engine = Engine()
        original_update = Handle.execute_update

        async def lost_record(handle, name, value, **kwargs):
            result = await original_update(handle, name, value, **kwargs)
            if name == "record_deployment_submission":
                raise TimeoutError("Lost recorded receipt reply")
            return result

        with patch.object(Handle, "execute_update", lost_record):
            with pytest.raises(TimeoutError):
                await api.submit(
                    engine, spec(), "task", command_id="original", budget=8, session_id=None
                )
        recorded = copy.deepcopy(engine.client.registry.submissions["original"]["run_receipt"])
        engine.client.runs.clear()
        result = await api.submit(
            engine, spec(), "task", command_id="original", budget=8, session_id=None
        )
        assert asdict(result.receipt) == recorded
        assert len(engine.client.registry.state.roots) == 1

    asyncio.run(run())


def test_fresh_invalid_release_does_not_reserve_root_or_business_command():
    async def run():
        api = module()
        engine = Engine()
        engine.release = {**engine.release, "providers": {"other": {"kind": "changed"}}}
        with pytest.raises((ValidationError, DefinitionMismatch)):
            await api.submit(engine, spec(), "task", command_id="fresh", budget=8, session_id=None)
        assert not engine.client.registry.submissions
        assert not engine.client.registry.state.roots
        assert not engine.client.runs

    asyncio.run(run())


@pytest.mark.parametrize("publication", [2, 3])
def test_reset_registry_refuses_before_reserve_or_business_start(publication):
    async def run():
        api = module()
        engine = Engine()
        engine.release["deployment_admission_protocol"]["version"] = publication
        engine.client.registry = Registry(publication)
        engine.client.registry_queue = engine.task_queue
        engine.client.registry_epoch = "reset-epoch"
        with pytest.raises(DefinitionMismatch):
            await api.submit(engine, spec(), "task", command_id="fresh", budget=8, session_id=None)
        assert not engine.client.registry.state.roots
        assert not engine.client.runs
        assert not engine.client.updates

    asyncio.run(run())


def test_submission_registry_handle_is_pinned_to_original_sdk_epoch():
    async def run():
        api = module()
        engine = Engine()
        handle = await api._registry(
            engine, engine.client, asdict(SCOPE), NAMESPACE, POLICY.identity
        )
        assert handle.epoch == "registry-epoch"

    asyncio.run(run())
