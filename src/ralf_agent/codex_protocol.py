"""Reviewed Codex protocol shapes; not authorization or environment isolation."""

import hashlib
import json
from importlib.resources import files

from jsonschema import Draft7Validator

from .errors import DefinitionMismatch, ValidationError

_VERSION = "0.144.4"
_SCHEMA_SHA256 = "5d2ba8cdee699144bd0ec23760146c6f45919fa9ac6ec5b61004dc3ea7b2a275"


def _snapshot(value, label):
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 64 or count > 65536:
            raise ValidationError(f"Codex {label} exceeds the structural bound")
        if type(item) is dict:
            if len(item) > 65536 or any(type(k) is not str for k in item):
                raise ValidationError(f"Codex {label} requires bounded string keys")
            pending.extend((k, depth + 1) for k in item)
            pending.extend((v, depth + 1) for v in item.values())
        elif type(item) is list:
            if len(item) > 65536:
                raise ValidationError(f"Codex {label} exceeds the structural bound")
            pending.extend((v, depth + 1) for v in item)
        elif type(item) is str:
            if len(item) > 1048576 or any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                raise ValidationError(f"Codex {label} exceeds the UTF-8 bound")
        elif item is not None and type(item) not in (bool, int, float):
            raise ValidationError(f"Codex {label} requires finite JSON")
    output = bytearray()
    try:
        for part in json.JSONEncoder(allow_nan=False, ensure_ascii=False).iterencode(value):
            if len(part) > 1048576:
                raise ValueError
            encoded = part.encode("utf-8")
            if len(output) + len(encoded) > 1048576:
                raise ValueError
            output.extend(encoded)
        return json.loads(output)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise ValidationError(f"Codex {label} requires bounded finite JSON") from None


def _strict_request(value):
    if isinstance(value, dict):
        result = {k: _strict_request(v) for k, v in value.items()}
        if "properties" in result and "additionalProperties" not in result:
            result["additionalProperties"] = False
        return result
    if isinstance(value, list):
        return [_strict_request(v) for v in value]
    return value


class CodexProtocol:
    """Finite Schema validation for one pinned native protocol subset.

    Valid parameters may still request unsafe native permissions. The caller
    must separately enforce a verified environment/profile and outer authority.
    Validation neither starts a process nor changes Run/Action state.
    """

    def __init__(self, *, external_version: str = _VERSION):
        if external_version != _VERSION:
            raise DefinitionMismatch("Codex protocol version differs from the reviewed Schema")
        data = files("ralf_agent").joinpath("_codex_protocol_schema.json").read_bytes()
        if hashlib.sha256(data).hexdigest() != _SCHEMA_SHA256:
            raise DefinitionMismatch("Codex protocol Schema integrity differs")
        document = json.loads(data)
        self._requests, self._responses = {}, {}
        for method, schemas in document["schemas"].items():
            request = _strict_request(schemas["request"])
            Draft7Validator.check_schema(request)
            Draft7Validator.check_schema(schemas["response"])
            self._requests[method] = Draft7Validator(request)
            self._responses[method] = Draft7Validator(schemas["response"])

    @property
    def identity(self):
        return {
            "kind": "codex-app-server-protocol",
            "version": "1",
            "external_version": _VERSION,
            "schema_digest": _SCHEMA_SHA256,
            "methods": sorted(self._requests),
            "experimental_api": False,
            "environment_verified": False,
            "governance_verified": False,
        }

    def _validate(self, method, value, *, response):
        validators = self._responses if response else self._requests
        label = "response" if response else "request"
        if type(method) is not str or method not in validators or type(value) is not dict:
            raise ValidationError(f"Codex {label} method or value is not supported")
        snapshot = _snapshot(value, label)
        if not validators[method].is_valid(snapshot):
            raise ValidationError(f"Codex {label} does not match the pinned Schema")
        if not response and method == "initialize":
            capabilities = snapshot.get("capabilities") or {}
            if any(
                capabilities.get(name, False)
                for name in (
                    "experimentalApi",
                    "mcpServerOpenaiFormElicitation",
                    "requestAttestation",
                )
            ):
                raise ValidationError("Codex extended handshake capabilities are unavailable")
        return snapshot

    def validate_request(self, method: str, params: dict) -> dict:
        return self._validate(method, params, response=False)

    def validate_response(self, method: str, result: dict) -> dict:
        return self._validate(method, result, response=True)
