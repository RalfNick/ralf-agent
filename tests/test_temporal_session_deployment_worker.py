"""Selected Session transport remains distinct from business Activity admission."""

from types import SimpleNamespace

import pytest

from ralf_agent import DeploymentAdmissionPolicy, Scope, ToolRegistry
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal_activities import TemporalRuntime


def runtime():
    return TemporalRuntime(
        providers={"default": EchoProvider("session")},
        tools=ToolRegistry(),
        enable_sessions=True,
        deployment_sessions=True,
        admission_policy=DeploymentAdmissionPolicy("worker-session"),
    )


def client():
    from tests.test_temporal_session_deployment_control import Client, fixture

    return Client(fixture()[1])


def test_selected_run_keeps_public_call_ledger_and_seal():
    from ralf_agent.temporal_deployment_release_state import initialize

    state = SimpleNamespace(manifest=runtime().manifest)
    initialize(state)
    assert state.deployment_calls == {}
    assert state.deployment_seal is None
    assert state.deployment_retirement is None


def test_worker_registers_exact_session_and_registry_transports(monkeypatch):
    import temporalio.worker
    from temporalio import activity

    from ralf_agent.temporal import build_temporal_worker
    from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner
    from ralf_agent.temporal_session_deployment_control import (
        REGISTRY_ACTIVITY,
        is_registered_activity,
        is_registered_registry_activity,
    )
    from ralf_agent.temporal_session_state import SESSION_ACTIVITY

    selected, connection = runtime(), client()
    captured = {}
    monkeypatch.setattr(temporalio.worker, "Worker", lambda *a, **kw: captured.update(kw))
    owner = WorkerExecutionOwner(scope=Scope(), release=selected.orchestration_release)
    build_temporal_worker(connection, task_queue="original", runtime=selected, activity_owner=owner)
    functions = {activity._Definition.from_callable(f).name: f for f in captured["activities"]}
    # Worker ownership is the only outer wrapper on these mechanical transports.
    assert is_registered_activity(selected, connection, functions[SESSION_ACTIVITY].__wrapped__)
    assert is_registered_registry_activity(
        selected, connection, functions[REGISTRY_ACTIVITY].__wrapped__
    )


@pytest.mark.parametrize("registry", [False, True])
def test_transport_factory_bypasses_business_gate_but_same_name_is_refused(registry):
    from temporalio import activity

    from ralf_agent.temporal_deployment_execution import wrap_activities
    from ralf_agent.temporal_session_deployment_control import (
        registered_registry_session_activities,
        registered_session_deployment_activities,
    )

    selected, connection = runtime(), client()
    factory = (
        registered_registry_session_activities
        if registry
        else registered_session_deployment_activities
    )
    original = factory(selected, connection)[0]
    assert wrap_activities(selected, connection, [original]) == [original]

    @activity.defn(name=activity._Definition.from_callable(original).name)
    async def copied(value: dict) -> dict:
        return {}

    with pytest.raises(DefinitionMismatch):
        wrap_activities(selected, connection, [copied])


