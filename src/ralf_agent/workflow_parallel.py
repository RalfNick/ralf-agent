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
        if action["status"] in {"ready", "waiting_approval", "waiting_input", "not_dispatched"}:
            action["status"] = "cancelled"


class ParallelWorkflowRuntime:
    def __init__(self, engine):
        self.engine = engine

    def _node_runners(self, run, node_id):
        from .delegated_coding import registered_coding_tool

        index, node = next((i, n) for i, n in enumerate(run["plan"]["nodes"]) if n["id"] == node_id)
        recorded = self.engine._step_manifest(run, index)["tools"]
        names = [node["tool"]] if node.get("tool") else (node.get("agent") or {}).get("tools", [])
        return [
            handler.runner
            for name in names
            if name in recorded
            if (handler := registered_coding_tool(self.engine.tools.get(name))) is not None
        ]

    def _admit(self, run, candidates, active):
        """An original resource has one owner until its worker and native work end."""
        from .delegated_coding import registered_coding_tool
        from .local_delegated_coding import pending_delegated_work

        if run["manifest"].get("delegated_composition_protocol") != 1:
            return list(candidates)
        occupied = {id(runner) for node_id in active for runner in self._node_runners(run, node_id)}
        pending = {}
        for action in pending_delegated_work(run):
            handler = registered_coding_tool(self.engine.tools.get(action["tool"]))
            pending.setdefault(id(handler.runner), set()).add(
                run["plan"]["nodes"][action["node"]]["id"]
            )
        accepted = []
        for node_id in candidates:
            runners = self._node_runners(run, node_id)
            if any(
                id(runner) in occupied
                or pending.get(id(runner), set()) - {node_id}
                or (runner.active_operations and node_id not in pending.get(id(runner), set()))
                for runner in runners
            ):
                continue
            accepted.append(node_id)
            occupied.update(id(runner) for runner in runners)
        return accepted

    async def _settle_closed(self, run_id):
        from .local_delegated_coding import stop_work

        engine = self.engine
        if not await stop_work(engine, run_id):
            return False
        with engine.store.transaction():
            run = engine._authorized(run_id)
            if run["state"] == "cancelling":
                terminal = run.get("delegated_failure", {}).get("terminal", "cancelled")
                run["state"] = terminal
                engine._commit(run, "run_" + terminal)
        return True

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
                        await self._settle_closed(run_id)
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
                held = False
                admitted = self._admit(run, resumable, active)[:slots]
                held = len(admitted) < min(slots, len(resumable))
                for node_id in admitted:
                    attempted.add(node_id)
                    active[node_id] = self._launch(run_id, node_id)
                slots = limit - len(active)
                if slots:
                    run = engine._authorized(run_id)
                    batch = self._select(run, slots)
                    admitted = self._admit(run, [s.node_id for s in batch.selections], active)
                    held = held or len(admitted) < len(batch.selections)
                    batch = WorkflowBatch(
                        tuple(s for s in batch.selections if s.node_id in admitted),
                        batch.skipped,
                        batch.done,
                        batch.result,
                    )
                    if batch.done:
                        from .remote_composite_saves import save_result

                        if (
                            await save_result(engine, run_id, batch.result, skipped=batch.skipped)
                            is False
                        ):
                            break
                    with engine.store.transaction():
                        current = engine._authorized(run_id)
                        if current["state"] in CLOSED:
                            continue
                        for node_id in batch.skipped:
                            if current["workflow"]["nodes"][node_id]["state"] != "skipped":
                                current["workflow"]["nodes"][node_id] = {"state": "skipped"}
                                engine.store.emit(
                                    run_id, "workflow_node_skipped", {"node_id": node_id}
                                )
                        for selection in batch.selections:
                            current["workflow"]["nodes"][selection.node_id] = {
                                "state": "running",
                                "input": copy.deepcopy(selection.input),
                                "execution": create_frame(
                                    engine, current, selection.node_id, selection.input
                                ),
                            }
                        if batch.done:
                            from .session_composites import save_composite_turn_result

                            save_composite_turn_result(engine, current, batch.result)
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
                if held:
                    # A physical owner elsewhere may still be finishing. No new
                    # frame or attempt, and the original Run remains retryable.
                    break
                with engine.store.transaction():
                    run = engine._authorized(run_id)
                    states = {s["state"] for s in run["workflow"]["nodes"].values()}
                    from .local_user_input import pause_state

                    run["state"] = pause_state(
                        states, fallback="running" if "running" in states else "failed"
                    )
                    if run["state"] == "failed":
                        run["error"] = {"code": "invalid_workflow_state"}
                    engine._commit(run, "workflow_paused")
                break
        except RalfError as exc:
            from .binding_manifests import all_step_manifests

            run = engine._authorized(run_id)
            coding = any(
                m.get("delegated_coding_tools") for m in all_step_manifests(run["manifest"])
            )
            if coding and any(not task.done() for task in active.values()):
                from .local_delegated_coding import request_cancel
                from .local_user_input import retire

                with engine.store.transaction():
                    run = engine._authorized(run_id)
                    run["delegated_failure"] = {
                        "code": exc.code,
                        "terminal": "cancelled" if run["state"] == "cancelling" else "failed",
                    }
                    request_cancel(run, {"command": "failure", "code": exc.code})
                    retire(run)
                    run["state"], run["error"] = "cancelling", {"code": exc.code}
                    close_nodes(run)
                    engine._commit(run, "run_cancelling")
            else:
                engine._fail(run_id, exc.code)
            await self._drain(active)
            if engine._authorized(run_id)["state"] == "cancelling":
                await self._settle_closed(run_id)
        except BaseException:
            # Keep separately tracked workers alive even if this supervisor is
            # itself cancelled. Global event-loop cancellation still leaves real
            # synchronous handlers protected by ThreadExecutionTracker.
            if engine._authorized(run_id)["state"] not in CLOSED:
                engine.cancel(run_id, command_id=f"parallel-cancel:{run_id}:{id(active)}")
            await self._drain(active)
            raise
        if engine._authorized(run_id)["state"] in CLOSED:
            from .composite_context import recover_terminal_frames

            await recover_terminal_frames(engine, run_id)
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
