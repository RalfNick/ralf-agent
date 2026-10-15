"""Closing admits only the original factory ACK through its full SDK gate."""

import asyncio
from types import MethodType, SimpleNamespace

import pytest

from ralf_agent import Scope
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import ACK_ACTIVITY


def environment(monkeypatch):
    from temporalio import activity

    from ralf_agent import temporal_activities as activities
    from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner
    from ralf_agent.temporal_deployment_execution import wrap_activities
    from tests.test_temporal_session_deployment_control import positive_observation

    proof, client = positive_observation()
    runtime = proof.runtime
    runtime.orchestration_release = runtime.manifest
    runtime.model_continuation = runtime.coding_execution = False
    runtime.acknowledge_evidence = MethodType(TemporalRuntime.acknowledge_evidence, runtime)
    received = []

    class Journal:
        async def acknowledge(self, envelope, observation):
            received.append((envelope, observation))

    runtime.journal = Journal()
    info = SimpleNamespace(
        workflow_id=proof.intent["run_id"],
        workflow_run_id=client.business_epoch,
        workflow_namespace=client.namespace,
        activity_id="ack:original-action:1",
        activity_type=ACK_ACTIVITY,
        attempt=1,
    )
    monkeypatch.setattr(activity, "info", lambda: info)
    original = next(
        function
        for function in activities.registered_activities(runtime, client)
        if activity._Definition.from_callable(function).name == ACK_ACTIVITY
    )
    guarded = wrap_activities(runtime, client, [original])[0]
    # This is the same trusted registration step used by build_temporal_worker;
    # no request or Activity name can create an entry in this weak registry.
    activities._register_evidence_wrapper(runtime, client, original, guarded)
    owner = WorkerExecutionOwner(scope=Scope(**proof.intent["scope"]), release=runtime.manifest)
    wrapped = owner.wrap_activities(
        [guarded], client=client, runtime=runtime, maintenance=((guarded, "evidence"),)
    )[0]
    request = {
        "scope": proof.intent["scope"],
        "run_id": info.workflow_id,
        "execution_epoch": info.workflow_run_id,
        "runtime_manifest": runtime.manifest,
        "action_id": "original-action",
        "attempt_id": "original-action:attempt:1",
        "effect_key": "original-effect",
        "tool_manifest": {"name": "write"},
        "arguments": {},
        "operation_digest": "a" * 64,
        "result": {"committed": True},
        "source": "manual-evidence",
    }
    root = client.business_closure["deployment"]["admission"]["root"]
    client.registry_state.bind_deployment_root(
        {
            "scope": root["scope"],
            "namespace": root["namespace"],
            "admission_policy": client.registry_state.policy,
            **{
                key: root[key]
                for key in (
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "execution_epoch": client.business_epoch,
        }
    )
    client.business_retirement = None
    # Mock SDK read/Update responses, retaining the real universal proof and ownership wrappers.
    from tests.test_temporal_session_deployment_control import RegistryHandle

    state = SimpleNamespace(deployment_calls={})
    original_handle = client.get_workflow_handle

    class Handle:
        def __init__(self, original):
            self.original = original

        def __getattr__(self, name):
            return getattr(self.original, name)

        async def query(self, name, value):
            if value["kind"] == "deployment_admission" and self.original is not None:
                client.events.append("original-sdk-proof")
            if value["kind"] == "deployment_admission" and isinstance(
                self.original, RegistryHandle
            ):
                return client.registry_state.deployment_admission(value)
            return await self.original.query(name, value)

        async def execute_update(self, name, value, **options):
            if name == "deployment_call_started":
                client.events.append(name)
                state.deployment_calls[value["activity_id"]] = {"stopped": False}
                return {
                    **{key: value[key] for key in ("activity_id", "attempt", "invocation_id")},
                    "allowed": True,
                }
            if name == "deployment_call_ended":
                client.events.append(name)
                state.deployment_calls[value["activity_id"]]["stopped"] = True
                return {
                    **{key: value[key] for key in ("activity_id", "attempt", "invocation_id")},
                    "recorded": True,
                }
            return await self.original.execute_update(name, value, **options)

    monkeypatch.setattr(
        client, "get_workflow_handle", lambda *a, **kw: Handle(original_handle(*a, **kw))
    )
    return runtime, client, info, owner, wrapped, guarded, request, received, state


def test_original_evidence_ack_remains_owned_and_sdk_guarded_after_close(monkeypatch):
    async def run():
        runtime, client, _, owner, wrapped, _, request, received, state = environment(monkeypatch)
        owner.stop_admission()
        try:
            assert await wrapped(request) == {"ok": True}
            assert len(received) == 1
            assert "original-sdk-proof" in client.events
            assert "deployment_call_started" in client.events
            assert "deployment_call_ended" in client.events
            assert all(call["stopped"] for call in state.deployment_calls.values())
        finally:
            await owner.aclose(wait_timeout=2)
            await runtime._deployment_execution_owner.aclose(wait_timeout=2)

    asyncio.run(run())


@pytest.mark.parametrize("change", ["scope", "epoch", "leaf"])
def test_closing_ack_identity_failure_never_reaches_journal(monkeypatch, change):
    async def run():
        runtime, _, _, owner, wrapped, _, request, received, _ = environment(monkeypatch)
        owner.stop_admission()
        if change == "scope":
            request = {**request, "scope": {**request["scope"], "principal": "foreign"}}
        elif change == "epoch":
            request = {**request, "execution_epoch": "replacement"}
        else:
            runtime.acknowledge_evidence = lambda value: None
        try:
            with pytest.raises(DefinitionMismatch):
                await wrapped(request)
            assert received == []
        finally:
            await owner.aclose(wait_timeout=2)
            await runtime._deployment_execution_owner.aclose(wait_timeout=2)

    asyncio.run(run())


def test_copied_ack_wrapper_cannot_claim_original_maintenance(monkeypatch):
    from types import FunctionType

    runtime, client, _, owner, _, original, _, _, _ = environment(monkeypatch)
    copied = FunctionType(
        original.__code__,
        original.__globals__,
        original.__name__,
        original.__defaults__,
        original.__closure__,
    )
    copied.__dict__.update(original.__dict__)
    with pytest.raises(DefinitionMismatch):
        owner.wrap_activities(
            [copied], client=client, runtime=runtime, maintenance=((copied, "evidence"),)
        )


def test_closing_new_business_activity_still_refused(monkeypatch):
    from temporalio import activity

    async def run():
        runtime, client, _, owner, _, _, request, received, _ = environment(monkeypatch)

        @activity.defn(name=ACK_ACTIVITY)
        async def forged(value: dict) -> dict:
            raise AssertionError("Caller name is not maintenance authority")

        wrapped = owner.wrap_activities([forged], client=client, runtime=runtime)[0]
        owner.stop_admission()
        try:
            with pytest.raises(ValidationError, match="admission is closed"):
                await wrapped(request)
            assert received == []
        finally:
            await owner.aclose(wait_timeout=2)
            await runtime._deployment_execution_owner.aclose(wait_timeout=2)

    asyncio.run(run())


def test_actual_worker_registers_each_original_evidence_wrapper_without_overwrite(monkeypatch):
    import temporalio.worker
    from temporalio import activity

    from ralf_agent.temporal import build_temporal_worker
    from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner, _evidence_registration
    from tests.test_temporal_session_deployment_worker import client, runtime

    selected, connection = runtime(), client()
    captured = []
    monkeypatch.setattr(
        temporalio.worker, "Worker", lambda *args, **kwargs: captured.append(kwargs)
    )
    originals = []
    for _ in range(2):
        owner = WorkerExecutionOwner(scope=Scope(), release=selected.orchestration_release)
        build_temporal_worker(
            connection, task_queue="original", runtime=selected, activity_owner=owner
        )
        functions = {
            activity._Definition.from_callable(function).name: function
            for function in captured[-1]["activities"]
        }
        originals.append(functions[ACK_ACTIVITY].__wrapped__)
    assert originals[0] is not originals[1]
    assert all(_evidence_registration(selected, connection, original) for original in originals)
    assert not _evidence_registration(runtime(), connection, originals[0])
    assert not _evidence_registration(selected, client(), originals[0])


def test_unwrapped_or_named_ack_cannot_register_maintenance(monkeypatch):
    from temporalio import activity

    runtime, client, _, owner, _, original, _, _, _ = environment(monkeypatch)

    @activity.defn(name=ACK_ACTIVITY)
    async def copied_name(request: dict) -> dict:
        return {"ok": True}

    for candidate in (original.__wrapped__, copied_name):
        with pytest.raises(DefinitionMismatch):
            owner.wrap_activities(
                [candidate], client=client, runtime=runtime, maintenance=((candidate, "evidence"),)
            )
