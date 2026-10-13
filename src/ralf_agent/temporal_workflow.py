"""The independent Temporal Workflow/History execution authority.

This SDK-specific module is loaded only by the explicit worker/replayer factory.
Business terminal Runs remain queryable and accept durable late-evidence/control
Updates; the facade never completes or restarts them to bypass unknown effects.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.exceptions import TimeoutError as ActivityTimeoutError

with workflow.unsafe.imports_passed_through():
    from . import (
        temporal_context_read_state,  # noqa: F401 -- preload original pure read gates
        temporal_parent_completion_state,  # noqa: F401 -- preload pure parent release gates
        temporal_session_identity,  # noqa: F401 -- preload pure Session addressing
        temporal_tool_execution,  # noqa: F401 -- preload fixed Tool protocol
        temporal_tool_execution_state,  # noqa: F401 -- preload original Tool gates
        temporal_user_input,  # noqa: F401 -- preload original pure input gates
    )
    from .temporal_bindings import ROLES as _binding_roles  # noqa: F401
    from .temporal_completion_state import ACTIVITY as COMPLETION_ACTIVITY
    from .temporal_context_read_protocol import owns_activity as owns_context_read
    from .temporal_limits_state import ACTIVITY as LIMITS_ACTIVITY
    from .temporal_managed_context import ACTIVITY as MANAGED_CONTEXT_ACTIVITY
    from .temporal_memory import ACTIVITY as MEMORY_ACTIVITY
    from .temporal_session_save_state import ACTIVITY as SESSION_SAVE_ACTIVITY
    from .temporal_state import (
        ACK_ACTIVITY,
        CONTEXT_ACTIVITY,
        MODEL_ACTIVITY,
        MODEL_ADOPTION_ACTIVITY,
        RECONCILE_ACTIVITY,
        TOOL_ACTIVITY,
        WORKFLOW_NAME,
        TemporalRunState,
        detached,
        digest,
    )


@workflow.defn(name=WORKFLOW_NAME)
class TemporalRunWorkflow:
    @workflow.init
    def __init__(self, accepted: dict):
        # Queries/Updates may run before the run coroutine is scheduled.
        info = workflow.info()
        self.state = TemporalRunState(
            info.workflow_id,
            accepted["scope"],
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
            info.run_id,
        )
        self.wake_revision = 0
        self._check_session_parent(info)

    def _check_session_parent(self, info):
        links = self.state.request.get("session_lineage", {}).get("links", [])
        if links and (info.parent is None or info.parent.workflow_id != links[-1]["parent_run_id"]):
            raise ApplicationError(
                "Session member is not owned by its original direct parent",
                type="definition_mismatch",
                non_retryable=True,
            )
        turn = self.state.request.get("session_turn")
        if turn is not None and (
            info.parent is None or info.parent.workflow_id != turn["coordinator_id"]
        ):
            raise ApplicationError(
                "Session Turn is not owned by its original coordinator",
                type="definition_mismatch",
                non_retryable=True,
            )

    @workflow.run
    async def run(self, accepted: dict) -> None:
        policy = self.state.manifest.get("execution_policy", {})
        if policy.get("run_timeout_seconds") is not None:
            asyncio.create_task(self._deadline(policy["run_timeout_seconds"]))
        timeout = timedelta(seconds=accepted["activity_timeout"])
        total_timeout = timedelta(seconds=accepted["activity_timeout"] * 2 + 5)
        while True:
            await self._notify_session()
            observed_wake = self.wake_revision
            if self.state.pending_acks:
                evidence = self.state.pending_acks.pop(0)
                self.state.active_evidence_ack = evidence["action_id"]
                try:
                    result = await workflow.execute_activity(
                        ACK_ACTIVITY,
                        evidence,
                        start_to_close_timeout=timeout,
                        schedule_to_close_timeout=total_timeout,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        activity_id=f"ack:{evidence['action_id']}:{len(self.state.event_log)}",
                    )
                    if not result["ok"]:
                        self.state.deferred_acks.append(evidence)
                    self.state._emit(
                        "effect_journal_acknowledged"
                        if result["ok"]
                        else "effect_journal_ack_deferred",
                        {"action_id": evidence["action_id"], **result},
                    )
                except ActivityError:
                    self.state.deferred_acks.append(evidence)
                    self.state._emit(
                        "effect_journal_ack_deferred",
                        {"action_id": evidence["action_id"], "code": "activity_failed"},
                    )
                finally:
                    self.state.active_evidence_ack = None
                continue
            if self.state.reconcile_requests:
                action = self.state.reconcile_requests.pop(0)
                self.state.active_reconciliation = action["id"]
                envelope = self.state.envelope(action)
                try:
                    response = await workflow.execute_activity(
                        RECONCILE_ACTIVITY,
                        envelope,
                        start_to_close_timeout=timeout,
                        schedule_to_close_timeout=total_timeout,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        activity_id=f"reconcile:{action['id']}:{len(self.state.event_log)}",
                    )
                    if response["ok"]:
                        self.state.accept_tool(action["id"], response, reconciled=True)
                    else:
                        self.state._emit(
                            "effect_reconciliation_unverified",
                            {"action_id": action["id"], "code": response["code"]},
                        )
                except ActivityError:
                    self.state._emit(
                        "effect_reconciliation_unverified",
                        {"action_id": action["id"], "code": "activity_failed"},
                    )
                finally:
                    self.state.active_reconciliation = None
                continue
            operation = self.state.next_operation()
            if operation is None:
                expiry = policy.get("approval_timeout_seconds")
                pending = next(
                    (
                        action
                        for action in self.state.actions
                        if action["status"] == "waiting_approval"
                    ),
                    None,
                )
                if (
                    pending is not None
                    and expiry is not None
                    and self.state.state not in {"cancelled", "failed", "succeeded"}
                ):
                    if "approval_expires_at" not in pending:
                        pending["approval_expires_at"] = workflow.now().timestamp() + expiry
                        self.state._emit(
                            "approval_expiry_recorded",
                            {
                                "action_id": pending["id"],
                                "expires_at": pending["approval_expires_at"],
                            },
                        )
                    remaining = max(0, pending["approval_expires_at"] - workflow.now().timestamp())
                    try:
                        await workflow.wait_condition(
                            lambda wake=observed_wake: self.wake_revision != wake,
                            timeout=timedelta(seconds=remaining),
                        )
                    except TimeoutError:
                        if pending["status"] == "waiting_approval" and self.state.state not in {
                            "cancelled",
                            "failed",
                            "succeeded",
                        }:
                            pending["status"] = "failed"
                            self.state.state, self.state.error = (
                                "failed",
                                {"code": "approval_expired"},
                            )
                            self.state._emit("approval_expired", {"action_id": pending["id"]})
                else:
                    await workflow.wait_condition(
                        lambda wake=observed_wake: self.wake_revision != wake
                    )
                continue
            action, request = operation
            try:
                response = await workflow.execute_activity(
                    COMPLETION_ACTIVITY
                    if action["kind"] == "agent_completion"
                    else LIMITS_ACTIVITY
                    if action["kind"] == "agent_limits"
                    else MEMORY_ACTIVITY
                    if action["kind"] == "managed_memory"
                    else SESSION_SAVE_ACTIVITY
                    if action["kind"] == "managed_session"
                    else MANAGED_CONTEXT_ACTIVITY
                    if action["kind"] == "managed_context"
                    else CONTEXT_ACTIVITY
                    if action["kind"] == "context"
                    else MODEL_ADOPTION_ACTIVITY
                    if action["kind"] == "model_adoption"
                    else MODEL_ACTIVITY
                    if action["kind"] == "model"
                    else TOOL_ACTIVITY,
                    request,
                    start_to_close_timeout=timeout,
                    schedule_to_close_timeout=total_timeout,
                    retry_policy=RetryPolicy(
                        maximum_attempts=1
                        if owns_context_read(self.state.manifest, action)
                        else 3
                        if action["kind"] in {"agent_limits", "agent_completion", "model_adoption"}
                        or (
                            action["kind"] == "managed_session"
                            and action["phase"] != "session-write"
                        )
                        or (
                            action["kind"] == "managed_context"
                            and action["phase"] not in {"write", "summary"}
                        )
                        or (
                            action["kind"] == "managed_memory"
                            and action["phase"] not in {"select", "memory-write"}
                        )
                        or (
                            action["kind"] == "context"
                            and self.state.manifest["kernel"] == "temporal-3"
                        )
                        else 1
                    ),
                    activity_id=action["id"]
                    if action["kind"]
                    in {
                        "context",
                        "managed_context",
                        "managed_memory",
                        "agent_limits",
                        "agent_completion",
                        "managed_session",
                        "model_adoption",
                    }
                    else action["attempts"][0]["id"],
                )
                if action["kind"] == "agent_completion":
                    self.state.accept_completion(action["id"], response)
                elif action["kind"] == "managed_session":
                    self.state.accept_session(action["id"], response)
                elif action["kind"] == "agent_limits":
                    self.state.accept_limits(action["id"], response)
                elif action["kind"] == "managed_memory":
                    self.state.accept_memory(action["id"], response)
                elif action["kind"] == "managed_context":
                    self.state.accept_managed_context(action["id"], response)
                elif action["kind"] == "context":
                    self.state.accept_context(action["id"], response)
                elif action["kind"] == "model_adoption":
                    self.state.accept_model_adoption(action["id"], response)
                elif action["kind"] == "model":
                    self.state.accept_model(action["id"], response)
                else:
                    self.state.accept_tool(action["id"], response)
            except ActivityError as exc:
                complete_history_read = (
                    self.state.manifest.get("binding_protocol") in (7, 8, 9, 10)
                    and self.state.manifest.get("model_history_protocol") in (1, 2)
                    and owns_context_read(self.state.manifest, action)
                    and action.get("phase") in {"context", "plan"}
                )
                context_timeout = isinstance(exc.cause, ActivityTimeoutError)
                # A server timeout is not evidence that a Python thread or
                # downstream request stopped. Preserve the dispatched identity.
                if action["kind"] == "managed_session":
                    self.state.accept_session(
                        action["id"],
                        {
                            "ok": False,
                            "code": "activity_outcome_unknown",
                            "dispatched": action["phase"] == "session-write",
                            "execution_stopped": False,
                        },
                    )
                elif action["kind"] == "agent_completion":
                    self.state.accept_completion(
                        action["id"], {"ok": False, "code": "validation_error"}
                    )
                elif action["kind"] == "agent_limits":
                    self.state.accept_limits(action["id"], {"ok": False, "code": "limits_failed"})
                elif action["kind"] == "managed_memory":
                    self.state.accept_memory(
                        action["id"],
                        {
                            "ok": False,
                            "code": "activity_outcome_unknown",
                            "dispatched": action["phase"] in {"select", "memory-write"},
                            "execution_uncertain": action["phase"] == "memory-write",
                        },
                    )
                elif action["kind"] == "managed_context":
                    self.state.accept_managed_context(
                        action["id"],
                        {
                            "ok": False,
                            "code": "context_failed"
                            if complete_history_read and not context_timeout
                            else "activity_outcome_unknown",
                            "dispatched": action["phase"] in {"write", "summary"},
                            "execution_uncertain": action["phase"] == "write",
                        },
                    )
                elif action["kind"] == "context":
                    self.state.accept_context(
                        action["id"],
                        {
                            "ok": False,
                            "code": "activity_outcome_unknown"
                            if complete_history_read and context_timeout
                            else "context_failed",
                        },
                    )
                elif action["kind"] == "model_adoption":
                    self.state.accept_model_adoption(
                        action["id"], {"ok": False, "code": "activity_outcome_unknown"}
                    )
                else:
                    self.state.operation_unknown(action["id"], "activity_outcome_unknown")

    async def _deadline(self, seconds):
        await workflow.sleep(seconds)
        if self.state.state not in {"succeeded", "failed", "cancelled"}:
            self.state.state, self.state.error = "cancelled", {"code": "deadline_exceeded"}
            from .temporal_user_input import close_pending

            close_pending(self.state)
            self.state._emit("deadline_exceeded")
            self.wake_revision += 1

    @workflow.update(name="command")
    async def command(self, request: dict) -> dict:
        try:
            receipt = self.state.command(request["command_id"], request["payload"])
            if request["payload"]["kind"] == "drive":
                self.state.retry_blocked()
            self.wake_revision += 1
            return receipt
        except Exception as exc:
            raise ApplicationError(
                "Temporal command was rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="admit_context_dispatch")
    async def admit_context_dispatch(self, request: dict) -> dict:
        try:
            return self.state.admit_context_dispatch(request)
        except Exception as exc:
            raise ApplicationError(
                "Context dispatch admission rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="session_execution_ended")
    async def session_execution_ended(self, proof: dict) -> dict:
        try:
            result = self.state.session_execution_ended(proof)
            self.state.retry_blocked()
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Session execution end rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="context_execution_ended")
    async def context_execution_ended(self, proof: dict) -> dict:
        try:
            result = self.state.context_execution_ended(proof)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Context execution end rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="admit_tool_dispatch")
    async def admit_tool_dispatch(self, request: dict) -> dict:
        try:
            return self.state.admit_tool_dispatch(request)
        except Exception as exc:
            raise ApplicationError(
                "Tool dispatch admission rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="tool_execution_ended")
    async def tool_execution_ended(self, proof: dict) -> dict:
        try:
            result = self.state.tool_execution_ended(proof)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Tool execution end rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.query(name="view")
    def view(self, request: dict) -> dict:
        try:
            self.state.authorize(request.get("scope"))
            kind = request["kind"]
            if kind == "session_proof":
                if "session_history" not in self.state.request:
                    return {"error": "validation_error"}
                return {
                    "scope": self.state.scope,
                    "request": self.state.request,
                    **self.state.diagnostics(),
                }
            if kind == "status":
                return self.state.snapshot()
            if kind == "diagnostics":
                return self.state.diagnostics()
            if kind == "memory_stages":
                return detached(list(getattr(self.state, "memory_stages", {}).values()))
            if kind == "session_stages":
                return detached(list(getattr(self.state, "session_stages", {}).values()))
            if kind == "completion_stages":
                return detached(list(getattr(self.state, "completion_stages", {}).values()))
            if kind == "context_stages":
                return detached(list(getattr(self.state, "managed_context_stages", {}).values()))
            if kind == "context_read_stages":
                return detached(list(getattr(self.state, "context_read_stages", {}).values()))
            if kind == "context_artifacts":
                from .temporal_managed_context import artifact_records

                return detached(artifact_records(self.state))
            if kind == "events":
                return detached(
                    [e for e in self.state.event_log if e["seq"] > request["after"]][
                        : request["limit"]
                    ]
                )
            if kind == "submission":
                payload = {
                    "kind": "submit",
                    "scope": request["scope"],
                    "request": request["request"],
                }
                # Querying existing receipt is read-only and deliberately does
                # not resolve the facade's newly configured runtime release.
                command_id = request["command_id"]
                if self.state.command_digests.get(command_id) != digest(payload):
                    return {"error": "idempotency_conflict"}
                return detached(self.state.receipts[command_id])
            return {"error": "validation_error"}
        except Exception as exc:
            return {"error": getattr(exc, "code", "validation_error")}

    async def _notify_session(self):
        turn = self.state.request.get("session_turn", self.state.request.get("session_observer"))
        if turn is None:
            return
        from .temporal_session_state import quiet

        if (
            quiet(self.state.diagnostics())
            and getattr(self, "_session_notified", None) != self.state.revision
        ):
            await workflow.get_external_workflow_handle(turn["coordinator_id"]).signal(
                "wake", {"scope": self.state.scope}
            )
            self._session_notified = self.state.revision


with workflow.unsafe.imports_passed_through():
    from .temporal_state import COMMAND_REGISTRY_NAME, TemporalCommandRegistryState


@workflow.defn(name=COMMAND_REGISTRY_NAME)
class TemporalCommandRegistryWorkflow:
    """History-backed scoped command acceptance, with no Run-result authority."""

    @workflow.init
    def __init__(self, accepted: dict):
        self.commands = TemporalCommandRegistryState(accepted["scope"])

    @workflow.run
    async def run(self, accepted: dict) -> None:
        await workflow.wait_condition(lambda: False)

    @workflow.update(name="reserve")
    async def reserve(self, request: dict) -> dict:
        # No await or external I/O: one Update atomically pins identity/target.
        try:
            return self.commands.reserve(request)
        except Exception as exc:
            raise ApplicationError(
                "Temporal command identity was rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.query(name="view")
    def view(self, request: dict) -> dict:
        if request.get("scope") != self.commands.scope:
            return {"error": "authorization_denied"}
        return {
            "scope": detached(self.commands.scope),
            "capacity": self.commands.capacity,
            "accepted_commands": len(self.commands.identities),
        }
