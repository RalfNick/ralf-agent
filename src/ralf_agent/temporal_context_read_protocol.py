"""Fixed read-lifetime metadata; original History owns admission and progress."""

import copy

from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, ValidationError
from .ports import is_async_callable
from .session_types import sha
from .task_controls import _binding
from .types import canonical, digest

PHASES = frozenset({"context", "plan", "read", "verify", "finalize"})
METHODS = ("execute", "wait", "aclose")


def enabled(manifest):
    return "context_read_protocol" in manifest


def owns_activity(manifest, action):
    return enabled(manifest) and (
        action["kind"] == "context"
        or action["kind"] == "managed_context"
        and action.get("phase") in PHASES
    )


def validate_protocol(manifest):
    registration = manifest.get("context_read_protocol")
    if "context_read_protocol" not in manifest and manifest.get("binding_protocol") != 2:
        if "context_read_metadata_bridges" in manifest:
            raise DefinitionMismatch(
                "Context metadata bridges require their original read protocol"
            )
        return
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] not in (2, 3, 4)
        or (manifest["binding_protocol"] in (3, 4) and "tool_execution_protocol" not in manifest)
        or (manifest["binding_protocol"] == 4 and manifest.get("sandbox_binding_protocol") != 1)
        or type(registration) is not dict
        or set(registration) != {"version", "phases", "owner", "implementation"}
        or type(registration["version"]) is not int
        or registration["version"] != 1
        or registration["phases"] != sorted(PHASES)
        or type(registration["owner"]) is not dict
        or not registration["owner"]
        or type(registration["implementation"]) is not dict
        or set(registration["implementation"]) != set(METHODS)
    ):
        raise DefinitionMismatch("Unsupported original Context read execution protocol")
    try:
        if len(canonical(registration).encode("utf-8")) > 65536:
            raise ValidationError("Context read metadata exceeds its bounded allowance")
        for value in registration["implementation"].values():
            sha(value)
        bridges = manifest.get("context_read_metadata_bridges", {})
        if (
            type(bridges) is not dict
            or len(bridges) > 256
            or len(canonical(bridges).encode("utf-8")) > 1048576
            or not set(bridges)
            <= set(manifest.get("session_save_protocol", {}).get("dataset_ports", {}))
            or any(type(port) is not dict or not port for port in bridges.values())
        ):
            raise ValidationError("Context metadata bridge escaped its original registered dataset")
        for key in bridges:
            sha(key)
    except (ValidationError, TypeError, ValueError):
        raise DefinitionMismatch("Context reads lost their fixed bounded owner identity") from None


class ContextExecutionRegistration:
    def __init__(self, owner):
        self.owner = self._owner = owner
        self._methods = {name: _binding(getattr(owner, name, None)) for name in METHODS}
        self._identity = self._capture()

    def _capture(self):
        identity = getattr(self.owner, "identity", None)
        if (
            type(identity) is not dict
            or not identity
            or any(not is_async_callable(getattr(self.owner, name, None)) for name in METHODS)
        ):
            raise ValidationError("Context execution requires fixed identity and async owner ports")
        result = {
            "version": 1,
            "phases": sorted(PHASES),
            "owner": copy.deepcopy(identity),
            "implementation": {
                name: executable_digest(getattr(self.owner, name)) for name in METHODS
            },
        }
        validate_protocol(
            {"kernel": "temporal-3", "binding_protocol": 2, "context_read_protocol": result}
        )
        return result

    def check(self):
        if (
            self.owner is not self._owner
            or any(
                _binding(getattr(self.owner, name, None)) != binding
                for name, binding in self._methods.items()
            )
            or digest(self._capture()) != digest(self._identity)
        ):
            raise DefinitionMismatch("Context execution owner, methods or configuration changed")

    @property
    def identity(self):
        self.check()
        return copy.deepcopy(self._identity)


def publish(manifest, registration):
    """An explicit metadata proposal; Runtime publication waits for original gates."""
    from .temporal_state import validate_manifest

    if not isinstance(registration, ContextExecutionRegistration):
        raise ValidationError("Context reads require an original fixed execution registration")
    result = validate_manifest(copy.deepcopy(manifest))
    return propose(result, registration)


def propose(manifest, registration):
    """Pure original metadata assembly; caller validates the complete joint release."""
    if not isinstance(registration, ContextExecutionRegistration):
        raise ValidationError("Context reads require an original fixed execution registration")
    result = copy.deepcopy(manifest)
    if enabled(result) or result.get("binding_protocol", 1) != 1:
        raise DefinitionMismatch("Context execution requires its original baseline proposal")
    result.update(
        kernel="temporal-3",
        binding_protocol=2,
        dispatch_admission="history-1",
        context_read_protocol=registration.identity,
    )
    validate_protocol(result)
    return result
