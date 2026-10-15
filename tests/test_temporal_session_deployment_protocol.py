"""Explicit Session deployment publication preserves existing selections."""

import copy
import hashlib

import pytest

from ralf_agent import temporal_deployment_protocol as protocol
from ralf_agent.errors import DefinitionMismatch, ValidationError
from tests.test_temporal_deployment_protocol import POLICY


def base():
    return {"kernel": "temporal-1", "session_protocol": 1, "dispatch_admission": "history-1"}


def selected():
    value = base()
    value["session_deployment_protocol"] = 1
    value["deployment_admission_protocol"] = {
        "version": 4,
        "policy": copy.deepcopy(POLICY),
        "registry_id": protocol.registry_id(POLICY["deployment_id"]),
        "implementation": {name: "a" * 64 for name in protocol.SESSION_SOURCE_FILES},
    }
    return value


def test_four_is_explicit_public_session_selection():
    value = selected()
    assert protocol.public_selected(value)
    assert protocol.validate_protocol(value) is None


def test_session_publication_hashes_complete_sources_and_keeps_input(tmp_path, monkeypatch):
    for name in protocol.SESSION_SOURCE_FILES:
        (tmp_path / name).write_bytes((name + " original").encode())
    monkeypatch.setattr(protocol, "__file__", str(tmp_path / "temporal_deployment_protocol.py"))
    original = base()
    value = protocol.publish(original, POLICY, public=True, session_deployment=True)
    assert original == base()
    assert value["session_deployment_protocol"] == 1
    assert value["deployment_admission_protocol"]["version"] == 4
    assert value["deployment_admission_protocol"]["implementation"] == {
        name: hashlib.sha256((name + " original").encode()).hexdigest()
        for name in protocol.SESSION_SOURCE_FILES
    }
    assert len(protocol.SESSION_SOURCE_FILES) == len(set(protocol.SESSION_SOURCE_FILES))
    unchanged = protocol.publish(original, POLICY, public=True)
    assert unchanged["deployment_admission_protocol"]["version"] == 2
    assert "session_deployment_protocol" not in unchanged


@pytest.mark.parametrize(
    "mutation",
    [
        "no_session",
        "bool_session",
        "bool_marker",
        "no_marker",
        "coding",
        "missing_source",
        "extra_source",
        "legacy_marker",
    ],
)
def test_four_refuses_incomplete_or_other_protocol_selection(mutation):
    value = selected()
    if mutation == "no_session":
        value.pop("session_protocol")
    elif mutation == "bool_session":
        value["session_protocol"] = True
    elif mutation == "bool_marker":
        value["session_deployment_protocol"] = True
    elif mutation == "no_marker":
        value.pop("session_deployment_protocol")
    elif mutation == "coding":
        value["coding_execution_protocol"] = {"version": 6}
    elif mutation == "missing_source":
        value["deployment_admission_protocol"]["implementation"].pop("temporal_session_client.py")
    elif mutation == "extra_source":
        value["deployment_admission_protocol"]["implementation"]["unknown.py"] = "a" * 64
    else:
        value["deployment_admission_protocol"]["version"] = 2
        value["deployment_admission_protocol"]["implementation"] = {
            name: "a" * 64 for name in protocol.PUBLIC_SOURCE_FILES
        }
    with pytest.raises(DefinitionMismatch):
        protocol.validate_protocol(value)


@pytest.mark.parametrize(
    "policy,public,selection", [(None, True, True), (POLICY, False, True), (POLICY, True, 1)]
)
def test_session_selection_requires_explicit_public_policy(policy, public, selection):
    with pytest.raises((DefinitionMismatch, ValidationError)):
        protocol.publish(base(), policy, public=public, session_deployment=selection)
