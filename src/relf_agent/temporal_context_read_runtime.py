"""Worker read ownership; original History remains the sole execution authority."""

import math

from .errors import CloseIncomplete, DefinitionMismatch, ValidationError
from .temporal_context_read_protocol import PHASES
from .types import digest


def _timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValidationError("Context wait timeout must be finite and nonnegative")


def owner(runtime):
    host = getattr(runtime, "_selected_host", None) or runtime
    if runtime.context_execution is not host._context_execution_owner:
        raise DefinitionMismatch("Selected Context read lost its original host owner")
    if host.context_execution is not host._context_execution_owner:
        raise DefinitionMismatch("Context read execution owner changed")
    if host._context_execution_pin is not None:
        host._context_execution_pin.check()
    return host


async def execute(runtime, request, operation, *, dispatch_guard=None, on_end=None):
    from .temporal_activities import _code
    from .temporal_context_execution import ContextExecutionRejected
    from .temporal_managed_context import admit_dispatch
    from .temporal_state import detached

    try:
        host = owner(runtime)
        runtime.validate_release(request["runtime_manifest"])
        if host._context_read_closing:
            raise ValidationError("Context read admission is closed")
        if (
            request.get("phase") not in PHASES
            or not callable(on_end)
            or not callable(dispatch_guard)
        ):
            raise ValidationError("Context reads require an original phase and end notification")
        request = detached(request)
        proof = {
            name: request[name]
            for name in ("scope", "action_id", "release_digest", "execution_epoch")
        }
        proof["request_digest"] = digest(request)
        admission = {"allowed": None}

        async def tracked_guard(value):
            result = await dispatch_guard(value)
            expected = {name: request[name] for name in ("run_id", "action_id", "release_digest")}
            if (
                type(result) is dict
                and all(result.get(name) == fixed for name, fixed in expected.items())
                and type(result.get("allowed")) is bool
            ):
                admission["allowed"] = result["allowed"]
            return result

        async def read():
            await admit_dispatch(request, tracked_guard)
            runtime.validate_release(request["runtime_manifest"])
            owner(runtime)
            if host._context_read_closing:
                raise ContextExecutionRejected(handler_not_started=True)
            result = await operation(request)
            runtime.validate_release(request["runtime_manifest"])
            owner(runtime)
            return result

        async def ended(value):
            # A cancelled/failed admission observation may hide a persisted grant.
            # Retain the original callback and resolve that uncertainty before ACK.
            if admission["allowed"] is None:
                try:
                    await admit_dispatch(request, tracked_guard)
                except Exception:
                    if admission["allowed"] is not False:
                        raise
            if admission["allowed"] is True:
                return await on_end(value)
            return None

        return await host.context_execution.execute(read, proof=proof, on_end=ended)
    except Exception as exc:
        return {
            "ok": False,
            "code": _code(exc, "context_failed"),
            **(
                {"handler_not_started": exc.handler_not_started}
                if isinstance(exc, ContextExecutionRejected)
                else {}
            ),
        }


async def wait(runtime, *, wait_timeout=30):
    _timeout(wait_timeout)
    host = owner(runtime)
    if host.context_execution is None:
        return True
    result = await host.context_execution.wait(wait_timeout=wait_timeout)
    if type(result) is not bool:
        raise ValidationError("Context execution wait must return a completed boolean")
    owner(runtime)
    return result


async def close(runtime, *, wait_timeout=30):
    from .temporal_activities import _completed_none

    _timeout(wait_timeout)
    host = owner(runtime)
    host._context_read_closing = True
    if not await wait(runtime, wait_timeout=wait_timeout):
        raise CloseIncomplete({"context_execution": "pending"})
    if host._context_execution_owned:
        _completed_none(
            await host.context_execution.aclose(wait_timeout=wait_timeout),
            "Context execution close",
        )
    owner(runtime)
