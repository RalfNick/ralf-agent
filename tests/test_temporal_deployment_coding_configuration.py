"""Public integration progresses through real construction; private stays refused."""

import asyncio

import pytest

from ralf_agent import (
    ComponentRegistry,
    DeploymentAdmissionPolicy,
    TemporalProfile,
    TemporalRuntime,
    TemporalRuntimeBuilder,
    ToolRegistry,
)
from ralf_agent.errors import ValidationError
from tests.test_temporal_deployment_public_registry import Provider


@pytest.fixture(autouse=True, scope="module")
def _optional_sdk():
    pytest.importorskip("temporalio")


def test_public_builder_can_construct_coding_components_before_resource_validation():
    async def run():
        calls = []
        registry = ComponentRegistry()
        registry.register(
            "provider",
            "original-model",
            lambda config, context: calls.append("provider") or Provider(),
        )
        profile = TemporalProfile(
            "coding-public",
            "1",
            {"default": {"adapter": "original-model"}},
            execution={"coding_execution": True},
        )
        with pytest.raises(ValidationError, match="registered|PostgreSQL"):
            await TemporalRuntimeBuilder(registry).abuild(
                profile, admission_policy=DeploymentAdmissionPolicy("coding-public")
            )
        assert calls == ["provider"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "workflow_module", ["ralf_agent.temporal_workflow", "ralf_agent.temporal_parent_workflow"]
)
def test_registered_sdk_sandbox_accepts_the_original_coding_root_with_fixed_guards(workflow_module):
    import copy
    import importlib

    from temporalio.worker.workflow_sandbox._importer import Importer
    from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

    from ralf_agent.temporal import _workflow_runner
    from tests.test_temporal_deployment_coding_registry import coding_request
    from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY

    importlib.import_module(workflow_module)  # Worker registration precedes SDK sandbox creation.
    request = coding_request()
    context = RestrictionContext()
    importer = Importer(_workflow_runner().restrictions, context)
    with importer.applied():
        importlib.import_module(workflow_module)
        module = importlib.import_module("ralf_agent.temporal_state")
        context.is_runtime = True
        try:
            state = module.TemporalCommandRegistryState(
                admission_policy=POLICY.identity, namespace=NAMESPACE, admission_protocol=3
            )
            receipt = state.reserve(copy.deepcopy(request))
            assert receipt["record_state"] == "durably_recorded"
            assert len(state.deployment.roots) == 1
        finally:
            context.is_runtime = False


def test_public_sdk_reaches_native_resource_check_and_private_sdk_stays_refused():
    args = {"providers": {"default": Provider()}, "tools": ToolRegistry(), "coding_execution": True}
    with pytest.raises(ValidationError, match="registered|PostgreSQL"):
        TemporalRuntime(**args, admission_policy=DeploymentAdmissionPolicy("public"))
    with pytest.raises(ValidationError, match="physical-close integration"):
        TemporalRuntime(**args, _deployment_admission_policy=DeploymentAdmissionPolicy("private"))


def test_complete_public_coding_assembly_publishes_both_original_inventories(tmp_path, monkeypatch):
    from ralf_agent import Scope
    from ralf_agent.runtime_lifecycle import BuildContext
    from ralf_agent.temporal_coding_factories import build
    from ralf_agent.temporal_deployment_protocol import CODING_SOURCE_FILES, PUBLIC_SOURCE_FILES
    from ralf_agent.temporal_journal import PostgresEffectJournal
    from tests.test_temporal_coding_factories import Connection, entry, publish_initialization

    async def run():
        events = []
        publish_initialization(monkeypatch, events)
        context = BuildContext(None, tmp_path / "unused", Scope(), tmp_path, allow_async=True)
        effect = context.own_async(PostgresEffectJournal(Connection(events), owns_connection=True))
        context.coding_execution, context.effect_journal = True, effect
        tools = await build(entry(tmp_path), context)
        runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=tools,
            journal=effect,
            coding_execution=True,
            admission_policy=DeploymentAdmissionPolicy("public-coding"),
        )
        try:
            release = runtime.manifest
            assert release["deployment_admission_protocol"]["version"] == 3
            assert set(release["deployment_admission_protocol"]["implementation"]) == set(
                CODING_SOURCE_FILES
            )
            assert set(PUBLIC_SOURCE_FILES) <= set(
                release["deployment_admission_protocol"]["implementation"]
            )
            assert release["coding_execution_protocol"]["version"] == 6
            assert release["binding_protocol"] == 22
        finally:
            await context.cleanup_async()

    asyncio.run(run())


@pytest.mark.parametrize("existing_resources", [False, True])
def test_never_attached_public_native_assembly_closes_its_owned_components(
    tmp_path, monkeypatch, existing_resources
):
    from ralf_agent import Scope
    from ralf_agent.runtime_lifecycle import BuildContext
    from ralf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly
    from ralf_agent.temporal_coding_factories import build
    from ralf_agent.temporal_journal import PostgresEffectJournal
    from tests.test_temporal_coding_factories import Connection, entry, publish_initialization

    async def run():
        events, scope = [], Scope()
        publish_initialization(monkeypatch, events)
        context = BuildContext(None, tmp_path / "unused", scope, tmp_path, allow_async=True)
        effect = context.own_async(PostgresEffectJournal(Connection(events), owns_connection=True))
        context.coding_execution, context.effect_journal = True, effect
        tools = await build(entry(tmp_path), context)
        remaining = [{"original_resource": "retained"}] if existing_resources else []

        async def resources(requested_scope):
            assert requested_scope == scope
            return remaining.copy()

        runner_journal = tools.get("coding").handler.runner._journal
        monkeypatch.setattr(runner_journal, "composition_resources", resources)
        runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=tools,
            journal=effect,
            coding_execution=True,
            admission_policy=DeploymentAdmissionPolicy("never-attached"),
        )
        profile = TemporalProfile(
            "never-attached",
            "1",
            {"default": {"adapter": "offline-echo"}},
            execution={"coding_execution": True},
        )
        assembly = TemporalRuntimeAssembly(runtime, context, profile, scope)
        assert assembly.release["binding_protocol"] == 22
        assert assembly._client is None and assembly._worker is None and not assembly._engines
        assert len(context._resources) == 3
        try:
            if existing_resources:
                from ralf_agent.errors import CloseIncomplete

                originals = tuple(context._resources)
                with pytest.raises(CloseIncomplete):
                    await assembly.aclose()
                assert not assembly._closed and tuple(context._resources) == originals
                remaining.clear()  # Fixture backend now reports original cleanup completed.
            await assembly.aclose()
            assert assembly._closed and context._resources == []
            await assembly.aclose()
        finally:
            await context.cleanup_async()

    asyncio.run(run())
