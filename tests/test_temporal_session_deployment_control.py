"""SDK-bound Session controls; callbacks are never authority by themselves."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_session_state import SESSION_ACTIVITY, SESSION_WORKFLOW
from ralf_agent.types import digest


def fixture():
    from tests.test_temporal_session_deployment_dto import DEPLOYMENT, intent

    accepted = intent()
    value = {
        "version": 1,
        "mode": "register",
        "scope": accepted["scope"],
        "namespace": accepted["namespace"],
        "coordinator_id": accepted["coordinator_id"],
        "coordinator_execution_epoch": accepted["coordinator_execution_epoch"],
        "intent": accepted,
    }
    info = SimpleNamespace(
        workflow_id=accepted["coordinator_id"],
        workflow_run_id=accepted["coordinator_execution_epoch"],
        workflow_namespace=accepted["namespace"]["name"],
        activity_id="1",
        activity_type=SESSION_ACTIVITY,
        attempt=1,
        task_queue=accepted["binding"]["task_queue"],
    )
    return DEPLOYMENT, value, info


class Runtime:
    def __init__(self, manifest):
        self.manifest = manifest
        from ralf_agent.temporal_context_execution import ContextExecutionOwner

        self._deployment_execution_owner = ContextExecutionOwner()
        self._deployment_execution_owner_pin = self._deployment_execution_owner

    def validate_release(self, manifest=None):
        if manifest is not None and manifest != self.manifest:
            raise DefinitionMismatch("changed release")


class Handle:
    def __init__(self, client, epoch):
        self.client, self.epoch = client, epoch

    async def describe(self):
        c, i = self.client, self.client.intent
        c.event("describe")
        return SimpleNamespace(
            id=i["coordinator_id"],
            run_id=c.epoch,
            namespace=c.namespace,
            workflow_type=SESSION_WORKFLOW,
            task_queue=i["binding"]["task_queue"],
            parent_id=None,
            parent_run_id=None,
            raw_info=SimpleNamespace(first_run_id=c.first_epoch),
        )

    def fetch_history_events(self, **kwargs):
        async def events():
            from temporalio.api.common.v1 import Payloads, WorkflowType
            from temporalio.api.history.v1 import (
                HistoryEvent,
                WorkflowExecutionStartedEventAttributes,
            )
            from temporalio.api.taskqueue.v1 import TaskQueue

            c, i = self.client, self.client.intent
            payload = await c.data_converter.encode([c.accepted])
            c.event("history")
            yield HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    workflow_type=WorkflowType(name=SESSION_WORKFLOW),
                    task_queue=TaskQueue(name=i["binding"]["task_queue"]),
                    input=Payloads(payloads=payload),
                    original_execution_run_id=c.original_epoch,
                    first_execution_run_id=c.first_epoch,
                ),
            )

        return events()

    async def query(self, name, value):
        c = self.client
        c.event(value["kind"])
        if value["kind"] in {"deployment_session_command", "deployment_session_lifecycle"}:
            from ralf_agent.temporal_session_deployment_state import START_SELECTOR_FIELDS

            assert set(value) == START_SELECTOR_FIELDS | {"kind"}
        if value["kind"] == "deployment_session_intent":
            return copy.deepcopy(c.intent)
        if value["kind"] == "deployment_session_receipt":
            return copy.deepcopy(c.session_receipt_result)
        if value["kind"] == "deployment_session_command":
            i = c.intent
            return {
                "session_ref": copy.deepcopy(i["session_ref"]),
                "receipt": {
                    "command_id": i["session_command_id"],
                    "kind": "session_submit",
                    "run_id": None,
                    "record_state": "durably_recorded",
                    "apply_state": "applied",
                    "outcome": {
                        "turn": {
                            **{k: copy.deepcopy(i[k]) for k in ("turn_id", "turn_seq")},
                            "session": copy.deepcopy(i["session_ref"]),
                            "command_id": i["session_command_id"],
                            "run": {"run_id": i["run_id"]},
                        }
                    },
                },
            }
        if value["kind"] == "deployment_session_lifecycle":
            return copy.deepcopy(c.lifecycle)
        raise AssertionError(value)

    async def execute_update(self, name, value, **kwargs):
        c = self.client
        c.event(name)
        if name == "session_deployment_call_start":
            c.calls.append(copy.deepcopy(value["identity"]))
            if getattr(c, "start_error", None) is not None:
                raise c.start_error
            return {
                "identity": copy.deepcopy(value["identity"]),
                "allowed": not getattr(c, "start_denied", False),
            }
        if name == "session_deployment_call_end":
            assert c.body_stopped
            assert digest(value["body_result"]) == value["body_result_digest"]
            result = {
                **{key: copy.deepcopy(item) for key, item in value.items() if key != "body_result"},
                "recorded": True,
            }
            if not hasattr(c, "original_end_ack"):
                c.original_end_ack = copy.deepcopy(result)
            assert result == c.original_end_ack
            if getattr(c, "lose_end_reply", False):
                c.lose_end_reply = False
                raise TimeoutError("original end ACK reply lost")
            return result
        raise AssertionError(name)


class Client:
    def __init__(self, value):
        from temporalio.converter import DataConverter

        self.intent = copy.deepcopy(value["intent"])
        self.namespace = value["namespace"]["name"]
        self.namespace_uuid = value["namespace"]["id"]
        self.epoch = self.first_epoch = self.original_epoch = value["coordinator_execution_epoch"]
        self.data_converter = DataConverter.default
        self.workflow_service = SimpleNamespace(describe_namespace=self.describe_namespace)
        i = self.intent
        self.accepted = {
            "scope": i["scope"],
            "namespace_id": i["namespace"]["id"],
            "session_namespace": i["session_ref"]["key"]["namespace"],
            "session_id": i["session_ref"]["key"]["session_id"],
            "command_id": "open",
            **copy.deepcopy(i["binding"]),
        }
        self.lifecycle = {
            "start_issued": False,
            "refusal_barrier": None,
            "start": {
                "version": 1,
                "intent": copy.deepcopy(i),
                "phase": "intent-accepted",
                "reservation": None,
                "execution_epoch": None,
                "run_receipt": None,
                "last_error": None,
                "start_refusal": None,
            },
        }
        self.events, self.calls, self.mutate = [], [], None
        self.body_stopped = False

    def event(self, name):
        self.events.append(name)
        if name == "session_deployment_call_end" and hasattr(self, "end_attempted"):
            self.end_attempted.set()
        if self.mutate:
            self.mutate(name)

    async def describe_namespace(self, request):
        self.event("namespace")
        return SimpleNamespace(namespace_info=SimpleNamespace(id=self.namespace_uuid))

    def get_workflow_handle(self, identity, *, run_id=None):
        if identity == self.intent["run_id"]:
            return BusinessHandle(self, run_id)
        if identity == getattr(self, "registry_id", None):
            return RegistryHandle(self, run_id)
        assert identity == self.intent["coordinator_id"]
        return Handle(self, run_id)


def validation():
    from ralf_agent.temporal_session_deployment_control import SessionControlValidation

    deployment, value, info = fixture()
    client = Client(value)
    runtime = Runtime(copy.deepcopy(value["intent"]["binding"]["manifest"]))
    return SessionControlValidation(runtime, client, value, info, deployment_id=deployment), client


def test_original_coordinator_start_history_and_durable_intent_are_read():
    proof, client = validation()
    result = asyncio.run(proof.validate())
    assert result["intent"] == client.intent
    assert result["session_origin"]["coordinator_original_execution_epoch"] == client.epoch
    assert {"history", "describe", "deployment_session_intent"} <= set(client.events)


@pytest.mark.parametrize("field", ["epoch", "first_epoch", "original_epoch", "namespace_uuid"])
def test_changed_original_sdk_identity_refuses(field):
    proof, client = validation()
    setattr(client, field, "22222222-2222-4222-8222-222222222222")
    with pytest.raises(DefinitionMismatch):
        asyncio.run(proof.validate())


def test_reset_during_intent_query_refuses_before_callback():
    proof, client = validation()
    client.mutate = lambda name: (
        setattr(client, "epoch", "reset") if name == "deployment_session_intent" else None
    )
    with pytest.raises(DefinitionMismatch):
        asyncio.run(proof.validate())


def test_replaced_endpoint_after_sdk_await_refuses():
    proof, client = validation()
    client.mutate = lambda name: (
        setattr(client, "get_workflow_handle", lambda *a, **k: None)
        if name == "namespace"
        else None
    )
    with pytest.raises(DefinitionMismatch):
        asyncio.run(proof.validate())


def test_forged_durable_intent_refuses_even_with_valid_digest():
    proof, client = validation()
    client.intent["submission"]["request"]["input"] = "changed"
    client.intent["intent_digest"] = digest(
        {k: v for k, v in client.intent.items() if k != "intent_digest"}
    )
    with pytest.raises(DefinitionMismatch):
        asyncio.run(proof.validate())


def test_owned_body_ends_before_ack_and_ack_covers_full_response():
    from ralf_agent.temporal_session_deployment_control import owned_control_body

    proof, client = validation()

    async def body():
        try:
            return {"registered": True}
        finally:
            client.body_stopped = True

    result = asyncio.run(owned_control_body(proof, body))
    assert result["ok"] is True
    assert result["result"] == {"registered": True}
    assert result["call_end"]["body_result_digest"] == digest(
        {"ok": True, "result": {"registered": True}}
    )
    assert len(client.calls) == 1
    assert "session_deployment_call_end" in client.events
    assert not any("deployment_call" in e and "session" not in e for e in client.events)


def test_owned_body_failed_identity_never_begins_call_or_body():
    from ralf_agent.temporal_session_deployment_control import owned_control_body

    proof, client = validation()
    client.original_epoch = "reset"

    async def body():
        client.body_stopped = True
        return {"registered": True}

    with pytest.raises(DefinitionMismatch):
        asyncio.run(owned_control_body(proof, body))
    assert client.calls == []
    assert not client.body_stopped


def test_factory_registration_rejects_copied_function_marker_and_resource():
    from functools import wraps

    from ralf_agent.temporal_session_deployment_control import (
        is_registered_activity,
        registered_session_deployment_activities,
    )

    _, value, _ = fixture()
    client = Client(value)
    runtime = Runtime(value["intent"]["binding"]["manifest"])
    original = registered_session_deployment_activities(runtime, client)[0]
    assert is_registered_activity(runtime, client, original)

    @wraps(original)
    async def copied(value):
        return await original(value)

    assert not is_registered_activity(runtime, client, copied)
    assert not is_registered_activity(Runtime(runtime.manifest), client, original)
    client.get_workflow_handle = lambda *a, **k: None
    assert not is_registered_activity(runtime, client, original)


def registry_fixture():
    from ralf_agent.temporal_deployment_admission import registry_id
    from ralf_agent.temporal_deployment_protocol import publish
    from tests.test_temporal_deployment_session_registry import POLICY

    deployment, value, info = fixture()
    i = value["intent"]
    manifest = publish(
        i["binding"]["manifest"], POLICY.identity, public=True, session_deployment=True
    )
    i["binding"]["manifest"] = manifest
    i["session_ref"]["definition_digest"] = digest(i["binding"])
    i["submission"]["manifest"] = manifest
    i["submission"]["request"]["session_turn"]["session_ref"] = copy.deepcopy(i["session_ref"])
    i["intent_digest"] = digest({k: v for k, v in i.items() if k != "intent_digest"})
    client = Client(value)
    client.registry_id = registry_id(deployment)
    client.registry_epoch = "registry-original"
    client.registry_manifest = manifest
    runtime = Runtime(manifest)
    runtime._deployment_admission_policy_pin = POLICY
    runtime._deployment_admission_policy = POLICY
    runtime._deployment_admission_identity = POLICY.identity
    info.workflow_id, info.workflow_run_id = client.registry_id, client.registry_epoch
    info.activity_type = "ralf.temporal.session-deployment-verify.v1"
    prepared = {
        "intent": i,
        "session_origin": {
            "version": 1,
            **{
                k: copy.deepcopy(i[k])
                for k in (
                    "namespace",
                    "coordinator_id",
                    "coordinator_execution_epoch",
                    "session_ref",
                    "session_command_id",
                    "turn_id",
                    "turn_seq",
                    "intent_digest",
                )
            },
            "coordinator_first_execution_epoch": i["coordinator_execution_epoch"],
            "coordinator_original_execution_epoch": i["coordinator_execution_epoch"],
        },
    }
    prepared["request"] = {
        "scope": i["scope"],
        "admission_policy": POLICY.identity,
        "namespace": i["namespace"],
        "command_id": i["run_command_id"],
        "kind": "submit",
        "target": i["run_id"],
        "payload_digest": digest(i["submission"]["request"]),
        "root_admission": {
            "version": 4,
            "manifest_digest": digest(manifest),
            "submission": i["submission"],
            "session_origin": prepared["session_origin"],
        },
    }
    return (
        runtime,
        client,
        info,
        {
            "mode": "session_root",
            "scope": i["scope"],
            "manifest": manifest,
            "registry_execution_epoch": client.registry_epoch,
            "prepared": prepared,
        },
    )


def test_registry_root_verification_reads_original_coordinator_not_attestation():
    from ralf_agent.temporal_session_deployment_control import verify_registry_request

    runtime, client, info, request = registry_fixture()
    result = asyncio.run(verify_registry_request(runtime, client, request, info=info))
    assert result == {
        "ok": True,
        "result": {k: request["prepared"][k] for k in ("intent", "session_origin")},
    }
    assert "deployment_session_command" in client.events


def test_registry_root_verification_rejects_forged_activity_before_reads():
    from ralf_agent.temporal_session_deployment_control import verify_registry_request

    runtime, client, info, request = registry_fixture()
    info.workflow_id = "forged"
    with pytest.raises(DefinitionMismatch):
        asyncio.run(verify_registry_request(runtime, client, request, info=info))
    assert client.events == []


class RegistryHandle(Handle):
    async def describe(self):
        from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME

        c = self.client
        c.event("registry_describe")
        return SimpleNamespace(
            id=c.registry_id,
            run_id=c.registry_epoch,
            namespace=c.namespace,
            workflow_type=COMMAND_REGISTRY_NAME,
            task_queue="registry-queue",
            parent_id=None,
            parent_run_id=None,
            raw_info=SimpleNamespace(first_run_id=c.registry_epoch),
        )

    def fetch_history_events(self, **kwargs):
        async def events():
            from temporalio.api.common.v1 import Payloads, WorkflowType
            from temporalio.api.history.v1 import (
                HistoryEvent,
                WorkflowExecutionStartedEventAttributes,
            )
            from temporalio.api.taskqueue.v1 import TaskQueue

            from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME

            c = self.client
            payload = await c.data_converter.encode(
                [
                    {
                        "deployment_admission": {
                            "version": 4,
                            "policy": c.registry_manifest["deployment_admission_protocol"][
                                "policy"
                            ],
                            "namespace": c.intent["namespace"],
                        }
                    }
                ]
            )
            yield HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    workflow_type=WorkflowType(name=COMMAND_REGISTRY_NAME),
                    task_queue=TaskQueue(name="registry-queue"),
                    input=Payloads(payloads=payload),
                    original_execution_run_id=c.registry_epoch,
                    first_execution_run_id=c.registry_epoch,
                ),
            )

        return events()

    async def execute_update(self, name, value, **kwargs):
        c = self.client
        c.event(name)
        if name == "record_deployment_submission":
            return c.registry_state.record_deployment_submission(value)
        if name == "reserve_session_root":
            request, intent = value["request"], value["intent"]
            prepared = c.registry_state.prepare_session_root(request, intent)
            if "receipt" in prepared:
                return prepared["receipt"]
            # Mock only the SDK Workflow boundary, run real Registry prepare/commit.
            result = c.registry_state.commit_session_root(
                request, intent, {k: prepared[k] for k in ("intent", "session_origin")}
            )
            if getattr(c, "lose_reserve_reply", False):
                raise TimeoutError("reply lost after original commit")
            return result
        raise AssertionError(name)

    async def query(self, name, value):
        c = self.client
        c.event("registry_" + value["kind"])
        if value["kind"] == "deployment_session_root":
            return c.registry_state.deployment_session_root(value)
        if value["kind"] == "deployment_submission":
            record = c.registry_state.deployment_session_root(
                {**value, "kind": "deployment_session_root"}
            )
            return {
                k: record[k]
                for k in ("reservation", "submission", "run_receipt", "execution_epoch")
            }
        if value["kind"] == "deployment_retirement":
            return copy.deepcopy(c.business_retirement)
        assert value["kind"] == "deployment_configuration"
        return {
            "version": 4,
            "registry_id": c.registry_id,
            "namespace": c.intent["namespace"],
            "policy": c.registry_manifest["deployment_admission_protocol"]["policy"],
        }


def test_register_recovers_original_claim_without_second_reserve():
    from ralf_agent.temporal_session_deployment_control import SessionControlValidation, _register
    from tests.test_temporal_deployment_session_registry import state

    runtime, client, info, request = registry_fixture()
    client.registry_state = state()
    from tests.test_temporal_deployment_session_registry import intent_request

    intent_request(client.registry_state)
    prepared = request["prepared"]
    client.registry_state.commit_session_root(
        prepared["request"],
        prepared["intent"],
        {k: prepared[k] for k in ("intent", "session_origin")},
    )
    wire = {
        "version": 1,
        "mode": "register",
        "intent": prepared["intent"],
        **{
            k: prepared["intent"][k]
            for k in (
                "scope",
                "namespace",
                "coordinator_id",
                "coordinator_execution_epoch",
            )
        },
    }
    info.workflow_id = wire["coordinator_id"]
    info.workflow_run_id = wire["coordinator_execution_epoch"]
    info.activity_type = SESSION_ACTIVITY
    proof = SessionControlValidation(
        runtime,
        client,
        wire,
        info,
        deployment_id=client.registry_manifest["deployment_admission_protocol"]["policy"][
            "deployment_id"
        ],
    )
    result = asyncio.run(_register(proof))
    assert result["start"]["phase"] == "held-unbound"
    assert result["start"]["intent"] == prepared["intent"]
    assert "reserve_session_root" not in client.events


def session_validation():
    from ralf_agent.temporal_session_deployment_control import SessionControlValidation
    from tests.test_temporal_deployment_session_registry import intent_request, state

    runtime, client, info, request = registry_fixture()
    client.registry_state = state()
    intent_request(client.registry_state)
    i = request["prepared"]["intent"]
    wire = {
        "version": 1,
        "mode": "register",
        "intent": i,
        **{
            k: i[k]
            for k in (
                "scope",
                "namespace",
                "coordinator_id",
                "coordinator_execution_epoch",
            )
        },
    }
    info.workflow_id, info.workflow_run_id, info.activity_type = (
        i["coordinator_id"],
        i["coordinator_execution_epoch"],
        SESSION_ACTIVITY,
    )
    return SessionControlValidation(
        runtime,
        client,
        wire,
        info,
        deployment_id=client.registry_manifest["deployment_admission_protocol"]["policy"][
            "deployment_id"
        ],
    ), client


def test_register_reserve_reply_loss_recovers_first_claim_and_envelope():
    from ralf_agent.temporal_session_deployment_control import _register

    proof, client = session_validation()
    client.lose_reserve_reply = True
    result = asyncio.run(_register(proof))
    assert result["start"]["phase"] == "held-unbound"
    assert len(client.registry_state.roots) == 1
    assert client.events.count("reserve_session_root") == 1
    assert result["start"]["intent"]["submission"] == client.intent["submission"]


def test_register_capacity_is_deferred_without_new_turn_or_business_start():
    from ralf_agent.temporal_session_deployment_control import _register
    from tests.test_temporal_deployment_session_registry import intent_request, verified

    proof, client = session_validation()
    other, request = intent_request(client.registry_state, command_id="other-submit")
    client.registry_state.commit_session_root(request, other, verified(other, request))
    result = asyncio.run(_register(proof))
    assert result["start"]["phase"] == "capacity-deferred"
    assert len(client.registry_state.roots) == 1
    assert result["start"]["intent"] == client.intent


def test_start_issued_pending_claim_stays_uncertain_without_second_reserve():
    from ralf_agent.temporal_session_deployment_control import _register
    from tests.test_temporal_deployment_session_registry import intent_request, verified

    proof, client = session_validation()
    i, request = intent_request(client.registry_state)
    client.registry_state.commit_session_root(request, i, verified(i, request))
    client.lifecycle["start_issued"] = True
    result = asyncio.run(_register(proof))
    assert result["start"]["phase"] == "start-uncertain"
    assert "reserve_session_root" not in client.events


def observing_validation():
    from ralf_agent.temporal_session_deployment_control import SessionControlValidation
    from tests.test_temporal_deployment_session_registry import intent_request, verified
    from tests.test_temporal_session_deployment_dto import start

    proof, client = session_validation()
    i, request = intent_request(client.registry_state)
    client.registry_state.commit_session_root(request, i, verified(i, request))
    record = client.registry_state.submissions[digest([i["scope"], i["run_command_id"]])]
    client.business_epoch = "original-business-epoch"
    record["execution_epoch"] = client.business_epoch
    record["run_receipt"] = start(i, "started")["run_receipt"]
    client.business_closure = {"ready": False}
    wire = {**proof.value, "mode": "observe"}
    proof = SessionControlValidation(
        proof.runtime, client, wire, proof.info, deployment_id=proof.deployment_id
    )
    return proof, client


def test_quiet_but_not_retired_observation_cannot_advance():
    from ralf_agent.temporal_session_deployment_control import _observe

    proof, client = observing_validation()
    result = asyncio.run(_observe(proof))
    assert result == {
        "advance": None,
        "registry_execution_epoch": client.registry_epoch,
        "execution_epoch": client.business_epoch,
    }
    assert "deployment_closure" in client.events
    assert not any(e == "reserve_session_root" for e in client.events)


def test_actual_business_parent_mismatch_refuses_before_observe():
    from ralf_agent.temporal_session_deployment_control import _observe

    proof, client = observing_validation()
    client.business_parent_epoch = "forged-coordinator-epoch"
    with pytest.raises(DefinitionMismatch):
        asyncio.run(_observe(proof))
    assert "deployment_closure" not in client.events


class BusinessHandle(Handle):
    async def describe(self):
        from ralf_agent.temporal_state import WORKFLOW_NAME

        c, i = self.client, self.client.intent
        c.event("business_describe")
        if not hasattr(c, "business_epoch"):
            from ralf_agent.errors import NotFound

            raise NotFound("original child not visible")
        return SimpleNamespace(
            id=i["run_id"],
            run_id=c.business_epoch,
            namespace=c.namespace,
            workflow_type=WORKFLOW_NAME,
            task_queue=i["submission"]["task_queue"],
            parent_id=i["coordinator_id"],
            parent_run_id=getattr(c, "business_parent_epoch", i["coordinator_execution_epoch"]),
            raw_info=SimpleNamespace(first_run_id=c.business_epoch),
        )

    def fetch_history_events(self, **kwargs):
        async def events():
            from temporalio.api.common.v1 import Payloads, WorkflowExecution, WorkflowType
            from temporalio.api.history.v1 import (
                HistoryEvent,
                WorkflowExecutionStartedEventAttributes,
            )
            from temporalio.api.taskqueue.v1 import TaskQueue

            from ralf_agent.temporal_state import WORKFLOW_NAME

            c, i = self.client, self.client.intent
            payload = await c.data_converter.encode(
                [
                    {
                        "scope": i["scope"],
                        "command_id": i["run_command_id"],
                        "request": i["submission"]["request"],
                        "manifest": i["submission"]["manifest"],
                        "activity_timeout": i["submission"]["activity_timeout"],
                        "deployment_admission": {
                            "version": 2,
                            "root": c.registry_state.submissions[
                                digest([i["scope"], i["run_command_id"]])
                            ]["reservation"]["root_admission"],
                            "lineage": [],
                            "session_origin": c.registry_state.session_roots[
                                digest([i["scope"], i["run_command_id"]])
                            ]["session_origin"],
                        },
                    }
                ]
            )
            yield HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    workflow_type=WorkflowType(name=WORKFLOW_NAME),
                    task_queue=TaskQueue(name=i["submission"]["task_queue"]),
                    input=Payloads(payloads=payload),
                    original_execution_run_id=c.business_epoch,
                    first_execution_run_id=c.business_epoch,
                    parent_workflow_namespace=c.namespace,
                    parent_workflow_execution=WorkflowExecution(
                        workflow_id=i["coordinator_id"], run_id=i["coordinator_execution_epoch"]
                    ),
                ),
            )

        return events()

    async def query(self, name, value):
        self.client.event(value["kind"])
        if value["kind"] == "submission":
            return copy.deepcopy(self.client.original_submission_receipt)
        if value["kind"] == "deployment_closure":
            return copy.deepcopy(self.client.business_closure)
        if value["kind"] == "deployment_admission":
            return copy.deepcopy(self.client.business_closure["deployment"])
        if value["kind"] == "session_proof":
            return copy.deepcopy(self.client.business_session_proof)
        if value["kind"] == "deployment_start":
            i, c = self.client.intent, self.client
            return {
                "scope": i["scope"],
                "run_id": i["run_id"],
                "execution_epoch": c.business_epoch,
                "activity_timeout": i["submission"]["activity_timeout"],
                "task_queue": i["submission"]["task_queue"],
                "request_digest": digest(i["submission"]["request"]),
                "manifest_digest": digest(i["submission"]["manifest"]),
            }
        raise AssertionError(value)


def receipt_request(*, rejected=False):
    runtime, client, info, request = registry_fixture()
    i = client.intent
    binding = copy.deepcopy(i["binding"])
    if rejected:
        binding["task_queue"] = "requested-rebind-queue"
    payload = {
        "kind": "rebind" if rejected else "open",
        "scope": i["scope"],
        "command_id": "rebind" if rejected else "open",
        "binding": binding,
    }
    if rejected:
        payload.update(session_ref=i["session_ref"], expected_binding_revision=1)
    receipt = {
        "command_id": payload["command_id"],
        "kind": "session_" + payload["kind"],
        "run_id": None,
        "record_state": "durably_recorded",
        "apply_state": "rejected" if rejected else "applied",
        "outcome": {"error": "session_busy"} if rejected else {"session_ref": i["session_ref"]},
    }
    client.session_receipt_result = {
        "receipt": receipt,
        "session_ref": copy.deepcopy(i["session_ref"]),
    }
    request["mode"] = "session_receipt"
    request["prepared"] = {
        "session_submission": {
            "version": 1,
            "session_key": i["session_ref"]["key"],
            "payload": payload,
            "logical_payload": {},
            "binding": binding,
        },
        "receipt": receipt,
    }
    info.task_queue = binding["task_queue"]
    return runtime, client, info, request


def test_original_applied_open_receipt_is_indexed_only_after_actual_sdk_reads():
    from ralf_agent.temporal_session_deployment_control import verify_registry_request

    runtime, client, info, request = receipt_request()
    result = asyncio.run(verify_registry_request(runtime, client, request, info=info))
    assert result == {"ok": True, "result": request["prepared"]}
    assert "deployment_session_receipt" in client.events


def test_rejected_rebind_receipt_keeps_original_ref_without_adopting_requested_binding():
    from ralf_agent.temporal_session_deployment_control import verify_registry_request

    runtime, client, info, request = receipt_request(rejected=True)
    result = asyncio.run(verify_registry_request(runtime, client, request, info=info))
    assert result == {"ok": True, "result": request["prepared"]}
    assert client.session_receipt_result["session_ref"]["definition_digest"] != digest(
        request["prepared"]["session_submission"]["binding"]
    )


def test_lost_end_ack_keeps_owned_debt_and_retries_same_original_ack():
    from ralf_agent.temporal_session_deployment_control import owned_control_body

    async def scenario():
        proof, client = validation()
        client.lose_end_reply = True
        client.end_attempted = asyncio.Event()
        bodies = []

        async def body():
            bodies.append("once")
            client.body_stopped = True
            return {"observed": True}

        task = asyncio.create_task(owned_control_body(proof, body))
        await client.end_attempted.wait()
        # Allow the failed end callback to finish; the body is already stopped.
        await asyncio.sleep(0)
        assert not task.done()
        assert not await proof.runtime._deployment_execution_owner.wait(wait_timeout=0)
        assert await proof.runtime._deployment_execution_owner.wait(wait_timeout=1)
        result = await task
        assert result["call_end"] == client.original_end_ack
        assert bodies == ["once"]
        assert len(client.calls) == 1

    asyncio.run(scenario())


def test_never_claimed_requires_positive_original_durable_barrier():
    from ralf_agent.temporal_session_deployment_control import verify_registry_request
    from tests.test_temporal_deployment_session_registry import refusal_request

    runtime, client, info, request = registry_fixture()
    refusal = refusal_request(client.intent)
    request["mode"] = "session_never_claimed"
    request["prepared"] = {**request["prepared"], "request": refusal, "barrier": refusal["barrier"]}
    # An absent child/start event is not evidence of the recorded barrier.
    with pytest.raises(DefinitionMismatch):
        asyncio.run(verify_registry_request(runtime, client, request, info=info))
    client.lifecycle["refusal_barrier"] = refusal["barrier"]
    result = asyncio.run(verify_registry_request(runtime, client, request, info=info))
    assert result["result"]["barrier"] == refusal["barrier"]
    client.lifecycle["start_issued"] = True
    with pytest.raises(DefinitionMismatch):
        asyncio.run(verify_registry_request(runtime, client, request, info=info))


def test_factory_registration_pins_verifier_source_ports(monkeypatch):
    from ralf_agent.temporal_session_deployment_control import (
        SessionControlValidation,
        is_registered_activity,
        registered_session_deployment_activities,
    )

    _, value, _ = fixture()
    client, runtime = Client(value), Runtime(value["intent"]["binding"]["manifest"])
    function = registered_session_deployment_activities(runtime, client)[0]
    monkeypatch.setattr(SessionControlValidation, "validate", lambda self: None)
    assert not is_registered_activity(runtime, client, function)


def positive_observation():
    from tests.test_temporal_session_deployment_state import advance

    proof, client = observing_validation()
    evidence = advance(SimpleNamespace(intent=proof.intent))
    deployment = evidence["closure"]["deployment"]
    receipt = {
        "version": 1,
        "run_id": proof.intent["run_id"],
        "execution_epoch": client.business_epoch,
        "root": deployment["admission_receipt"]["root"],
        "metadata_digest": digest(deployment["admission"]),
    }
    receipt["proof_digest"] = digest(receipt)
    deployment["admission_receipt"] = receipt
    deployment["proof_digest"] = digest(
        {k: v for k, v in deployment.items() if k != "proof_digest"}
    )
    seal = evidence["closure"]["seal"]
    seal["receipt_digest"] = digest(receipt)
    seal["proof_digest"] = digest({k: v for k, v in seal.items() if k != "proof_digest"})
    evidence["retirement"]["certificate"] = copy.deepcopy(seal)
    client.business_closure = evidence["closure"]
    client.business_session_proof = evidence["run_proof"]
    client.business_retirement = evidence["retirement"]
    return proof, client


def test_positive_original_retirement_returns_advance_without_new_reserve():
    from ralf_agent.temporal_session_deployment_control import _observe

    proof, client = positive_observation()
    result = asyncio.run(_observe(proof))
    assert result["advance"]["retirement"] == client.business_retirement
    assert result["advance"]["run_proof"] == client.business_session_proof
    assert result["advance"]["intent_digest"] == proof.intent["intent_digest"]
    assert "reserve_session_root" not in client.events


def test_sealed_run_without_original_registry_retirement_stays_pending():
    from ralf_agent.temporal_session_deployment_control import _observe

    proof, client = positive_observation()
    client.business_retirement = None
    result = asyncio.run(_observe(proof))
    assert result["advance"] is None
    assert "session_proof" not in client.events


def test_run_origin_read_verifier_needs_no_fabricated_activity_identity():
    from ralf_agent.temporal_session_deployment_verification import validate_session_origin

    runtime, client, _, request = registry_fixture()
    prepared = request["prepared"]
    result = asyncio.run(
        validate_session_origin(runtime, client, prepared["intent"], prepared["session_origin"])
    )
    assert result == {k: prepared[k] for k in ("intent", "session_origin")}


def test_register_records_original_child_receipt_after_worker_bound_before_facade_ack():
    from ralf_agent.temporal_session_deployment_control import _register

    proof, client = observing_validation()
    proof.value["mode"] = "register"
    # Preserve the invocation request pin by constructing a new register context.
    from ralf_agent.temporal_session_deployment_control import SessionControlValidation

    proof = SessionControlValidation(
        proof.runtime, client, proof.value, proof.info, deployment_id=proof.deployment_id
    )
    record = client.registry_state.submissions[
        digest([proof.intent["scope"], proof.intent["run_command_id"]])
    ]
    client.original_submission_receipt = copy.deepcopy(record["run_receipt"])
    record["execution_epoch"] = record["run_receipt"] = None
    client.lifecycle["start_issued"] = True
    result = asyncio.run(_register(proof))
    assert result["start"]["phase"] == "started"
    assert result["execution_epoch"] == client.business_epoch
    assert client.events.count("record_deployment_submission") == 1
    assert "reserve_session_root" not in client.events


@pytest.mark.parametrize("outcome", ["rejected", "uncertain"])
def test_unacknowledged_call_start_preserves_failure_without_unobserved_ack_future(outcome):
    import gc

    from ralf_agent.temporal_session_deployment_control import owned_control_body

    async def scenario():
        proof, client = validation()
        expected = (
            TimeoutError("uncertain original call-start reply") if outcome == "uncertain" else None
        )
        client.start_error, client.start_denied = expected, outcome == "rejected"
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        unobserved = []
        loop.set_exception_handler(lambda loop, context: unobserved.append(context))
        bodies = []

        async def body():
            bodies.append("must not start")
            return {}

        try:
            try:
                await owned_control_body(proof, body)
            except Exception as actual:
                if expected is not None:
                    assert actual is expected
                else:
                    assert isinstance(actual, DefinitionMismatch)
                actual.__traceback__ = None
            else:
                pytest.fail("Original call-start failure must propagate")
            if outcome == "uncertain":
                assert not await proof.runtime._deployment_execution_owner.wait(wait_timeout=0)
                # The original control body never ran; a healed original start
                # readback must still end its admitted Session call explicitly.
                client.body_stopped = True
            client.start_error = None
            assert await proof.runtime._deployment_execution_owner.wait(wait_timeout=1)
            gc.collect()
            await asyncio.sleep(0)
            assert bodies == []
            if outcome == "uncertain":
                assert client.original_end_ack["body_result_digest"] == digest(
                    {"ok": False, "code": "session_control_start_unavailable"}
                )
            else:
                assert "session_deployment_call_end" not in client.events
            assert unobserved == []
        finally:
            loop.set_exception_handler(previous)

    asyncio.run(scenario())


def test_capacity_retry_uses_new_sdk_update_after_completed_capacity_failure(monkeypatch):
    from ralf_agent.temporal_session_deployment_control import _register

    original_update = RegistryHandle.execute_update
    outcomes = {}

    async def deduplicated(self, name, value, **options):
        if name != "reserve_session_root":
            return await original_update(self, name, value, **options)
        key = options["id"]
        if key in outcomes:
            outcome = outcomes[key]
            if isinstance(outcome, Exception):
                raise outcome
            return copy.deepcopy(outcome)
        try:
            outcome = await original_update(self, name, value, **options)
        except Exception as exc:
            outcomes[key] = exc
            raise
        outcomes[key] = copy.deepcopy(outcome)
        return outcome

    monkeypatch.setattr(RegistryHandle, "execute_update", deduplicated)
    proof, client = session_validation()
    client.registry_state.roots["occupied-original-root"] = {"scope": proof.intent["scope"]}
    first = asyncio.run(_register(proof))
    assert first["start"]["phase"] == "capacity-deferred"
    client.registry_state.roots.clear()
    second = asyncio.run(_register(proof))
    assert second["start"]["phase"] == "held-unbound"
    assert len(client.registry_state.roots) == 1
    assert second["start"]["intent"] == first["start"]["intent"]


def test_lost_applied_call_start_reply_recovers_original_owner_and_ends_without_body(monkeypatch):
    from ralf_agent.temporal_session_deployment_control import owned_control_body

    original_update = Handle.execute_update
    starts = {}
    attempts = []

    async def deduplicated(self, name, value, **options):
        if name != "session_deployment_call_start":
            return await original_update(self, name, value, **options)
        key = options["id"]
        attempts.append(key)
        if key in starts:
            return copy.deepcopy(starts[key])
        result = await original_update(self, name, value, **options)
        starts[key] = copy.deepcopy(result)
        self.client.body_stopped = True
        raise TimeoutError("original call start committed but its reply was lost")

    monkeypatch.setattr(Handle, "execute_update", deduplicated)

    async def scenario():
        proof, client = validation()
        bodies = []

        async def body():
            bodies.append("must-not-run")
            return {}

        with pytest.raises(TimeoutError):
            await owned_control_body(proof, body)
        assert await proof.runtime._deployment_execution_owner.wait(wait_timeout=1)
        assert bodies == []
        assert len(client.calls) == 1
        assert len(attempts) == 2 and attempts[0] == attempts[1]
        assert client.original_end_ack["identity"] == client.calls[0]
        assert client.original_end_ack["body_result_digest"] == digest(
            {"ok": False, "code": "session_control_start_unavailable"}
        )
        assert client.original_end_ack["body_stopped"] is True
        assert client.original_end_ack["recorded"] is True

    asyncio.run(scenario())
