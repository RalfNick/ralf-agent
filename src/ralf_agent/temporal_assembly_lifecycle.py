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
        self._maintenance = {}

    def stop_admission(self):
        self._closing = True

    def wrap_activities(self, activities, *, client, runtime=None, maintenance=()):
        from temporalio import activity

        namespace = getattr(client, "namespace", None)
        if type(namespace) is not str or not namespace.strip():
            raise DefinitionMismatch("Worker requires its original client namespace")
        from .temporal_state import detached

        manifest = None if runtime is None else detached(runtime.orchestration_release)

        def wrap(function):
            selected = [kind for original, kind in maintenance if function is original]
            token = None
            if selected:
                from .temporal_deployment_coding_bridge import is_registered_stop_activity
                from .temporal_deployment_release import is_registered_activity

                kind = selected[0]
                control = (
                    kind == "control"
                    and manifest.get("deployment_admission_protocol", {}).get("version") in (3, 4)
                    and activity._Definition.from_callable(function).name
                    == "ralf.temporal.control.v1"
                )
                native_stop = (
                    kind == "native-stop"
                    and manifest.get("deployment_admission_protocol", {}).get("version") == 3
                    and activity._Definition.from_callable(function).name == "ralf_coding_stop"
                    and _native_stop_registration(runtime, client, function)
                )
                evidence = (
                    kind == "evidence"
                    and manifest.get("session_deployment_protocol") == 1
                    and manifest.get("deployment_admission_protocol", {}).get("version") == 4
                    and _evidence_registration(runtime, client, function)
                )
                session_check = None
                if manifest.get("session_deployment_protocol") == 1:
                    from .temporal_session_deployment_control import (
                        is_registered_activity as is_session_activity,
                    )
                    from .temporal_session_deployment_control import (
                        is_registered_registry_activity,
                    )

                    session_check = {
                        "session-control": is_session_activity,
                        "session-registry": is_registered_registry_activity,
                    }.get(kind)
                session = session_check is not None and session_check(runtime, client, function)
                if (
                    len(selected) != 1
                    or runtime is None
                    or kind
                    not in {
                        "release",
                        "stop",
                        "control",
                        "native-stop",
                        "session-control",
                        "session-registry",
                        "evidence",
                    }
                    or not (
                        control
                        or native_stop
                        or session
                        or evidence
                        or kind == "release"
                        and is_registered_activity(runtime, client, function)
                        or kind == "stop"
                        and is_registered_stop_activity(runtime, client, function)
                    )
                ):
                    raise DefinitionMismatch("Worker maintenance registration changed")
                binding = _maintenance_binding(function)
                validator = _maintenance_binding(runtime.validate_release)
                native_registration = _maintenance_binding(_native_stop_registration)
                evidence_registration = _maintenance_binding(_evidence_registration)
                evidence_ack = (
                    _maintenance_binding(runtime.acknowledge_evidence) if evidence else None
                )
                name = activity._Definition.from_callable(function).name

                def maintenance_check(request):
                    from .temporal_deployment_execution import _activity_body

                    if (
                        _maintenance_binding(function) != binding
                        or _maintenance_binding(runtime.validate_release) != validator
                        or kind == "native-stop"
                        and (
                            _maintenance_binding(_native_stop_registration) != native_registration
                            or _native_stop_registration(runtime, client, function) != native_stop
                        )
                        or digest(runtime.orchestration_release) != self.release_digest
                        or kind == "evidence"
                        and (
                            _maintenance_binding(_evidence_registration) != evidence_registration
                            or _evidence_registration(runtime, client, function) != evidence
                            or _maintenance_binding(runtime.acknowledge_evidence) != evidence_ack
                        )
                        or activity._Definition.from_callable(function).name != name
                        or activity.info().activity_type != name
                        or self._closing
                        and kind == "release"
                        and request.get("mode") not in {"release", "verify"}
                        or self._closing
                        and kind == "control"
                        and _activity_body(request).get("mode") not in {"observe", "cancel"}
                        or session_check is not None
                        and not session_check(runtime, client, function)
                        or self._closing
                        and kind == "session-control"
                        and request.get("mode") != "observe"
                        or self._closing
                        and kind == "session-registry"
                        and request.get("mode") not in {"session_receipt", "session_never_claimed"}
                    ):
                        raise DefinitionMismatch("Worker original maintenance identity changed")
                    runtime.validate_release(manifest)

                token = object()
                self._maintenance[token] = maintenance_check

            @wraps(function)
            async def wrapped(request):
                info = activity.info()
                original_info = (
                    info.workflow_namespace,
                    info.workflow_id,
                    info.workflow_run_id,
                    info.activity_id,
                    info.attempt,
                )

                def check():
                    if (
                        client.namespace != namespace
                        or info.workflow_namespace != namespace
                        or original_info
                        != (
                            info.workflow_namespace,
                            info.workflow_id,
                            info.workflow_run_id,
                            info.activity_id,
                            info.attempt,
                        )
                    ):
                        raise DefinitionMismatch("Worker Activity namespace changed")
                    if token is not None:
                        self._maintenance[token](request)

                check()
                from .temporal_state import detached

                request = detached(request)

                async def operation():
                    check()
                    result = await function(request)
                    check()
                    return result

                return await self.execute(operation, info=info, request=request, _maintenance=token)

            return wrapped

        return [wrap(function) for function in activities]

    async def execute(self, operation, *, info, request, _maintenance=None):
        if self._closing and _maintenance not in self._maintenance:
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


