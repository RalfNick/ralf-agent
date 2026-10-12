"""Actual Tool operation and end acknowledgement are owned beyond observation."""

from .errors import CloseIncomplete, DefinitionMismatch, ValidationError
from .temporal_context_read_runtime import _timeout
from .types import digest


def owner(runtime):
    host = getattr(runtime, "_selected_host", None) or runtime
    if (
        runtime.tool_execution is not host._tool_execution_owner
        or host.tool_execution is not host._tool_execution_owner
    ):
        raise DefinitionMismatch("Tool execution lost its original host owner")
    if host._tool_execution_pin is not None:
        host._tool_execution_pin.check()
    return host


async def execute(runtime, request, *, dispatch_guard=None, on_end=None):
    from .temporal_activities import _code
    from .temporal_bindings import selected_runtime
    from .temporal_context_execution import ContextExecutionRejected
    from .temporal_managed_context import admit_dispatch
    from .temporal_state import detached

    started = False
    try:
        host = owner(runtime)
        runtime.validate_release(request["runtime_manifest"])
        if host._tool_execution_closing or not callable(dispatch_guard) or not callable(on_end):
            raise ValidationError("Tool execution requires open ownership and original callbacks")
        fixed = detached(request)
        proof = {
            name: fixed[name]
            for name in ("scope", "action_id", "release_digest", "execution_epoch")
        } | {"request_digest": digest(fixed)}

        async def operation():
            nonlocal started
            await admit_dispatch(fixed, dispatch_guard)
            runtime.validate_release(fixed["runtime_manifest"])
            owner(runtime)
            if host._tool_execution_closing:
                raise ContextExecutionRejected(handler_not_started=True)
            selected = selected_runtime(runtime, fixed)
            started = True
            return await selected._execute_tool(fixed)

        async def ended(value):
            # The actual owning operation has completed, including delegated
            # threads. Denied admission also supplies genuine no-start evidence.
            owner(runtime)
            return await on_end(value)

        try:
            return await host.tool_execution.execute(operation, proof=proof, on_end=ended)
        except ContextExecutionRejected as exc:
            if exc.handler_not_started:
                await ended(proof)
            raise
    except Exception as exc:
        return {
            "ok": False,
            "code": _code(exc, "tool_execution_failed"),
            "dispatched": started,
            **(
                {"handler_not_started": exc.handler_not_started}
                if isinstance(exc, ContextExecutionRejected)
                else {}
            ),
        }


async def wait(runtime, *, wait_timeout=30):
    _timeout(wait_timeout)
    host = owner(runtime)
    if host.tool_execution is None:
        return True
    result = await host.tool_execution.wait(wait_timeout=wait_timeout)
    if type(result) is not bool:
        raise ValidationError("Tool execution wait must return a completed boolean")
    owner(runtime)
    return result


async def close(runtime, *, wait_timeout=30):
    _timeout(wait_timeout)
    host = owner(runtime)
    host._tool_execution_closing = True
    if not await wait(runtime, wait_timeout=wait_timeout):
        raise CloseIncomplete({"tool_execution": "pending"})
    # Direct Runtime injection is borrowed. Factory ownership remains in the
    # original assembly ledger, which closes only after this drain succeeds.
    owner(runtime)
