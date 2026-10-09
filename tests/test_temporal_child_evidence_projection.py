import asyncio
import copy

import pytest

from ralf_agent.errors import ValidationError

from .temporal_composite_agent_fixture import CompositeClient, definitions


def test_parent_resource_evidence_ignores_child_cancel_bookkeeping_in_v2(monkeypatch):
    async def scenario():
        from .temporal_agent_fixture import engine

        client = CompositeClient()
        raw = engine(
            monkeypatch, client=client, release=client.worker_runtime.orchestration_release
        )
        handle = await raw.submit(definitions()["nested"], "q", command_id="s", budget=64)
        parent = client.states[handle.run_id]
        child = client.states[parent.children[0]["run_id"]]
        value = {**child.diagnostics(), "scope": parent.scope}
        parent.observation_version = 2
        # Establish a fingerprint for v2 before changing opaque control metadata.
        parent.children[0].pop("observation_digest", None)
        parent.children[0].pop("observed_revision", None)
        parent.observe(child.run_id, value)
        before = parent.revision
        changed = copy.deepcopy(value)
        changed["workflow"]["children"][0]["cancel_confirmed"] = True
        parent.observe(child.run_id, changed)
        assert parent.revision == before and parent.budget["reserved"] == 24
        # Execution quiescence remains authoritative, not bookkeeping.
        changed["workflow"]["quiescent"] = True
        with pytest.raises(ValidationError):
            parent.observe(child.run_id, changed)
        # Old histories retain their full original fingerprint contract.
        parent.observation_version = 1
        parent.children[0].pop("observation_digest", None)
        parent.children[0].pop("observed_revision", None)
        parent.observe(child.run_id, value)
        legacy_changed = copy.deepcopy(value)
        legacy_changed["workflow"]["children"][0]["cancel_confirmed"] = True
        with pytest.raises(ValidationError):
            parent.observe(child.run_id, legacy_changed)

    asyncio.run(scenario())