def _maintenance_binding(function):
    layers, seen = [], set()
    while hasattr(function, "__wrapped__"):
        if id(function) in seen:
            raise DefinitionMismatch("Worker maintenance wrapper identity changed")
        seen.add(id(function))
        layers.append(_maintenance_leaf(function))
        function = function.__wrapped__
    return (*layers, _maintenance_leaf(function))


def _native_stop_registration(runtime, client, function):
    """Recognize the fixed factory body behind its universal admission wrapper."""
    from types import CodeType

    from . import temporal_activities as activities
    from . import temporal_deployment_execution as execution
    from . import temporal_session_activities as sessions

    def nested(code, name):
        return next(
            (
                item
                for item in code.co_consts
                if isinstance(item, CodeType) and item.co_name == name
            ),
            None,
        )

    def captures(value):
        return dict(
            zip(
                value.__code__.co_freevars,
                (cell.cell_contents for cell in value.__closure__ or ()),
                strict=True,
            )
        )

    factory_code = activities.registered_activities.__code__
    wrap_code = nested(execution.wrap_activities.__code__, "wrap")
    original = getattr(function, "__wrapped__", None)
    if (
        wrap_code is None
        or getattr(function, "__code__", None) is not nested(wrap_code, "wrapped")
        or getattr(function, "__globals__", None) is not execution.__dict__
        or getattr(original, "__code__", None) is not nested(factory_code, "coding_stop")
        or getattr(original, "__globals__", None) is not activities.__dict__
    ):
        return False
    wrapper = captures(function)
    body = captures(original)
    tree = body.get("tree_guard")
    if not (
        wrapper.get("function") is original
        and wrapper.get("runtime") is runtime
        and wrapper.get("client") is client
        and body.get("runtime") is runtime
        and body.get("client") is client
        and getattr(tree, "__code__", None) is nested(factory_code, "tree_guard")
        and getattr(tree, "__globals__", None) is activities.__dict__
        and captures(tree).get("client") is client
        and captures(tree).get("validate_tree_activity") is sessions.validate_tree_activity
    ):
        return False
    return (
        _maintenance_binding(tree),
        _maintenance_binding(sessions.validate_tree_activity),
    )


def _evidence_registration(runtime, client, function):
    """Only the registered ACK object inside its original universal SDK gate."""
    from types import CodeType

    from . import temporal_activities as activities
    from . import temporal_deployment_execution as execution

    def nested(code, name):
        return next(
            (
                item
                for item in code.co_consts
                if isinstance(item, CodeType) and item.co_name == name
            ),
            None,
        )

    def captures(value):
        return dict(
            zip(
                value.__code__.co_freevars,
                (cell.cell_contents for cell in value.__closure__ or ()),
                strict=True,
            )
        )

    registered = activities._EVIDENCE_REGISTRATIONS.get(function)
    original = getattr(function, "__wrapped__", None)
    if original is None:
        return False
    factory = activities._EVIDENCE_REGISTRATIONS.get(original)
    wrapper_code = nested(execution.wrap_activities.__code__, "wrap")
    if (
        registered is None
        or len(registered) != 3
        or registered[0] is not runtime
        or registered[1] is not client
        or registered[2] is not original
        or factory is None
        or len(factory) != 2
        or factory[0] is not runtime
        or factory[1] is not client
        or getattr(runtime.acknowledge_evidence, "__self__", None) is not runtime
        or getattr(runtime.acknowledge_evidence, "__func__", None)
        is not activities.TemporalRuntime.acknowledge_evidence
        or wrapper_code is None
        or getattr(function, "__code__", None) is not nested(wrapper_code, "wrapped")
        or getattr(function, "__globals__", None) is not execution.__dict__
        or getattr(original, "__code__", None)
        is not nested(activities.registered_activities.__code__, "evidence")
        or getattr(original, "__globals__", None) is not activities.__dict__
    ):
        return False
    wrapper, body = captures(function), captures(original)
    if not (
        wrapper.get("function") is original
        and wrapper.get("runtime") is runtime
        and wrapper.get("client") is client
        and body.get("runtime") is runtime
    ):
        return False
    return (
        _maintenance_binding(activities.registered_activities),
        _maintenance_binding(execution.wrap_activities),
        _maintenance_binding(execution.validate_activity),
    )


