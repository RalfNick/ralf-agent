"""Candidate tree releases must not reinterpret native save-v1 releases."""

import copy

import pytest

from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.temporal_state import validate_manifest

from .test_temporal_session_tree_sources import setup


def proposal(manifest):
    from relf_agent.temporal_session_topology import (
        CompositeSessionTopology,
        SessionTopologyRegistration,
    )
    from relf_agent.temporal_session_tree_protocol import propose_manifest

    return propose_manifest(manifest, SessionTopologyRegistration(CompositeSessionTopology()))


def test_tree_candidate_is_explicit_versioned_and_does_not_mutate_native_release():
    host, _, _ = setup()
    original = host.orchestration_release
    before = copy.deepcopy(original)
    candidate = proposal(original)
    assert candidate["session_save_protocol"]["version"] == 2
    assert candidate["session_tree_protocol"]["version"] == 1
    assert original == before == host.orchestration_release
    assert original["session_save_protocol"]["version"] == 1
    assert "session_tree_protocol" not in original
    assert validate_manifest(candidate) == candidate


@pytest.mark.parametrize("damage", ["version", "save-version", "method", "policy", "extra"])
def test_unsupported_or_unfixed_tree_protocol_is_refused_before_io(damage):
    host, _, _ = setup()
    candidate = proposal(host.orchestration_release)
    tree = candidate["session_tree_protocol"]
    if damage == "version":
        tree["version"] = True
    elif damage == "save-version":
        candidate["session_save_protocol"]["version"] = 1
    elif damage == "method":
        tree["implementation"]["member_address"] = "unfixed"
    elif damage == "policy":
        tree["policy"] = None
    else:
        tree["grant_execution"] = True
    with pytest.raises((DefinitionMismatch, ValidationError)):
        validate_manifest(candidate)


def test_candidate_requires_original_session_admission_and_save_contract():
    host, _, _ = setup()
    manifest = host.orchestration_release
    del manifest["session_protocol"]
    with pytest.raises((DefinitionMismatch, ValidationError)):
        proposal(manifest)


def test_native_save_v2_without_explicit_topology_is_refused():
    host, _, _ = setup()
    manifest = host.orchestration_release
    manifest["session_save_protocol"]["version"] = 2
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)


@pytest.mark.parametrize("value", [True, None, []])
def test_malformed_save_policy_is_rejected_as_a_contract_error(value):
    host, _, _ = setup()
    manifest = host.orchestration_release
    manifest["session_save_protocol"] = value
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)


def test_explicit_null_tree_policy_is_not_treated_as_legacy():
    host, _, _ = setup()
    manifest = host.orchestration_release
    manifest["session_tree_protocol"] = None
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)
