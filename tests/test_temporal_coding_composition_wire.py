"""Actual Profile publication survives the SDK's canonical JSON boundary."""

import asyncio
import copy
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope, TemporalProfile
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.postgres_runner_journal import PostgresRunnerJournal
from ralf_agent.runtime_builder import ComponentRegistry
from ralf_agent.temporal_builder import TemporalRuntimeBuilder
from ralf_agent.temporal_coding_composition_control import _validate_proof
from ralf_agent.temporal_coding_composition_state import (
    initialize,
    initialize_namespace,
    physical_stop_view,
)
from ralf_agent.temporal_journal import PostgresEffectJournal
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.types import digest, submission_request
from tests.test_temporal_coding_factories import Connection, entry, publish_initialization
from tests.test_temporal_engine import Provider


def test_actual_selected_profile_proof_matches_sdk_json_manifest_and_request(tmp_path, monkeypatch):
    from temporalio.converter import DataConverter

    events = []
    publish_initialization(monkeypatch, events)

    async def no_records(self, scope):
        return ()

    monkeypatch.setattr(PostgresRunnerJournal, "composition_resources", no_records)
    registry = ComponentRegistry()

    async def effect(config, context):
        return context.own_async(PostgresEffectJournal(Connection(events), owns_connection=True))

    registry.register_async("effect_journal", "wire-owner", effect)
    registry.register("provider", "wire-peer", lambda config, context: Provider())
    profile = TemporalProfile(
        "wire-profile",
        "107",
        {"default": {"adapter": "wire-peer"}},
        {
            "effect_journal": {"adapter": "wire-owner"},
            "tools": {"adapter": "codex-coding-postgres", "config": entry(tmp_path)},
        },
        execution={"coding_execution": True, "coding_composition": True},
    )
    scope, namespace = Scope(), {"name": "default", "id": "11111111-1111-1111-1111-111111111111"}

    async def run():
        assembly = await TemporalRuntimeBuilder(registry).abuild(profile, scope=scope)
        try:
            release = assembly.release
            assert release["context_builder"] == {"kind": "bounded-context", "version": "2"}
            request = submission_request(
                GraphWorkflowSpec("serial", [GraphNode("a", agent=AgentSpec("a", "Answer"))]),
                {"original": ("one", "two"), "typed_marker": 1},
                budget=8,
            )
            state = TemporalParentState(
                "original-root", asdict(scope), "submit", request, release, "original-epoch"
            )
            initialize(state, namespace="default")
            initialize_namespace(
                state,
                {
                    "scope": asdict(scope),
                    "run_id": state.run_id,
                    "execution_epoch": state.epoch,
                    "manifest_digest": digest(release),
                    "namespace": namespace,
                },
            )
            proof = physical_stop_view(state)
            wire = (
                await DataConverter.default.decode(await DataConverter.default.encode([proof]))
            )[0]
            assert wire["manifest"] != release and digest(wire["manifest"]) == digest(release)
            assert wire["request"] != request and digest(wire["request"]) == digest(request)
            result = _validate_proof(
                wire,
                scope=asdict(scope),
                run_id=state.run_id,
                epoch=state.epoch,
                manifest=release,
                namespace=namespace,
                request=request,
            )
            assert result["request_digest"] == digest(request)
            changed_request = copy.deepcopy(wire["request"])
            changed_request["input"]["typed_marker"] = True
            with pytest.raises(DefinitionMismatch):
                _validate_proof(
                    wire,
                    scope=asdict(scope),
                    run_id=state.run_id,
                    epoch=state.epoch,
                    manifest=release,
                    namespace=namespace,
                    request=changed_request,
                )
            changed = dict(release)
            changed["binding_protocol"] = True
            with pytest.raises(DefinitionMismatch):
                _validate_proof(
                    wire,
                    scope=asdict(scope),
                    run_id=state.run_id,
                    epoch=state.epoch,
                    manifest=changed,
                    namespace=namespace,
                    request=request,
                )
        finally:
            await assembly.aclose()

    asyncio.run(run())
