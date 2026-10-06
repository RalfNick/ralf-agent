"""Bounded per-Run scheduling over durable, isolated native node frames."""

import asyncio
import copy

from .errors import DefinitionMismatch, RalfError, ValidationError
from .node_execution import NodeEngine, create_frame
from .types import digest
from .workflow import ExecutionPlan
from .workflow_scheduler import WorkflowBatch, validate_batch

CLOSED = {"succeeded", "failed", "cancelled", "cancelling"}


def is_parallel(run):
    return run.get("plan", {}).get("schema_version") == 3


def close_nodes(run, failed_index=None):
    for index, node in enumerate(run["plan"]["nodes"]):
        state = run["workflow"]["nodes"][node["id"]]
        if state["state"] not in {"completed", "skipped", "failed", "cancelled"}:
            state["state"] = "failed" if index == failed_index else "cancelled"
    for action in run["actions"]:
        if action["status"] in {"ready", "waiting_approval", "not_dispatched"}:
            action["status"] = "cancelled"


class ParallelWorkflowRuntime:
    def __init__(self, engine):
        self.engine = engine

    def _select(self, run, limit):
        engine, scheduler = self.engine, self.engine.workflow_scheduler
        states = {
            key: {k: copy.deepcopy(v) for k, v in state.items() if k != "execution"}
            for key, state in run["workflow"]["nodes"].items()
        }
        try:
            selected = engine._component_result(
                scheduler.select(
                    ExecutionPlan(run["plan"]),
                    copy.deepcopy(run["input"]),
                    copy.deepcopy(states),
                    limit,
                ),
                WorkflowBatch,
                "WorkflowScheduler.select",
            )
            batch = WorkflowBatch(
                selected.selections, selected.skipped, selected.done, selected.result
            )
            validate_batch(ExecutionPlan(run["plan"]), run["input"], states, limit, batch)
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Workflow scheduler failed") from exc
        current = engine._authorized(run["id"])
        engine._check_release(current)
        if digest(
            engine._component_identity(scheduler, ("select",), True, "Workflow scheduler")
        ) != digest(run["manifest"]["workflow"]["scheduler"]):
            raise DefinitionMismatch("The selecting Workflow scheduler changed")
        if digest(current["workflow"]) != digest(run["workflow"]):
            raise ValidationError("Workflow changed during scheduling")
        return batch

    def _launch(self, run_id, node_id):
        engine = self.engine
        task = asyncio.create_task(NodeEngine(engine, run_id, node_id)._drive_locked(run_id))
        engine._parallel_tasks.setdefault(run_id, set()).add(task)

        def completed(finished):
            if not finished.cancelled():
                finished.exception()
            tasks = engine._parallel_tasks.get(run_id)
            if tasks is not None:
                tasks.discard(finished)
                if not tasks:
                    engine._parallel_tasks.pop(run_id, None)
            engine._cleanup_execution(run_id)

        task.add_done_callback(completed)
        return task

    async def drive(self, run_id):
        engine, active, attempted = self.engine, {}, set()
        limit = engine._authorized(run_id)["plan"]["max_concurrency"]
        try:
            while True:
                # Retrieve exceptions before deciding whether any successors run.
                for node_id, task in list(active.items()):
                    if task.done():
                        del active[node_id]
                        if task.cancelled():
                            raise asyncio.CancelledError
                        error = task.exception()
                        if error is not None:
                            raise error
                run = engine._authorized(run_id)
                if run["state"] in CLOSED:
                    if active:
                        await asyncio.wait(active.values(), return_when=asyncio.FIRST_COMPLETED)
                        continue
                    if run["state"] == "cancelling":
                        with engine.store.transaction():
                            run = engine._authorized(run_id)
                            run["state"] = "cancelled"
                            engine._commit(run, "run_cancelled")
                    break
                engine._check_release(run)
                slots = limit - len(active)
                # Resume a previously accepted frame at most once this drive.
                resumable = [
                    key
                    for key, s in run["workflow"]["nodes"].items()
                    if "execution" in s
                    and s["state"] not in {"completed", "skipped", "failed", "cancelled"}
                    and key not in attempted
                ]
                for node_id in resumable[:slots]:
                    attempted.add(node_id)
                    active[node_id] = self._launch(run_id, node_id)
                slots = limit - len(active)
                if slots:
                    run = engine._authorized(run_id)
                    batch = self._select(run, slots)
                    with engine.store.transaction():
                        current = engine._authorized(run_id)
                        if current["state"] in CLOSED:
                            continue
                        for node_id in batch.skipped:
                            current["workflow"]["nodes"][node_id] = {"state": "skipped"}
                            engine.store.emit(run_id, "workflow_node_skipped", {"node_id": node_id})
                        for selection in batch.selections:
                            current["workflow"]["nodes"][selection.node_id] = {
                                "state": "running",
                                "input": copy.deepcopy(selection.input),
                                "execution": create_frame(
                                    engine, current, selection.node_id, selection.input
                                ),
                            }
                        if batch.done:
                            current["state"], current["result"], current["error"] = (
                                "succeeded",
                                batch.result,
                                None,
                            )
                        if batch.skipped or batch.selections or batch.done:
                            engine._commit(
                                current,
                                "run_succeeded" if batch.done else "workflow_batch_selected",
                            )
                            for selection in batch.selections:
                                engine.store.emit(
                                    run_id, "workflow_node_started", {"node_id": selection.node_id}
                                )
                    for selection in batch.selections:
                        attempted.add(selection.node_id)
                        active[selection.node_id] = self._launch(run_id, selection.node_id)
                    if batch.done:
                        break
                if active:
                    await asyncio.wait(active.values(), return_when=asyncio.FIRST_COMPLETED)
                    continue
                with engine.store.transaction():
                    run = engine._authorized(run_id)
                    states = {s["state"] for s in run["workflow"]["nodes"].values()}
                    run["state"] = (
                        "waiting_reconciliation"
                        if "waiting_reconciliation" in states
                        else "waiting_approval"
                        if "waiting_approval" in states
                        else "running"
                        if "running" in states
                        else "failed"
                    )
                    if run["state"] == "failed":
                        run["error"] = {"code": "invalid_workflow_state"}
                    engine._commit(run, "workflow_paused")
                break
        except RalfError as exc:
            engine._fail(run_id, exc.code)
            await self._drain(active)
        except BaseException:
            # Keep separately tracked workers alive even if this supervisor is
            # itself cancelled. Global event-loop cancellation still leaves real
            # synchronous handlers protected by ThreadExecutionTracker.
            if engine._authorized(run_id)["state"] not in CLOSED:
                engine.cancel(run_id, command_id=f"parallel-cancel:{run_id}:{id(active)}")
            await self._drain(active)
            raise
        engine._mark_workflow_quiescent(run_id, supervisor=True)
        return engine.status(run_id)

    @staticmethod
    async def _drain(active):
        if active:
            await asyncio.shield(asyncio.gather(*active.values(), return_exceptions=True))

    def adopt(self, run_id):
        run = self.engine._authorized(run_id)
        for node_id, state in run["workflow"]["nodes"].items():
            if "execution" in state:
                NodeEngine(self.engine, run_id, node_id)._adopt_received_evidence(run_id)

    def reconcile(self, run_id, action_id, result, command_id):
        run = self.engine._authorized(run_id)
        action = next((a for a in run["actions"] if a["id"] == action_id), None)
        if action is None:
            raise ValidationError("No unknown tool effect to reconcile")
        node_id = run["plan"]["nodes"][action["node"]]["id"]
        return NodeEngine(self.engine, run_id, node_id).reconcile(
            run_id, action_id, result, command_id=command_id
        )
