"""Explicit integration cannot replace or drop either original publication."""

import copy

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_deployment_protocol import (
    PUBLIC_SOURCE_FILES,
    public_selected,
    validate_protocol,
)
from ralf_agent.types import digest
from tests.test_temporal_coding_configuration import manifest
from tests.test_temporal_deployment_protocol import POLICY

ADDITIONS = (
    "temporal_deployment_coding_registry.py",
    "temporal_deployment_coding_state.py",
    "temporal_deployment_coding_bridge.py",
    "temporal_coding_state.py",
    "temporal_coding_runtime.py",
    "temporal_coding_composition_state.py",
    "temporal_coding_composition_control.py",
    "temporal_coding_composition_submissions.py",
    "temporal_coding_protocol.py",
    "temporal_coding_composition_protocol.py",
    "temporal_deployment_control_projection.py",
    "temporal_deployment_coding_validation.py",
    "temporal_deployment_control_transport.py",
)


def selected():
    value = manifest()
    value["deployment_admission_protocol"] = {
        "version": 3,
        "policy": copy.deepcopy(POLICY),
        "registry_id": "ralf-temporal-deployment-" + digest("execution-state"),
        "implementation": {name: "c" * 64 for name in (*PUBLIC_SOURCE_FILES, *ADDITIONS)},
    }
    return value


def test_public_three_admits_the_existing_complete_native_release():
    value = selected()
    assert public_selected(value) is True
    assert validate_protocol(value) is None


@pytest.mark.parametrize(
    "mutation",
    [
        "drop_old_pin",
        "drop_bridge",
        "ordinary",
        "wrong_native",
        "wrong_binding",
        "private",
        "drop_projection",
        "drop_validation",
        "drop_control",
    ],
)
def test_integration_requires_both_full_publications(mutation):
    value = selected()
    if mutation == "drop_old_pin":
        value["deployment_admission_protocol"]["implementation"].pop("temporal.py")
    elif mutation == "drop_bridge":
        value["deployment_admission_protocol"]["implementation"].pop(
            "temporal_deployment_coding_bridge.py"
        )
    elif mutation in {"drop_projection", "drop_validation", "drop_control"}:
        value["deployment_admission_protocol"]["implementation"].pop(
            {
                "drop_projection": "temporal_deployment_control_projection.py",
                "drop_validation": "temporal_deployment_coding_validation.py",
                "drop_control": "temporal_deployment_control_transport.py",
            }[mutation]
        )
    elif mutation == "ordinary":
        value.pop("coding_execution_protocol")
    elif mutation == "wrong_native":
        value["coding_execution_protocol"]["version"] = 5
    elif mutation == "wrong_binding":
        value["binding_protocol"] = 10
    else:
        value["deployment_admission_protocol"]["version"] = 1
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)
