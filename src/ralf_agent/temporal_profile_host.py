"""Owned catalog resources; original assemblies retain execution authority."""

import asyncio
from dataclasses import asdict

from .errors import DefinitionMismatch, RuntimeClosed, ValidationError
from .types import digest, runtime_profile_identity


class CatalogConstructionCleanup:
    def __init__(self, context, constructions):
        self._context, self._constructions = context, constructions
        self._aclosing = False

    async def aclose(self, *, wait_timeout=30):
        self._context._check_cleanup_origin()
        if self._aclosing:
            raise ValidationError("Catalog cleanup is already closing")
        self._aclosing = True
        try:
            for construction in self._constructions:
                await construction.wait(wait_timeout=wait_timeout)
            await self._context.cleanup_async()
        finally:
            self._aclosing = False


class TemporalProfileHost:
    """Snapshot and construction ownership; Workers are explicitly started later."""

    def __init__(self, assemblies, context, constructions, default, scope):
        self._assemblies = tuple(assemblies)
        self._context, self._constructions = context, constructions
        self._default, self._scope = dict(default), scope
        self._loop = asyncio.get_running_loop()
        self._cleanup = CatalogConstructionCleanup(context, constructions)
        self._closed = False
        self._closing, self._aclosing = False, False
        self._start_task = None
        self._client = None
        self._route = None
        self._namespace_id = None
        self._queues, self._engines = {}, {}
        self._runtimes = []

    @property
    def profiles(self):
        return tuple(assembly.profile for assembly in self._assemblies)

    @property
    def default_profile(self):
        return next(profile for profile in self.profiles if profile.identity == self._default)

    @property
    def scope(self):
        return self._scope

    async def aclose(self, *, wait_timeout=30):
        from .temporal_host_lifecycle import close_host

        await close_host(self, wait_timeout)

    def _check(self, *, started=False):
        if asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Use the Host on its construction loop")
        if self._closing or self._closed:
            raise RuntimeClosed("Temporal Host is closing or closed")
        if started and (
            self._start_task is None
            or not self._start_task.done()
            or self._start_task.exception() is not None
        ):
            raise ValidationError("Start all original Workers before using the Host")
        self._check_client()

    def _check_client(self):
        if self._client is not None and self._client_route(self._client) != self._route:
            raise DefinitionMismatch("Host Client namespace or endpoint changed")

    async def _check_namespace(self, *, started=False):
        from .temporal_session_activities import namespace_id

        self._check(started=started)
        current = await namespace_id(self._client)
        self._check(started=started)
        if current != self._namespace_id:
            raise DefinitionMismatch("Original Host namespace UUID changed")

    @staticmethod
    def _client_route(client):
        endpoint = getattr(
            getattr(getattr(client, "service_client", None), "config", None), "target_host", None
        )
        namespace = getattr(client, "namespace", None)
        if any(type(v) is not str or not v.strip() for v in (endpoint, namespace)):
            raise ValidationError("Host requires the actual Client endpoint and namespace")
        return endpoint, namespace

    def _stop_admission(self):
        self._closing = True
        for assembly in self._assemblies:
            assembly._begin_close()
        for runtime in self._runtimes:
            if runtime.state == "open":
                runtime.state = "closing"

    def _worker_finished(self, assembly, task):
        if not assembly._worker_lifetime.is_set():
            self._stop_admission()

    async def start_workers(
        self, client, *, queue_prefix="ralf-profile", engine_options=None, worker_options=None
    ):
        from .temporal import _sdk
        from .temporal_session_activities import namespace_id
        from .temporal_state import COMMAND_REGISTRY_NAME

        self._check()
        if self._start_task is not None:
            raise ValidationError("Host retains its original Worker startup")
        if (
            type(queue_prefix) is not str
            or not queue_prefix.strip()
            or len(queue_prefix.encode("utf-8")) > 128
        ):
            raise ValidationError("Host queue prefix requires1 to128 UTF-8 bytes")
        from .temporal_startup_options import validate_engine_options, validate_worker_options

        engine_options = validate_engine_options(engine_options)
        worker_options = validate_worker_options(
            worker_options, releases=[assembly.release for assembly in self._assemblies]
        )
        sdk = _sdk()
        self._client, self._route = client, self._client_route(client)

        async def start():
            self._namespace_id = await namespace_id(client)
            self._check()
            from .temporal_session_state import resource_id

            resource_id(self._namespace_id)
            for assembly in self._assemblies:
                queue = (
                    queue_prefix
                    + "-"
                    + digest([self._namespace_id, asdict(self.scope), assembly.release])
                )
                self._queues[queue] = assembly
                self._engines[digest(assembly.profile.identity)] = assembly.create_engine(
                    client, task_queue=queue, **engine_options
                )
            registry_ids = dict.fromkeys(
                engine.command_registry_id for engine in self._engines.values()
            )
            for registry_id in registry_ids:
                try:
                    original = await client.get_workflow_handle(registry_id).describe()
                except sdk[6] as exc:
                    if exc.status != sdk[7].NOT_FOUND:
                        raise
                else:
                    self._check()
                    if (
                        original.id != registry_id
                        or original.namespace != client.namespace
                        or original.workflow_type != COMMAND_REGISTRY_NAME
                        or original.task_queue not in self._queues
                    ):
                        raise DefinitionMismatch(
                            "Original command Registry queue or type is unavailable"
                        )
            await self._check_namespace()
            for queue, assembly in self._queues.items():
                self._check()
                await assembly.start_worker(client, task_queue=queue, **worker_options)
                assembly._worker_start.add_done_callback(
                    lambda task, assembly=assembly: self._worker_finished(assembly, task)
                )
                await self._check_namespace()

        self._start_task = asyncio.create_task(start())
        self._start_task.add_done_callback(
            lambda task: None if task.cancelled() else task.exception()
        )
        try:
            await asyncio.shield(self._start_task)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._stop_admission()
            raise
        return self

    def _profile(self, identity):
        identity = runtime_profile_identity(identity)
        for profile in self.profiles:
            if profile.identity == identity:
                return profile
        raise DefinitionMismatch("Original registered Profile is unavailable or changed")

    def select_default(self, identity):
        self._check(started=True)
        self._default = self._profile(identity).identity

    def runtime(self, identity=None):
        from .temporal_host_runtime import HostedTemporalRuntime

        self._check(started=True)
        profile = self._profile(self._default if identity is None else identity)
        engine = self._engines[digest(profile.identity)]
        assembly = next(a for a in self._assemblies if a.profile.identity == profile.identity)
        self._check_engine(assembly, engine)
        runtime = HostedTemporalRuntime(self, assembly, engine)
        self._runtimes.append(runtime)
        return runtime

    def _check_engine(self, assembly, engine):
        queue = next(q for q, value in self._queues.items() if value is assembly)
        if (
            engine.client is not self._client
            or engine.scope != self.scope
            or engine.namespace != self._route[1]
            or engine.task_queue != queue
            or digest(engine.release) != digest(assembly.release)
        ):
            raise DefinitionMismatch("Facade Engine differs from its original Host authority")

    async def aattach(self, ref):
        from .temporal_host_routing import attach_run

        return await attach_run(self, ref)

    async def aattach_session(self, ref):
        from .temporal_host_routing import attach_session

        return await attach_session(self, ref)
