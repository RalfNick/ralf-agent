"""An original checked SDK transport must not recursively repeat origin facts."""

import asyncio
import copy

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_session_deployment_control import _CheckedClient
from relf_agent.temporal_session_deployment_verification import (
    SessionControlValidation,
    validate_session_origin,
)
from tests.test_temporal_deployment_session_registry import deployment_intent
from tests.test_temporal_session_deployment_control import Client, Runtime, fixture
from tests.test_temporal_session_deployment_dto import origin

FACTS = [
    "namespace",
    "describe",
    "history",
    "deployment_session_intent",
    "deployment_session_command",
    "describe",
    "namespace",
]


def environment():
    deployment, wire, info = fixture()
    wire["intent"] = deployment_intent()
    client = Client(wire)
    runtime = Runtime(wire["intent"]["binding"]["manifest"])
    proof = SessionControlValidation(runtime, client, wire, info, deployment_id=deployment)
    return proof, client


@pytest.mark.parametrize("checked", [False, True])
def test_original_origin_readset_has_seven_facts_with_direct_or_checked_transport(checked):
    proof, client = environment()
    transport = _CheckedClient(proof) if checked else client
    accepted = asyncio.run(
        validate_session_origin(proof.runtime, transport, proof.intent, origin(proof.intent))
    )
    assert accepted["intent"] == proof.intent
    assert accepted["session_origin"] == origin(proof.intent)
    assert client.events == FACTS


@pytest.mark.parametrize(
    "fault", ["reset", "namespace", "runtime", "source", "activity", "resource", "wrapper"]
)
def test_original_checked_transport_drift_during_sdk_read_never_returns_authority(
    fault, monkeypatch
):
    from relf_agent import temporal_session_deployment_verification as verification

    proof, client = environment()
    transport = _CheckedClient(proof)
    accepted = []
    replacement, _ = environment()
    fired = False

    def mutate(name):
        nonlocal fired
        if fired:
            return
        fired = True
        if fault == "reset":
            client.epoch = "replacement-epoch"
        elif fault == "namespace":
            client.namespace_uuid = "22222222-2222-4222-8222-222222222222"
        elif fault == "runtime":
            proof.runtime.manifest = {"changed": True}
        elif fault == "source":
            monkeypatch.setattr(
                verification,
                "_reject",
                lambda: (_ for _ in ()).throw(DefinitionMismatch("changed verifier source")),
            )
        elif fault == "activity":
            proof.info.attempt += 1
        elif fault == "resource":
            client.data_converter = copy.copy(client.data_converter)
        else:
            transport.validation = replacement

    client.mutate = mutate

    async def run():
        result = await validate_session_origin(
            proof.runtime, transport, proof.intent, origin(proof.intent)
        )
        accepted.append(result)

    with pytest.raises(DefinitionMismatch):
        asyncio.run(run())
    assert fired and not accepted


def test_checked_transport_cannot_replace_independent_verifier_with_outer_result(monkeypatch):
    proof, client = environment()
    transport = _CheckedClient(proof)

    async def forged_result():
        return {"intent": proof.intent, "session_origin": origin(proof.intent)}

    monkeypatch.setattr(proof, "validate", forged_result)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(
            validate_session_origin(proof.runtime, transport, proof.intent, origin(proof.intent))
        )
    assert not client.events


def test_foreign_checked_subclass_retains_original_transport_checks():
    class ForeignClient(_CheckedClient):
        pass

    proof, client = environment()
    result = asyncio.run(
        validate_session_origin(
            proof.runtime, ForeignClient(proof), proof.intent, origin(proof.intent)
        )
    )
    assert result["session_origin"] == origin(proof.intent)
    assert len(client.events) == 56
