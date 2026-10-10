"""Borrowed asynchronous Session entry over the existing client Runtime."""

from .agent_harness import AgentHarness
from .errors import RuntimeClosed
from .session_types import SessionRef, TurnAdmission
from .temporal_session_state import detached
from .temporal_state import text
from .types import credits


class TemporalAgentSession:
    def __init__(self, runtime, ref, *, receipt=None):
        self.runtime, self.ref, self.receipt = runtime, ref, receipt
        self._closed = False

    def _check(self, *, accepting=False):
        if self._closed:
            raise RuntimeClosed("Session entry is closed")
        self.runtime._check(accepting=accepting)
        if self.runtime._drained:
            raise RuntimeClosed("Client resources are closing")

    async def submit(self, input, *, command_id, budget=32):
        self._check(accepting=True)
        from .temporal_agent_runtime import TemporalAgentRun

        input = detached(input)
        text(command_id, "Command ID")
        credits(budget)

        async def operation():
            client = await self.runtime._session_client()
            receipt = await client.submit(self.ref, input, command_id=command_id, budget=budget)
            turn = TurnAdmission.from_dict(receipt.outcome["turn"])
            info = self.runtime._info(
                await client.engine.diagnostics(turn.run.run_id), turn.run.run_id
            )
            self._check()
            self.runtime._validate(turn.run)
            if info.release_digest != turn.run.release_digest:
                from .errors import DefinitionMismatch

                raise DefinitionMismatch("Session Turn differs from original Run release")
            result = TemporalAgentRun(self.runtime, turn.run, info.snapshot, receipt=receipt)
            result.turn = turn
            return result

        return await self.runtime._supervisor.call(operation())

    async def run(self, input, *, command_id, wait_timeout=None, terminal_only=False, budget=32):
        run = await self.submit(input, command_id=command_id, budget=budget)
        return await run.wait(wait_timeout=wait_timeout, terminal_only=terminal_only)

    async def status(self):
        self._check()
        client = await self.runtime._session_client()
        result = await client.status(self.ref)
        self._check()
        return result

    async def turns(self, *, after=0, limit=100):
        self._check()
        client = await self.runtime._session_client()
        values = await client.view(self.ref, "turns", after=after, limit=limit)
        self._check()
        return [TurnAdmission.from_dict(v) for v in values]

    async def diagnostics(self):
        self._check()
        client = await self.runtime._session_client()
        result = await client.view(self.ref, "status")
        self._check()
        return detached(result)

    async def rebind(self, definition, *, expected_binding_revision, command_id):
        self._check(accepting=True)
        definition = (
            definition if isinstance(definition, AgentHarness) else AgentHarness(definition)
        )

        async def operation():
            client = await self.runtime._session_client()
            receipt = await client.rebind(
                self.ref,
                definition,
                expected_binding_revision=expected_binding_revision,
                command_id=command_id,
            )
            self._check()
            return TemporalAgentSession(
                self.runtime, SessionRef.from_dict(receipt.outcome["session_ref"]), receipt=receipt
            )

        return await self.runtime._supervisor.call(operation())

    async def aclose(self):
        self._closed = True

    async def __aenter__(self):
        self._check()
        return self

    async def __aexit__(self, *args):
        await self.aclose()
