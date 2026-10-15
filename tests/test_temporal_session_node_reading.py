"""Correlated node proposals retain raw SDK reads without granting Session authority."""

import asyncio
import copy
from collections import Counter

import pytest

from ralf_agent import temporal_deployment_execution as execution
from ralf_agent import temporal_deployment_execution_state as admission
from ralf_agent import temporal_session_deployment_verification as verification
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.types import canonical
from tests.test_temporal_session_deployment_dto import origin
from tests.test_temporal_session_tree_reading import ready, tree_environment


def reader():
    helper = getattr(verification, "_read_session_node", None)
    assert callable(helper), "Missing original Session node proposal reader"
    return helper


@pytest.mark.parametrize("member", ["root", "child"])
def test_original_node_reads_keep_full_proposal_and_correlation_without_session_authority(
    monkeypatch, member
):
    async def run():
        validation, client, parent, _ = tree_environment(monkeypatch)
        node = parent if member == "root" else client.states[parent.children[0]["run_id"]]
        expected = {"intent": validation.intent, "session_origin": origin(validation.intent)}
        client.events.clear()
        client.reads.clear()
        value, identity = await reader()(
            validation.runtime,
            client,
            execution._policy(validation.runtime),
            parent.scope,
            node.run_id,
            node.epoch,
        )
        assert value == admission.view(node) and identity == expected
        registry_id = parent.deployment_admission["root"]["registry_id"]
        assert client.reads == Counter(
            {
                (node.run_id, "describe"): 1,
                (node.run_id, "deployment_admission"): 1,
                (registry_id, "deployment_session_root"): 1,
                (node.run_id, "deployment_start"): 1,
            }
        )
        # This API deliberately returns a proposal. The independent full
        # Session SDK exit belongs to the caller, never to this helper.
        assert client.events == ["namespace", "namespace"]
        assert client.writes == []
        value["request"]["input"] = "detached mutation"
        identity["intent"]["binding"]["task_queue"] = "detached mutation"
        assert node.request["input"] != "detached mutation"
        assert client.record["intent"] == expected["intent"]

    asyncio.run(run())


def test_repeated_node_reads_require_the_same_complete_canonical_identity(monkeypatch):
    async def run():
        validation, client, parent, _ = tree_environment(monkeypatch)
        policy = execution._policy(validation.runtime)
        value, identity = await reader()(
            validation.runtime, client, policy, parent.scope, parent.run_id, parent.epoch
        )
        before = client.reads.copy()
        current, repeated = await reader()(
            validation.runtime,
            client,
            policy,
            parent.scope,
            parent.run_id,
            parent.epoch,
            expected_identity=canonical(identity),
        )
        assert current == value and repeated == identity
        assert client.reads == Counter({key: count * 2 for key, count in before.items()})
        changed = copy.deepcopy(identity)
        changed["intent"]["binding"]["task_queue"] = "different original binding"
        starts = client.reads[(parent.run_id, "deployment_start")]
        with pytest.raises(DefinitionMismatch):
            await reader()(
                validation.runtime,
                client,
                policy,
                parent.scope,
                parent.run_id,
                parent.epoch,
                expected_identity=canonical(changed),
            )
        assert client.reads[(parent.run_id, "deployment_start")] == starts
        assert client.writes == []

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["start", "registry_origin", "epoch", "namespace"])
def test_original_node_binding_drift_never_returns_a_positive_proposal(monkeypatch, fault):
    async def run():
        validation, client, parent, _ = tree_environment(monkeypatch)
        expected = canonical(
            {"intent": validation.intent, "session_origin": origin(validation.intent)}
        )

        def change(identity, kind, result):
            if fault == "start" and kind == "deployment_start":
                result["task_queue"] = "foreign"
            elif fault == "registry_origin" and kind == "deployment_session_root":
                result["session_origin"]["coordinator_execution_epoch"] = "foreign"
            elif fault == "epoch" and kind == "deployment_session_root":
                parent.epoch = "reset"
            elif fault == "namespace" and kind == "deployment_session_root":
                client.namespace_uuid = "22222222-2222-4222-8222-222222222222"

        client.hook = change
        with pytest.raises(DefinitionMismatch):
            await reader()(
                validation.runtime,
                client,
                execution._policy(validation.runtime),
                parent.scope,
                parent.run_id,
                parent.epoch,
                expected_identity=expected,
            )
        assert client.writes == []

    asyncio.run(run())


def test_tree_pins_the_shared_reader_before_accepting_its_proposal(monkeypatch):
    async def run():
        validation, client, _, _, readonly, policy, proof = await ready(monkeypatch)
        changed = []

        def replace(identity, kind, result):
            if kind == "deployment_start" and not changed:
                changed.append(True)
                monkeypatch.setattr(verification, "_read_session_node", lambda *args: None)

        client.hook = replace
        with pytest.raises(DefinitionMismatch):
            await verification._read_session_tree(validation, readonly, policy, proof)
        assert changed and client.writes == []

    asyncio.run(run())