def test_closing_observer_body_survives_caller_cancel_and_drains_original_end_ack(monkeypatch):
    import asyncio

    from temporalio import activity

    from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner
    from ralf_agent.temporal_session_deployment_control import (
        registered_session_deployment_activities,
    )
    from tests.test_temporal_session_deployment_control import positive_observation

    async def scenario():
        proof, connection = positive_observation()
        selected = proof.runtime
        selected.orchestration_release = selected.manifest
        entered, finish = asyncio.Event(), asyncio.Event()
        get_handle = connection.get_workflow_handle

        class GatedHandle:
            def __init__(self, original):
                self.original = original

            def __getattr__(self, name):
                return getattr(self.original, name)

            async def query(self, name, request):
                if request["kind"] == "deployment_closure":
                    entered.set()
                    await finish.wait()
                return await self.original.query(name, request)

        connection.get_workflow_handle = lambda *args, **kwargs: GatedHandle(
            get_handle(*args, **kwargs)
        )
        connection.body_stopped = True
        monkeypatch.setattr(activity, "info", lambda: proof.info)
        original = registered_session_deployment_activities(selected, connection)[0]
        owner = WorkerExecutionOwner(
            scope=Scope(**proof.intent["scope"]), release=selected.manifest
        )
        wrapped = owner.wrap_activities(
            [original],
            client=connection,
            runtime=selected,
            maintenance=((original, "session-control"),),
        )[0]
        owner.stop_admission()
        call = asyncio.create_task(wrapped(proof.value))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            assert not await owner.wait(wait_timeout=0)
            assert not await selected._deployment_execution_owner.wait(wait_timeout=0)
            assert len(connection.calls) == 1
            assert "session_deployment_call_end" not in connection.events
            retirement = connection.business_retirement.copy()
            finish.set()
            assert await owner.wait(wait_timeout=2)
            assert await selected._deployment_execution_owner.wait(wait_timeout=2)
            assert connection.original_end_ack["recorded"] is True
            assert connection.original_end_ack["body_stopped"] is True
            assert connection.original_end_ack["identity"] == connection.calls[0]
            assert connection.calls[0]["mode"] == "observe"
            assert connection.business_retirement == retirement
            assert "reserve_session_root" not in connection.events
        finally:
            finish.set()
            await asyncio.gather(call, return_exceptions=True)
            await owner.aclose(wait_timeout=2)
            await selected._deployment_execution_owner.aclose(wait_timeout=2)

    asyncio.run(scenario())


@pytest.mark.parametrize("registry", [False, True])
def test_closing_worker_refuses_new_session_or_root_registration_before_factory_body(
    monkeypatch, registry
):
    import asyncio

    from temporalio import activity

    from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner
    from ralf_agent.temporal_session_deployment_control import (
        REGISTRY_ACTIVITY,
        registered_registry_session_activities,
        registered_session_deployment_activities,
    )
    from tests.test_temporal_session_deployment_control import positive_observation

    async def scenario():
        proof, connection = positive_observation()
        selected = proof.runtime
        selected.orchestration_release = selected.manifest
        factory = (
            registered_registry_session_activities
            if registry
            else registered_session_deployment_activities
        )
        original = factory(selected, connection)[0]
        kind = "session-registry" if registry else "session-control"
        if registry:
            proof.info.activity_type = REGISTRY_ACTIVITY
        monkeypatch.setattr(activity, "info", lambda: proof.info)
        owner = WorkerExecutionOwner(
            scope=Scope(**proof.intent["scope"]), release=selected.manifest
        )
        wrapped = owner.wrap_activities(
            [original], client=connection, runtime=selected, maintenance=((original, kind),)
        )[0]
        owner.stop_admission()
        request = {**proof.value, "mode": "session_root" if registry else "register"}
        connection.events.clear()
        try:
            with pytest.raises(DefinitionMismatch):
                await wrapped(request)
            assert connection.events == []
            assert connection.calls == []
            assert await owner.wait(wait_timeout=0)
        finally:
            await owner.aclose(wait_timeout=2)
            await selected._deployment_execution_owner.aclose(wait_timeout=2)

    asyncio.run(scenario())


@pytest.mark.parametrize("registry", [False, True])
@pytest.mark.parametrize("change", ["client", "runtime", "copied-function"])
def test_worker_maintenance_requires_this_factory_object_and_original_ports(registry, change):
    from types import FunctionType

    from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner
    from ralf_agent.temporal_session_deployment_control import (
        registered_registry_session_activities,
        registered_session_deployment_activities,
    )

    selected, connection = runtime(), client()
    factory = (
        registered_registry_session_activities
        if registry
        else registered_session_deployment_activities
    )
    original = factory(selected, connection)[0]
    target_runtime, target_client, function = selected, connection, original
    if change == "client":
        target_client = client()
    elif change == "runtime":
        target_runtime = runtime()
    else:
        function = FunctionType(
            original.__code__,
            original.__globals__,
            original.__name__,
            original.__defaults__,
            original.__closure__,
        )
        function.__dict__.update(original.__dict__)
    owner = WorkerExecutionOwner(scope=Scope(), release=selected.orchestration_release)
    with pytest.raises(DefinitionMismatch):
        owner.wrap_activities(
            [function],
            client=target_client,
            runtime=target_runtime,
            maintenance=((function, "session-registry" if registry else "session-control"),),
        )
