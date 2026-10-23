"""Invalid startup leaves original Host state untouched, without service I/O."""

import asyncio
from datetime import timedelta

import pytest

from relf_agent import TemporalRuntimeBuilder
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.types import digest

from .test_temporal_catalog_assembly import catalog
from .test_temporal_profile_host import sdk as sdk_fixture

sdk = sdk_fixture


@pytest.mark.parametrize(
    "which,value",
    [
        ("engine", {"unknown": True}),
        ("engine", {"activity_timeout": float("nan")}),
        ("engine", {"drive_timeout": True}),
        ("worker", {"unknown": True}),
        ("worker", {"activities": []}),
        ("worker", {"max_cached_workflows": -1}),
        ("worker", {"identity": 42}),
        ("worker", {"max_concurrent_workflow_tasks": 1}),
        ("worker", {"graceful_shutdown_timeout": timedelta(seconds=-1)}),
        ("worker", "first-profile-build"),
    ],
)
def test_invalid_options_before_rpc_state_or_worker_and_corrected_retry(
    tmp_path, sdk, monkeypatch, which, value
):
    async def run():
        calls = []

        async def namespace(client):
            calls.append("namespace")
            return "namespace-uuid"

        monkeypatch.setattr("relf_agent.temporal_session_activities.namespace_id", namespace)
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        if value == "first-profile-build":
            selected = {"build_id": digest(host._assemblies[0].release)}
        else:
            selected = value
        try:
            with pytest.raises((ValidationError, DefinitionMismatch)):
                await host.start_workers(sdk.client, **{which + "_options": selected})
            assert calls == [] and sdk.workers == []
            assert host._client is None and host._route is None and host._start_task is None
            assert host._engines == {} and host._queues == {}
            await host.start_workers(sdk.client, engine_options={"activity_timeout": 2})
            assert len(sdk.workers) == 2 and calls
        finally:
            await host.aclose()

    asyncio.run(run())


def test_valid_options_snapshot_survives_caller_mutation_during_namespace_lookup(
    tmp_path, sdk, monkeypatch
):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def namespace(client):
            entered.set()
            await release.wait()
            return "namespace-uuid"

        monkeypatch.setattr("relf_agent.temporal_session_activities.namespace_id", namespace)
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        supplied = {"activity_timeout": 2}
        starting = asyncio.create_task(host.start_workers(sdk.client, engine_options=supplied))
        try:
            await entered.wait()
            supplied["activity_timeout"] = 0
            release.set()
            await starting
            assert host.runtime().engine.activity_timeout == 2
        finally:
            release.set()
            await asyncio.gather(starting, return_exceptions=True)
            await host.aclose()

    asyncio.run(run())
