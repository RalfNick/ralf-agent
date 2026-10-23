"""Opt-in, bounded Session write evidence; never an execution authority."""

import inspect
import json
from dataclasses import asdict
from typing import Protocol

from .errors import ValidationError
from .types import Scope, canonical


class SyncSessionReceiptBackend(Protocol):
    """Synchronous equivalent; callers use the existing memory_call bridge."""

    session_receipt_version: int

    def inspect_message(self, scope: Scope, session_id: str, message_id: str) -> dict: ...


class SessionReceiptBackend(Protocol):
    """Native async receipt backend, retained for existing remote adapters."""

    session_receipt_version: int

    async def inspect_message(self, scope: Scope, session_id: str, message_id: str) -> dict: ...


def inspection_inputs(scope, session_id, message_id):
    if not isinstance(scope, Scope):
        raise ValidationError("Session inspection requires trusted Scope")
    for value in (session_id, message_id):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                "Session inspection requires non-empty storage/message identities"
            )


def supports_remote_session(backend):
    version = getattr(backend, "session_receipt_version", None)
    return (
        type(version) is int
        and version == 1
        and callable(getattr(backend, "inspect_message", None))
    )


def validate_inspection(value, scope, address, message_id):
    """Detach a completed, exact scoped receipt and reject deferred results."""
    if type(value) is not dict:
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError("Session inspection requires a completed JSON object")
    value = json.loads(canonical(value))
    if (
        not isinstance(scope, Scope)
        or set(value) != {"scope", "session_id", "message_id", "revision", "receipt"}
        or value["scope"] != asdict(scope)
        or value["session_id"] != address
        or value["message_id"] != message_id
        or type(value["revision"]) is not int
        or value["revision"] < 0
    ):
        raise ValidationError("Session inspection identity or revision is invalid")
    receipt = value["receipt"]
    if receipt is not None and (
        type(receipt) is not dict
        or set(receipt) != {"revision", "message"}
        or type(receipt["revision"]) is not int
        or not 1 <= receipt["revision"] <= value["revision"]
        or type(receipt["message"]) is not dict
    ):
        raise ValidationError("Session inspection returned an invalid write receipt")
    return value
