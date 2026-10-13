"""Actual Tool calls and rejection end acknowledgements retain fixed ownership."""

import asyncio
import inspect
import uuid

from .errors import CloseIncomplete, DefinitionMismatch, ValidationError
from .temporal_context_read_runtime import _timeout
from .types import canonical, digest


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


async def completed(value):
    """Dispose unfinished return objects without adopting them as observations."""
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()
    elif inspect.isasyncgen(value):
        await value.aclose()
    elif isinstance(value, asyncio.Future):
        value.cancel()
        if value.get_loop() is asyncio.get_running_loop():
            await asyncio.gather(value, return_exceptions=True)
    if (
        inspect.isawaitable(value)
        or inspect.isgenerator(value)
        or inspect.isasyncgen(value)
        or hasattr(value, "__enter__")
        or hasattr(value, "__aenter__")
    ):
        raise ValidationError("Tool owner ports require completed values")
    return value


async def execute(runtime, request, *, dispatch_guard=None, on_end=None, coding_callbacks=None):
    from .temporal_activities import _code
    from .temporal_bindings import selected_runtime
    from .temporal_context_execution import ContextExecutionRejected
    from .temporal_state import detached

    started = False
    try:
        host = owner(runtime)
        runtime.validate_release(request["runtime_manifest"])
        if host._tool_execution_closing or not callable(dispatch_guard) or not callable(on_end):
            raise ValidationError("Tool execution requires open ownership and original callbacks")
        fixed, invocation = detached(request), uuid.uuid4().hex
        proof = {
            name: fixed[name]
            for name in ("scope", "action_id", "release_digest", "execution_epoch")
        } | {"request_digest": digest(fixed)}
        actual_end = asyncio.Event()
        claimed = False
        authority = None

        async def actual_ended(value):
            if value != proof:
                raise DefinitionMismatch("Tool owner changed its fixed actual end proof")
            actual_end.set()

        async def business():
            nonlocal started
            runtime.validate_release(fixed["runtime_manifest"])
            owner(runtime)
            if host._tool_execution_closing:
                raise ContextExecutionRejected(handler_not_started=True)
            selected = selected_runtime(runtime, fixed)
            started = True
            return await selected._execute_tool(fixed, coding_authority=authority)

        async def invocation_operation():
            nonlocal claimed, authority
            if "coding_request" in fixed:
                from .delegated_coding import registered_coding_tool

                if not callable(coding_callbacks):
                    raise ContextExecutionRejected(handler_not_started=True)
                selected = selected_runtime(runtime, fixed)
                handler = registered_coding_tool(selected.tools.get(fixed["tool"]))
                authority = await coding_callbacks(invocation, handler.runner)
                grant = await dispatch_guard(
                    fixed, invocation_id=invocation, owner_proof=authority.owner_proof
                )
            else:
                grant = await dispatch_guard(fixed, invocation_id=invocation)
            expected = {name: fixed[name] for name in ("run_id", "action_id", "release_digest")}
            if (
                type(grant) is not dict
                or any(grant.get(name) != value for name, value in expected.items())
                or grant.get("invocation_id") != invocation
                or type(grant.get("allowed")) is not bool
                or type(grant.get("claimed")) is not bool
            ):
                raise DefinitionMismatch("Tool admission lost original invocation claim")
            # Only the first claim, including a cancelled no-start claim, may
            # acknowledge this intent. A foreign rejection cannot end its owner.
            claimed = grant["claimed"]
            if not grant["allowed"]:
                actual_end.set()
                raise ContextExecutionRejected(handler_not_started=True)
            claimed = True
            try:
                result = await completed(
                    await host.tool_execution.execute(business, proof=proof, on_end=actual_ended)
                )
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise ValidationError("Tool owner execute requires a completed response")
                canonical(result)
                return result
            except ContextExecutionRejected as exc:
                if exc.handler_not_started:
                    actual_end.set()
                raise
            finally:
                # A malformed adapter that never called the operation has no
                # business effect; valid started operations require its end hook.
                if not started:
                    actual_end.set()

        async def notify(value):
            if not claimed:
                return
            await actual_end.wait()
            owner(runtime)
            result = await completed(await on_end(proof | {"invocation_id": invocation}))
            if result is not None:
                raise ValidationError("Tool end acknowledgement must return completed None")

        # This bounded mechanical owner retains rejection notifications too.
        return await host._tool_notifications.execute(
            invocation_operation,
            proof={**proof, "action_id": proof["action_id"] + ":" + invocation},
            on_end=notify,
        )
    except Exception as exc:
        duplicate = isinstance(exc, ContextExecutionRejected) and not exc.handler_not_started
        return {
            "ok": False,
            "code": _code(exc, "tool_execution_failed"),
            "dispatched": started or duplicate,
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
    result = await completed(await host.tool_execution.wait(wait_timeout=wait_timeout))
    if type(result) is not bool:
        raise ValidationError("Tool execution wait must return a completed boolean")
    if not result:
        return False
    result = await host._tool_notifications.wait(wait_timeout=wait_timeout)
    owner(runtime)
    return result


async def close(runtime, *, wait_timeout=30):
    _timeout(wait_timeout)
    host = owner(runtime)
    host._tool_execution_closing = True
    if not await wait(runtime, wait_timeout=wait_timeout):
        raise CloseIncomplete({"tool_execution": "pending"})
    if host._tool_notifications is not None:
        await host._tool_notifications.aclose(wait_timeout=wait_timeout)
    owner(runtime)
