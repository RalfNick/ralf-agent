"""Actual Worker calls and factory resources, independent of History authority."""

import asyncio
import math
from dataclasses import asdict
from functools import wraps

from .errors import CloseIncomplete, DefinitionMismatch, ValidationError
from .temporal_context_execution import ContextExecutionOwner
from .types import Scope, digest


class WorkerExecutionOwner:
    """Mechanical actual-call ownership; never acknowledges a business Action."""

    def __init__(self, *, scope, release):
        if not isinstance(scope, Scope):
            raise ValidationError("Worker calls require a trusted Scope")
        self.scope = asdict(scope)
        self.release_digest = digest(release)
        self._execution = ContextExecutionOwner(max_calls=256)
        self._closing = False

    def stop_admission(self):
        self._closing = True

    def wrap_activities(self, activities, *, client):
        from temporalio import activity

        namespace = getattr(client, "namespace", None)
        if type(namespace) is not str or not namespace.strip():
            raise DefinitionMismatch("Worker requires its original client namespace")

        def wrap(function):
            @wraps(function)
            async def wrapped(request):
                info = activity.info()

                def check():
                    if client.namespace != namespace or info.workflow_namespace != namespace:
                        raise DefinitionMismatch("Worker Activity namespace changed")

                check()
                from .temporal_state import detached

                request = detached(request)

                async def operation():
                    check()
                    result = await function(request)
                    check()
                    return result

                return await self.execute(operation, info=info, request=request)

            return wrapped

        return [wrap(function) for function in activities]

    async def execute(self, operation, *, info, request):
        if self._closing:
            raise ValidationError("Worker call admission is closed")
        if type(request) is not dict or request.get("scope") != self.scope:
            raise DefinitionMismatch("Worker call differs from its trusted assembly Scope")
        if (
            type(info.attempt) is not int
            or info.attempt < 1
            or any(
                type(value) is not str or not value.strip()
                for value in (info.workflow_id, info.workflow_run_id, info.activity_id)
            )
        ):
            raise DefinitionMismatch("Worker call requires actual original SDK execution identity")
        proof = {
            "scope": self.scope,
            "action_id": digest([info.workflow_id, info.activity_id, info.attempt]),
            "release_digest": self.release_digest,
            "request_digest": digest(request),
            "execution_epoch": info.workflow_run_id,
        }
        return await self._execution.execute(operation, proof=proof)

    async def wait(self, *, wait_timeout=30):
        return await self._execution.wait(wait_timeout=wait_timeout)

    async def aclose(self, *, wait_timeout=30):
        return await self._execution.aclose(wait_timeout=wait_timeout)


