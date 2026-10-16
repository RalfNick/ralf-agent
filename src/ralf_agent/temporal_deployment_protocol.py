"""Fixed deployment publication; Workflow validation performs no source I/O."""

import copy
import hashlib
from pathlib import Path

from .errors import DefinitionMismatch, ValidationError
from .temporal_deployment_admission import _exact, _policy, _sha, registry_id
from .temporal_deployment_coding_state import check_guard_registration as _guard_registration

_GUARD_REGISTRATION_CODE = _guard_registration.__code__

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
    "temporal_reservation_transport.py",
    "temporal_context_execution.py",
    "tools.py",
    "temporal_assembly_lifecycle.py",
    "temporal_builder.py",
    "temporal_agent_runtime.py",
    "temporal_host_runtime.py",
    "temporal_profile_host.py",
)

CODING_SOURCE_FILES = PUBLIC_SOURCE_FILES + (
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

SESSION_SOURCE_FILES = CODING_SOURCE_FILES + (
    "temporal_session_state.py",
    "temporal_session_workflow.py",
    "temporal_session_client.py",
    "temporal_session_activities.py",
    "temporal_session_identity.py",
    "temporal_session_tree.py",
    "temporal_session_deployment_dto.py",
    "temporal_session_deployment_state.py",
    "temporal_deployment_session_registry.py",
    "temporal_session_deployment_control.py",
    "temporal_session_deployment_verification.py",
    "temporal_deployment_session_updates.py",
    "temporal_session_deployment_client.py",
    "temporal_session_deployment_close.py",
    "temporal_session_activity_reads.py",
)


def public_selected(manifest):
    return (
        selected(manifest)
        and type(manifest["deployment_admission_protocol"]) is dict
        and type(manifest["deployment_admission_protocol"].get("version")) is int
        and manifest["deployment_admission_protocol"].get("version") in (2, 3, 4)
    )


def selected(manifest):
    return type(manifest) is dict and "deployment_admission_protocol" in manifest


def validate_protocol(manifest):
    if not selected(manifest):
        if type(manifest) is dict and "session_deployment_protocol" in manifest:
            raise DefinitionMismatch("Session deployment requires its selected publication")
        return
    value = manifest["deployment_admission_protocol"]
    try:
        _exact(value, {"version", "policy", "registry_id", "implementation"})
        if type(value["version"]) is not int or value["version"] not in (1, 2, 3, 4):
            raise ValidationError("Invalid original deployment protocol version")
        policy = _policy(value["policy"])
        if value["registry_id"] != registry_id(policy["deployment_id"]):
            raise DefinitionMismatch("Original deployment Registry address changed")
        _exact(
            value["implementation"],
            set(
                SESSION_SOURCE_FILES
                if value["version"] == 4
                else CODING_SOURCE_FILES
                if value["version"] == 3
                else PUBLIC_SOURCE_FILES
                if value["version"] == 2
                else SOURCE_FILES
            ),
        )
        for fingerprint in value["implementation"].values():
            _sha(fingerprint)
        if manifest.get("kernel") not in {"temporal-1", "temporal-2", "temporal-3"}:
            raise DefinitionMismatch("Unsupported deployment runtime release")
        if value["version"] == 4:
            if (
                type(manifest.get("session_protocol")) is not int
                or manifest["session_protocol"] != 1
                or type(manifest.get("session_deployment_protocol")) is not int
                or manifest["session_deployment_protocol"] != 1
                or manifest.get("dispatch_admission") != "history-1"
            ):
                raise DefinitionMismatch("Deployment4 requires its explicit Session protocol")
        elif "session_deployment_protocol" in manifest:
            raise DefinitionMismatch("Session deployment requires publication4")
        coding = value["version"] == 3 or (
            value["version"] == 4 and "coding_execution_protocol" in manifest
        )
        if coding:
            from . import temporal_deployment_coding_state
            from .temporal_coding_protocol import validate_protocol as validate_coding

            if (
                temporal_deployment_coding_state.check_guard_registration is not _guard_registration
                or _guard_registration.__code__ is not _GUARD_REGISTRATION_CODE
            ):
                raise DefinitionMismatch("Original Coding guard registration changed")
            _guard_registration(manifest)

            if "coding_execution_protocol" not in manifest:
                raise DefinitionMismatch("Deployment3 requires original Coding publication")
            validate_coding(manifest)
        elif manifest.get("kernel") == "temporal-3" and (
            type(manifest.get("binding_protocol")) is not int
            or not 1 <= manifest["binding_protocol"] <= 10
            or manifest.get("dispatch_admission") != "history-1"
        ):
            raise DefinitionMismatch("Unsupported deployment binding header")
        if not coding and any(
            name in manifest
            for name in ("coding_execution_protocol", "coding_composition_protocol")
        ):
            raise DefinitionMismatch("Deployment Coding execution is not admitted")
    except (ValidationError, TypeError, ValueError, KeyError):
        raise DefinitionMismatch("Invalid fixed deployment admission publication") from None


def publish(manifest, policy_identity, *, public=False, _copy=True, session_deployment=False):
    result = copy.deepcopy(manifest) if _copy else manifest
    if type(session_deployment) is not bool:
        raise ValidationError("Session deployment selection requires an explicit boolean")
    if session_deployment and (not public or policy_identity is None):
        raise ValidationError("Session deployment requires explicit public admission")
    if policy_identity is None:
        return result
    policy = _policy(policy_identity)
    directory = Path(__file__).parent
    version = (
        4
        if session_deployment
        else 3
        if public and "coding_execution_protocol" in result
        else 2
        if public
        else 1
    )
    if session_deployment:
        result["session_deployment_protocol"] = 1
    files = (
        SESSION_SOURCE_FILES
        if version == 4
        else CODING_SOURCE_FILES
        if version == 3
        else PUBLIC_SOURCE_FILES
        if version == 2
        else SOURCE_FILES
    )
    result["deployment_admission_protocol"] = {
        "version": version,
        "policy": policy,
        "registry_id": registry_id(policy["deployment_id"]),
        "implementation": {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in files
        },
    }
    validate_protocol(result)
    return result
