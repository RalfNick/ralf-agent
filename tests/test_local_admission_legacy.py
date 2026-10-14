"""Deployment installation must keep original composite publication recoverable."""

import asyncio
import copy

import pytest

from ralf_agent import (
    AgentSpec,
    DeploymentAdmissionPolicy,
    LocalEngine,
    SQLiteStore,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.orchestration_types import DynamicWorkflowSpec, TeamSpec
from ralf_agent.runtime_builder import EchoProvider


@pytest.mark.parametrize("kind", ["team", "dynamic", "nested"])
def test_legacy_composite_release_is_not_rewritten_by_host_deployment_installation(tmp_path, kind):
    member = AgentSpec("member", "Answer")
    definition = (
        TeamSpec("team", {"member": member})
        if kind == "team"
        else DynamicWorkflowSpec("plan", {"member": member})
        if kind == "dynamic"
        else TeamSpec("outer", {"inner": WorkflowSpec("sequence", [member])})
    )
    path = tmp_path / "legacy-composite.sqlite"

    def engine(**options):
        return LocalEngine(
            SQLiteStore(path),
            providers={"default": EchoProvider("legacy")},
            tools=ToolRegistry(),
            **options,
        )

    with engine() as original:
        handle = original.submit(definition, "q", command_id="original")
        manifest = copy.deepcopy(original.store.run(handle.run_id)["manifest"])
        release = original.store.run(handle.run_id)["release_digest"]
    with engine(
        admission_policy=DeploymentAdmissionPolicy("deployment", max_active_root_runs=1)
    ) as restored:
        assert restored.submit(definition, "q", command_id="original") == handle
        assert asyncio.run(restored.drive(handle.run_id)).state == "succeeded"
        record = restored.store.run(handle.run_id)
        assert record["manifest"] == manifest and record["release_digest"] == release
        assert "local_admission" not in record
        assert restored.store.local_capacity_holders(restored.scope) == ()
