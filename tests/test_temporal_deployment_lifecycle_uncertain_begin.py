"""An accepted begin with an invalid ACK remains an original end obligation."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")

from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.types import digest
from tests.test_temporal_deployment_release import environment, module


def corrupt_begin_ack(monkeypatch, *, persistent):
    from temporalio import activity

    runtime, client, state, proof, info = environment(monkeypatch)
    monkeypatch.setattr(activity, "info", lambda: info)
    get_handle = client.get_workflow_handle
    control = {"corrupt": True}
    requests = []

    def handle(*args, **options):
        original = get_handle(*args, **options)
        update = original.execute_update

        async def execute(name, request, **update_options):
            result = await update(name, request, **update_options)
            if name == "deployment_call_started":
                requests.append((copy.deepcopy(request), copy.deepcopy(update_options)))
                if control["corrupt"]:
                    if not persistent:
                        control["corrupt"] = False
                    # The original reducer has already accepted the complete
                    # invocation. An invalid receipt cannot prove no grant.
                    return {**result, "unexpected": True}
            return result

        original.execute_update = execute
        return original

    client.get_workflow_handle = handle
    called = []

    @activity.defn(name="test.business")
    async def body(request: dict) -> dict:
        called.append(copy.deepcopy(request))
        return {"done": True}

    carrier = {"scope": state.scope, "_deployment_activity_request": {"input": "original"}}
    return runtime, client, state, proof, control, requests, called, body, carrier


def assert_original_begin_requests(requests):
    assert len(requests) >= 2
    identity, options = requests[0]
    assert options == {"id": "ralf-deployment-call:" + digest(identity)}
    assert all(request == identity and selected == options for request, selected in requests)


def test_invalid_first_accepted_begin_ack_recovers_same_invocation_end_without_business(
    monkeypatch,
):
    async def run():
        runtime, client, state, proof, _, requests, called, body, carrier = corrupt_begin_ack(
            monkeypatch, persistent=False
        )
        with module().activity_context(runtime, client, proof, carrier):
            with pytest.raises(DefinitionMismatch):
                await module().wrap_activity(runtime, client, body)(
                    carrier["_deployment_activity_request"]
                )
        await module().close_owner(runtime, wait_timeout=2)
        assert called == []
        assert_original_begin_requests(requests)
        assert len(state.deployment_calls) == 1
        record = next(iter(state.deployment_calls.values()))
        assert record["stopped"] is True and record["end_proof"] == requests[0][0]
        ends = [entry for entry in client.updates if entry[2] == "deployment_call_ended"]
        assert len(ends) == 1 and ends[0][3] == requests[0][0]
        assert not runtime._deployment_execution_owner._entries

    asyncio.run(run())


def test_persistently_invalid_accepted_begin_ack_keeps_owner_until_original_end_confirmed(
    monkeypatch,
):
    async def run():
        runtime, client, state, proof, control, requests, called, body, carrier = corrupt_begin_ack(
            monkeypatch, persistent=True
        )
        try:
            with module().activity_context(runtime, client, proof, carrier):
                with pytest.raises(DefinitionMismatch):
                    await module().wrap_activity(runtime, client, body)(
                        carrier["_deployment_activity_request"]
                    )
            with pytest.raises(CloseIncomplete):
                await module().close_owner(runtime, wait_timeout=0.03)
            assert called == []
            assert_original_begin_requests(requests)
            assert len(state.deployment_calls) == 1
            record = next(iter(state.deployment_calls.values()))
            assert record["stopped"] is False and record["end_proof"] is None
            assert not [entry for entry in client.updates if entry[2] == "deployment_call_ended"]
            assert len(runtime._deployment_execution_owner._entries) == 1
        finally:
            control["corrupt"] = False
            await module().close_owner(runtime, wait_timeout=2)
        assert next(iter(state.deployment_calls.values()))["stopped"] is True
        assert called == [] and not runtime._deployment_execution_owner._entries

    asyncio.run(run())


@pytest.mark.parametrize("transport", ["legacy", "signal"])
def test_original_handler_refusal_closes_owner_without_grant_business_or_end(
    monkeypatch, transport
):
    from temporalio import activity
    from temporalio.client import WorkflowUpdateFailedError
    from temporalio.exceptions import ApplicationError

    from ralf_agent import temporal_deployment_lifecycle_transport as lifecycle
    from ralf_agent.temporal_state import TemporalRunState
    from ralf_agent.temporal_workflow import TemporalRunWorkflow

    async def run():
        runtime, client, state, proof, info = environment(monkeypatch)
        monkeypatch.setattr(activity, "info", lambda: info)
        get_handle = client.get_workflow_handle
        requests, signals, called = [], [], []
        original_info = SimpleNamespace(
            workflow_id=state.run_id,
            namespace=client.namespace,
            run_id=state.epoch,
            first_execution_run_id=state.epoch,
            original_execution_run_id=state.epoch,
        )
        host = object.__new__(TemporalRunWorkflow)
        host.state, host.wake_revision = state, 0
        state.authorize = lambda scope: TemporalRunState.authorize(state, scope)
        if transport == "signal":
            # A real original reducer refuses all new grants after its seal.
            # No call record is created and no business handler has started.
            state.deployment_seal = {"irreversible": True}

        class Handle:
            def __init__(self, original):
                self.original = original

            def __getattr__(self, name):
                return getattr(self.original, name)

            async def query(self, name, request):
                if transport == "signal" and "deployment_lifecycle_observation" in request:
                    return {
                        "deployment_lifecycle_observation": lifecycle.observe(
                            host, request["deployment_lifecycle_observation"], original_info
                        )
                    }
                return await self.original.query(name, request)

            async def signal(self, name, envelope):
                assert transport == "signal" and name == "deployment_lifecycle"
                signals.append(copy.deepcopy(envelope))
                await lifecycle.accept(host, envelope, original_info)

            async def execute_update(self, name, request, **options):
                if name == "deployment_call_started":
                    requests.append((copy.deepcopy(request), copy.deepcopy(options)))
                    assert transport == "legacy"
                    raise WorkflowUpdateFailedError(
                        ApplicationError(
                            "Original call is refused",
                            type="definition_mismatch",
                            non_retryable=True,
                        )
                    )
                return await self.original.execute_update(name, request, **options)

        client.get_workflow_handle = lambda *args, **options: Handle(get_handle(*args, **options))

        @activity.defn(name="test.business")
        async def body(request: dict) -> dict:
            called.append(copy.deepcopy(request))
            return {"done": True}

        carrier = {"scope": state.scope, "_deployment_activity_request": {"input": "original"}}
        with module().activity_context(runtime, client, proof, carrier):
            with pytest.raises(lifecycle.LifecycleRefused) as rejected:
                await module().wrap_activity(runtime, client, body)(
                    carrier["_deployment_activity_request"]
                )
        assert type(rejected.value) is lifecycle.LifecycleRefused
        assert rejected.value.code == "definition_mismatch"
        await module().close_owner(runtime, wait_timeout=2)
        assert not runtime._deployment_execution_owner._entries
        assert called == [] and state.deployment_calls == {}
        assert not [entry for entry in client.updates if entry[2] == "deployment_call_ended"]
        if transport == "legacy":
            assert len(requests) == 1 and not signals
            assert requests[0][1] == {"id": "ralf-deployment-call:" + digest(requests[0][0])}
        else:
            assert len(signals) == 1 and not requests

    asyncio.run(run())
