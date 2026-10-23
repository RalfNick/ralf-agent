"""Session-origin Coding keeps native closure and its original live receiver."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent import Scope, TemporalProfile
from relf_agent.errors import DefinitionMismatch
from relf_agent.runtime_lifecycle import BuildContext
from relf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly
from relf_agent.temporal_deployment_coding_state import check_guard_registration, selected


@pytest.mark.parametrize(
    ("publication", "coding", "expected"), [(3, False, True), (4, False, False), (4, True, True)]
)
def test_only_coding_publication4_uses_native_closure(publication, coding, expected):
    manifest = {"deployment_admission_protocol": {"version": publication}}
    if coding:
        manifest["coding_execution_protocol"] = {"version": 6}
    assert selected(manifest) is expected


def test_session_coding_guard_still_checks_original_native_alias(monkeypatch):
    from relf_agent import temporal_coding_state as native

    manifest = {
        "deployment_admission_protocol": {"version": 4},
        "coding_execution_protocol": {"version": 6},
    }
    monkeypatch.setattr(native, "guard_mutation", lambda *args: False)
    with pytest.raises(DefinitionMismatch):
        check_guard_registration(manifest)
    check_guard_registration({"deployment_admission_protocol": {"version": 4}})


def test_session_coding_cold_fence_keeps_zero_charge_unknown(monkeypatch):
    from relf_agent import temporal_deployment_coding_state as coding
    from relf_agent.temporal_deployment_release_state import closure
    from tests import test_temporal_deployment_coding_state as original

    attach = original.attach
    monkeypatch.setattr(original, "attach", lambda state, patch: attach(state, patch, version=4))
    state, action, _, identity = original.cold(monkeypatch, cost=0)
    reservation = state.reservations[action["attempts"][0]["id"]]
    before = copy.deepcopy((action, reservation))
    candidate = coding.coding_call_candidate(state, identity)
    result = coding.adopt_call_fence(
        state,
        {"scope": state.scope, "identity": identity},
        {**candidate, "process_present": False, "native_fenced": True},
    )
    assert result["recorded"] is True
    assert (action, reservation) == before
    assert action["status"] == "outcome_unknown" and reservation["status"] == "unknown"
    assert reservation["amount"] == 0 and closure(state)[0] is False


def test_owned_session_coding_physical_close_precedes_session_drain_and_worker_stop(
    tmp_path, monkeypatch
):
    from relf_agent import temporal
    from relf_agent import temporal_deployment_coding_bridge as coding
    from relf_agent import temporal_deployment_release as release
    from relf_agent import temporal_session_deployment_close as sessions

    async def run():
        events = []
        coding_closed = asyncio.Event()
        scope = Scope("original", "owner")
        client = SimpleNamespace(namespace="original")

        class Resource:
            async def aclose(self):
                events.append("resource-close")

        class Worker:
            async def __aenter__(self):
                events.append("worker-start")

            async def __aexit__(self, *args):
                events.append("worker-stop")

        async def drain(**kwargs):
            pass

        context = BuildContext(None, tmp_path / "unused", scope, tmp_path, allow_async=True)
        context.own_async(Resource())
        runtime = SimpleNamespace(
            orchestration_release={
                "binding_protocol": 22,
                "coding_execution_protocol": {"version": 6},
                "session_deployment_protocol": 1,
                "deployment_admission_protocol": {"version": 4},
            },
            coding_execution=True,
            _deployment_public_execution=True,
            close_deployment_execution=drain,
            close_context_execution=drain,
            close_session_execution=drain,
        )
        profile = TemporalProfile("profile", "1", {"default": {"adapter": "echo"}})
        assembly = TemporalRuntimeAssembly(runtime, context, profile, scope)

        async def close_coding(runtime, *, client, scope, task_queue):
            assert client is assembly._client and scope is assembly.scope
            assert task_queue == "original-queue" and "worker-stop" not in events
            events.append("coding-close")
            coding_closed.set()

        async def close_sessions(runtime, *, client, scope, task_queue, wait_timeout):
            assert "worker-stop" not in events
            events.append("session-fence")
            # The original Session closes acceptance first, but cannot confirm
            # drain before its native Coding resources have actually stopped.
            await coding_closed.wait()
            assert "coding-close" in events and "worker-stop" not in events
            events.append("session-drain")

        async def retired(*args, **kwargs):
            assert "session-drain" in events and "worker-stop" not in events
            events.append("retirement")

        monkeypatch.setattr(temporal, "build_temporal_worker", lambda *a, **kw: Worker())
        monkeypatch.setattr(coding, "close", close_coding)
        monkeypatch.setattr(coding, "wait_retirement", retired)
        monkeypatch.setattr(sessions, "close", close_sessions)
        monkeypatch.setattr(release, "check_owner", lambda runtime: None)
        await assembly.start_worker(client, task_queue="original-queue")
        await assembly.aclose()
        assert events == [
            "worker-start",
            "session-fence",
            "coding-close",
            "session-drain",
            "retirement",
            "worker-stop",
            "resource-close",
        ]

    asyncio.run(run())


@pytest.mark.parametrize("composition", [False, True])
def test_session_coding_worker_preserves_original_stop_maintenance(
    tmp_path, monkeypatch, composition
):
    import temporalio.worker
    from temporalio import activity

    from relf_agent import DeploymentAdmissionPolicy
    from relf_agent.errors import ValidationError
    from relf_agent.temporal import build_temporal_worker
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_assembly_lifecycle import (
        WorkerExecutionOwner,
        _native_stop_registration,
    )
    from relf_agent.temporal_coding_factories import build
    from relf_agent.temporal_coding_state import CODING_STOP_ACTIVITY
    from relf_agent.temporal_deployment_coding_bridge import STOP_ACTIVITY
    from relf_agent.temporal_journal import PostgresEffectJournal
    from tests.test_temporal_coding_factories import Connection, entry, publish_initialization
    from tests.test_temporal_deployment_public_registry import Provider

    async def run():
        events, captured = [], {}
        publish_initialization(monkeypatch, events)
        scope = Scope()
        context = BuildContext(None, tmp_path / "unused", scope, tmp_path, allow_async=True)
        effect = context.own_async(PostgresEffectJournal(Connection(events), owns_connection=True))
        context.coding_execution, context.coding_composition, context.effect_journal = (
            True,
            composition,
            effect,
        )
        tools = await build(entry(tmp_path), context)
        selected_runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=tools,
            journal=effect,
            coding_execution=True,
            coding_composition=composition,
            enable_sessions=True,
            deployment_sessions=True,
            admission_policy=DeploymentAdmissionPolicy("coding-maintenance"),
        )

        class Client:
            namespace = "original"

            def __init__(self):
                from temporalio.converter import DataConverter

                self.data_converter = DataConverter.default
                self.workflow_service = SimpleNamespace(describe_namespace=self.describe_namespace)

            async def describe_namespace(self, request):
                raise AssertionError("No SDK namespace request expected before original proof")

            def get_workflow_handle(self, identity, *, run_id=None):
                assert (identity, run_id) == ("original-run", "original-epoch")
                raise LookupError("original SDK proof must be read")

        client = Client()
        owner = WorkerExecutionOwner(scope=scope, release=selected_runtime.orchestration_release)
        monkeypatch.setattr(temporalio.worker, "Worker", lambda *a, **kw: captured.update(kw))
        build_temporal_worker(
            client, task_queue="original", runtime=selected_runtime, activity_owner=owner
        )
        functions = {activity._Definition.from_callable(f).name: f for f in captured["activities"]}
        try:
            assert STOP_ACTIVITY in functions
            assert _native_stop_registration(
                selected_runtime, client, functions[CODING_STOP_ACTIVITY].__wrapped__
            )
            owner.stop_admission()
            monkeypatch.setattr(
                activity,
                "info",
                lambda: SimpleNamespace(
                    workflow_id="original-run",
                    workflow_run_id="original-epoch",
                    workflow_namespace="original",
                    activity_id="original-stop",
                    attempt=1,
                    activity_type=CODING_STOP_ACTIVITY,
                ),
            )
            request = {
                "scope": {"workspace": scope.workspace, "principal": scope.principal},
                "run_id": "original-run",
                "execution_epoch": "original-epoch",
                "runtime_manifest": selected_runtime.orchestration_release,
            }
            # The exact stop remains admitted to its original SDK proof read;
            # no original handler or journal I/O is authorized by the maintenance token.
            with pytest.raises(LookupError, match="original SDK proof"):
                await functions[CODING_STOP_ACTIVITY](request)
            monkeypatch.setattr(
                activity,
                "info",
                lambda: SimpleNamespace(
                    workflow_id="original-run",
                    workflow_run_id="original-epoch",
                    workflow_namespace="original",
                    activity_id="new-model",
                    attempt=1,
                    activity_type="ralf.temporal.model.v1",
                ),
            )
            with pytest.raises(ValidationError, match="admission is closed"):
                await functions["ralf.temporal.model.v1"](request)
        finally:
            await owner.aclose(wait_timeout=2)
            await context.cleanup_async()

    asyncio.run(run())
