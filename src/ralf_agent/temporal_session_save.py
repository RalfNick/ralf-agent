"""Worker data I/O, with decisions accepted only by original Run History."""

from .errors import DefinitionMismatch, ValidationError
from .session_receipts import validate_inspection
from .temporal_session_data import selected_registration, verify_dataset
from .temporal_session_data_state import expected_read
from .temporal_session_save_state import bounded_inspection
from .types import Scope, canonical, digest


async def execute(runtime, request, *, dispatch_guard=None, on_end=None):
    from .temporal_activities import _code
    from .temporal_state import detached

    dispatched, execution_stopped = False, False
    try:
        runtime.validate_release(request["runtime_manifest"])
        if "session_save_protocol" not in runtime.manifest:
            raise DefinitionMismatch("Original Session writes are not registered")
        intent = request["intent"]
        expected = expected_read(runtime.manifest, request)
        if (
            intent["version"] != 1
            or type(intent["version"]) is not int
            or intent["run_id"] != request["run_id"]
            or intent["scope"] != request["scope"]
            or intent["node"] != request["session_data_node"]
            or intent["address"] != expected["address"]
            or intent["registration_digest"] != expected["registration_digest"]
            or type(intent["expected_revision"]) is not int
            or intent["expected_revision"] < 0
            or not intent["message_id"].startswith("ralf-session-message-v1:")
            or type(intent["message"]) is not dict
            or len(canonical(intent["message"]))
            > runtime.manifest["session_save_protocol"]["max_message_chars"]
        ):
            raise DefinitionMismatch("Session write lost original fixed source/address")
        original = selected_registration(runtime, request)
        await verify_dataset(runtime, request)
        phase, scope = request["phase"], Scope(**request["scope"])
        if phase == "session-write":
            from .temporal_managed_context import admit_dispatch

            await admit_dispatch(request, dispatch_guard)
            runtime.validate_release(request["runtime_manifest"])
            dispatched = True
            try:
                revision = await runtime.session_execution.append(
                    original,
                    scope,
                    intent["address"],
                    detached(intent["message"]),
                    expected_revision=intent["expected_revision"],
                    message_id=intent["message_id"],
                    proof={k: request[k] for k in ("scope", "action_id", "release_digest")}
                    | {"request_digest": digest(request)},
                    on_end=on_end,
                )
            finally:
                # Cancellation is not proof a delegated thread stopped. Real
                # completion tracking and an independent History proof follow.
                import asyncio
                import sys

                error = sys.exception()
                execution_stopped = not isinstance(error, asyncio.CancelledError)
            runtime.validate_release(request["runtime_manifest"])
            await verify_dataset(runtime, request)
            if type(revision) is not int or revision != intent["expected_revision"] + 1:
                raise ValidationError("Session append requires its original committed revision")
            return {
                "ok": True,
                "revision": revision,
                "dispatched": True,
                "execution_stopped": execution_stopped,
            }
        if phase in {"inspect", "verify"}:
            value = await original.fixed.call(
                "session", "inspect_message", scope, intent["address"], intent["message_id"]
            )
            runtime.validate_release(request["runtime_manifest"])
            await verify_dataset(runtime, request)
            value = bounded_inspection(
                value,
                scope,
                intent["address"],
                intent["message_id"],
                runtime.manifest["session_save_protocol"]["max_message_chars"],
            )
            return {"ok": True, "inspection": value, "dispatched": False}
        if phase == "adopt":
            value = validate_inspection(
                request["received_inspection"], scope, intent["address"], intent["message_id"]
            )
            if value["receipt"] is None:
                raise ValidationError("Original Session receipt is absent")
            return {"ok": True, "intent_digest": digest(intent), "dispatched": False}
        raise ValidationError("Unknown Session save phase")
    except Exception as exc:
        return {
            "ok": False,
            "code": _code(exc, "session_save_failed"),
            "dispatched": dispatched,
            "execution_stopped": execution_stopped,
        }
