"""Pure, replaceable Agent completion rules over committed execution evidence."""

import json
import re
from typing import Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .errors import ValidationError
from .orchestration_types import _JsonValue
from .types import canonical


class CompletionRequest(_JsonValue):
    def __init__(self, task, output, receipts):
        if not isinstance(receipts, (list, tuple)) or any(
            not isinstance(item, dict)
            or set(item) != {"id", "tool", "arguments", "result", "receipt", "effect_key"}
            or not isinstance(item["arguments"], dict)
            or not isinstance(item["receipt"], dict)
            or any(
                not isinstance(item[key], str) or not item[key]
                for key in ("id", "tool", "effect_key")
            )
            for item in receipts
        ):
            raise ValidationError("Completion receipts require committed tool evidence")
        self._data_json = canonical({"task": task, "output": output, "receipts": list(receipts)})


class CompletionVerdict(_JsonValue):
    def __init__(self, status, feedback=None):
        if status not in {"accept", "reject", "retry"}:
            raise ValidationError("Completion verdict must accept, reject or retry")
        if feedback is not None and (
            not isinstance(feedback, str) or not feedback.strip() or len(feedback) > 4096
        ):
            raise ValidationError("Completion feedback must contain 1 to 4096 characters")
        if status == "retry" and feedback is None or status == "accept" and feedback is not None:
            raise ValidationError("Retry requires feedback; accepted completion has no feedback")
        self._data_json = canonical({"status": status, "feedback": feedback})


class CompletionVerifier(Protocol):
    identity: dict

    def verify(self, request: CompletionRequest) -> CompletionVerdict: ...


class SchemaCompletionVerifier:
    """Baseline only: the authority has already applied required output Schemas."""

    identity = {"kind": "schema-completion-verifier", "version": "1"}

    def verify(self, request):
        return CompletionVerdict("accept")


def _schema(schema):
    if schema is None:
        return None
    if not isinstance(schema, (dict, bool)):
        raise ValidationError("Completion rules require JSON Schemas")
    try:
        schema = json.loads(canonical(schema))
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValidationError("Invalid completion rule Schema") from exc
    return schema


def _pointer(value, pointer):
    for part in pointer.split("/")[1:] if pointer else []:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(part)
    return value


def _matches(schema, value):
    try:
        # Empty registry has no retrieval callback. Only resources contained in
        # this fixed Schema can be resolved; a URI never becomes hidden I/O.
        return Draft202012Validator(schema, registry=Registry()).is_valid(value)
    except Unresolvable as exc:
        raise ValidationError("Completion Schema contains an unresolved reference") from exc


class ToolReceiptVerifier:
    """Require a corresponding committed result; external truth remains host-owned."""

    def __init__(
        self,
        tool,
        *,
        when=None,
        result_schema=None,
        argument_bindings=None,
        on_missing="retry",
        feedback=None,
    ):
        if not isinstance(tool, str) or not tool.strip():
            raise ValidationError("Completion rule requires a tool name")
        if on_missing not in {"reject", "retry"}:
            raise ValidationError("Missing tool evidence must reject or retry")
        bindings = {} if argument_bindings is None else argument_bindings
        if not isinstance(bindings, dict) or any(
            not isinstance(key, str)
            or not key
            or not isinstance(pointer, str)
            or pointer
            and (not pointer.startswith("/") or re.search(r"~(?![01])", pointer))
            for key, pointer in bindings.items()
        ):
            raise ValidationError("Argument bindings require valid JSON Pointers")
        verdict = CompletionVerdict(
            on_missing,
            feedback
            if feedback is not None
            else f"A corresponding completed {tool} tool receipt is required. Continue using the allowed tools and normal approval flow; do not claim completion without evidence.",
        )
        self._identity_json = canonical(
            {
                "kind": "tool-receipt-completion-verifier",
                "version": "1",
                "tool": tool,
                "when": _schema(when),
                "result_schema": _schema(result_schema),
                "argument_bindings": bindings,
                "missing_verdict": verdict.to_dict(),
            }
        )

    @property
    def identity(self):
        return json.loads(self._identity_json)

    def verify(self, request):
        config = self.identity
        if config["when"] is not None and not _matches(config["when"], request.output):
            return CompletionVerdict("accept")
        try:
            arguments = {
                key: _pointer(request.output, pointer)
                for key, pointer in config["argument_bindings"].items()
            }
        except (KeyError, IndexError):
            return CompletionVerdict(**config["missing_verdict"])
        for receipt in request.receipts:
            if receipt["tool"] != config["tool"]:
                continue
            if any(
                key not in receipt["arguments"]
                or canonical(receipt["arguments"][key]) != canonical(value)
                for key, value in arguments.items()
            ):
                continue
            if config["result_schema"] is None or _matches(
                config["result_schema"], receipt["result"]
            ):
                return CompletionVerdict("accept")
        return CompletionVerdict(**config["missing_verdict"])
