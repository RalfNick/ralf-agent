"""One original Coding4 observation validates after the fixed child SDK read."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent import temporal_coding_composition_control as composition_control
from relf_agent import temporal_coding_composition_state as composition_state
from relf_agent import temporal_deployment_coding_bridge as bridge
from relf_agent import temporal_deployment_coding_validation as validation
from relf_agent import temporal_deployment_control_projection as projection
from relf_agent import temporal_deployment_control_transport as transport
from relf_agent import temporal_deployment_execution as execution
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_parent_state import PARENT_WORKFLOW_NAME
from relf_agent.types import digest
from tests import test_temporal_session_coding_child_identity as child_fixture
from tests import test_temporal_session_coding_projection as sdk_fixture
from tests.test_temporal_deployment_control_transport_projection import setup


def environment(monkeypatch):
    from temporalio.client import WorkflowExecutionStatus

    _, _, value = setup()
    captured, steps = {}, []
    session_class = child_fixture.TemporalSessionState

    def session(*args, **options):
        captured["session"] = session_class(*args, **options)
        return captured["session"]

    def original(*, composition=False):
        parent, call = child_fixture.original_child()
        call = next(child for child in parent.children if child["run_id"] == call["run_id"])
        captured.update(parent=parent, call=call)
        intent = captured["session"].deployment_turn().intent
        parent.deployment_task_queue = intent["submission"]["task_queue"]
        parent.deployment_activity_timeout = intent["submission"]["activity_timeout"]
        call.update(dispatch_started=True, deployment_execution_epoch="child-epoch")
        call["child_execution"] = {
            "namespace": intent["namespace"],
            "execution_epoch": "child-epoch",
            "original_execution_epoch": "child-epoch",
        }
        return intent, parent.deployment_admission, parent

    node_identity = projection.node_identity_digest

    def identity(proof, start, coding=None):
        return node_identity(
            proof,
            start,
            composition_state.physical_stop_view(captured["parent"]) if coding is None else coding,
        )

    monkeypatch.setattr(child_fixture, "TemporalSessionState", session)
    monkeypatch.setattr(sdk_fixture, "coding_original", original)
    monkeypatch.setattr(projection, "node_identity_digest", identity)
    runtime, client, _, info = sdk_fixture.sdk_session_environment(monkeypatch)
    parent, call = captured["parent"], captured["call"]
    info.task_queue = parent.deployment_task_queue
    client.descriptions["root"].workflow_type = PARENT_WORKFLOW_NAME
    descriptor = SimpleNamespace(
        id=call["run_id"],
        run_id="child-epoch",
        namespace=client.namespace,
        task_queue=info.task_queue,
        parent_id=parent.run_id,
        parent_run_id=parent.epoch,
        workflow_type="ralf.temporal.run.v1",
        status=WorkflowExecutionStatus.RUNNING,
        raw_info=SimpleNamespace(first_run_id="child-epoch"),
    )
    from relf_agent.temporal_state import WORKFLOW_NAME

    descriptor.workflow_type = WORKFLOW_NAME
    client.descriptions["child"] = descriptor
    original_handle = client.get_workflow_handle

    def handle(identity, **options):
        result = original_handle(identity, **options)
        if identity == call["run_id"]:
            describe = result.describe

            async def child_description():
                steps.append("child-describe")
                if captured.get("during_describe"):
                    captured["during_describe"]()
                return await describe()

            result.describe = child_description
        return result

    client.get_workflow_handle = handle

    async def physical(*args, **kwargs):
        return composition_state.physical_stop_view(parent)

    async def ancestry(*args, **kwargs):
        return []

    async def original_proof(*args, **kwargs):
        return await execution._proof()

    monkeypatch.setattr(execution, "validate_activity", original_proof)
    monkeypatch.setattr(composition_control, "_proof", physical)
    monkeypatch.setattr(composition_control, "_ancestry", ancestry)
    value.update(scope=parent.scope, manifest=parent.manifest)
    value["snapshot"]["run_id"] = call["run_id"]
    value["snapshot"]["actions"] = []
    child_proof = value["coding_composition_proof"]
    child_proof.update(
        scope=parent.scope,
        run_id=call["run_id"],
        namespace=parent.composition_namespace,
        request=call["request"],
        request_digest=digest(call["request"]),
        manifest=parent.manifest,
    )
    child_proof["proof_digest"] = digest(
        {k: v for k, v in child_proof.items() if k != "proof_digest"}
    )

    async def control(*args):
        steps.append("control")
        return copy.deepcopy(value)

    real_validator = validation.CodingValidation

    class TracedValidation(real_validator):
        async def validate(self):
            steps.append("validate")
            return await super().validate()

        async def permission(self):
            steps.append("permission")
            return await super().permission()

    monkeypatch.setattr(bridge, "control", control)
    monkeypatch.setattr(composition_control, "control", control)
    monkeypatch.setattr(validation, "CodingValidation", TracedValidation)
    return runtime, client, parent, call, info, captured, steps


def test_coding_four_observe_validates_after_child_read_once_before_body(monkeypatch):
    async def run():
        runtime, client, parent, call, info, _, steps = environment(monkeypatch)
        result = await transport.execute(
            runtime, client, transport.request(parent, call, "observe"), info
        )
        assert transport.expand_response(parent, call, {"ok": True, "result": result})["ok"]
        assert steps == ["child-describe", "validate", "control", "child-describe", "validate"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["runtime", "parent-reset", "child-reset", "namespace", "callback"]
)
def test_child_read_drift_is_refused_before_bridge_body(monkeypatch, fault):
    async def run():
        runtime, client, parent, call, info, captured, steps = environment(monkeypatch)

        def changed():
            if fault == "runtime":
                runtime.changed = True
            elif fault == "parent-reset":
                client.descriptions["root"].run_id = "reset-parent"
            elif fault == "child-reset":
                client.descriptions["child"].run_id = "reset-child"
            elif fault == "namespace":
                client.namespace_uuid = "22222222-2222-4222-8222-222222222222"
            else:
                client.get_workflow_handle = lambda *args, **kwargs: None

        captured["during_describe"] = changed
        with pytest.raises(DefinitionMismatch):
            await transport.execute(
                runtime, client, transport.request(parent, call, "observe"), info
            )
        assert steps[0] == "child-describe" and "control" not in steps

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["register", "cancel", "recover"])
def test_other_coding_four_modes_keep_original_validation_order(monkeypatch, mode):
    async def run():
        runtime, client, parent, call, info, _, steps = environment(monkeypatch)
        await transport.execute(runtime, client, transport.request(parent, call, mode), info)
        assert steps == (
            ["permission", "control", "permission"]
            if mode == "register"
            else ["validate", "child-describe", "validate", "control", "child-describe", "validate"]
        )

    asyncio.run(run())


def test_legacy_three_observe_keeps_original_three_real_validations(monkeypatch):
    from tests.test_temporal_deployment_coding_validation import environment as legacy

    async def run():
        _, _, value = setup()  # Build original manifests before injecting SDK readers.
        runtime, client, _, info, _ = legacy(monkeypatch, depth=1)
        proof = await execution._proof(None, None, None, None, client.descriptions["root"].id)
        parent = SimpleNamespace(
            scope=proof["scope"],
            run_id=proof["run_id"],
            epoch=proof["execution_epoch"],
            request=proof["request"],
            manifest=proof["manifest"],
            composition_namespace=proof["namespace"],
            deployment_task_queue="original-queue",
        )
        call = proof["children"][0]
        # This invocation validates the Parent itself, with no child edge
        # selector; the shared depth-one fixture originally addresses its leaf.
        client.compact["root"]["edge"] = None
        client.compact["root"]["proof_digest"] = digest(
            {key: item for key, item in client.compact["root"].items() if key != "proof_digest"}
        )
        info.workflow_id, info.workflow_run_id = parent.run_id, parent.epoch
        info.task_queue = parent.deployment_task_queue
        value.update(scope=parent.scope, manifest=parent.manifest)
        value["snapshot"].update(run_id=call["run_id"], actions=[])
        value["coding_composition_proof"] = await composition_control._proof(
            client, parent.scope, call["run_id"]
        )
        steps = []
        get_handle = client.get_workflow_handle

        def handle(identity, **options):
            result = get_handle(identity, **options)
            if identity == call["run_id"]:
                describe = result.describe

                async def child_description():
                    steps.append("child-describe")
                    return await describe()

                result.describe = child_description
            return result

        async def original(*args, **kwargs):
            return copy.deepcopy(proof)

        async def ancestry(*args, **kwargs):
            return []

        async def control(*args):
            steps.append("control")
            return copy.deepcopy(value)

        real_validator = validation.CodingValidation

        class TracedValidation(real_validator):
            async def validate(self):
                steps.append("validate")
                return await super().validate()

        monkeypatch.setattr(client, "get_workflow_handle", handle)
        monkeypatch.setattr(execution, "validate_activity", original)
        monkeypatch.setattr(execution, "_proof", original)
        monkeypatch.setattr(composition_control, "_ancestry", ancestry)
        monkeypatch.setattr(bridge, "control", control)
        monkeypatch.setattr(validation, "CodingValidation", TracedValidation)
        await transport.execute(runtime, client, transport.request(parent, call, "observe"), info)
        assert steps == [
            "validate",
            "child-describe",
            "validate",
            "control",
            "child-describe",
            "validate",
        ]

    asyncio.run(run())
