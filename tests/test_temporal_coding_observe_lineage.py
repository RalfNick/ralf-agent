"""Closed node collection correlates a descendant with its original business root."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent import temporal_deployment_coding_validation as validation
from relf_agent import temporal_deployment_execution as execution
from relf_agent.errors import DefinitionMismatch
from tests.test_temporal_coding_observe_validation import environment


@pytest.mark.parametrize("missing_pin", [False, True])
def test_descendant_collection_keeps_original_root_and_refuses_missing_ancestor_pin(
    monkeypatch, missing_pin
):
    async def run():
        e = environment(monkeypatch)
        child = e.client.states[e.call["run_id"]]
        policy = execution._policy(e.runtime)
        proof = await execution._proof(
            e.runtime, e.client, policy, child.scope, child.run_id, child.epoch, required=True
        )
        expected_root = await execution._ancestry(
            e.runtime, e.client, policy, proof, read_only=True
        )
        info = copy.copy(e.info)
        info.workflow_id, info.workflow_run_id = child.run_id, child.epoch
        reader = validation._ObservationValidation(
            e.runtime,
            e.client,
            {
                "scope": child.scope,
                "run_id": child.run_id,
                "execution_epoch": child.epoch,
                "runtime_manifest": child.manifest,
                "coding_parent": child.request["coding_parent"],
            },
            info,
        )
        reader._open_reading(proof)
        e.counts.clear()
        e.client.events.clear()
        try:
            if missing_pin:
                e.call["deployment_execution_epoch"] = None
                with pytest.raises(DefinitionMismatch):
                    await reader._bootstrap_nodes(reader._read_client())
            else:
                leaf, root, nodes = await reader._bootstrap_nodes(reader._read_client())
                assert leaf == proof and root == expected_root
                assert [node["run_id"] for node in nodes] == [child.run_id, e.parent.run_id]
                assert e.counts[("query", "deployment_admission")] == 4
                assert e.counts[("query", "deployment_session_root")] == 4
                assert e.counts[("query", "deployment_start")] == 4
                assert e.client.events.count("history") == 0
                await reader._finish_reading()
                assert e.client.events.count("history") == 1
        finally:
            reader._discard_reading()
        assert reader._snapshot is reader._reading is reader._reading_identity is None
        assert e.probe.writes == []

    asyncio.run(run())


def test_closed_collection_pins_the_original_read_port_instance(monkeypatch):
    async def run():
        e = environment(monkeypatch)
        proof = await execution._proof(
            e.runtime,
            e.client,
            execution._policy(e.runtime),
            e.parent.scope,
            e.parent.run_id,
            e.parent.epoch,
            required=True,
        )
        reader = validation._ObservationValidation(
            e.runtime,
            e.client,
            {
                "scope": e.parent.scope,
                "run_id": e.parent.run_id,
                "execution_epoch": e.parent.epoch,
                "runtime_manifest": e.parent.manifest,
            },
            e.info,
        )
        reader._open_reading(proof)
        try:
            # A lookalike is not the originally constructed read-only transport,
            # even if it copies the immutable identity field.
            reader._reading = SimpleNamespace(_identity=reader._reading_identity)
            with pytest.raises(DefinitionMismatch):
                reader._check(full=False)
        finally:
            reader._discard_reading()
        assert e.probe.writes == []

    asyncio.run(run())