def _maintenance_leaf(function):
    target = getattr(function, "__func__", function)
    return (
        target,
        getattr(function, "__self__", None),
        target.__code__,
        target.__defaults__,
        None if target.__kwdefaults__ is None else tuple(target.__kwdefaults__.items()),
        tuple(id(cell.cell_contents) for cell in (target.__closure__ or ())),
    )


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
        self._session_stop_task = None
        self._aclosing = False
        self._client, self._queue = None, None
        self._engines = []
        self._calls = WorkerExecutionOwner(scope=scope, release=self.release)
        self._coding_submissions = None
        if self.release.get("binding_protocol") in (13, 15, 17, 19, 21, 23) or (
            self.release.get("deployment_admission_protocol", {}).get("version") in (2, 3, 4)
        ):
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
        if self.release.get("session_deployment_protocol") == 1 and self._client is not None:
            from .temporal_session_deployment_close import close as close_sessions

            if self._session_stop_task is None:
                self._session_stop_task = asyncio.create_task(
                    close_sessions(
                        self._runtime,
                        client=self._client,
                        scope=self._scope,
                        task_queue=self._queue,
                        wait_timeout=wait_timeout,
                    )
                )
                self._session_stop_task.add_done_callback(_observe)
            try:
                await _bounded_task(self._session_stop_task, wait_timeout)
            except BaseException:
                if self._session_stop_task.done():
                    self._session_stop_task = None
                raise
        if getattr(self._runtime, "coding_execution", False):
            if (
                self._runtime.orchestration_release.get("binding_protocol")
                in (13, 15, 17, 19, 21, 23)
                or (
                    self._runtime.orchestration_release.get("binding_protocol") == 22
                    and self._runtime.orchestration_release.get(
                        "deployment_admission_protocol", {}
                    ).get("version")
                    == 3
                )
            ) and self._client is None:
                await self._close_unused_composition()
            else:
                if (
                    self._runtime.orchestration_release.get(
                        "deployment_admission_protocol", {}
                    ).get("version")
                    == 3
                ):
                    from .temporal_deployment_coding_bridge import close as close_coding
                elif self._runtime.orchestration_release.get("binding_protocol") in (
                    13,
                    15,
                    17,
                    19,
                    21,
                    23,
                ):
                    from .temporal_coding_composition_control import close as close_coding
                else:
                    from .temporal_coding_runtime import close as close_coding

                if self._coding_stop_task is None:
                    close_options = {"client": self._client, "scope": self._scope}
                    if (
                        self._runtime.orchestration_release.get(
                            "deployment_admission_protocol", {}
                        ).get("version")
                        == 3
                    ):
                        close_options["task_queue"] = self._queue
                    self._coding_stop_task = asyncio.create_task(
                        close_coding(self._runtime, **close_options)
                    )
                    self._coding_stop_task.add_done_callback(_observe)
                try:
                    await _bounded_task(self._coding_stop_task, wait_timeout)
                except BaseException:
                    if self._coding_stop_task.done():
                        self._coding_stop_task = None
                    raise
        # Keep the actual-call tracker and the original poller open while
        # original Histories finish their release/Registry verification chain.
        if not await self._calls.wait(wait_timeout=wait_timeout):
            raise CloseIncomplete("Original Worker calls remain owned")
        hosted_deployment = (
            self._worker is not None
            and self.release.get("deployment_admission_protocol", {}).get("version") == 3
        )
        if hosted_deployment:
            from .temporal_deployment_release import check_owner

            owner = check_owner(self._runtime)
            if owner is not None and not await owner.wait(wait_timeout=wait_timeout):
                raise CloseIncomplete("Original public deployment calls remain owned")
        elif getattr(self._runtime, "_deployment_public_execution", False):
            await self._runtime.close_deployment_execution(wait_timeout=wait_timeout)
        await self._runtime.close_context_execution(wait_timeout=wait_timeout)
        await self._runtime.close_session_execution(wait_timeout=wait_timeout)
        if hosted_deployment:
            from .temporal_deployment_coding_bridge import wait_retirement

            await wait_retirement(
                self._runtime, client=self._client, scope=self._scope, wait_timeout=wait_timeout
            )
            await self._runtime.close_deployment_execution(wait_timeout=wait_timeout)
        await self._calls.aclose(wait_timeout=wait_timeout)

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
