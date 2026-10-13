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

    _schema_file = "_codex_protocol_schema.json"
    _schema_digest = _SCHEMA_SHA256
    _null_requests = frozenset()

    def __init__(self, *, external_version: str = _VERSION):
        if external_version != _VERSION:
            raise DefinitionMismatch("Codex protocol version differs from the reviewed Schema")
        data = files("ralf_agent").joinpath(self._schema_file).read_bytes()
        if hashlib.sha256(data).hexdigest() != self._schema_digest:
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
        nullable = not response and type(method) is str and method in self._null_requests
        if (
            type(method) is not str
            or method not in validators
            or (type(value) is not dict and not (nullable and value is None))
        ):
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


class CodexControlProtocol(CodexProtocol):
    """Stable configuration readback only; never permits a Thread or Turn."""

    _schema_file = "_codex_control_schema.json"
    _schema_digest = "87807599334eb051aee3aedfae349c936108a0122770e73f0d466433d39d55bf"
    _null_requests = frozenset({"configRequirements/read"})

    @property
    def identity(self):
        return {
            "kind": "codex-app-server-control-protocol",
            "version": "1",
            "external_version": _VERSION,
            "schema_digest": self._schema_digest,
            "methods": sorted(self._requests),
            "experimental_api": False,
            "execution_admitted": False,
        }

    def validate_request(self, method: str, params: dict | None) -> dict | None:
        return self._validate(method, params, response=False)


class CodexCodingProtocol(CodexProtocol):
    """The finite union of reviewed business and control shapes.

    This schema permission does not admit execution. The runner must verify
    the same connection's control readback, profile and original engine grant.
    Both reference protocols retain their original resource bytes and identity.
    """

    _null_requests = CodexControlProtocol._null_requests

    def __init__(self, *, external_version: str = _VERSION):
        self._business_protocol = CodexProtocol(external_version=external_version)
        self._control_protocol = CodexControlProtocol(external_version=external_version)
        self._requests = {
            **self._control_protocol._requests,
            **self._business_protocol._requests,
        }
        self._responses = {
            **self._control_protocol._responses,
            **self._business_protocol._responses,
        }

    @property
    def identity(self):
        return {
            "kind": "codex-app-server-coding-protocol",
            "version": "1",
            "external_version": _VERSION,
            "business_protocol": self._business_protocol.identity,
            "control_protocol": self._control_protocol.identity,
            "methods": sorted(self._requests),
            "experimental_api": False,
            "execution_admitted": False,
            "environment_verified": False,
            "governance_verified": False,
        }

    def validate_request(self, method: str, params: dict | None) -> dict | None:
        return self._validate(method, params, response=False)
