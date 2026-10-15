"""Fresh Session SDK reads validate mutable resources before returning authority."""

import asyncio
import copy

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_session_deployment_verification import SessionControlValidation
from tests.test_temporal_session_deployment_control import Client, Runtime, fixture


class CountedRuntime(Runtime):
    def __init__(self, manifest):
        super().__init__(manifest)
        self.validations = 0

    def validate_release(self, manifest=None):
        self.validations += 1
        super().validate_release(manifest)


def original():
    deployment, wire, info = fixture()
    runtime = CountedRuntime(copy.deepcopy(wire["intent"]["binding"]["manifest"]))
    client = Client(wire)
    proof = SessionControlValidation(runtime, client, wire, info, deployment_id=deployment)
    runtime.validations = 0
    return proof, client, runtime


def test_sdk_readset_avoids_rebuilding_complete_worker_manifest_per_transport_read():
    proof, client, runtime = original()
    accepted = asyncio.run(proof.validate())
    assert accepted["intent"] == client.intent
    assert client.events == [
        "namespace",
        "describe",
        "history",
        "deployment_session_intent",
        "deployment_session_command",
        "describe",
        "namespace",
    ]
    # A read-only set must not multiply complete Coding inventory discovery
    # across its SDK awaits. Both public boundaries still validate resources.
    assert runtime.validations == 2


@pytest.mark.parametrize(
    "boundary",
    ["namespace", "describe", "history", "deployment_session_intent", "deployment_session_command"],
)
def test_changed_worker_resource_during_readset_never_returns_authority(boundary):
    proof, client, runtime = original()
    dispatched = []

    def mutate(name):
        if name == boundary:
            runtime.manifest = {"changed_worker_resource": True}

    client.mutate = mutate

    async def scenario():
        await proof.validate()
        dispatched.append("native-send")

    with pytest.raises(DefinitionMismatch):
        asyncio.run(scenario())
    assert not dispatched
