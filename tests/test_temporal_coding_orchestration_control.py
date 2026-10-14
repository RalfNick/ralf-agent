"""Root admission and recovery obey the original SDK identity for every parent kind."""

import asyncio
from types import SimpleNamespace

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.types import digest
from tests import test_temporal_coding_composition_control as fixture


@pytest.fixture
def namespace(monkeypatch):
    from ralf_agent import temporal_session_activities

    async def identity(client):
        return fixture.NAMESPACE["id"]

    monkeypatch.setattr(temporal_session_activities, "namespace_id", identity)


def application(monkeypatch, kind):
    manifest = {
        "kernel": "temporal-3",
        "binding_protocol": 21,
        "coding_composition_protocol": {
            "version": 6,
            "topology": "bounded-agent-orchestration",
        },
    }
    monkeypatch.setattr(fixture, "MANIFEST", manifest)
    client = fixture.Client({"definition": {"kind": kind}, "input": "task", "budget": 8})
    value = {
        "scope": fixture.SCOPE,
        "run_id": "root",
        "execution_epoch": "root-epoch",
        "command_id": "root-command",
        "request": client.proofs["root"]["request"],
        "runtime_manifest": manifest,
    }
    info = SimpleNamespace(
        workflow_id="root", workflow_run_id="root-epoch", workflow_namespace="original"
    )
    return client, value, info


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic"])
def test_original_parent_admission_and_cold_discovery(monkeypatch, namespace, kind):
    client, value, info = application(monkeypatch, kind)
    result = asyncio.run(fixture.module().root_admission(fixture.runtime(), client, value, info))
    assert result == {
        "namespace": fixture.NAMESPACE,
        "admitted": True,
        "execution_epoch": "root-epoch",
    }
    root = asyncio.run(
        fixture.module()._initialize_root(
            client, fixture.SCOPE, client.candidate, fixture.MANIFEST, fixture.NAMESPACE
        )
    )
    assert root["execution_epoch"] == "root-epoch"
    assert root["request_digest"] == digest(value["request"])
    assert client.candidate["execution_epoch"] == "root-epoch"


@pytest.mark.parametrize("kind", ["team", "dynamic"])
def test_owned_close_stops_original_parent_before_releasing_admission(monkeypatch, namespace, kind):
    client, _, _ = application(monkeypatch, kind)
    asyncio.run(
        fixture.module().close(
            fixture.runtime(), client=client, scope=fixture.Scope(**fixture.SCOPE)
        )
    )
    assert client.candidate["close_requested"] is True
    assert client.proofs["root"]["physical_stopped"] is True
    commands = [call for call in client.calls if call[0] == "update" and call[3] == "command"]
    assert commands and all(call[2] == "root-epoch" for call in commands)


@pytest.mark.parametrize("kind", ["agent", "sequence", "unknown"])
def test_root_admission_rejects_nonparent_before_registry_io(monkeypatch, namespace, kind):
    client, value, info = application(monkeypatch, kind)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(fixture.module().root_admission(fixture.runtime(), client, value, info))
    assert client.calls == []


@pytest.mark.parametrize("kind", ["team", "dynamic"])
def test_replacement_sdk_epoch_cannot_admit_original_parent(monkeypatch, namespace, kind):
    client, value, info = application(monkeypatch, kind)
    info.workflow_run_id = "replacement-epoch"
    with pytest.raises(DefinitionMismatch):
        asyncio.run(fixture.module().root_admission(fixture.runtime(), client, value, info))
    assert client.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "foreign"),
        ("member", "foreign"),
        ("planning_revision", 1),
        ("command_id", "foreign"),
        ("child_request_digest", "foreign"),
    ],
)
def test_child_discovery_refuses_altered_frozen_intent_before_sdk_io(
    monkeypatch, namespace, field, value
):
    application(monkeypatch, "dynamic")
    client, run_id = fixture.linked_client()
    call = client.children[0]
    call["planning_revision"] = 0
    call[field] = value
    with pytest.raises(DefinitionMismatch):
        asyncio.run(
            fixture.module()._child_proof(
                client, client.proofs["root"], call, fixture.MANIFEST, fixture.NAMESPACE
            )
        )
    assert client.calls == []
