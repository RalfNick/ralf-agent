"""Own outbound RPC completion, without owning remote business execution."""

import asyncio


class RpcTaskSupervisor:
    def __init__(self):
        self.tasks, self.refs = set(), {}
        self.failures = 0

    async def call(self, operation):
        task = asyncio.create_task(operation)
        self.tasks.add(task)
        task.add_done_callback(self._completed)
        return await asyncio.shield(task)

    def _completed(self, task):
        self.tasks.discard(task)
        if task.cancelled() or task.exception() is not None:
            self.failures += 1

    @property
    def status(self):
        return {"running": len(self.tasks), "paused": 0, "failed": self.failures}

    async def drain(self):
        while self.tasks:
            await asyncio.gather(
                *(asyncio.shield(t) for t in tuple(self.tasks)), return_exceptions=True
            )
            await asyncio.sleep(0)
