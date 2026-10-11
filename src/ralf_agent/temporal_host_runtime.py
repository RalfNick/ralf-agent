"""Host pins and queue checks wrap original Facade RPCs, never business state."""

import asyncio

from .errors import DefinitionMismatch, ValidationError
from .temporal_agent_runtime import TemporalClientRuntime


class HostedTemporalRuntime(TemporalClientRuntime):
    def __init__(self, host, assembly, engine):
        self._host, self._assembly = host, assembly
        super().__init__(engine)
        from .temporal_session_state import locator

        self._session_locator = locator(host._namespace_id)

    def _check(self, *, accepting=False):
        super()._check(accepting=accepting)
        self._host._check(started=True)
        self._host._check_engine(self._assembly, self.engine)

    def _dispatch_engine(self):
        view = super()._dispatch_engine()
        view.client = HostedClient(self, self._client)
        return view

    async def aclose(self, *, close_timeout=None):
        # Drift invalidates admission, but cannot abandon the original RPCs.
        # This Facade only borrows its Engine/Client; the Host drains Workers.
        if asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Close the Facade on its construction loop")
        return await self._close_resources(close_timeout=close_timeout)

    async def aattach_session(self, ref):
        from .temporal_agent_session import TemporalAgentSession

        client = await self._session_client()
        observed = await client.status(ref)
        self._check()
        if observed.ref != ref or observed.binding_revision != ref.binding_revision:
            raise DefinitionMismatch("Session binding changed during attachment")
        return TemporalAgentSession(self, ref)


class HostedClient:
    def __init__(self, runtime, client):
        self.runtime, self.client = runtime, client

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def check(self):
        self.runtime._check()
        await self.runtime._host._check_namespace(started=True)
        self.runtime._check()

    def get_workflow_handle(self, identity, **options):
        return HostedHandle(self, identity, self.client.get_workflow_handle(identity, **options))

    async def start_workflow(self, *args, **options):
        from .temporal import _sdk

        await self.check()
        handle = self.get_workflow_handle(options["id"])
        try:
            await handle.describe()
        except _sdk()[6] as exc:
            if exc.status != _sdk()[7].NOT_FOUND:
                raise
        await self.check()
        result = await self.client.start_workflow(*args, **options)
        await self.check()
        return result


class HostedHandle:
    def __init__(self, transport, identity, handle):
        self.transport, self.identity, self.handle = transport, identity, handle

    async def describe(self):
        from .temporal_parent_state import PARENT_WORKFLOW_NAME
        from .temporal_session_state import SESSION_WORKFLOW
        from .temporal_state import COMMAND_REGISTRY_NAME, WORKFLOW_NAME

        await self.transport.check()
        value = await self.handle.describe()
        await self.transport.check()
        kinds = (
            {COMMAND_REGISTRY_NAME}
            if self.identity.startswith("ralf-temporal-commands-")
            else {SESSION_WORKFLOW}
            if self.identity.startswith("ralf-temporal-session-")
            else {WORKFLOW_NAME, PARENT_WORKFLOW_NAME}
        )
        host = self.transport.runtime._host
        if (
            value.id != self.identity
            or value.namespace != host._route[1]
            or value.workflow_type not in kinds
            or value.task_queue not in host._queues
        ):
            raise DefinitionMismatch("Original Workflow queue, type or namespace is unavailable")
        return value

    async def query(self, *args, **options):
        await self.describe()
        value = await self.handle.query(*args, **options)
        await self.transport.check()
        return value

    async def execute_update(self, *args, **options):
        await self.describe()
        value = await self.handle.execute_update(*args, **options)
        await self.transport.check()
        return value
