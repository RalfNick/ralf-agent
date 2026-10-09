"""Strong ownership of Local drive tasks; business facts stay in the authority."""

import asyncio

from .errors import ExecutionHostFailed

TERMINAL = {"succeeded", "failed", "cancelled"}
PAUSED = {"waiting_approval", "waiting_reconciliation", "waiting_input"}


class RunTaskSupervisor:
    def __init__(self, engine, *, unresolved=None):
        self.engine = engine
        self.unresolved = unresolved
        self.tasks, self.refs, self.errors = {}, {}, {}
        self.wake_requests = set()

    def prune(self):
        for run_id in tuple(self.refs):
            if run_id in self.tasks:
                continue
            snapshot = self.engine.status(run_id)
            if snapshot.state in TERMINAL:
                self.errors.pop(run_id, None)
                unknown = any(
                    action["kind"] == "tool" and action["status"] == "outcome_unknown"
                    for action in snapshot.actions
                )
                if self.unresolved is not None:
                    unknown = unknown or any(
                        item["kind"] in {"reconciliation", "auxiliary"}
                        for item in self.unresolved(self.refs[run_id])
                    )
                if not unknown:
                    self.refs.pop(run_id, None)

    def start(self, ref):
        self.prune()
        if self.engine.status(ref.run_id).state in TERMINAL:
            flow = self.engine.diagnostics(ref.run_id).workflow or {}
            # Explicit late-evidence controls may release descendant capacity
            # after parent cancellation. Drive only the authority's terminal
            # housekeeping; it never reopens the parent's business state.
            unresolved = self.unresolved(ref) if self.unresolved is not None else []
            if flow.get("quiescent") is not False and not any(
                item.get("source") in {"remote_session", "memory", "context"} for item in unresolved
            ):
                return
        self.refs[ref.run_id] = ref
        self.errors.pop(ref.run_id, None)
        if ref.run_id in self.tasks:
            self.wake_requests.add(ref.run_id)
        else:
            task = asyncio.create_task(self.engine.drive(ref.run_id))
            self.tasks[ref.run_id] = task
            task.add_done_callback(lambda done: self._completed(ref.run_id, done))

    def _completed(self, run_id, task):
        ref = self.refs.get(run_id)
        if self.tasks.get(run_id) is task:
            self.tasks.pop(run_id, None)
        error = None if task.cancelled() else task.exception()
        if task.cancelled() or error is not None:
            self.errors[run_id] = getattr(error, "code", "execution_host_failed")
        try:
            self.prune()
        except Exception:
            # Resource-close failure is reported by the Runtime; do not silently
            # lose an accepted Run's locator because observation is unavailable.
            pass
        if run_id in self.wake_requests:
            self.wake_requests.discard(run_id)
            if ref is not None:
                try:
                    self.start(ref)
                except Exception as error:
                    self.errors[run_id] = getattr(error, "code", "execution_host_failed")

    def check_error(self, run_id):
        if run_id in self.errors:
            raise ExecutionHostFailed(
                "Hosted execution stopped; inspect original Run and explicitly resume"
            )

    @property
    def status(self):
        self.prune()
        return {
            "running": len(self.tasks),
            "paused": sum(
                run_id not in self.tasks and run_id not in self.errors for run_id in self.refs
            ),
            "failed": len(self.errors),
        }

    async def drain(self):
        while self.tasks:
            await asyncio.gather(
                *(asyncio.shield(t) for t in tuple(self.tasks.values())), return_exceptions=True
            )
            await asyncio.sleep(0)
        await self.engine.wait_for_threads()
        self.prune()
        if self.errors:
            raise ExecutionHostFailed("Hosted execution failed before a stable pause")
        for run_id in self.refs:
            if self.engine.status(run_id).state not in PAUSED | TERMINAL:
                raise ExecutionHostFailed("Accepted Run requires explicit recovery before closing")
