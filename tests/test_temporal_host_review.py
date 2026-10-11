"""Whole-review regressions: ordinary entries retain original Host authority."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, ComponentRegistry, Scope, TemporalRuntimeBuilder
from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal_session_state import SESSION_WORKFLOW, TemporalSessionState, workflow_id
from ralf_agent.temporal_state import WORKFLOW_NAME
from ralf_agent.types import digest, submission_request

from .test_temporal_catalog_assembly import catalog
from .test_temporal_host_sessions import profiles
from .test_temporal_profile_host import sdk as sdk_fixture

sdk = sdk_fixture


@pytest.mark.parametrize("change", ["scope", "client", "queue", "release"])
def test_new_facade_refuses_shared_engine_drift(tmp_path, sdk, change):
    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        await host.start_workers(sdk.client)
        first = host.runtime()
        name = {"scope": "scope", "client": "client", "queue": "task_queue", "release": "_release"}[
            change
        ]
        original = getattr(first.engine, name)
        changed = {
            "scope": Scope("outside", "another"),
            "client": type(sdk.client)(),
            "queue": "unserved",
            "release": host._assemblies[1].release,
        }[change]
        try:
            setattr(first.engine, name, changed)
            with pytest.raises(DefinitionMismatch):
                host.runtime()
        finally:
            setattr(first.engine, name, original)
            await host.aclose()

    asyncio.run(run())


def test_ordinary_session_open_refuses_replaced_namespace_before_admission(
    tmp_path, sdk, monkeypatch
):
    async def run():
        current = ["namespace-uuid"]

        async def namespace(client):
            return current[0]

        monkeypatch.setattr("ralf_agent.temporal_session_activities.namespace_id", namespace)
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(profiles())
        await host.start_workers(sdk.client)
        calls = []

        async def start(*args, **kwargs):
            calls.append(kwargs)
            raise AssertionError("Replaced namespace must never receive admission")

        sdk.client.start_workflow = start
        try:
            current[0] = "replacement-uuid"
            with pytest.raises(DefinitionMismatch):
                await host.runtime().open_session(
                    AgentSpec("a", "Answer"), "chat", command_id="open"
                )
            assert calls == []
        finally:
            current[0] = "namespace-uuid"
            await host.aclose()

    asyncio.run(run())


def session_state(host):
    runtime = host.runtime(host.profiles[0].identity)
    return TemporalSessionState(
        {
            "scope": asdict(host.scope),
            "namespace_id": "namespace-uuid",
            "session_namespace": None,
            "session_id": "chat",
            "command_id": "open",
            "request": submission_request(AgentSpec("a", "Answer"), None),
            "manifest": runtime.engine.release,
            "task_queue": runtime.engine.task_queue,
            "activity_timeout": 10,
        }
    )


def description(host, sdk, identity, kind, queue):
    sdk.client.descriptions[identity] = SimpleNamespace(
        id=identity,
        namespace=sdk.client.namespace,
        workflow_type=kind,
        task_queue=queue,
        run_id="original-uuid",
    )


def test_ordinary_open_refuses_unserved_coordinator_before_updates(tmp_path, sdk):
    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(profiles())
        await host.start_workers(sdk.client)
        state = session_state(host)
        description(host, sdk, workflow_id(state.key), SESSION_WORKFLOW, "unserved-old-profile")
        calls = []

        async def start(*args, **kwargs):
            calls.append(kwargs)
            raise AssertionError("Unserved Coordinator must refuse before Updates")

        sdk.client.start_workflow = start
        try:
            with pytest.raises(DefinitionMismatch):
                await host.runtime().open_session(
                    AgentSpec("a", "Answer"), "chat", command_id="open"
                )
            assert calls == [] and sdk.client.query_calls == []
        finally:
            await host.aclose()

    asyncio.run(run())


def test_ordinary_duplicate_submit_refuses_unserved_run_before_query(tmp_path, sdk):
    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        await host.start_workers(sdk.client)
        runtime = host.runtime()
        identity = "ralf-temporal-" + digest([asdict(host.scope), "original"])
        description(host, sdk, identity, WORKFLOW_NAME, "unserved-old-profile")

        async def guard(*args, **kwargs):
            pass

        runtime.engine._guard = guard
        try:
            with pytest.raises(DefinitionMismatch):
                await runtime.submit(AgentSpec("a", "Answer"), "task", command_id="original")
            assert sdk.client.query_calls == []
        finally:
            await host.aclose()

    asyncio.run(run())


def test_close_after_client_drift_drains_original_rpc_then_all_workers_and_shared_resource(
    tmp_path, sdk
):
    async def run():
        class Provider(EchoProvider):
            async def aclose(self):
                sdk.events.append("resource-closed")

        resource = Provider("shared")
        factories = ComponentRegistry()
        factories.register("provider", "test", lambda c, ctx: ctx.own_async(resource))
        host = await TemporalRuntimeBuilder(factories, base_dir=tmp_path).abuild_catalog(
            catalog("test")
        )
        await host.start_workers(sdk.client)
        runtime = host.runtime()
        started, release = asyncio.Event(), asyncio.Event()

        async def held():
            started.set()
            await release.wait()

        pending = asyncio.create_task(runtime._supervisor.call(held()))
        original = sdk.client.namespace
        try:
            await started.wait()
            sdk.client.namespace = "changed"
            with pytest.raises(CloseIncomplete):
                await host.aclose(wait_timeout=0)
            assert not any(e.startswith("stopped:") for e in sdk.events)
            assert "resource-closed" not in sdk.events
            release.set()
            await pending
            await host.aclose()
            assert len([e for e in sdk.events if e.startswith("stopped:")]) == 2
            assert sdk.events.count("resource-closed") == 1
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
            sdk.client.namespace = original
            await host.aclose()

    asyncio.run(run())


def test_attachment_refuses_rebind_observed_after_binding_query(tmp_path, sdk):
    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(profiles())
        await host.start_workers(sdk.client)
        state = session_state(host)
        ref = state.ref
        metadata = state.profile_binding()
        second = host.runtime(host.profiles[1].identity)
        state.command(
            {
                "scope": state.scope,
                "kind": "rebind",
                "command_id": "rebind",
                "session_ref": ref.to_dict(),
                "expected_binding_revision": 1,
                "binding": {
                    "request": state.binding["request"],
                    "manifest": second.engine.release,
                    "task_queue": second.engine.task_queue,
                    "activity_timeout": 10,
                },
            }
        )
        identity = workflow_id(state.key)
        description(host, sdk, identity, SESSION_WORKFLOW, metadata["task_queue"])
        sdk.client.queries[identity] = {"profile_binding": metadata, "status": state.snapshot()}
        try:
            with pytest.raises(DefinitionMismatch):
                await host.aattach_session(ref)
        finally:
            await host.aclose()

    asyncio.run(run())
