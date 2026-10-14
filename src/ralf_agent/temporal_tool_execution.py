"""Explicit fixed Tool lifetime publication; original History owns progression."""

import json
import math

from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, ValidationError
from .ports import is_async_callable
from .session_types import sha
from .task_controls import _binding
from .types import canonical, digest

METHODS = ("execute", "wait", "aclose")


def notification_identity():
    from .temporal_context_execution import ContextExecutionOwner

    return {
        "max_calls": 256,
        "implementation": {
            name: executable_digest(getattr(ContextExecutionOwner, name)) for name in METHODS
        },
    }


def ordinary(value):
    count, size = 0, 0

    def visit(item, depth):
        nonlocal count, size
        count += 1
        if count > 4096 or depth > 16:
            raise ValidationError("Tool owner metadata exceeds its structural allowance")
        kind = type(item)
        if kind is str:
            size += len(item.encode("utf-8"))
        elif kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValidationError("Tool owner metadata requires ordinary string keys")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif kind is list:
            for child in item:
                visit(child, depth + 1)
        elif kind not in (int, float, bool, type(None)) or (
            kind is float and not math.isfinite(item)
        ):
            raise ValidationError("Tool owner metadata requires finite ordinary JSON")
        if size > 65536:
            raise ValidationError("Tool owner metadata exceeds its byte allowance")

    try:
        visit(value, 0)
        encoded = canonical(value)
        if len(encoded.encode("utf-8")) > 65536:
            raise ValidationError("Tool owner metadata exceeds its serialized allowance")
        return json.loads(encoded)
    except (UnicodeError, RecursionError):
        raise ValidationError("Tool owner metadata requires bounded UTF-8 JSON") from None


def enabled(manifest):
    return "tool_execution_protocol" in manifest


def validate_protocol(manifest):
    if not enabled(manifest) and manifest.get("binding_protocol") != 3:
        return
    value = manifest.get("tool_execution_protocol")
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] not in (3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
        or (manifest["binding_protocol"] == 4 and manifest.get("sandbox_binding_protocol") != 1)
        or type(value) is not dict
        or set(value) != {"version", "owner", "implementation", "notifications"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["owner"]) is not dict
        or not value["owner"]
        or type(value["implementation"]) is not dict
        or set(value["implementation"]) != set(METHODS)
    ):
        raise DefinitionMismatch("Unsupported original Tool execution protocol")
    try:
        ordinary(value)
        for item in value["implementation"].values():
            sha(item)
        if value["notifications"] != notification_identity():
            raise ValidationError("Tool notifications lost their fixed mechanical owner")
    except (ValidationError, ValueError, TypeError):
        raise DefinitionMismatch("Tool execution lost its fixed bounded owner identity") from None


class ToolExecutionRegistration:
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
            raise ValidationError("Tool execution requires fixed identity and async owner ports")
        value = {
            "version": 1,
            "owner": ordinary(identity),
            "implementation": {
                name: executable_digest(getattr(self.owner, name)) for name in METHODS
            },
            "notifications": notification_identity(),
        }
        validate_protocol(
            {"kernel": "temporal-3", "binding_protocol": 3, "tool_execution_protocol": value}
        )
        return value

    def check(self):
        if (
            self.owner is not self._owner
            or any(
                _binding(getattr(self.owner, name, None)) != binding
                for name, binding in self._methods.items()
            )
            or digest(self._capture()) != digest(self._identity)
        ):
            raise DefinitionMismatch("Tool execution owner, methods or configuration changed")

    @property
    def identity(self):
        self.check()
        return ordinary(self._identity)


def publish(manifest, registration):
    from .temporal_state import validate_manifest

    result = validate_manifest(ordinary_manifest(manifest))
    return validate_manifest(propose(result, registration))


def propose(manifest, registration):
    """Pure original metadata assembly; caller validates the complete joint release."""
    result = ordinary_manifest(manifest)
    if not isinstance(registration, ToolExecutionRegistration):
        raise ValidationError("Tool execution requires an original fixed registration")
    if enabled(result):
        raise DefinitionMismatch("Tool execution requires its original baseline proposal")
    result.update(
        kernel="temporal-3",
        binding_protocol=3,
        dispatch_admission="history-1",
        tool_execution_protocol=registration.identity,
    )
    return result


def ordinary_manifest(manifest):
    # The complete runtime manifest has its existing, independent size contract.
    return json.loads(canonical(manifest))
