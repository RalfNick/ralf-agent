"""Bind read evidence to the actual original Activity run and client namespace."""

import asyncio
from types import SimpleNamespace

import pytest

from relf_agent.errors import DefinitionMismatch

from .test_temporal_context_read_state import admission, proof, state_for


class Client:
    namespace = "original-namespace"

    def __init__(self, state):
        self.state, self.handles, self.updates = state, [], []
        self.end_response = None

    def get_workflow_handle(self, workflow_id, *, run_id=None):
        self.handles.append((workflow_id, run_id))
        return self

    async def query(self, name, value):
        assert name == "view" and value["kind"] == "status"
        self.state.authorize(value["scope"])
        return self.state.snapshot()

    async def describe(self):
        from relf_agent.temporal_state import WORKFLOW_NAME

        return SimpleNamespace(
            id=self.state.run_id,
            run_id=self.state.epoch,
            namespace=self.namespace,
            workflow_type=WORKFLOW_NAME,
            raw_info=SimpleNamespace(first_run_id=self.state.epoch),
        )

    async def signal(self, *args, **options):
        raise AssertionError("An exactly identified legacy Worker must receive no Signal")

    async def execute_update(self, name, payload, *, id):
        self.updates.append((name, payload, id))
        if name == "admit_context_dispatch":
            return self.state.admit_context_dispatch(payload)
        assert name == "context_execution_ended"
        from relf_agent.types import digest

        assert id == "ralf-context-read-ended:" + digest(payload)
        if self.end_response is not None:
            return self.end_response
        return self.state.context_execution_ended(payload)


def setup():
    state, action, request = state_for()
    client = Client(state)
    info = SimpleNamespace(
        workflow_id=state.run_id,
        workflow_run_id=state.epoch,
        workflow_namespace=client.namespace,
    )
    return state, action, request, client, info


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_id", "foreign-workflow"),
        ("workflow_run_id", "foreign-epoch"),
        ("workflow_namespace", "foreign-namespace"),
    ],
)
def test_read_worker_rejects_foreign_actual_activity_before_admission(field, value):
    from relf_agent.temporal_context_read_activities import callbacks

    async def run():
        _, _, request, client, info = setup()
        setattr(info, field, value)
        guard, _ = callbacks(client, request, info)
        with pytest.raises(DefinitionMismatch):
            await guard(request)
        assert client.updates == []

    asyncio.run(run())


def test_end_callback_keeps_original_run_uuid_without_live_activity_context():
    from relf_agent.temporal_context_read_activities import callbacks

    async def run():
        state, _, request, client, info = setup()
        guard, ended = callbacks(client, request, info)
        assert (await guard(request))["allowed"] is True
        info.workflow_run_id = "new-activity"
        assert await ended(proof(request)) is None
        assert client.handles and set(client.handles) == {(state.run_id, state.epoch)}
        assert client.updates[-1][0] == "context_execution_ended"
        assert not state.quiescent  # Actual end alone cannot consume the response.
        before = state.revision
        await ended(proof(request))
        assert state.revision == before

    asyncio.run(run())


def test_client_namespace_change_refuses_late_end_notification():
    from relf_agent.temporal_context_read_activities import callbacks

    async def run():
        state, _, request, client, info = setup()
        guard, ended = callbacks(client, request, info)
        await guard(request)
        client.namespace = "replacement-namespace"
        with pytest.raises(DefinitionMismatch):
            await ended(proof(request))
        assert state.diagnostics()["context_reads"][0]["execution_end_proof"] is None
        assert len(client.updates) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "ack",
    [
        {"recorded": True},
        {"action_id": "other", "recorded": True},
        {"action_id": "run:context:0:1", "recorded": 1},
    ],
)
def test_truthy_or_foreign_end_ack_is_not_completion(ack):
    from relf_agent.temporal_context_read_activities import callbacks

    async def run():
        _, _, request, client, info = setup()
        guard, ended = callbacks(client, request, info)
        await guard(request)
        client.end_response = ack
        with pytest.raises(DefinitionMismatch):
            await ended(proof(request))

    asyncio.run(run())


def test_actual_workflow_end_update_records_only_original_read_evidence():
    pytest.importorskip("temporalio")
    from relf_agent.temporal_workflow import TemporalRunWorkflow

    async def run():
        state, _, request, _, _ = setup()
        state.admit_context_dispatch(admission(request))
        workflow = SimpleNamespace(state=state, wake_revision=0)
        ack = await TemporalRunWorkflow.context_execution_ended(workflow, proof(request))
        assert ack == {"action_id": request["action_id"], "recorded": True}
        assert workflow.wake_revision == 1 and not state.quiescent

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["context", "plan", "read", "verify", "finalize"])
def test_original_read_activity_is_single_attempt_only_for_explicit_protocol(phase):
    from relf_agent.temporal_context_read_protocol import owns_activity

    state, action, _ = state_for(phase)
    assert owns_activity(state.manifest, action)
    legacy = dict(state.manifest)
    legacy.pop("context_read_protocol")
    assert not owns_activity(legacy, action)
    assert not owns_activity(state.manifest, {"kind": "managed_context", "phase": "write"})
    assert not owns_activity(state.manifest, {"kind": "managed_context", "phase": "summary"})


def test_read_owner_spi_is_exported_without_loading_optional_sdk():
    import relf_agent as r

    assert r.ContextExecutionOwner().identity["kind"] == "context-execution-owner"
    assert r.ContextExecutionPort.execute
    error = r.ContextExecutionRejected(handler_not_started=True)
    assert error.handler_not_started is True


def test_original_read_stages_query_is_pure_and_detached():
    pytest.importorskip("temporalio")
    from relf_agent.temporal_workflow import TemporalRunWorkflow

    state, _, request, _, _ = setup()
    state.admit_context_dispatch(admission(request))
    workflow = SimpleNamespace(state=state)
    stages = TemporalRunWorkflow.view(
        workflow, {"scope": state.scope, "kind": "context_read_stages"}
    )
    assert isinstance(stages, list) and stages[0]["response_observed"] is False
    stages[0]["response_observed"] = True
    assert state.diagnostics()["context_reads"][0]["response_observed"] is False


def test_engine_read_stage_api_only_queries_original_history():
    from relf_agent.temporal import TemporalEngine

    async def run():
        seen = []

        class Engine:
            async def _view(self, run_id, kind):
                seen.append((run_id, kind))
                return [{"action_id": "original"}]

        assert await TemporalEngine.context_read_stages(Engine(), "original") == [
            {"action_id": "original"}
        ]
        assert seen == [("original", "context_read_stages")]

    asyncio.run(run())


def test_worker_and_replayer_preload_pure_original_read_rules():
    pytest.importorskip("temporalio")
    from relf_agent.temporal import _workflow_runner

    modules = _workflow_runner().restrictions.passthrough_modules
    assert {
        "relf_agent.temporal_context",
        "relf_agent.temporal_context_read_protocol",
        "relf_agent.temporal_context_read_state",
    } <= modules
