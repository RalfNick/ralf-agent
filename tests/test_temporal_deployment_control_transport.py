"""Public command lookup precedes target inspection and preserves SDK bindings."""

import asyncio
import copy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict
from ralf_agent.types import digest
from tests.test_temporal_deployment_submissions import (
    NAMESPACE,
    POLICY,
    SCOPE,
    Engine,
    Registry,
    spec,
)
from tests.test_temporal_deployment_submissions import (
    Client as OriginalClient,
)
from tests.test_temporal_deployment_submissions import (
    Handle as OriginalHandle,
)


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


class Handle(OriginalHandle):
    async def describe(self):
        self.client.calls.append(("describe", self.id, self.epoch))
        value = await super().describe()
        if self.id != self.client.registry_id:
            value.raw_info = SimpleNamespace(
                first_run_id=self.client.runs[self.id].get("first_epoch", value.run_id)
            )
        return value

    async def query(self, name, value):
        self.client.calls.append(("query", self.id, self.epoch, copy.deepcopy(value)))
        if self.id == self.client.registry_id and value["kind"] == "deployment_control":
            result = self.client.registry.state.deployment_control(value)
        else:
            result = await super().query(name, value)
        if (
            value["kind"] == "deployment_control"
            and self.client.corrupt_lookup
            and result is not None
        ):
            result["control_binding"]["namespace"] = {
                **NAMESPACE,
                "id": "22222222-2222-2222-2222-222222222222",
            }
        return result

    async def execute_update(self, name, value, **options):
        self.client.calls.append(("update", self.id, self.epoch, name, copy.deepcopy(value)))
        if name == "reserve" and "descendant" in value:
            # Stand in for the Registry-owned Activity; transport hints are not
            # themselves a verification result or a second root reservation.
            prepared = self.client.registry.state.prepare_deployment_control(value)
            if "receipt" in prepared:
                return prepared["receipt"]
            self.client.verifications.append(copy.deepcopy(prepared))
            assert (
                value["descendant"]["execution_epoch"] == self.client.runs[value["target"]]["epoch"]
            )
            binding = self.client.binding
            result = self.client.registry.state.commit_deployment_control(value, binding)
            if self.client.corrupt_reply:
                result["control_binding"]["root_run_id"] = "foreign-root"
            return result
        return await super().execute_update(name, value, **options)


class Client(OriginalClient):
    def __init__(self):
        super().__init__()
        self.calls, self.verifications = [], []
        self.corrupt_reply = self.corrupt_lookup = False

    def get_workflow_handle(self, identity, **options):
        return Handle(self, identity, options.get("run_id"))


async def environment(publication=2):
    from ralf_agent import AgentSpec
    from ralf_agent import temporal_deployment_submissions as transport
    from ralf_agent.binding_definitions import AgentDefinition
    from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
    from tests.test_temporal_deployment_coding_registry import coding_request

    client, selected = Client(), spec()
    engine = Engine(client)
    if publication == 3:
        client.registry, client.registry_queue = Registry(3), engine.task_queue
        release = copy.deepcopy(coding_request()["root_admission"]["submission"]["manifest"])
        release["deployment_admission_protocol"].update(
            policy=POLICY.identity, registry_id=client.registry_id
        )
        for record in release["binding_catalog"]["records"].values():
            record["scope"] = asdict(SCOPE)
        engine.release = release
        selected = AgentDefinition(
            AgentSpec("answer", "Answer", tools=("coding",)),
            AgentBindingDescriptor(runner=BindingSelection.ref("native", "1")),
        )
    root = await transport.submit(engine, selected, "task", command_id="original-root")
    root_run = client.runs[root.run_id]
    accepted = copy.deepcopy(root_run["accepted"])
    accepted["command_id"] = "original-child"
    child = "original-child"
    request = accepted["request"]
    link = {
        "parent_run_id": root.run_id,
        "parent_execution_epoch": root_run["epoch"],
        "parent_request_digest": digest(root_run["accepted"]["request"]),
        "parent_manifest_digest": digest(root_run["accepted"]["manifest"]),
        "call_id": "original-intent",
        "child_run_id": child,
        "child_command_id": accepted["command_id"],
        "child_request_digest": digest(request),
    }
    accepted["deployment_admission"]["lineage"] = [link]
    client.runs[child] = {
        **copy.deepcopy(root_run),
        "accepted": accepted,
        "epoch": "child-epoch",
        "parent_id": root.run_id,
        "parent_run_id": root_run["epoch"],
    }
    client.binding = {
        "version": 1,
        "scope": asdict(SCOPE),
        "namespace": NAMESPACE,
        "target": child,
        "target_execution_epoch": "child-epoch",
        "root_run_id": root.run_id,
        "root_execution_epoch": root_run["epoch"],
    }
    client.calls.clear()
    client.updates.clear()
    return engine, child, root


