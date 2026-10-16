"""Fixed release publication, with pure validation on Workflow History."""

import copy
import hashlib
import importlib
from pathlib import Path

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.types import digest

POLICY = {
    "kind": "deployment-admission-policy",
    "deployment_id": "execution-state",
    "version": "original",
    "max_active_root_runs": 4,
    "max_active_root_runs_per_scope": 2,
}
FILES = {
    "temporal_deployment_execution_state.py",
    "temporal_deployment_protocol.py",
    "temporal_deployment_execution.py",
    "temporal_activities.py",
    "temporal_state.py",
    "temporal_workflow.py",
    "temporal_command_transport.py",
    "temporal_execution_end_transport.py",
    "temporal_scoped_manual_transport.py",
    "temporal_parent_workflow.py",
    "temporal_parent_state.py",
    "temporal_control_activities.py",
    "temporal.py",
}


def test_original_execution_admission_helpers_are_available():
    for name in ("temporal_deployment_protocol", "temporal_deployment_execution_state"):
        assert importlib.util.find_spec("ralf_agent." + name) is not None


@pytest.fixture
def protocol():
    name = "ralf_agent.temporal_deployment_protocol"
    assert importlib.util.find_spec(name) is not None, "Deployment publication is missing"
    return importlib.import_module(name)


def manifest():
    return {
        "kernel": "temporal-1",
        "deployment_admission_protocol": {
            "version": 1,
            "policy": copy.deepcopy(POLICY),
            "registry_id": "ralf-temporal-deployment-" + digest("execution-state"),
            "implementation": {name: "a" * 64 for name in FILES},
        },
    }


def test_selection_and_default_publication_keep_input_byte_identity(protocol):
    original = {"kernel": "temporal-1", "opaque": ["unchanged"]}
    assert not protocol.selected(original)
    assert protocol.publish(original, None) == original
    assert protocol.validate_protocol(original) is None
    assert original == {"kernel": "temporal-1", "opaque": ["unchanged"]}


def test_publication_hashes_every_fixed_source_without_changing_manifest(
    protocol, tmp_path, monkeypatch
):
    for index, name in enumerate(sorted(FILES)):
        (tmp_path / name).write_bytes(f"original implementation {index}\n".encode())
    monkeypatch.setattr(protocol, "__file__", str(tmp_path / "temporal_deployment_protocol.py"))
    original = {"kernel": "temporal-1"}
    selected = protocol.publish(original, POLICY)
    assert protocol.selected(selected)
    assert original == {"kernel": "temporal-1"}
    published = selected["deployment_admission_protocol"]
    assert published["policy"] == POLICY
    assert published["registry_id"] == "ralf-temporal-deployment-" + digest("execution-state")
    assert published["implementation"] == {
        name: hashlib.sha256(f"original implementation {index}\n".encode()).hexdigest()
        for index, name in enumerate(sorted(FILES))
    }
    assert protocol.validate_protocol(selected) is None
    (tmp_path / "temporal_workflow.py").write_bytes(b"replacement implementation")
    assert (
        protocol.publish(original, POLICY)["deployment_admission_protocol"]["implementation"]
        != published["implementation"]
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m["deployment_admission_protocol"].update(version=True),
        lambda m: m["deployment_admission_protocol"].update(extra=True),
        lambda m: m["deployment_admission_protocol"].update(registry_id="foreign"),
        lambda m: m["deployment_admission_protocol"]["policy"].update(max_active_root_runs=True),
        lambda m: m["deployment_admission_protocol"]["policy"].update(extra="foreign"),
        lambda m: m["deployment_admission_protocol"]["implementation"].pop("temporal.py"),
        lambda m: m["deployment_admission_protocol"]["implementation"].update(extra="a" * 64),
        lambda m: m["deployment_admission_protocol"]["implementation"].update(
            **{"temporal.py": "wrong"}
        ),
        lambda m: m.update(kernel="foreign"),
        lambda m: m.update(
            kernel="temporal-3", binding_protocol=True, dispatch_admission="history-1"
        ),
        lambda m: m.update(
            kernel="temporal-3", binding_protocol=11, dispatch_admission="history-1"
        ),
        lambda m: m.update(coding_execution_protocol={}),
        lambda m: m.update(coding_composition_protocol={}),
    ],
)
def test_invalid_selected_protocol_refuses_in_pure_validation(protocol, change):
    value = manifest()
    change(value)
    with pytest.raises((DefinitionMismatch, ValidationError)):
        protocol.validate_protocol(value)


def test_workflow_validation_does_not_read_current_worker_source(protocol, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Workflow validation attempted file I/O")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    assert protocol.validate_protocol(manifest()) is None
