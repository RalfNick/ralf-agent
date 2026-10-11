"""History Session coordination, with durable intents and business child ownership."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    ChildWorkflowError,
    WorkflowAlreadyStartedError,
)

with workflow.unsafe.imports_passed_through():
    from . import temporal_session_identity  # noqa: F401 -- preload pure Session addressing
    from .temporal_parent_state import PARENT_WORKFLOW_NAME
    from .temporal_session_state import (
        SESSION_ACTIVITY,
        SESSION_WORKFLOW,
        TemporalSessionState,
    )
    from .temporal_state import WORKFLOW_NAME


@workflow.defn(name=SESSION_WORKFLOW)
class TemporalSessionWorkflow:
    @workflow.init
    def __init__(self, accepted: dict):
        self.state = TemporalSessionState(accepted)
        self.wake_revision = 0

    async def _control(self, mode, intent):
        try:
            return await workflow.execute_activity(
                SESSION_ACTIVITY,
                {
                    "mode": mode,
                    "scope": self.state.scope,
                    "namespace_id": self.state.namespace_id,
                    "intent": intent,
                },
                task_queue=intent["task_queue"],
                start_to_close_timeout=timedelta(seconds=intent["activity_timeout"]),
                schedule_to_close_timeout=timedelta(seconds=intent["activity_timeout"] * 3 + 5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            return {"ok": False, "code": "session_control_unavailable"}

    @workflow.run
    async def run(self, accepted: dict):
        while True:
            observed = self.wake_revision
            intent = self.state.start_intent()
            if intent is not None:
                if not intent["started"]:
                    registered = await self._control("register", intent)
                    if registered["ok"]:
                        try:
                            await workflow.start_child_workflow(
                                PARENT_WORKFLOW_NAME
                                if intent["request"]["definition"]["kind"]
                                in {"graph", "team", "dynamic"}
                                else WORKFLOW_NAME,
                                {
                                    "scope": self.state.scope,
                                    "command_id": intent["command_id"],
                                    "request": intent["request"],
                                    "manifest": intent["manifest"],
                                    "activity_timeout": intent["activity_timeout"],
                                },
                                id=intent["run_id"],
                                task_queue=intent["task_queue"],
                                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                                retry_policy=None,
                            )
                        except (WorkflowAlreadyStartedError, ChildWorkflowError):
                            # Observe the original identity; never invent another Run.
                            pass
                        self.state.mark_started()
                    else:
                        self.state.error = {"code": registered["code"]}
                if self.state.active is not None and self.state.active["started"]:
                    observed_run = await self._control("observe", intent)
                    if observed_run["ok"]:
                        try:
                            self.state.adopt_observation(observed_run["result"])
                        except Exception as exc:
                            self.state.error = {
                                "code": getattr(exc, "code", "session_evidence_invalid")
                            }
                    else:
                        self.state.error = {"code": observed_run["code"]}
            await workflow.wait_condition(lambda wake=observed: self.wake_revision != wake)

    @workflow.update(name="command")
    async def command(self, request: dict) -> dict:
        try:
            receipt = self.state.command(request)
            self.wake_revision += 1
            return receipt
        except Exception as exc:
            raise ApplicationError(
                "Session command rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="start_receipt")
    async def start_receipt(self, request: dict) -> dict:
        if request.get("scope") != self.state.scope or not any(
            t["run"]["run_id"] == request.get("run_id") for t in self.state.records
        ):
            raise ApplicationError(
                "Unknown scoped Turn", type="authorization_denied", non_retryable=True
            )
        await workflow.wait_condition(lambda: request["run_id"] in self.state.started_runs)
        return {"run_id": request["run_id"], "started": True}

    @workflow.signal(name="wake")
    def wake(self, request: dict):
        if request.get("scope") == self.state.scope:
            self.wake_revision += 1

    @workflow.query(name="view")
    def view(self, request: dict) -> dict:
        if request.get("scope") != self.state.scope:
            return {"error": "authorization_denied"}
        try:
            if request["kind"] == "status":
                return self.state.snapshot()
            if request["kind"] == "turns":
                return self.state.turns(after=request["after"], limit=request["limit"])
            return {"error": "validation_error"}
        except Exception as exc:
            return {"error": getattr(exc, "code", "validation_error")}
