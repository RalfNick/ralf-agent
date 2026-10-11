"""Original SDK registration survives mechanical actual-call ownership."""

import asyncio
import contextvars
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import Scope
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner


def test_sdk_activity_definition_and_context_survive_observer_cancel(monkeypatch):
    activity = pytest.importorskip("temporalio.activity")

    async def run():
        context = contextvars.ContextVar("original-sdk-context")
        context.set("original-uuid")
        actual = SimpleNamespace(
            workflow_id="run",
            workflow_run_id="original-uuid",
            workflow_namespace="original",
            activity_id="model:0",
            attempt=2,
        )
        monkeypatch.setattr(activity, "info", lambda: actual)
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        @activity.defn(name="original.activity")
        async def original(request: dict) -> dict:
            assert activity.info() is actual
            assert context.get() == "original-uuid"
            calls.append(request)
            started.set()
            await release.wait()
            return {"complete": True}

        owner = WorkerExecutionOwner(scope=Scope(), release={"fixed": "release"})
        client = SimpleNamespace(namespace="original")
        wrapped = owner.wrap_activities([original], client=client)[0]
        definition = activity._Definition.from_callable(wrapped)
        assert definition.name == "original.activity"
        assert definition.fn is wrapped and definition.arg_types == [dict]
        task = asyncio.create_task(definition.fn({"scope": asdict(Scope())}))
        try:
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not await owner.wait(wait_timeout=0)
            release.set()
            assert await owner.wait(wait_timeout=3)
            assert len(calls) == 1
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await owner.aclose(wait_timeout=3)

    asyncio.run(run())


@pytest.mark.parametrize("change", ["sdk-namespace", "client-namespace", "request-scope"])
def test_wrapped_activity_refuses_foreign_identity_before_handler(monkeypatch, change):
    activity = pytest.importorskip("temporalio.activity")

    async def run():
        actual = SimpleNamespace(
            workflow_id="run",
            workflow_run_id="uuid",
            workflow_namespace="original",
            activity_id="tool:0",
            attempt=1,
        )
        monkeypatch.setattr(activity, "info", lambda: actual)
        calls = []

        @activity.defn(name="original.tool")
        async def original(request: dict) -> dict:
            calls.append("write")
            return {}

        owner = WorkerExecutionOwner(scope=Scope(), release={"fixed": "release"})
        client = SimpleNamespace(namespace="original")
        wrapped = owner.wrap_activities([original], client=client)[0]
        request = {"scope": asdict(Scope())}
        if change == "sdk-namespace":
            actual.workflow_namespace = "other"
        elif change == "client-namespace":
            client.namespace = "other"
        else:
            request["scope"] = asdict(Scope("other", "user"))
        try:
            with pytest.raises(DefinitionMismatch):
                await wrapped(request)
            assert calls == []
        finally:
            await owner.aclose()

    asyncio.run(run())


def test_build_worker_installs_owner_on_every_original_activity(monkeypatch):
    pytest.importorskip("temporalio.worker")
    import temporalio.worker

    from ralf_agent import ToolRegistry
    from ralf_agent.runtime_builder import EchoProvider
    from ralf_agent.temporal import build_temporal_worker
    from ralf_agent.temporal_activities import TemporalRuntime, registered_activities
    from ralf_agent.temporal_control_activities import registered_parent_activities
    from ralf_agent.temporal_session_activities import registered_session_activities

    runtime = TemporalRuntime(providers={"default": EchoProvider("offline")}, tools=ToolRegistry())
    client = SimpleNamespace(namespace="original")
    expected = registered_activities(runtime, client) + registered_parent_activities(
        runtime, client
    )
    expected += registered_session_activities(runtime, client)
    captured = {}
    monkeypatch.setattr(
        temporalio.worker, "Worker", lambda *args, **kwargs: captured.update(kwargs)
    )
    owner = WorkerExecutionOwner(scope=Scope(), release=runtime.orchestration_release)
    build_temporal_worker(client, task_queue="queue", runtime=runtime, activity_owner=owner)
    assert "activity_owner" not in captured
    assert len(captured["activities"]) == len(expected)
    from temporalio import activity

    for actual, original in zip(captured["activities"], expected, strict=True):
        assert actual is not original
        assert (
            activity._Definition.from_callable(actual).name
            == activity._Definition.from_callable(original).name
        )
        assert actual.__wrapped__.__name__ == original.__name__
