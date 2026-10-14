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
    from . import (  # noqa: F401 -- preload frozen pure DTO/adoption  # noqa: F401
        parent_completion,
        parent_completion_protocol,
        temporal_coding_composition_state,
        temporal_context_read_protocol,
        temporal_context_read_state,
    )
    from .errors import RalfError
    from .orchestration_types import ChildCall
    from .temporal_parent_completion_state import ACTIVITY as PARENT_COMPLETION_ACTIVITY
    from .temporal_parent_session import ROOT_READ_ACTIVITY
    from .temporal_parent_state import (
        CONTROL_ACTIVITY,
        PARENT_WORKFLOW_NAME,
        SELECTION_ACTIVITY,
        TemporalParentState,
        ValidationError,
    )
    from .temporal_session_save_state import ACTIVITY as SESSION_SAVE_ACTIVITY
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
        self._check_session_parent(info)
        self._check_composition_parent(info)

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
        from .temporal_coding_composition_state import enabled
        from .types import digest

        value = {
            "mode": mode,
            "child": detached(call),
            "parent_id": self.state.run_id,
            "scope": self.state.scope,
            "task_queue": workflow.info().task_queue,
            "runtime_manifest": self.state.manifest,
        }
        if enabled(self.state.manifest):
            value.update(
                parent_execution_epoch=self.state.epoch,
                parent_request_digest=digest(self.state.request),
                parent_release_digest=self.state.release_digest,
                namespace=detached(self.state.composition_namespace),
            )
        return await self._activity(CONTROL_ACTIVITY, value, activity_timeout)

    async def _admit_composition(self, accepted, activity_timeout):
        from .temporal_coding_composition_state import ACTIVITY, adopt_admission

        response = await self._activity(
            ACTIVITY,
            {
                "scope": self.state.scope,
                "run_id": self.state.run_id,
                "execution_epoch": self.state.epoch,
                "command_id": accepted["command_id"],
                "request": self.state.request,
                "runtime_manifest": self.state.manifest,
            },
            activity_timeout,
        )
        if not response.get("ok"):
            return False
        try:
            adopt_admission(self.state, response["result"])
        except (RalfError, KeyError, TypeError):
            self.state._emit("coding_composition_admission_refused")
            return False
        return True

    def _observe_composition(self, run_id, value):
        from .temporal_coding_composition_state import (
            adopt_child_stop,
            pin_child_execution,
            request_parent_stop,
        )

        try:
            proof = value["coding_composition_proof"]
            pin_child_execution(self.state, run_id, proof)
            adopt_child_stop(self.state, run_id, proof)
            self.state.observe(run_id, value)
            call = next(c for c in self.state.children if c["run_id"] == run_id)
            call["physical_recovered_revision"] = self.state.memory_recovery_revision
        except (RalfError, KeyError, TypeError) as exc:
            request_parent_stop(
                self.state,
                terminal_state="failed",
                reason={"code": getattr(exc, "code", "child_evidence_refused")},
            )
            self.state._emit("child_evidence_refused")
            return False
        return True

    async def _deadline(self, seconds):
        await workflow.sleep(seconds)
        if self.state.state not in TERMINAL:
            from .temporal_coding_composition_state import enabled, request_parent_stop

            if enabled(self.state.manifest):
                request_parent_stop(
                    self.state, terminal_state="cancelled", reason={"code": "deadline_exceeded"}
                )
                self.wake_revision += 1
                return
            self.state.state, self.state.error = "cancelled", {"code": "deadline_exceeded"}
            from .temporal_user_input import close_pending

            close_pending(self.state)
            self.state._emit("deadline_exceeded")
            self.wake_revision += 1

    @workflow.run
    async def run(self, accepted: dict) -> None:
        from .temporal_coding_composition_state import (
            enabled,
            physical_stop_view,
            pin_child_execution,
            refresh_parent_stop,
        )
        from .types import digest

        composition = enabled(self.state.manifest)
        if composition and not workflow.patched(
            "ralf-coding-composition-v7"
            if self.state.manifest.get("binding_protocol") == 23
            else "ralf-coding-composition-v6"
            if self.state.manifest.get("binding_protocol") == 21
            else "ralf-coding-composition-v5"
            if self.state.manifest.get("binding_protocol") == 19
            else "ralf-coding-composition-v4"
            if self.state.manifest.get("binding_protocol") == 17
            else "ralf-coding-composition-v3"
            if self.state.manifest.get("binding_protocol") == 15
            else "ralf-coding-composition-v2"
            if self.state.manifest.get("binding_protocol") == 13
            else "ralf-coding-composition-v1"
        ):
            raise ApplicationError(
                "Coding composition History marker unavailable",
                type="definition_mismatch",
                non_retryable=True,
            )
        self.state.observation_version = (
            2 if workflow.patched("ralf-parent-control-evidence-v2") else 1
        )
        self.state.parent_completion_enabled = (
            self.state.parent_completion_enabled and workflow.patched("ralf-parent-completion-v1")
        )
        timeout = timedelta(seconds=accepted["activity_timeout"])
        deadline = self.state.policy.run_timeout_seconds
        if deadline is not None:
            asyncio.create_task(self._deadline(deadline))
        while True:
            if (
                composition
                and self.state.composition_admission is None
                and self.state.composition_stop_intent is None
            ):
                if not await self._admit_composition(accepted, timeout):
                    try:
                        observed = self.wake_revision
                        await workflow.wait_condition(
                            lambda wake=observed: self.wake_revision != wake,
                            timeout=timedelta(seconds=0.5),
                        )
                    except TimeoutError:
                        pass
                    continue
            if composition:
                refresh_parent_stop(self.state)
            await self._notify_session()
            observed_wake = self.wake_revision
            changed = False
            for call in tuple(self.state.children):
                if call.get("settled") and (
                    not composition
                    or call.get("physical_no_start")
                    or call.get("physical_stop_proof", {}).get("physical_stopped")
                ):
                    continue
                if (
                    composition
                    and self.state.composition_stop_intent is not None
                    and call.get("physical_stop_proof", {}).get("physical_stopped")
                    and self.state.memory_recovery_revision
                    <= call.get("physical_recovered_revision", 0)
                ):
                    continue
                recovery = getattr(self.state, "memory_recovery_revision", 0)
                if (
                    self.state.manifest["kernel"] == "temporal-3"
                    and call.get("dispatch_started")
                    and call.get("uncertain")
                    and recovery > call.get("memory_recovered_revision", 0)
                ):
                    result = await self._control("recover", call, timeout)
                    if result["ok"]:
                        call["memory_recovered_revision"] = recovery
                if self.state.state in TERMINAL or (
                    composition and self.state.composition_stop_intent is not None
                ):
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
                            value = result["result"]
                            if composition:
                                self._observe_composition(call["run_id"], value)
                            else:
                                self.state.observe(call["run_id"], value)
                        except ValidationError as exc:
                            if self.state.state not in TERMINAL:
                                self.state.state, self.state.error = "failed", {"code": exc.code}
                            self.state._emit("child_evidence_refused")
                    changed |= before != self.state.revision
            operation = self.state.next_session_operation()
            if operation is not None:
                action, request = operation
                try:
                    response = await workflow.execute_activity(
                        ROOT_READ_ACTIVITY
                        if action["kind"] == "session_root_read"
                        else SESSION_SAVE_ACTIVITY,
                        request,
                        start_to_close_timeout=timeout,
                        schedule_to_close_timeout=timeout * 2 + timedelta(seconds=5),
                        retry_policy=RetryPolicy(
                            maximum_attempts=1
                            if action["phase"] in {"session-write", "session-root-read"}
                            else 3
                        ),
                        activity_id=action["id"],
                    )
                except ActivityError:
                    response = {
                        "ok": False,
                        "code": "activity_outcome_unknown",
                        "dispatched": action["phase"] == "session-write",
                        "execution_stopped": False,
                    }
                if action["kind"] == "session_root_read":
                    self.state.accept_session_root(action["id"], response)
                else:
                    self.state.accept_session(action["id"], response)
                continue
            if self.state.state not in TERMINAL and (
                not composition or self.state.composition_stop_intent is None
            ):
                try:
                    completion = self.state.next_parent_completion_operation()
                    if completion is not None:
                        action, request = completion
                        # This Activity is explicitly pure. Retry only its fixed
                        # proposal; selection/control and model dispatch retain
                        # their original one-attempt execution contracts.
                        try:
                            response = await workflow.execute_activity(
                                PARENT_COMPLETION_ACTIVITY,
                                request,
                                start_to_close_timeout=timeout,
                                schedule_to_close_timeout=timeout * 4 + timedelta(seconds=5),
                                retry_policy=RetryPolicy(maximum_attempts=3),
                                activity_id=action["id"],
                            )
                        except ActivityError:
                            response = {"ok": False, "code": "parent_activity_unavailable"}
                        self.state.accept_parent_completion(action["id"], response)
                        continue
                except ValidationError as exc:
                    self.state.state, self.state.error = "failed", {"code": exc.code}
                    self.state._emit("parent_failed")
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
                    if self.state.state in TERMINAL or (
                        composition and self.state.composition_stop_intent is not None
                    ):
                        break
                    current = next(c for c in self.state.children if c["run_id"] == call["run_id"])
                    current["dispatch_started"] = True
                    self.state._emit("child_start_intent", {"run_id": call["run_id"]})
                    kind = call["request"]["definition"]["kind"]
                    try:
                        handle = await workflow.start_child_workflow(
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
                        if composition:
                            pin_child_execution(
                                self.state,
                                call["run_id"],
                                {
                                    "namespace": detached(self.state.composition_namespace),
                                    "execution_epoch": handle.first_execution_run_id,
                                    "original_execution_epoch": handle.first_execution_run_id,
                                    "request_digest": digest(call["request"]),
                                    "parent_run_id": self.state.run_id,
                                    "parent_execution_epoch": self.state.epoch,
                                },
                            )
                    except (WorkflowAlreadyStartedError, ChildWorkflowError):
                        # Original stable identity is observed, never replaced.
                        self.state._emit("child_start_reply_uncertain", {"run_id": call["run_id"]})
                    self.state.mark_started(call["run_id"])
                    changed = True
                if self.state.children_quiescent and self.state.stage in {
                    "select",
                    "plan",
                    "verify",
                }:
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
                    if composition:
                        request.update(
                            scope=self.state.scope,
                            run_id=self.state.run_id,
                            execution_epoch=self.state.epoch,
                        )
                    if "runtime_profile" in self.state.manifest:
                        # Explicit managed Profile Workers validate the original
                        # Scope on every Activity, including pure selection.
                        # Historical unprofiled payloads retain their exact shape.
                        request["scope"] = self.state.scope
                    response = await self._activity(SELECTION_ACTIVITY, request, timeout)
                    if self.state.state not in TERMINAL and (
                        not composition or self.state.composition_stop_intent is None
                    ):
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
            await self._notify_session()
            if (self.state.state in TERMINAL or self.state.stage == "waiting_input") and (
                physical_stop_view(self.state)["physical_stopped"]
                if composition and self.state.state in TERMINAL
                else self.state.quiescent
            ):
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
