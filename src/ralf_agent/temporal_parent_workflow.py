"""Independent History parent scheduler with registered child Workflow ownership."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    ChildWorkflowError,
    WorkflowAlreadyStartedError,
)

with workflow.unsafe.imports_passed_through():
    from .orchestration_types import ChildCall
    from .temporal_parent_state import (
        CONTROL_ACTIVITY,
        PARENT_WORKFLOW_NAME,
        SELECTION_ACTIVITY,
        TemporalParentState,
        ValidationError,
    )
    from .temporal_state import TERMINAL, WORKFLOW_NAME, detached
    from .temporal_workflow import TemporalRunWorkflow


@workflow.defn(name=PARENT_WORKFLOW_NAME)
class TemporalParentWorkflow(TemporalRunWorkflow):
    @workflow.init
    def __init__(self, accepted: dict):
        info = workflow.info()
        self.state = TemporalParentState(
            info.workflow_id,
            accepted["scope"],
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
            info.run_id,
            accepted.get("depth", 0),
        )
        self.wake_revision = 0

    async def _activity(self, name, value, activity_timeout):
        try:
            return await workflow.execute_activity(
                name,
                value,
                start_to_close_timeout=activity_timeout,
                schedule_to_close_timeout=activity_timeout * 2,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError:
            return {"ok": False, "code": "parent_activity_unavailable"}

    async def _control(self, mode, call, activity_timeout):
        return await self._activity(
            CONTROL_ACTIVITY,
            {
                "mode": mode,
                "child": detached(call),
                "parent_id": self.state.run_id,
                "scope": self.state.scope,
                "task_queue": workflow.info().task_queue,
                "runtime_manifest": self.state.manifest,
            },
            activity_timeout,
        )

    async def _deadline(self, seconds):
        await workflow.sleep(seconds)
        if self.state.state not in TERMINAL:
            self.state.state, self.state.error = "cancelled", {"code": "deadline_exceeded"}
            self.state._emit("deadline_exceeded")
            self.wake_revision += 1

    @workflow.run
    async def run(self, accepted: dict) -> None:
        self.state.observation_version = (
            2 if workflow.patched("ralf-parent-control-evidence-v2") else 1
        )
        timeout = timedelta(seconds=accepted["activity_timeout"])
        deadline = self.state.policy.run_timeout_seconds
        if deadline is not None:
            asyncio.create_task(self._deadline(deadline))
        while True:
            observed_wake = self.wake_revision
            changed = False
            for call in tuple(self.state.children):
                if call.get("settled"):
                    continue
                if self.state.state in TERMINAL:
                    if not call.get("dispatch_started"):
                        call.update(state="cancelled", settled=True, spent=0)
                        self.state._emit("undispatched_child_released", {"run_id": call["run_id"]})
                        continue
                    if not call.get("cancel_confirmed"):
                        receipt = await self._control("cancel", call, timeout)
                        if receipt["ok"]:
                            call["cancel_confirmed"] = True
                if call.get("dispatch_started"):
                    before = self.state.revision
                    result = await self._control("observe", call, timeout)
                    if result["ok"]:
                        try:
                            self.state.observe(call["run_id"], result["result"])
                        except ValidationError as exc:
                            if self.state.state not in TERMINAL:
                                self.state.state, self.state.error = "failed", {"code": exc.code}
                            self.state._emit("child_evidence_refused")
                    changed |= before != self.state.revision
            if self.state.state not in TERMINAL:
                try:
                    calls = self.state.next_calls()
                except ValidationError as exc:
                    self.state.state, self.state.error = "failed", {"code": exc.code}
                    self.state._emit("parent_failed")
                    calls = []
                for call in calls:
                    registered = await self._control("register", call, timeout)
                    if not registered["ok"]:
                        self.state._emit(
                            "child_registration_deferred",
                            {"run_id": call["run_id"], "code": registered["code"]},
                        )
                        continue
                    if self.state.state in TERMINAL:
                        break
                    current = next(c for c in self.state.children if c["run_id"] == call["run_id"])
                    current["dispatch_started"] = True
                    self.state._emit("child_start_intent", {"run_id": call["run_id"]})
                    kind = call["request"]["definition"]["kind"]
                    try:
                        await workflow.start_child_workflow(
                            PARENT_WORKFLOW_NAME
                            if kind in {"graph", "team", "dynamic"}
                            else WORKFLOW_NAME,
                            {
                                "scope": self.state.scope,
                                "command_id": call["command_id"],
                                "request": call["request"],
                                "manifest": self.state.manifest,
                                "activity_timeout": accepted["activity_timeout"],
                                "depth": call["depth"],
                            },
                            id=call["run_id"],
                            task_queue=workflow.info().task_queue,
                            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                            retry_policy=None,
                        )
                    except (WorkflowAlreadyStartedError, ChildWorkflowError):
                        # Original stable identity is observed, never replaced.
                        self.state._emit("child_start_reply_uncertain", {"run_id": call["run_id"]})
                    self.state.mark_started(call["run_id"])
                    changed = True
                if not any(
                    not c.get("settled") for c in self.state.children
                ) and self.state.stage in {"select", "plan", "verify"}:
                    if self.state.stage == "plan":
                        planner = self.state.manifest["orchestration"]["planners"][
                            self.state.definition["planner"]
                        ]
                        previous = next(
                            (
                                c
                                for c in self.state.children
                                if c["member"] == "@planner"
                                and c["id"].startswith(str(self.state.planning_revision) + ":")
                            ),
                            None,
                        )
                        if planner["agent"] is not None and previous is None:
                            self.state.delegate(
                                ChildCall("planner", "@planner", self.state.planning_request())
                            )
                            continue
                        snapshot = None if previous is None else previous["snapshot"]
                    else:
                        snapshot = None
                    kind = "team" if self.state.stage == "select" else self.state.stage
                    request = {
                        "runtime_manifest": self.state.manifest,
                        "definition": self.state.definition,
                        "kind": kind,
                        "input": self.state.request["input"],
                        "results": self.state.results,
                        "planning_request": (
                            previous["request"]["input"]
                            if kind == "plan" and previous is not None
                            else self.state.planning_request()
                        )
                        if self.state.kind == "dynamic"
                        else None,
                        "planner_snapshot": snapshot,
                    }
                    response = await self._activity(SELECTION_ACTIVITY, request, timeout)
                    if self.state.state not in TERMINAL:
                        try:
                            if not response["ok"]:
                                raise ValidationError("Registered selection failed")
                            if kind == "verify":
                                self.state.accept_verification(response["result"])
                            else:
                                self.state.accept_selection(response["result"])
                        except (ValidationError, TypeError, KeyError) as exc:
                            self.state.state, self.state.error = (
                                "failed",
                                {"code": getattr(exc, "code", "selection_failed")},
                            )
                            self.state._emit("parent_failed")
                    changed = True
            # Quiescent waiting/terminal parents sleep without producing polling
            # Activities; unsettled children keep resource evidence observable.
            if self.state.state in TERMINAL and self.state.quiescent:
                await workflow.wait_condition(lambda wake=observed_wake: self.wake_revision != wake)
            elif changed:
                continue
            else:
                try:
                    await workflow.wait_condition(
                        lambda wake=observed_wake: self.wake_revision != wake,
                        timeout=timedelta(seconds=0.5),
                    )
                except TimeoutError:
                    pass

    @workflow.update(name="command")
    async def command(self, request: dict) -> dict:
        try:
            receipt = self.state.command(request["command_id"], request["payload"])
            self.wake_revision += 1
            return receipt
        except Exception as exc:
            raise ApplicationError(
                "Parent command rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.query(name="view")
    def view(self, request: dict) -> dict:
        return super().view(request)
