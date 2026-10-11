"""Global Worker stop phases precede the one shared resource release."""

import asyncio
import math

from .errors import ValidationError
from .temporal_assembly_lifecycle import _bounded_task


async def close_host(host, wait_timeout):
    if (
        type(wait_timeout) not in (int, float)
        or not math.isfinite(wait_timeout)
        or wait_timeout < 0
    ):
        raise ValidationError("Host close timeout must be finite and nonnegative")
    if asyncio.get_running_loop() is not host._loop:
        raise ValidationError("Close the Host on its construction loop")
    host._context._check_cleanup_origin()
    if host._aclosing:
        raise ValidationError("Temporal Host is already closing")
    if host._closed:
        return
    host._aclosing = True
    host._stop_admission()
    try:
        if host._start_task is not None:
            try:
                await _bounded_task(host._start_task, wait_timeout)
            except asyncio.CancelledError:
                if not host._start_task.cancelled():
                    raise
            except Exception:
                if not host._start_task.done():
                    raise
        for runtime in host._runtimes:
            await runtime.aclose(close_timeout=wait_timeout)
        for construction in host._constructions:
            await construction.wait(wait_timeout=wait_timeout)
        # Every version retains its notification receivers through the entire
        # global drain. No child may close the common resource ledger.
        for assembly in host._assemblies:
            await assembly._drain_execution(wait_timeout)
        for assembly in host._assemblies:
            await assembly._finish_worker(wait_timeout)
        await host._cleanup.aclose(wait_timeout=wait_timeout)
        host._closed = True
        errors = [a._worker_failure for a in host._assemblies if a._worker_failure is not None]
        if errors:
            if len(errors) == 1:
                raise errors[0]
            raise ExceptionGroup("Original Worker failures after owned cleanup", errors)
    finally:
        host._aclosing = False
