"""Borrowed Session entry; observations never advance execution or release lanes."""

from .errors import RuntimeClosed
from .session_types import SessionRef, TurnAdmission


class AgentSession:
    def __init__(self, runtime, ref, *, receipt=None):
        self.runtime, self.ref, self.receipt = runtime, ref, receipt
        self._closed = False

    def _authority(self, *, accepting=False):
        if self._closed:
            raise RuntimeClosed("Session entry is closed")
        self.runtime._check(accepting=accepting)
        if self.runtime._drained:
            raise RuntimeClosed("Execution resources are closing")
        return self.runtime._session_authority()

    async def submit(self, input, *, command_id, budget=32):
        from .agent_runtime import AgentRun

        receipt = self._authority(accepting=True).submit(
            self.ref, input, command_id=command_id, budget=budget
        )
        turn = TurnAdmission.from_dict(receipt.outcome["turn"])
        self.runtime._validate(turn.run)
        self.runtime._supervisor.start(turn.run)
        return AgentRun(self.runtime, turn.run, receipt=receipt, turn=turn)

    async def run(self, input, *, command_id, wait_timeout=None, terminal_only=False, budget=32):
        run = await self.submit(input, command_id=command_id, budget=budget)
        return await run.wait(wait_timeout=wait_timeout, terminal_only=terminal_only)

    async def status(self):
        return self._authority().status(self.ref)

    async def turns(self, *, after=0, limit=100):
        return self._authority().turns(self.ref, after=after, limit=limit)

    async def rebind(self, definition, *, expected_binding_revision, command_id):
        receipt = self._authority(accepting=True).rebind(
            self.ref,
            definition,
            expected_binding_revision=expected_binding_revision,
            command_id=command_id,
        )
        return AgentSession(
            self.runtime, SessionRef.from_dict(receipt.outcome["session_ref"]), receipt=receipt
        )

    async def aclose(self):
        self._closed = True

    async def __aenter__(self):
        self._authority()
        return self

    async def __aexit__(self, *args):
        await self.aclose()
