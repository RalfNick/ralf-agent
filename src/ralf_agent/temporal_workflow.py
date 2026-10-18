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
        coding_create_inventory,  # noqa: F401 -- preload fixed pure native inventory
        temporal_coding_composition_state,  # noqa: F401 -- original selected physical proof
        temporal_coding_state,  # noqa: F401 -- preload original pure native gates
        temporal_command_transport,  # noqa: F401 -- original Run control observations
        temporal_context_read_state,  # noqa: F401 -- preload original pure read gates
        temporal_deployment_coding_registry,  # noqa: F401 -- original scoped close index
        temporal_deployment_coding_state,  # noqa: F401 -- original pure call fencing
        temporal_deployment_control_projection,  # noqa: F401 -- fixed compact Query projector
        temporal_deployment_lifecycle_transport,  # noqa: F401 -- original public begin/seal
        temporal_deployment_registry,  # noqa: F401 -- preload pure acceptance
        temporal_deployment_retirement_transport,  # noqa: F401 -- original Registry retirement
        temporal_deployment_session_registry,  # noqa: F401 -- original Session command/claim facts
        temporal_deployment_session_updates,  # noqa: F401 -- Registry-owned SDK commit path
        temporal_execution_end_transport,  # noqa: F401 -- original physical end observations
        temporal_manual_recovery,  # noqa: F401 -- original Action recovery proof
        temporal_parent_completion_state,  # noqa: F401 -- preload pure parent release gates
        temporal_parent_state,  # noqa: F401 -- fixed original child addressing
        temporal_public_manual_transport,  # noqa: F401 -- original public Action verification
        temporal_scoped_manual_recovery,  # noqa: F401 -- scoped original Action proof
        temporal_scoped_manual_transport,  # noqa: F401 -- original async manual observations
        temporal_scoped_reservation,  # noqa: F401 -- scoped reservation observations
        temporal_session_identity,  # noqa: F401 -- preload pure Session addressing
        temporal_startup_options,  # noqa: F401 -- preload pure public acceptance validation
        temporal_tool_execution,  # noqa: F401 -- preload fixed Tool protocol
        temporal_tool_execution_state,  # noqa: F401 -- preload original Tool gates
        temporal_user_input,  # noqa: F401 -- preload original pure input gates
    )
    from . import temporal_deployment_coding_state as deployment_coding_state
    from . import temporal_deployment_execution_state as deployment_state
    from . import temporal_deployment_release_state as deployment_release_state
    from .temporal_bindings import ROLES as _binding_roles  # noqa: F401
    from .temporal_coding_state import CODING_STOP_ACTIVITY
    from .temporal_completion_state import ACTIVITY as COMPLETION_ACTIVITY
    from .temporal_context_read_protocol import owns_activity as owns_context_read
    from .temporal_deployment_execution_state import ACTIVITY as DEPLOYMENT_ACTIVITY
    from .temporal_deployment_protocol import public_selected as public_deployment
    from .temporal_deployment_protocol import selected as deployment_selected
    from .temporal_deployment_release import RELEASE_ACTIVITY as DEPLOYMENT_RELEASE_ACTIVITY
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
        if self.state.manifest.get("deployment_admission_protocol", {}).get("version") == 4:
            self._initialize_deployment(accepted, info)
            self._check_composition_parent(info)
        else:
            self._check_composition_parent(info)
            self._initialize_deployment(accepted, info)

    def _initialize_deployment(self, accepted, info):
        from .errors import RalfError

        self._deployment_initialization_error = None
        try:
            self._initialize_deployment_checked(accepted, info)
        except (RalfError, ApplicationError) as exc:
            self._deployment_initialization_error = getattr(exc, "code", None) or getattr(
                exc, "type", "definition_mismatch"
            )
        self._deployment_dirty = {}
        self._deployment_observed = {}
        self._deployment_observing = set()
        self._deployment_hint_tokens = {}
        self._deployment_read_failures = {}
        self._deployment_parent_pending = None
        self._deployment_parent_notified = None
        self._deployment_parent_notification_error = None
        self._deployment_parent_notification_retry = False
        self._deployment_parent_notification_attempts = 0
        self._deployment_notification_revisions = 0

    def _deployment_notifications_selected(self):
        return deployment_coding_state.selected(self.state.manifest) and hasattr(
            self.state, "deployment_admission"
        )

    def _deployment_query_epoch(self):
        from .errors import DefinitionMismatch

        info = workflow.info()
        if (
            not self._deployment_notifications_selected()
            or getattr(self, "_deployment_initialization_error", None) is not None
            or info.workflow_id != self.state.run_id
            or info.namespace != self.state.deployment_admission["root"]["namespace"]["name"]
            or any(
                getattr(info, name, None) != self.state.epoch
                for name in ("run_id", "first_execution_run_id", "original_execution_run_id")
            )
            or self.state.deployment_original_epoch != self.state.epoch
        ):
            raise DefinitionMismatch("Coding node requires its original SDK History")
        return info

    @workflow.query(name="deployment_coding_validation")
    def deployment_coding_validation(self, request: dict) -> dict:
        try:
            self._deployment_query_epoch()
            self.state.authorize(request.get("scope"))
            from .temporal_deployment_control_projection import node

            return node(self.state, request)
        except Exception as exc:
            return {"error": getattr(exc, "code", "definition_mismatch")}

    def _deployment_child_generation(self, call):
        if not hasattr(self, "_deployment_dirty"):
            self._deployment_dirty, self._deployment_observed, self._deployment_hint_tokens = (
                {},
                {},
                {},
            )
        return self._deployment_dirty.setdefault(call["run_id"], 1)

    def _deployment_child_is_dirty(self, call):
        return self._deployment_child_generation(call) != self._deployment_observed.get(
            call["run_id"], 0
        )

    def _deployment_child_observed(self, call, generation):
        if self._deployment_child_generation(call) != generation:
            return False
        self._deployment_observed[call["run_id"]] = generation
        getattr(self, "_deployment_read_failures", {}).pop(call["run_id"], None)
        return True

    def _deployment_child_read_ready(self, call, generation):
        failed = getattr(self, "_deployment_read_failures", {}).get(call["run_id"])
        return failed is None or failed["generation"] != generation or failed["ready"]

    def _deployment_child_read_failed(self, call, generation, code):
        if not hasattr(self, "_deployment_read_failures"):
            self._deployment_read_failures = {}
        previous = self._deployment_read_failures.get(call["run_id"])
        attempts = previous["attempts"] if previous and previous["generation"] == generation else 0
        transient = code in {
            "parent_activity_unavailable",
            "unavailable",
            "temporal_rpc_unavailable",
            "deadline_exceeded",
            "timeout",
            "activity_failed",
            "deployment_control_unavailable",
        }
        failed = {
            "generation": generation,
            "attempts": attempts + 1,
            "retry": transient and attempts + 1 < 3,
            "ready": False,
        }
        self._deployment_read_failures[call["run_id"]] = failed
        emit = getattr(self.state, "_emit", None)
        if emit is not None:
            emit(
                "deployment_child_observation_deferred",
                {
                    "run_id": call["run_id"],
                    "attempts": failed["attempts"],
                    "retryable": failed["retry"],
                    "code": code,
                },
            )

    def _deployment_child_retry_pending(self):
        return any(
            failed["retry"]
            and not failed["ready"]
            and self._deployment_dirty.get(run_id) == failed["generation"]
            for run_id, failed in getattr(self, "_deployment_read_failures", {}).items()
        )

    def _deployment_child_retry_tick(self):
        for run_id, failed in getattr(self, "_deployment_read_failures", {}).items():
            if failed["retry"] and self._deployment_dirty.get(run_id) == failed["generation"]:
                failed["ready"] = True

    def _deployment_force_child_reads(self):
        if self._deployment_notifications_selected():
            for call in getattr(self.state, "children", ()):
                self._deployment_dirty[call["run_id"]] = self._deployment_child_generation(call) + 1

    @workflow.signal(name="deployment_child_wake")
    async def deployment_child_wake(self, request: dict) -> None:
        # Signals are bounded hints, never source identity or permission proof.
        # Invalid signals cannot poison the Workflow task or adopt caller data.
        try:
            self._deployment_query_epoch()
            if type(request) is not dict or set(request) != {
                "version",
                "scope",
                "parent_run_id",
                "parent_execution_epoch",
                "child_run_id",
                "child_execution_epoch",
                "token",
            }:
                return
            if (
                type(request["version"]) is not int
                or request["version"] != 1
                or request["scope"] != self.state.scope
                or request["parent_run_id"] != self.state.run_id
                or request["parent_execution_epoch"] != self.state.epoch
                or type(request["token"]) is not str
                or len(request["token"]) != 64
                or set(request["token"]) - set("0123456789abcdef")
                or any(
                    type(request[key]) is not str or not 0 < len(request[key]) <= 1024
                    for key in ("child_run_id", "child_execution_epoch")
                )
            ):
                return
            call = next(
                (
                    c
                    for c in getattr(self.state, "children", ())
                    if c["run_id"] == request["child_run_id"] and c.get("dispatch_started")
                ),
                None,
            )
            if call is None:
                return
            pinned = (
                call.get("child_execution", {}).get("execution_epoch")
                if call.get("child_execution")
                else call.get("deployment_execution_epoch")
            )
            if pinned is not None and pinned != request["child_execution_epoch"]:
                return
            generation = self._deployment_child_generation(call)
            if (
                self._deployment_hint_tokens.get(call["run_id"]) == request["token"]
                and self._deployment_child_is_dirty(call)
                and call["run_id"] not in getattr(self, "_deployment_observing", ())
            ):
                return
            self._deployment_hint_tokens[call["run_id"]] = request["token"]
            self._deployment_dirty[call["run_id"]] = generation + 1
            self.wake_revision += 1
        except Exception:
            return

    def _deployment_notification_token(self):
        calls = getattr(self.state, "deployment_calls", {})
        tools = getattr(self.state, "tool_executions", {})
        return digest(
            [
                self.state.epoch,
                self.state.revision - getattr(self, "_deployment_notification_revisions", 0),
                [
                    (key, call["stopped"], digest(call.get("fence_proof")))
                    for key, call in sorted(calls.items())
                ],
                [
                    (
                        key,
                        tool.get("execution_stopped"),
                        digest(tool.get("end_proof")),
                        digest(tool.get("coding_owner_stop_proof")),
                    )
                    for key, tool in sorted(tools.items())
                ],
                digest(getattr(self.state, "deployment_seal", None)),
            ]
        )

    async def _notify_deployment_parent(self):
        if not self._deployment_notifications_selected():
            return True
        info = self._deployment_query_epoch()
        if info.parent is None:
            return True
        if info.parent.namespace != info.namespace:
            return True
        if getattr(self, "_deployment_parent_notification_error", None) is not None and not getattr(
            self, "_deployment_parent_notification_retry", False
        ):
            return False
        token = self._deployment_notification_token()
        pending = getattr(self, "_deployment_parent_pending", None)
        if pending is None:
            if token == getattr(self, "_deployment_parent_notified", None):
                return True
            pending = {
                "version": 1,
                "scope": detached(self.state.scope),
                "parent_run_id": info.parent.workflow_id,
                "parent_execution_epoch": info.parent.run_id,
                "child_run_id": self.state.run_id,
                "child_execution_epoch": self.state.epoch,
                "token": token,
            }
            self._deployment_parent_pending = pending
        try:
            self._deployment_parent_notification_attempts = (
                getattr(self, "_deployment_parent_notification_attempts", 0) + 1
            )
            await workflow.get_external_workflow_handle(
                info.parent.workflow_id, run_id=info.parent.run_id
            ).signal("deployment_child_wake", pending)
        except Exception as exc:
            transient = self._deployment_parent_notification_attempts < 3 and (
                isinstance(exc, TimeoutError)
                or getattr(exc, "type", None)
                in {
                    "unavailable",
                    "deadline_exceeded",
                    "timeout",
                }
            )
            error = {"type": type(exc).__name__, "retryable": transient}
            if error != getattr(self, "_deployment_parent_notification_error", None):
                before = self.state.revision
                emit = getattr(self.state, "_emit", None)
                if emit is not None:
                    emit("deployment_parent_notification_deferred", error)
                self._deployment_notification_revisions = (
                    getattr(self, "_deployment_notification_revisions", 0)
                    + self.state.revision
                    - before
                )
            self._deployment_parent_notification_error = error
            self._deployment_parent_notification_retry = transient
            return False
        self._deployment_parent_notified = pending["token"]
        self._deployment_parent_pending = None
        self._deployment_parent_notification_error = None
        self._deployment_parent_notification_retry = False
        self._deployment_parent_notification_attempts = 0
        return True

    def _initialize_deployment_checked(self, accepted, info):
        if not deployment_selected(self.state.manifest):
            if "deployment_admission" in accepted:
                raise ApplicationError(
                    "Deployment metadata requires its selected Worker",
                    type="definition_mismatch",
                    non_retryable=True,
                )
            return
        parent = info.parent
        deployment_state.initialize(
            self.state,
            accepted.get("deployment_admission"),
            namespace=info.namespace,
            epoch=info.run_id,
            original_epoch=info.original_execution_run_id,
            parent=None
            if parent is None
            else {
                "namespace": parent.namespace,
                "workflow_id": parent.workflow_id,
                "run_id": parent.run_id,
            },
        )

        if public_deployment(self.state.manifest):
            self.state.deployment_activity_timeout = accepted["activity_timeout"]
            self.state.deployment_task_queue = info.task_queue
            deployment_release_state.initialize(self.state)

    def _check_deployment_initialization(self):
        if getattr(self, "_deployment_initialization_error", None) is not None:
            self.state.state = "failed"
            self.state.error = {"code": self._deployment_initialization_error}
            self.state._emit("deployment_initialization_refused", self.state.error)
            raise ApplicationError(
                "Original deployment initialization refused",
                type=self._deployment_initialization_error,
                non_retryable=True,
            )

    async def _execute_activity(self, name, request, **options):
        if deployment_selected(self.state.manifest) and name not in (
            DEPLOYMENT_ACTIVITY,
            DEPLOYMENT_RELEASE_ACTIVITY,
            "ralf.temporal.deployment-coding-stop.v3",
        ):
            request = {
                "scope": self.state.scope,
                "_deployment_activity_request": request,
            }
        return await workflow.execute_activity(name, request, **options)

    async def _ensure_deployment_retirement(self, activity_timeout):
        if deployment_coding_state.selected(self.state.manifest):
            await self._recover_deployment_coding_calls()
        if (
            not public_deployment(self.state.manifest)
            or self.state.state not in {"succeeded", "failed", "cancelled"}
            or self.state.deployment_admission["lineage"]
            or self.state.deployment_retirement is not None
        ):
            return
        try:
            response = await self._execute_activity(
                DEPLOYMENT_RELEASE_ACTIVITY,
                {
                    "mode": "release",
                    "scope": self.state.scope,
                    "run_id": self.state.run_id,
                    "execution_epoch": self.state.epoch,
                },
                start_to_close_timeout=activity_timeout,
                schedule_to_close_timeout=activity_timeout * 2 + timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if not response.get("ok"):
                raise ApplicationError(
                    "Original deployment retirement deferred",
                    type=response.get("code", "deployment_release_failed"),
                )
            self.state.deployment_retirement = response["result"]
            self.state._emit("deployment_retired")
        except ActivityError:
            self.state._emit("deployment_retirement_deferred", {"code": "activity_failed"})
        except ApplicationError as exc:
            self.state._emit("deployment_retirement_deferred", {"code": exc.type})

    async def _ensure_deployment_admission(self, activity_timeout):
        if not deployment_selected(self.state.manifest) or deployment_state.admitted(self.state):
            return True
        try:
            response = await self._execute_activity(
                DEPLOYMENT_ACTIVITY,
                deployment_state.activity_request(self.state),
                start_to_close_timeout=activity_timeout,
                schedule_to_close_timeout=activity_timeout * 2 + timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if response.get("ok") is not True:
                raise ApplicationError(
                    "Original deployment admission unavailable",
                    type=response.get("code", "deployment_admission_unavailable"),
                    non_retryable=True,
                )
            if deployment_coding_state.selected(self.state.manifest):
                sideband = response.get("coding_admission")
                from .errors import DefinitionMismatch
                from .temporal_deployment_admission import _exact

                _exact(sideband, {"namespace", "execution_epoch", "admitted"})
                if (
                    sideband["namespace"] != self.state.deployment_admission["root"]["namespace"]
                    or sideband["execution_epoch"] != self.state.epoch
                    or type(sideband["admitted"]) is not bool
                ):
                    raise DefinitionMismatch("Original Coding admission sideband changed")
                if hasattr(self.state, "children"):
                    temporal_coding_composition_state.adopt_admission(self.state, sideband)
                else:
                    if temporal_coding_composition_state.enabled(self.state.manifest):
                        temporal_coding_composition_state.initialize_namespace(
                            self.state,
                            {
                                "scope": self.state.scope,
                                "run_id": self.state.run_id,
                                "execution_epoch": self.state.epoch,
                                "manifest_digest": digest(self.state.manifest),
                                "namespace": sideband["namespace"],
                            },
                        )
                    if not sideband["admitted"]:
                        self.state.command(
                            "ralf-deployment-admission-closed:"
                            + digest([self.state.run_id, self.state.epoch]),
                            {"kind": "cancel", "scope": self.state.scope},
                        )
            deployment_state.adopt(self.state, response["result"])
            self.state._emit("deployment_execution_admitted")
            return True
        except Exception as exc:
            code = getattr(exc, "type", None) or getattr(
                exc, "code", "deployment_admission_unavailable"
            )
            if getattr(self.state, "deployment_admission_error", None) != code:
                self.state.deployment_admission_error = code
                self.state._emit("deployment_admission_deferred", {"code": code})
            return False

    async def _wait_deployment_admission(self):
        observed = self.wake_revision
        try:
            await workflow.wait_condition(
                lambda: self.wake_revision != observed,
                timeout=timedelta(seconds=1),
            )
        except TimeoutError:
            pass

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

    def _check_composition_parent(self, info):
        from .temporal_coding_composition_state import enabled, initialize, validate_child_link

        if not enabled(self.state.manifest):
            return
        try:
            initialize(self.state, namespace=info.namespace)
            parent = info.parent
            validate_child_link(
                self.state,
                namespace=info.namespace,
                parent_namespace=None if parent is None else parent.namespace,
                parent_run_id=None if parent is None else parent.workflow_id,
                parent_epoch=None if parent is None else parent.run_id,
                original_epoch=info.original_execution_run_id,
            )
        except Exception as exc:
            raise ApplicationError(
                "Original Coding composition ownership rejected",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.run
    async def run(self, accepted: dict) -> None:
        self._check_deployment_initialization()
        if "tool_execution_protocol" not in self.state.manifest:
            self.state.tool_end_evidence_version = (
                1 if workflow.patched("ralf-unowned-tool-end-evidence-v1") else 0
            )
        policy = self.state.manifest.get("execution_policy", {})
        if policy.get("run_timeout_seconds") is not None:
            asyncio.create_task(self._deadline(policy["run_timeout_seconds"]))
        timeout = timedelta(seconds=accepted["activity_timeout"])
        total_timeout = timedelta(seconds=accepted["activity_timeout"] * 2 + 5)
        while True:
            if not await self._ensure_deployment_admission(timeout):
                await self._wait_deployment_admission()
                continue
            await self._notify_deployment_parent()
            await self._notify_session()
            observed_wake = self.wake_revision
            if self.state.pending_acks:
                evidence = self.state.pending_acks.pop(0)
                self.state.active_evidence_ack = evidence["action_id"]
                try:
                    result = await self._execute_activity(
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
                    response = await self._execute_activity(
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
                await self._ensure_deployment_retirement(timeout)
                await self._notify_deployment_parent()
                await self._notify_session()
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
                            timeout=timedelta(seconds=min(remaining, 1))
                            if getattr(self, "_deployment_parent_notification_retry", False)
                            else timedelta(seconds=remaining),
                        )
                    except TimeoutError:
                        if (
                            workflow.now().timestamp() >= pending["approval_expires_at"]
                            and pending["status"] == "waiting_approval"
                            and self.state.state
                            not in {
                                "cancelled",
                                "failed",
                                "succeeded",
                            }
                        ):
                            pending["status"] = "failed"
                            self.state.state, self.state.error = (
                                "failed",
                                {"code": "approval_expired"},
                            )
                            self.state._emit("approval_expired", {"action_id": pending["id"]})
                else:
                    try:
                        await workflow.wait_condition(
                            lambda wake=observed_wake: self.wake_revision != wake,
                            **(
                                {"timeout": timedelta(seconds=1)}
                                if getattr(self, "_deployment_parent_notification_retry", False)
                                else {}
                            ),
                        )
                    except TimeoutError:
                        pass
                continue
            action, request = operation
            try:
                response = await self._execute_activity(
                    CODING_STOP_ACTIVITY
                    if action["kind"] == "coding_stop"
                    else COMPLETION_ACTIVITY
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
                        if action["kind"] == "coding_stop"
                        or owns_context_read(self.state.manifest, action)
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
                        "coding_stop",
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
                if action["kind"] == "coding_stop":
                    self.state.accept_coding_stop(action["coding_action_id"], response)
                elif action["kind"] == "agent_completion":
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
                    self.state.manifest.get("binding_protocol")
                    in (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)
                    and self.state.manifest.get("model_history_protocol") in (1, 2)
                    and owns_context_read(self.state.manifest, action)
                    and action.get("phase") in {"context", "plan"}
                )
                context_timeout = isinstance(exc.cause, ActivityTimeoutError)
                # A server timeout is not evidence that a Python thread or
                # downstream request stopped. Preserve the dispatched identity.
                if action["kind"] == "coding_stop":
                    self.state.accept_coding_stop(
                        action["coding_action_id"], {"ok": False, "code": "stop_outcome_unknown"}
                    )
                elif action["kind"] == "managed_session":
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
            from .temporal_coding_state import enabled, request_stop, stopped

            request_stop(self.state, {"code": "deadline_exceeded"})
            self.state.state = (
                "cancelling"
                if enabled(self.state.manifest) and not stopped(self.state)
                else "cancelled"
            )
            self.state.error = {"code": "deadline_exceeded"}
            from .temporal_user_input import close_pending

            close_pending(self.state)
            self.state._emit("deadline_exceeded")
            self.wake_revision += 1
            await self._notify_deployment_parent()

    @workflow.update(name="command")
    async def command(self, request: dict) -> dict:
        try:
            receipt = self.state.command(request["command_id"], request["payload"])
            if request["payload"]["kind"] == "drive":
                self._deployment_parent_notification_error = None
                self._deployment_parent_notification_retry = False
                self._deployment_parent_notification_attempts = 0
            if (
                request["payload"]["kind"] == "drive"
                and getattr(self.state, "deployment_seal", None) is None
            ):
                self.state.retry_blocked()
            self.wake_revision += 1
            return receipt
        except Exception as exc:
            raise ApplicationError(
                "Temporal command was rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.signal(name="control_command")
    async def control_command(self, envelope: dict) -> None:
        from .temporal_command_transport import accept

        await accept(self, envelope, workflow.info())

    @workflow.signal(name="execution_ended")
    async def execution_ended(self, envelope: dict) -> None:
        from .temporal_execution_end_transport import accept

        await accept(self, envelope, workflow.info())

    @workflow.signal(name="deployment_lifecycle")
    async def deployment_lifecycle(self, envelope: dict) -> None:
        from .temporal_deployment_lifecycle_transport import accept

        await accept(self, envelope, workflow.info())

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

    @workflow.update(name="coding_owner_stopped")
    async def coding_owner_stopped(self, proof: dict) -> dict:
        try:
            result = self.state.coding_owner_stopped(proof)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original Coding process stop rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.query(name="coding_state")
    def coding_state(self, proof: dict) -> dict:
        try:
            return self.state.coding_state(proof)
        except Exception as exc:
            return {"error": getattr(exc, "code", "validation_error")}

    @workflow.update(name="admit_coding_phase")
    async def admit_coding_phase(self, payload: dict) -> dict:
        try:
            return self.state.admit_coding_phase(payload)
        except Exception as exc:
            raise ApplicationError(
                "Original Coding phase admission rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="coding_receipt")
    async def coding_receipt(self, payload: dict) -> dict:
        try:
            result = self.state.coding_receipt(payload)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original Coding receipt rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="admit_coding_stop")
    async def admit_coding_stop(self, proof: dict) -> dict:
        try:
            result = self.state.admit_coding_stop(proof)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original Coding stop admission rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="coding_composition_namespace")
    async def coding_composition_namespace(self, payload: dict) -> dict:
        from .temporal_coding_composition_state import initialize_namespace

        try:
            result = initialize_namespace(self.state, payload)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original namespace binding rejected",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="coding_composition_child_epoch")
    async def coding_composition_child_epoch(self, payload: dict) -> dict:
        from .temporal_coding_composition_state import pin_child_execution, validate_parent_update

        try:
            run_id, evidence = validate_parent_update(self.state, payload)
            result = pin_child_execution(self.state, run_id, evidence)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original child execution binding rejected",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="coding_composition_child_stopped")
    async def coding_composition_child_stopped(self, payload: dict) -> dict:
        from .temporal_coding_composition_state import adopt_child_stop, validate_parent_update

        try:
            run_id, evidence = validate_parent_update(self.state, payload)
            result = adopt_child_stop(self.state, run_id, evidence)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original child physical receipt rejected",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="deployment_call_started")
    async def deployment_call_started(self, payload: dict) -> dict:
        try:
            result = deployment_release_state.begin_activity(self.state, payload)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original actual call refused",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="deployment_call_ended")
    async def deployment_call_ended(self, payload: dict) -> dict:
        try:
            result = deployment_release_state.end_activity(self.state, payload)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original actual call end refused",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    async def _recover_deployment_coding_calls(self):
        if getattr(self.state, "deployment_seal", None) is not None:
            return
        for record in tuple(getattr(self.state, "deployment_calls", {}).values()):
            if record["stopped"]:
                continue
            try:
                deployment_coding_state.coding_call_candidate(self.state, record["identity"])
            except Exception:
                continue  # Other/missing owners remain independent unknown obligations.
            try:
                await self.deployment_coding_call_stopped(
                    {"scope": self.state.scope, "identity": record["identity"]}
                )
            except ApplicationError:
                self.state._emit(
                    "deployment_coding_call_stop_deferred",
                    {"activity_id": record["identity"]["activity_id"]},
                )

    @workflow.update(name="deployment_coding_call_stopped")
    async def deployment_coding_call_stopped(self, payload: dict) -> dict:
        from .errors import DefinitionMismatch
        from .temporal_deployment_admission import _exact

        try:
            _exact(payload, {"scope", "identity"})
            if payload["scope"] != self.state.scope:
                raise DefinitionMismatch("Original Coding stop scope changed")
            deployment_coding_state.coding_call_candidate(self.state, payload["identity"])
            key = deployment_release_state._identity(self.state, payload["identity"])
            stored = self.state.deployment_calls[key]["fence_proof"]
            if stored is None:
                response = await self._execute_activity(
                    "ralf.temporal.deployment-coding-stop.v3",
                    detached(payload),
                    task_queue=self.state.deployment_task_queue,
                    start_to_close_timeout=timedelta(
                        seconds=self.state.deployment_activity_timeout
                    ),
                    schedule_to_close_timeout=timedelta(
                        seconds=self.state.deployment_activity_timeout * 2 + 5
                    ),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                if response.get("ok") is not True:
                    raise ApplicationError(
                        "Original Coding stop remains unverified",
                        type=response.get("code", "deployment_coding_stop_failed"),
                    )
                stored = response["result"]
            result = deployment_coding_state.adopt_call_fence(self.state, payload, stored)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original SDK-owned Coding call stop refused",
                type=getattr(exc, "code", None) or getattr(exc, "type", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="deployment_seal")
    async def deployment_seal(self, payload: dict) -> dict:
        try:
            result = deployment_release_state.seal(self.state, payload)
            self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original deployment seal refused",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="deployment_child_epoch")
    async def deployment_child_epoch(self, payload: dict) -> dict:
        try:
            deployment_release_state.check_unsealed(self.state)
            return deployment_state.pin_child(self.state, payload)
        except Exception as exc:
            raise ApplicationError(
                "Original deployment child execution rejected",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.query(name="view")
    def view(self, request: dict) -> dict:
        try:
            self.state.authorize(request.get("scope"))
            kind = request["kind"]
            if kind == "status" and "deployment_lifecycle_observation" in request:
                from .temporal_deployment_lifecycle_transport import observe

                return {
                    "deployment_lifecycle_observation": observe(
                        self, request["deployment_lifecycle_observation"], workflow.info()
                    )
                }
            if kind == "status" and "execution_end_observation" in request:
                from .temporal_execution_end_transport import observe

                return {
                    "execution_end_observation": observe(
                        self, request["execution_end_observation"], workflow.info()
                    )
                }
            if kind == "status" and "command_observation" in request:
                from .temporal_command_transport import observe

                return {
                    "command_observation": observe(
                        self, request["command_observation"], workflow.info()
                    )
                }
            if kind == "deployment_coding_validation":
                return self.deployment_coding_validation(request)
            if kind == "deployment_admission":
                return deployment_state.view(self.state)
            if kind == "deployment_closure":
                return deployment_release_state.view(self.state)
            if kind == "deployment_manual_recovery":
                from .errors import DefinitionMismatch
                from .temporal_deployment_admission import _exact
                from .temporal_manual_recovery import action_proof

                _exact(request, {"kind", "scope", "payload"})
                info = workflow.info()
                if (
                    info.workflow_id != self.state.run_id
                    or info.namespace != getattr(self.state, "deployment_namespace", None)
                    or any(
                        getattr(info, name, None) != self.state.epoch
                        for name in (
                            "run_id",
                            "first_execution_run_id",
                            "original_execution_run_id",
                        )
                    )
                    or getattr(self.state, "deployment_original_epoch", None) != self.state.epoch
                ):
                    raise DefinitionMismatch("Manual proof requires its original SDK History")
                return action_proof(self.state, request["payload"])
            if kind == "deployment_coding_call_candidate":
                from .temporal_deployment_admission import _exact

                _exact(request, {"kind", "scope", "identity"})
                return deployment_coding_state.coding_call_candidate(
                    self.state, request["identity"]
                )
            if kind == "deployment_start" and public_deployment(self.state.manifest):
                return {
                    "scope": detached(self.state.scope),
                    "run_id": self.state.run_id,
                    "execution_epoch": self.state.epoch,
                    "activity_timeout": self.state.deployment_activity_timeout,
                    "task_queue": self.state.deployment_task_queue,
                    "request_digest": digest(self.state.request),
                    "manifest_digest": digest(self.state.manifest),
                }
            if kind == "session_proof":
                if "session_history" not in self.state.request:
                    return {"error": "validation_error"}
                return {
                    "scope": self.state.scope,
                    "request": self.state.request,
                    **self.state.diagnostics(),
                }
            if kind == "coding_composition_proof":
                from .temporal_coding_composition_state import physical_stop_view

                return physical_stop_view(self.state)
            if kind == "coding_composition_children":
                from .temporal_coding_composition_state import original_children

                return original_children(self.state)
            if kind == "coding_requests":
                from .temporal_coding_composition_state import coding_requests, enabled

                if enabled(self.state.manifest):
                    return coding_requests(self.state)
                from .temporal_coding_state import requests

                return requests(self.state)
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

    def _session_deployment_notification(self):
        from .errors import DefinitionMismatch
        from .temporal_session_deployment_state import selected

        if not selected(self.state.manifest):
            return None
        deployment_state._require(self.state)
        metadata = self.state.deployment_admission
        if metadata["lineage"]:
            return None
        origin = metadata["session_origin"]
        info = workflow.info()
        if (
            info.workflow_id != self.state.run_id
            or info.namespace != origin["namespace"]["name"]
            or any(
                getattr(info, name, None) != self.state.epoch
                for name in ("run_id", "first_execution_run_id", "original_execution_run_id")
            )
        ):
            raise DefinitionMismatch(
                "Session notification requires the original business SDK epoch"
            )
        token = digest(
            {
                "intent_digest": origin["intent_digest"],
                "run_id": self.state.run_id,
                "execution_epoch": self.state.epoch,
                "seal": getattr(self.state, "deployment_seal", None),
                "retirement": getattr(self.state, "deployment_retirement", None),
                "calls": getattr(self.state, "deployment_calls", {}),
                "evidence_acks": {
                    name: getattr(self.state, name, None)
                    for name in ("pending_acks", "deferred_acks", "active_evidence_ack")
                },
            }
        )
        return {
            "scope": detached(self.state.scope),
            **{
                name: detached(origin[name])
                for name in (
                    "namespace",
                    "coordinator_execution_epoch",
                    "session_command_id",
                    "turn_id",
                    "intent_digest",
                )
            },
            "run_id": self.state.run_id,
            "execution_epoch": self.state.epoch,
            "change_token": token,
        }

    async def _notify_deployment_session(self):
        from .temporal_session_state import quiet

        if not quiet(self.state.diagnostics()):
            return
        current = self._session_deployment_notification()
        if current is None:
            return
        if not hasattr(self, "_session_deployment_pending"):
            self._session_deployment_pending = None
            self._session_deployment_sent = None
        if self._session_deployment_pending is None:
            if current["change_token"] == self._session_deployment_sent:
                return
            self._session_deployment_pending = detached(current)
        origin = self.state.deployment_admission["session_origin"]
        for _ in range(2):
            pending = detached(self._session_deployment_pending)
            try:
                await workflow.get_external_workflow_handle(
                    origin["coordinator_id"], run_id=origin["coordinator_execution_epoch"]
                ).signal("wake", pending)
                current = self._session_deployment_notification()
            except Exception:
                # This debt never enters the original business closure/retirement.
                # An original recovery wake retries the same bytes without polling.
                return
            self._session_deployment_sent = pending["change_token"]
            self._session_deployment_pending = None
            if current is None or current["change_token"] == self._session_deployment_sent:
                return
            # A pending pre-retirement hint may have survived an earlier failure.
            # Deliver the changed retirement facts before the next passive wait.
            self._session_deployment_pending = detached(current)

    async def _notify_session(self):
        from .temporal_session_deployment_state import selected

        if selected(self.state.manifest):
            await self._notify_deployment_session()
            return
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
    from .temporal_deployment_admission import registry_id as deployment_registry_id
    from .temporal_reservation_transport import accept as accept_reservation_signal
    from .temporal_reservation_transport import observe as observe_reservation_signal
    from .temporal_state import COMMAND_REGISTRY_NAME, TemporalCommandRegistryState


@workflow.defn(name=COMMAND_REGISTRY_NAME)
class TemporalCommandRegistryWorkflow:
    """History-backed scoped command acceptance, with no Run-result authority."""

    @workflow.init
    def __init__(self, accepted: dict):
        from .errors import DefinitionMismatch

        self._deployment_registry_epoch = None
        self._deployment_registry_initialization_error = None
        if type(accepted) is not dict:
            raise DefinitionMismatch("Command registry requires a plain initialization envelope")
        if "deployment_admission" not in accepted:
            self.commands = TemporalCommandRegistryState(accepted["scope"])
            return

        selected = accepted["deployment_admission"]
        if (
            set(accepted) != {"deployment_admission"}
            or type(selected) is not dict
            or set(selected) != {"version", "policy", "namespace"}
            or type(selected["version"]) is not int
            or selected["version"] not in (1, 2, 3, 4)
            or selected["policy"] is None
            or selected["namespace"] is None
        ):
            raise DefinitionMismatch("Invalid original deployment admission envelope")
        info = workflow.info()
        commands = TemporalCommandRegistryState(
            admission_policy=selected["policy"],
            namespace=selected["namespace"],
            admission_protocol=selected["version"],
            **({"registry_execution_epoch": info.run_id} if selected["version"] == 4 else {}),
        )
        if info.namespace != selected["namespace"][
            "name"
        ] or info.workflow_id != deployment_registry_id(selected["policy"]["deployment_id"]):
            raise DefinitionMismatch("Deployment admission requires its original SDK address")
        self.commands = commands
        if selected["version"] in (2, 3, 4):
            # Defer refusal until an SDK-owned entry point. Raising from init
            # can leave the SDK's already-prepared run coroutine unawaited.
            epoch = getattr(info, "run_id", None)
            if (
                type(epoch) is not str
                or not epoch
                or getattr(info, "original_execution_run_id", None) != epoch
                or getattr(info, "first_execution_run_id", None) != epoch
            ):
                self._deployment_registry_initialization_error = "definition_mismatch"
            else:
                self._deployment_registry_epoch = epoch
                if selected["version"] in (3, 4):
                    self.commands.deployment.deployment_registry_execution_epoch = epoch

    def _check_deployment_registry_epoch(self):
        from .errors import DefinitionMismatch

        if self._deployment_registry_initialization_error is not None:
            raise DefinitionMismatch("Public Registry requires its original SDK History")
        epoch = self._deployment_registry_epoch
        if epoch is None:
            return
        info = workflow.info()
        if any(
            getattr(info, field, None) != epoch
            for field in ("run_id", "original_execution_run_id", "first_execution_run_id")
        ):
            raise DefinitionMismatch("Public Registry requires its original SDK History")

    @workflow.run
    async def run(self, accepted: dict) -> None:
        try:
            self._check_deployment_registry_epoch()
        except Exception as exc:
            raise ApplicationError(
                "Original deployment Registry initialization refused",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None
        await workflow.wait_condition(lambda: False)

    @workflow.update(name="reserve")
    async def reserve(self, request: dict) -> dict:
        try:
            self._check_deployment_registry_epoch()
            if self.commands.deployment is None and type(request) is dict and "recovery" in request:
                from .errors import DefinitionMismatch
                from .temporal_parent_state import CONTROL_ACTIVITY
                from .temporal_scoped_manual_recovery import commit, configuration, prepare

                original = configuration(self.commands, workflow.info())
                prepared = prepare(self.commands, request)
                if (
                    request["recovery"]["registry_execution_epoch"]
                    != original["registry_execution_epoch"]
                    or request["recovery"]["namespace"] != original["namespace"]
                ):
                    raise DefinitionMismatch("Manual control requires original Registry History")
                if "receipt" in prepared:
                    return prepared["receipt"]
                response = await workflow.execute_activity(
                    CONTROL_ACTIVITY,
                    {
                        "mode": "scoped_manual",
                        "scope": request["scope"],
                        "registry_execution_epoch": original["registry_execution_epoch"],
                        "namespace": original["namespace"],
                        **prepared,
                    },
                    task_queue=workflow.info().task_queue,
                    start_to_close_timeout=timedelta(seconds=30),
                    schedule_to_close_timeout=timedelta(seconds=65),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                if configuration(self.commands, workflow.info()) != original:
                    raise DefinitionMismatch("Original Registry changed during manual proof")
                if (
                    type(response) is not dict
                    or set(response) != {"ok", "result"}
                    or response["ok"] is not True
                ):
                    raise ApplicationError(
                        "Original scoped Action proof unavailable",
                        type=response.get("code", "definition_mismatch")
                        if type(response) is dict
                        else "definition_mismatch",
                    )
                return commit(self.commands, request, response["result"])
            if (
                self.commands.deployment is not None
                and self.commands.admission_protocol in (2, 3, 4)
                and type(request) is dict
                and ("descendant" in request or "recovery" in request)
            ):
                prepared = self.commands.prepare_deployment_control(request)
                if "receipt" in prepared:
                    return prepared["receipt"]
                envelope = prepared["submission"]
                response = await workflow.execute_activity(
                    DEPLOYMENT_RELEASE_ACTIVITY,
                    {
                        "mode": "manual_control" if "manual_payload" in prepared else "control",
                        "scope": prepared["request"]["scope"],
                        "root": prepared["root"],
                        "target": prepared["request"]["target"],
                        "target_execution_epoch": prepared["target_execution_epoch"],
                        "manifest": envelope["manifest"],
                        "registry_execution_epoch": workflow.info().run_id,
                        **(
                            {"payload": prepared["manual_payload"]}
                            if "manual_payload" in prepared
                            else {}
                        ),
                    },
                    task_queue=envelope["task_queue"],
                    start_to_close_timeout=timedelta(seconds=envelope["activity_timeout"]),
                    schedule_to_close_timeout=timedelta(
                        seconds=envelope["activity_timeout"] * 2 + 5
                    ),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                self._check_deployment_registry_epoch()
                if (
                    type(response) is not dict
                    or response.get("ok") is not True
                    or set(response) != {"ok", "result"}
                ):
                    raise ApplicationError(
                        "Original SDK descendant proof unavailable",
                        type=response.get("code", "definition_mismatch")
                        if type(response) is dict
                        else "definition_mismatch",
                    )
                return self.commands.commit_deployment_control(request, response["result"])
            return self.commands.reserve(request)
        except Exception as exc:
            raise ApplicationError(
                "Temporal command identity was rejected",
                type=getattr(exc, "code", None) or getattr(exc, "type", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.signal(name="reserve_command")
    def reserve_command(self, envelope: dict) -> None:
        accept_reservation_signal(self, envelope)

    @workflow.signal(name="reserve_scoped_command")
    def reserve_scoped_command(self, envelope: dict) -> None:
        from .temporal_scoped_reservation import accept

        accept(self, envelope, workflow.info())

    @workflow.signal(name="reserve_scoped_manual")
    async def reserve_scoped_manual(self, envelope: dict) -> None:
        from .temporal_scoped_manual_transport import accept

        await accept(self, envelope, workflow.info())

    @workflow.signal(name="reserve_public_manual")
    async def reserve_public_manual(self, envelope: dict) -> None:
        from .temporal_public_manual_transport import accept

        await accept(self, envelope, workflow.info())

    @workflow.signal(name="retire_deployment_root")
    async def retire_deployment_root(self, envelope: dict) -> None:
        from .temporal_deployment_retirement_transport import accept

        await accept(self, envelope, workflow.info())

    async def _session_verified_update(self, operation, request):
        from .temporal_deployment_session_updates import execute

        try:
            return await execute(self, operation, request)
        except Exception as exc:
            raise ApplicationError(
                "Original Session deployment verification rejected",
                type=getattr(exc, "code", None) or getattr(exc, "type", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="reserve_session_root")
    async def reserve_session_root(self, request: dict) -> dict:
        return await self._session_verified_update("session_root", request)

    @workflow.update(name="session_never_claimed")
    async def session_never_claimed(self, request: dict) -> dict:
        return await self._session_verified_update("session_never_claimed", request)

    @workflow.update(name="record_deployment_session_command")
    async def record_deployment_session_command(self, request: dict) -> dict:
        return await self._session_verified_update("session_receipt", request)

    @workflow.update(name="close_deployment_sessions")
    async def close_deployment_sessions(self, request: dict) -> dict:
        try:
            from .temporal_deployment_session_updates import state as session_state

            return session_state(self).close_deployment_sessions(request)
        except Exception as exc:
            raise ApplicationError(
                "Original scoped deployment Session close refused",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="record_deployment_submission")
    async def record_deployment_submission(self, request: dict) -> dict:
        try:
            self._check_deployment_registry_epoch()
            return self.commands.record_deployment_submission(request)
        except Exception as exc:
            raise ApplicationError(
                "Original deployment receipt refused",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="release_deployment_root")
    async def release_deployment_root(self, request: dict) -> dict:
        try:
            self._check_deployment_registry_epoch()
            previous = self.commands.deployment_retirement(request)
            if previous is not None:
                return previous
            prepared = self.commands.prepare_deployment_release(request)
            response = await workflow.execute_activity(
                DEPLOYMENT_RELEASE_ACTIVITY,
                {
                    "mode": "verify",
                    "scope": prepared["root"]["scope"],
                    "root": prepared["root"],
                    "certificate": prepared["certificate"],
                    "manifest": prepared["manifest"],
                    "registry_execution_epoch": workflow.info().run_id,
                },
                task_queue=prepared["task_queue"],
                start_to_close_timeout=timedelta(seconds=prepared["activity_timeout"]),
                schedule_to_close_timeout=timedelta(seconds=prepared["activity_timeout"] * 2 + 5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            self._check_deployment_registry_epoch()
            if not response.get("ok"):
                raise ApplicationError(
                    "Original SDK closure proof unavailable",
                    type=response.get("code", "deployment_release_failed"),
                )
            return self.commands.commit_deployment_release(request, response["result"])
        except Exception as exc:
            raise ApplicationError(
                "Original deployment retirement refused",
                type=getattr(exc, "code", None)
                or getattr(exc, "type", "deployment_release_failed"),
                non_retryable=True,
            ) from None

    @workflow.update(name="admit_coding_composition_submission")
    async def admit_coding_composition_submission(self, request: dict) -> dict:
        try:
            self._check_deployment_registry_epoch()
            if self.commands.deployment is not None:
                return self.commands.bind_coding_submission(request)
            if request.get("scope") != self.commands.scope:
                from .errors import AuthorizationDenied

                raise AuthorizationDenied("Command registry belongs to another trusted scope")
            if set(request) != {
                "scope",
                "command_id",
                "run_id",
                "request_digest",
                "manifest_digest",
                "execution_epoch",
                "namespace",
            }:
                from .errors import DefinitionMismatch

                raise DefinitionMismatch(
                    "Original composition admission requires complete SDK identity"
                )
            return self.commands.bind_composition_submission(
                request["command_id"],
                request["run_id"],
                request["request_digest"],
                request["manifest_digest"],
                request["execution_epoch"],
                request["namespace"],
            )
        except Exception as exc:
            raise ApplicationError(
                "Original composition admission rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="close_coding_composition_submissions")
    async def close_coding_composition_submissions(self, request: dict) -> dict:
        try:
            self._check_deployment_registry_epoch()
            if self.commands.deployment is not None:
                from .errors import DefinitionMismatch

                raise DefinitionMismatch("Deployment composition admission is not integrated")
            if request.get("scope") != self.commands.scope:
                from .errors import AuthorizationDenied

                raise AuthorizationDenied("Command registry belongs to another trusted scope")
            if set(request) != {"scope", "manifest_digest"}:
                from .errors import DefinitionMismatch

                raise DefinitionMismatch("Original composition close requires exact scope/release")
            return self.commands.close_composition_submissions(request["manifest_digest"])
        except Exception as exc:
            raise ApplicationError(
                "Original composition admission close rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="close_deployment_coding_submissions")
    async def close_deployment_coding_submissions(self, request: dict) -> dict:
        try:
            self._check_deployment_registry_epoch()
            return self.commands.close_coding_submissions(request)
        except Exception as exc:
            raise ApplicationError(
                "Original scoped deployment Coding close refused",
                type=getattr(exc, "code", "definition_mismatch"),
                non_retryable=True,
            ) from None

    @workflow.update(name="bind_deployment_root")
    async def bind_deployment_root(self, request: dict) -> dict:
        # This pins SDK identity only; it does not adopt outcomes or free quota.
        try:
            self._check_deployment_registry_epoch()
            return self.commands.bind_deployment_root(request)
        except Exception as exc:
            raise ApplicationError(
                "Original deployment root binding rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.query(name="view")
    def view(self, request: dict) -> dict:
        try:
            self._check_deployment_registry_epoch()
        except Exception as exc:
            return {"error": getattr(exc, "code", "definition_mismatch")}
        if request.get("kind") == "scoped_reserve_receipt":
            from .temporal_scoped_reservation import observe

            try:
                return observe(self, request, workflow.info())
            except Exception as exc:
                return {"error": getattr(exc, "code", "validation_error")}
        if self.commands.deployment is not None:
            try:
                if request.get("kind") == "deployment_retirement_observation":
                    from .temporal_deployment_retirement_transport import observe

                    if request.get("scope") != request["retirement_observation"]["scope"]:
                        return {"error": "authorization_denied"}
                    return observe(self, request["retirement_observation"], workflow.info())
                if request.get("kind") == "deployment_manual_observation":
                    from .temporal_public_manual_transport import observe

                    if request.get("scope") != request["manual_observation"]["scope"]:
                        return {"error": "authorization_denied"}
                    return observe(self, request["manual_observation"], workflow.info())
                if request.get("kind") == "deployment_reserve_receipt":
                    return observe_reservation_signal(self, request)
                if request.get("kind") in {
                    "deployment_session_command",
                    "deployment_session_root",
                    "deployment_session_never_claimed",
                }:
                    from .temporal_deployment_session_updates import state as session_state

                    method = {
                        "deployment_session_command": "deployment_session_command",
                        "deployment_session_root": "deployment_session_root",
                        "deployment_session_never_claimed": "deployment_session_never_claimed",
                    }[request["kind"]]
                    return getattr(session_state(self), method)(request)
                if request.get("kind") == "deployment_coding_validation":
                    return self.deployment_coding_validation(request)
                if request.get("kind") == "deployment_control":
                    return self.commands.deployment_control(request)
                if request.get("kind") == "coding_composition_candidates":
                    return self.commands.coding_candidates(request)
                if request.get("kind") == "coding_composition_admission":
                    return self.commands.coding_admission(request)
                if request.get("kind") == "deployment_configuration":
                    return self.commands.deployment_configuration(request)
                if request.get("kind") == "deployment_submission":
                    return self.commands.deployment_submission(request)
                if request.get("kind") == "deployment_retirement":
                    return self.commands.deployment_retirement(
                        {k: v for k, v in request.items() if k != "kind"}
                    )
                return self.commands.deployment_admission(request)
            except Exception as exc:
                return {"error": getattr(exc, "code", "validation_error")}
        if request.get("scope") != self.commands.scope:
            return {"error": "authorization_denied"}
        try:
            if request.get("kind") == "scoped_manual_configuration":
                if "manual_observation" in request:
                    from .temporal_scoped_manual_transport import observe

                    return {
                        "manual_observation": observe(
                            self, request["manual_observation"], workflow.info()
                        )
                    }
                from .temporal_scoped_manual_recovery import configuration

                return configuration(self.commands, workflow.info())
            if request.get("kind") == "scoped_drive_command":
                return self.commands.scoped_drive_command(request)
            if request.get("kind") == "coding_composition_candidates":
                return self.commands.composition_candidates(request["manifest_digest"])
            if request.get("kind") == "coding_composition_admission":
                return self.commands.composition_admission(
                    request["command_id"],
                    request["run_id"],
                    request["request_digest"],
                    request["manifest_digest"],
                )
        except Exception as exc:
            return {"error": getattr(exc, "code", "validation_error")}
        return {
            "scope": detached(self.commands.scope),
            "capacity": self.commands.capacity,
            "accepted_commands": len(self.commands.identities),
        }

    @workflow.query(name="deployment_coding_validation")
    def deployment_coding_validation(self, request: dict) -> dict:
        try:
            self._check_deployment_registry_epoch()
            if self.commands.admission_protocol not in (3, 4) or self.commands.deployment is None:
                raise ValueError("Original Registry3 required")
            info = workflow.info()
            if (
                info.workflow_id != self.commands.deployment.registry_id
                or info.namespace != self.commands.deployment.namespace["name"]
            ):
                raise ValueError("Registry3 SDK address changed")
            return self.commands.deployment.deployment_coding_validation(request)
        except Exception as exc:
            return {"error": getattr(exc, "code", "definition_mismatch")}