@pytest.mark.parametrize("publication", [2, 3])
@pytest.mark.parametrize("kind", ["approve", "cancel", "drive", "reconcile", "send_input", "patch"])
def test_descendant_guard_records_scoped_command_without_another_root(publication, kind):
    from ralf_agent import temporal_deployment_submissions as transport

    async def run():
        engine, child, root = await environment(publication)
        payload = {"kind": kind, "scope": asdict(SCOPE), "body": {"items": (1, 2)}}
        expected = copy.deepcopy(payload)
        binding = await transport.guard(engine, kind, "child-control", child, payload)
        assert binding == engine.client.binding and payload == expected
        assert (
            len(engine.client.registry.state.roots) == len(engine.client.registry.submissions) == 1
        )
        assert len(engine.client.registry.state.commands) == 2
        assert len(engine.client.verifications) == 1
        prepared = engine.client.verifications[0]
        assert prepared["submission"]["task_queue"] == "first-queue"
        assert prepared["submission"]["activity_timeout"] == 17
        assert prepared["root"]["run_id"] == root.run_id
        assert prepared["request"]["payload_digest"] == digest(payload)
        reserve = next(c[4] for c in engine.client.calls if c[0] == "update" and c[3] == "reserve")
        assert reserve["descendant"] == {
            "root_command_id": "original-root",
            "execution_epoch": "child-epoch",
        }
        assert "control_binding" not in reserve
        lookup = next(
            c
            for c in engine.client.calls
            if c[0] == "query" and c[3]["kind"] == "deployment_control"
        )
        child_describe = next(
            c for c in engine.client.calls if c[0] == "describe" and c[1] == child
        )
        assert engine.client.calls.index(lookup) < engine.client.calls.index(child_describe)

    asyncio.run(run())


def test_original_descendant_control_lookup_survives_alias_move_retirement_and_missing_current_target():
    from ralf_agent import temporal_deployment_submissions as transport

    async def run():
        engine, child, _ = await environment()
        payload = {"kind": "cancel", "scope": asdict(SCOPE)}
        original = await transport.guard(engine, "cancel", "original-control", child, payload)
        engine.client.registry.state.roots.clear()
        engine.client.runs.clear()
        engine.release = {**engine.release, "providers": {"moved": {"kind": "changed"}}}
        engine.task_queue, engine.activity_timeout = "moved-unserved-queue", 99
        engine.client.calls.clear()
        assert (
            await transport.guard(engine, "cancel", "original-control", child, payload) == original
        )
        assert not any(c[0] == "describe" and c[1] == child for c in engine.client.calls)
        assert not any(c[0] == "update" for c in engine.client.calls)
        assert len(engine.client.verifications) == 1
        with pytest.raises(IdempotencyConflict):
            await transport.guard(engine, "cancel", "original-control", "other-target", payload)

    asyncio.run(run())


def test_root_control_retains_legacy_none_result_and_four_field_receipt():
    from ralf_agent import temporal_deployment_submissions as transport

    async def run():
        engine, _, root = await environment()
        assert (
            await transport.guard(
                engine,
                "cancel",
                "root-control",
                root.run_id,
                {"kind": "cancel", "scope": asdict(SCOPE)},
            )
            is None
        )
        receipt = engine.client.registry.state.commands[digest([asdict(SCOPE), "root-control"])][
            "receipt"
        ]
        assert set(receipt) == {"command_id", "target", "record_state", "apply_state"}
        assert any(
            c[0] == "query" and c[3]["kind"] == "deployment_control" for c in engine.client.calls
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["target-first", "scope", "namespace", "reply-root", "lookup-namespace"]
)
def test_transport_refuses_changed_sdk_hints_or_original_binding(fault):
    from ralf_agent import temporal_deployment_submissions as transport

    async def run():
        engine, child, _ = await environment()
        payload = {"kind": "cancel", "scope": asdict(SCOPE)}
        if fault == "target-first":
            engine.client.runs[child]["first_epoch"] = "pre-reset-epoch"
        elif fault == "scope":
            engine.client.runs[child]["accepted"]["scope"]["principal"] = "foreign"
        elif fault == "namespace":
            engine.client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
            engine._deployment_namespace_binding = {"namespace": NAMESPACE}
        elif fault == "reply-root":
            engine.client.corrupt_reply = True
        elif fault == "lookup-namespace":
            await transport.guard(engine, "cancel", "original-control", child, payload)
            engine.client.corrupt_lookup = True
        with pytest.raises(AuthorizationDenied if fault == "scope" else DefinitionMismatch):
            await transport.guard(engine, "cancel", "original-control", child, payload)
        if fault in {"target-first", "scope", "namespace"}:
            assert not engine.client.verifications

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["version", "scope", "epoch", "extra"])
def test_duplicate_lookup_requires_exact_original_binding_schema_without_target_io(fault):
    from ralf_agent import temporal_deployment_submissions as transport

    async def run():
        engine, child, _ = await environment()
        payload = {"kind": "cancel", "scope": asdict(SCOPE)}
        await transport.guard(engine, "cancel", "original-control", child, payload)
        key = digest([asdict(SCOPE), "original-control"])
        binding = engine.client.registry.state.control_bindings[key]
        if fault == "version":
            binding["version"] = True
        elif fault == "scope":
            binding["scope"] = {**binding["scope"], "principal": "foreign"}
        elif fault == "epoch":
            binding["target_execution_epoch"] = ""
        else:
            binding["caller_attestation"] = True
        engine.client.runs.clear()
        engine.client.calls.clear()
        with pytest.raises(DefinitionMismatch):
            await transport.guard(engine, "cancel", "original-control", child, payload)
        assert not any(
            c[0] in {"describe", "update"} and c[1] == child for c in engine.client.calls
        )

    asyncio.run(run())


def test_guard_detaches_business_payload_before_first_sdk_await():
    from ralf_agent import temporal_deployment_submissions as transport

    async def run():
        engine, child, _ = await environment()
        payload = {"kind": "cancel", "scope": asdict(SCOPE), "body": {"items": [1, 2]}}
        original_digest = digest(payload)
        describe = engine.client.workflow_service.describe_namespace

        async def mutate(request):
            payload["body"]["items"].append(3)
            return await describe(request)

        engine.client.workflow_service.describe_namespace = mutate
        assert (
            await transport.guard(engine, "cancel", "original-control", child, payload)
            == engine.client.binding
        )
        assert engine.client.verifications[0]["request"]["payload_digest"] == original_digest
        assert digest(payload) != original_digest

    asyncio.run(run())
