"""Fixed deployment publication; Workflow validation performs no source I/O."""

import copy
import hashlib
from pathlib import Path

from .errors import DefinitionMismatch, ValidationError
from .temporal_deployment_admission import _exact, _policy, _sha, registry_id

SOURCE_FILES = (
    "temporal_deployment_execution_state.py",
    "temporal_deployment_protocol.py",
    "temporal_deployment_execution.py",
    "temporal_activities.py",
    "temporal_state.py",
    "temporal_workflow.py",
    "temporal_parent_workflow.py",
    "temporal_parent_state.py",
    "temporal_control_activities.py",
    "temporal.py",
)


PUBLIC_SOURCE_FILES = SOURCE_FILES + (
    "temporal_deployment_admission.py",
    "temporal_deployment_registry.py",
    "temporal_deployment_release_state.py",
    "temporal_deployment_release.py",
    "temporal_deployment_submissions.py",
    "temporal_context_execution.py",
    "tools.py",
    "temporal_assembly_lifecycle.py",
    "temporal_builder.py",
    "temporal_agent_runtime.py",
    "temporal_host_runtime.py",
    "temporal_profile_host.py",
)


def public_selected(manifest):
    return (
        selected(manifest)
        and type(manifest["deployment_admission_protocol"]) is dict
        and type(manifest["deployment_admission_protocol"].get("version")) is int
        and manifest["deployment_admission_protocol"].get("version") == 2
    )


def selected(manifest):
    return type(manifest) is dict and "deployment_admission_protocol" in manifest


def validate_protocol(manifest):
    if not selected(manifest):
        return
    value = manifest["deployment_admission_protocol"]
    try:
        _exact(value, {"version", "policy", "registry_id", "implementation"})
        if type(value["version"]) is not int or value["version"] not in (1, 2):
            raise ValidationError("Invalid original deployment protocol version")
        policy = _policy(value["policy"])
        if value["registry_id"] != registry_id(policy["deployment_id"]):
            raise DefinitionMismatch("Original deployment Registry address changed")
        _exact(
            value["implementation"],
            set(PUBLIC_SOURCE_FILES if value["version"] == 2 else SOURCE_FILES),
        )
        for fingerprint in value["implementation"].values():
            _sha(fingerprint)
        if manifest.get("kernel") not in {"temporal-1", "temporal-2", "temporal-3"}:
            raise DefinitionMismatch("Unsupported deployment runtime release")
        if manifest.get("kernel") == "temporal-3" and (
            type(manifest.get("binding_protocol")) is not int
            or not 1 <= manifest["binding_protocol"] <= 10
            or manifest.get("dispatch_admission") != "history-1"
        ):
            raise DefinitionMismatch("Unsupported deployment binding header")
        if any(
            name in manifest
            for name in ("coding_execution_protocol", "coding_composition_protocol")
        ):
            raise DefinitionMismatch("Deployment Coding execution is not admitted")
    except (ValidationError, TypeError, ValueError, KeyError):
        raise DefinitionMismatch("Invalid fixed deployment admission publication") from None


def publish(manifest, policy_identity, *, public=False):
    result = copy.deepcopy(manifest)
    if policy_identity is None:
        return result
    policy = _policy(policy_identity)
    directory = Path(__file__).parent
    result["deployment_admission_protocol"] = {
        "version": 2 if public else 1,
        "policy": policy,
        "registry_id": registry_id(policy["deployment_id"]),
        "implementation": {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in (PUBLIC_SOURCE_FILES if public else SOURCE_FILES)
        },
    }
    validate_protocol(result)
    return result
