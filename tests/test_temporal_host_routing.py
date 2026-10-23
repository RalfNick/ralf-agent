"""Server queue metadata selects an original Profile, never the current alias."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from relf_agent import AgentSpec, RunRef, TemporalRuntimeBuilder
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch
from relf_agent.temporal_state import WORKFLOW_NAME, TemporalRunState
from relf_agent.types import submission_request

from .test_temporal_catalog_assembly import catalog
from .test_temporal_profile_host import sdk as sdk_fixture

sdk = sdk_fixture


def original_run(host, sdk):
    runtime = host.runtime(host.profiles[0].identity)
    state = TemporalRunState(
        run_id="original-run",
        scope=asdict(host.scope),
        command_id="original-submit",
        request=submission_request(AgentSpec("a", "Answer"), "question"),
        manifest=runtime.engine.release,
    )
    sdk.client.descriptions[state.run_id] = SimpleNamespace(
        id=state.run_id,
        namespace=sdk.client.namespace,
        workflow_type=WORKFLOW_NAME,
        task_queue=runtime.engine.task_queue,
        run_id="original-uuid",
    )
    sdk.client.queries[state.run_id] = {"diagnostics": state.diagnostics()}
    ref = RunRef(
        runtime.authority_locator,
        host.scope.workspace,
        host.scope.principal,
        state.run_id,
        state.release_digest,
    )
    return state, ref


def test_attach_original_run_after_default_change_uses_original_profile(tmp_path, sdk):
    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        await host.start_workers(sdk.client)
        try:
            state, ref = original_run(host, sdk)
            host.select_default(host.profiles[1].identity)
            attached = await host.aattach(ref)
            assert attached.ref == ref
            assert attached._runtime.engine.release["runtime_profile"] == host.profiles[0].identity
            assert host.default_profile.version == "2"
            assert (await attached.diagnostics()).release_digest == state.release_digest
        finally:
            await host.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["queue", "profile", "scope"])
def test_original_ref_or_metadata_conflicts_refuse_without_substitution(tmp_path, sdk, change):
    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        await host.start_workers(sdk.client)
        try:
            state, ref = original_run(host, sdk)
            if change == "queue":
                sdk.client.descriptions[ref.run_id].task_queue = "unknown-version"
            elif change == "profile":
                sdk.client.queries[ref.run_id]["diagnostics"]["manifest"]["runtime_profile"] = (
                    host.profiles[1].identity
                )
            else:
                ref = RunRef(
                    ref.authority_locator,
                    "another-workspace",
                    ref.principal,
                    ref.run_id,
                    ref.release_digest,
                )
            with pytest.raises(AuthorizationDenied if change == "scope" else DefinitionMismatch):
                await host.aattach(ref)
            if change in {"queue", "scope"}:
                assert sdk.client.query_calls == []
        finally:
            await host.aclose()

    asyncio.run(run())


def test_namespace_uuid_changed_during_describe_refuses_before_query(tmp_path, sdk, monkeypatch):
    async def run():
        uuid = ["namespace-uuid"]

        async def namespace(client):
            return uuid[0]

        monkeypatch.setattr("relf_agent.temporal_session_activities.namespace_id", namespace)
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        await host.start_workers(sdk.client)
        try:
            _, ref = original_run(host, sdk)
            get_handle = sdk.client.get_workflow_handle

            def changed_handle(identity):
                handle = get_handle(identity)
                if identity == ref.run_id:
                    original = handle.describe

                    async def describe():
                        value = await original()
                        uuid[0] = "replacement-uuid"
                        return value

                    handle.describe = describe
                return handle

            sdk.client.get_workflow_handle = changed_handle
            with pytest.raises(DefinitionMismatch):
                await host.aattach(ref)
            assert sdk.client.query_calls == []
        finally:
            await host.aclose()

    asyncio.run(run())