class TemporalRuntimeAssembly:
    """Factory resource ownership; advanced hosts explicitly take that ownership."""

    def __init__(self, runtime, context, profile, scope):
        self._runtime, self._context = runtime, context
        self._profile, self._scope = profile, scope
        self._loop = asyncio.get_running_loop()
        self._closing, self._closed, self._detached = False, False, False
        self._worker = None
        self._worker_start = None
        self._worker_ready = None
        self._worker_lifetime = asyncio.Event()
        self._worker_stop = None
        self._worker_failure = None
        self._coding_stop_task = None
        self._aclosing = False
        self._client, self._queue = None, None
        self._engines = []
        self._calls = WorkerExecutionOwner(scope=scope, release=self.release)
        self._coding_submissions = None
        if self.release.get("binding_protocol") in (13, 15, 17, 19):
            from .temporal_coding_composition_submissions import CompositionSubmissionOwner

            self._coding_submissions = CompositionSubmissionOwner(scope=scope, release=self.release)

    @property
    def profile(self):
        return self._profile

    @property
    def scope(self):
        return self._scope

    @property
    def release(self):
        return self._runtime.orchestration_release

    @property
    def capabilities(self):
        return self._runtime.capabilities

    def _open(self):
        if self._closed or self._closing or self._detached:
            raise ValidationError("Temporal assembly is closing, closed, or handed off")
        if self._worker_start is not None and self._worker_start.done():
            raise ValidationError("Original Worker hosting Task stopped; close its assembly")

    def detach_components(self):
        self._open()
        if self._worker is not None or self._engines:
            raise ValidationError("Cannot transfer components after Worker or Engine creation")
        self._detached = True
        return self._runtime, self._context

    def _bind_client(self, client, task_queue):
        if type(task_queue) is not str or not task_queue.strip():
            raise ValidationError("Assembly requires an explicit original task queue")
        if self._client is not None and (client is not self._client or task_queue != self._queue):
            raise ValidationError("Assembly retains its original client and task queue")
        self._client, self._queue = client, task_queue

    async def start_worker(self, client, *, task_queue, **options):
        from .temporal import build_temporal_worker

        self._open()
        if asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Start Worker on the component construction loop")
        if self._worker is not None:
            raise ValidationError("Assembly already owns its original Worker")
        self._bind_client(client, task_queue)
        self._worker = build_temporal_worker(
            client,
            task_queue=task_queue,
            runtime=self._runtime,
            activity_owner=self._calls,
            **options,
        )
        self._worker_ready = self._loop.create_future()
        self._worker_ready.add_done_callback(_observe)

        async def host():
            try:
                await self._worker.__aenter__()
            except BaseException as exc:
                if not self._worker_ready.done():
                    self._worker_ready.set_exception(exc)
                raise
            self._worker_ready.set_result(None)
            # The SDK cancels this very Task on a fatal Worker run error.
            # Retain it for the whole lifetime, rather than losing that signal
            # by returning from the Task immediately after __aenter__.
            await self._worker_lifetime.wait()

        self._worker_start = asyncio.create_task(host())
        self._worker_start.add_done_callback(self._worker_finished)
        await asyncio.shield(self._worker_ready)
        return self

    def _worker_finished(self, task):
        _observe(task)
        if not self._worker_lifetime.is_set():
            self._closing = True
            self._calls.stop_admission()
            if self._coding_submissions is not None:
                self._coding_submissions.stop_admission()
            for engine in self._engines:
                # TemporalEngine.aclose only marks this local facade closed;
                # neither path closes its borrowed SDK client.
                engine._closed = True

    def create_engine(self, client, *, task_queue, **options):
        from .temporal import TemporalEngine

        self._open()
        if set(options) & {"scope", "release", "client"}:
            raise ValidationError(
                "Temporal engine must retain its fixed assembly Scope and release"
            )
        self._bind_client(client, task_queue)
        engine = TemporalEngine(
            client, task_queue=task_queue, release=self.release, scope=self.scope, **options
        )
        if self._coding_submissions is not None:
            engine._coding_submission_owner = self._coding_submissions
        self._engines.append(engine)
        return engine

    async def aclose(self, *, wait_timeout=30):
        if (
            type(wait_timeout) not in (int, float)
            or not math.isfinite(wait_timeout)
            or wait_timeout < 0
        ):
            raise ValidationError("Assembly close timeout must be finite and nonnegative")
        if asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Close Temporal resources on their construction loop")
        if self._detached or self._closed:
            return
        self._context._check_cleanup_origin()
        if self._aclosing:
            raise ValidationError("Temporal assembly is already closing")
        self._closing, self._aclosing = True, True
        self._begin_close()
        try:
            await self._drain_execution(wait_timeout)
            await self._finish_worker(wait_timeout)
            await self._context.cleanup_async()
            self._closed = True
            if self._worker_failure is not None:
                raise self._worker_failure
        finally:
            self._aclosing = False

    def _begin_close(self):
        self._closing = True
        if self._coding_submissions is not None:
            self._coding_submissions.stop_admission()
        self._calls.stop_admission()
        for engine in self._engines:
            engine._closed = True

    async def _close_unused_composition(self):
        """Release never-attached owned objects; this makes no History stop claim."""
        from .delegated_coding import registered_coding_tool
        from .temporal_tool_execution_runtime import wait as wait_tools

        if (
            self._client is not None
            or self._worker is not None
            or self._engines
            or self._coding_submissions is None
            or not await self._coding_submissions.wait(wait_timeout=0)
            or not await self._calls.wait(wait_timeout=0)
            or not await wait_tools(self._runtime, wait_timeout=0)
        ):
            raise CloseIncomplete({"coding_composition": "original SDK ownership unavailable"})
        self._runtime._tool_execution_closing = True
        self._runtime.validate_release()
        journals = {}
        for name in self._runtime.tools._tools:
            handler = registered_coding_tool(self._runtime.tools.get(name))
            if handler is not None:
                if (
                    type(handler.runner.active_operations) is not int
                    or handler.runner.active_operations != 0
                ):
                    raise CloseIncomplete(
                        {"coding_composition": "original native handler remains owned"}
                    )
                journals[id(handler.runner._journal)] = handler.runner._journal
        for journal in journals.values():
            if await journal.composition_resources(self._scope):
                raise CloseIncomplete(
                    {"coding_composition": "original records require their SDK client"}
                )
        self._runtime.validate_release()

    async def _drain_execution(self, wait_timeout):
        submissions = getattr(self, "_coding_submissions", None)
        if submissions is not None:
            await submissions.aclose(wait_timeout=wait_timeout)
        if self._worker_start is not None:
            try:
                await _bounded_task(self._worker_ready, wait_timeout)
            except (Exception, asyncio.CancelledError):
                if not self._worker_ready.done():
                    raise
        if getattr(self._runtime, "coding_execution", False):
            if (
                self._runtime.orchestration_release.get("binding_protocol") in (13, 15, 17, 19)
                and self._client is None
            ):
                await self._close_unused_composition()
            else:
                if self._runtime.orchestration_release.get("binding_protocol") in (13, 15, 17, 19):
                    from .temporal_coding_composition_control import close as close_coding
                else:
                    from .temporal_coding_runtime import close as close_coding

                if self._coding_stop_task is None:
                    self._coding_stop_task = asyncio.create_task(
                        close_coding(self._runtime, client=self._client, scope=self._scope)
                    )
                    self._coding_stop_task.add_done_callback(_observe)
                try:
                    await _bounded_task(self._coding_stop_task, wait_timeout)
                except BaseException:
                    if self._coding_stop_task.done():
                        self._coding_stop_task = None
                    raise
        await self._calls.aclose(wait_timeout=wait_timeout)
        await self._runtime.close_context_execution(wait_timeout=wait_timeout)
        await self._runtime.close_session_execution(wait_timeout=wait_timeout)

    async def _finish_worker(self, wait_timeout):
        if self._worker is None:
            return
        if self._worker_stop is None:
            self._worker_stop = asyncio.create_task(self._stop_worker())
            self._worker_stop.add_done_callback(_observe)
        try:
            self._worker_failure = await _bounded_task(self._worker_stop, wait_timeout)
        except BaseException:
            if self._worker_stop.done():
                self._worker_stop = None
            raise
        self._worker_lifetime.set()
        try:
            await _bounded_task(self._worker_start, wait_timeout)
        except asyncio.CancelledError:
            if not self._worker_start.cancelled():
                raise
        except Exception:
            if self._worker_ready.exception() is None:
                raise

    async def _stop_worker(self):
        cancelled = self._worker_start.cancelled()
        shutdown = getattr(self._worker, "shutdown", None)
        stopped = False
        if cancelled and shutdown is not None:
            # Public SDK shutdown establishes actual stop even when context
            # exit subsequently re-raises the fatal error from Worker.run().
            await shutdown()
            stopped = True
        try:
            await self._worker.__aexit__(asyncio.CancelledError if cancelled else None, None, None)
        except Exception as exc:
            if not stopped:
                raise
            return exc
        return None


def _observe(task):
    if not task.cancelled():
        task.exception()


async def _bounded_task(task, wait_timeout):
    if task.done():
        return await asyncio.shield(task)
    try:
        return await asyncio.wait_for(asyncio.shield(task), wait_timeout)
    except TimeoutError:
        raise CloseIncomplete("Original Worker startup or shutdown remains owned") from None
