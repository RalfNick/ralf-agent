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
    from . import (  # noqa: F401
        coding_create_inventory,  # Pure native inventory schema used during Session activation.
        temporal_context_read_protocol,
        temporal_context_read_state,
        temporal_parent_completion_state,
        temporal_session_identity,  # noqa: F401 -- preload pure Session addressing
    )
    from .temporal_parent_state import PARENT_WORKFLOW_NAME
    from .temporal_session_deployment_dto import ORIGIN_FIELDS, decode_control_body
    from .temporal_session_deployment_state import START_SELECTOR_FIELDS, selected
    from .temporal_session_state import (
        SESSION_ACTIVITY,
        SESSION_WORKFLOW,
        TemporalSessionState,
        workflow_id,
    )
    from .temporal_state import WORKFLOW_NAME


@workflow.defn(name=SESSION_WORKFLOW)
class TemporalSessionWorkflow:
    @workflow.init
    def __init__(self, accepted: dict):
        context = None
        if selected(accepted["manifest"]):
            info = workflow.info()
            if (
                info.run_id != info.first_execution_run_id
                or info.run_id != info.original_execution_run_id
                or info.parent is not None
            ):
                raise ApplicationError(
                    "Session coordinator execution changed",
                    type="definition_mismatch",
                    non_retryable=True,
                )
            context = {
                "namespace": {"name": info.namespace, "id": accepted["namespace_id"]},
                "coordinator_execution_epoch": info.run_id,
            }
        self.state = TemporalSessionState(accepted, deployment_context=context)
        if context is not None and (
            info.workflow_id != workflow_id(self.state.key)
            or info.task_queue != accepted["task_queue"]
        ):
            raise ApplicationError(
                "Session coordinator address or queue changed",
                type="definition_mismatch",
                non_retryable=True,
            )
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

    async def _deployment_control(self, mode, entry):
        intent = entry.intent
        self._deployment_control_waiting = entry.intent["intent_digest"]
        try:
            return await workflow.execute_activity(
                SESSION_ACTIVITY,
                entry.control_request(mode),
                task_queue=intent["binding"]["task_queue"],
                start_to_close_timeout=timedelta(seconds=intent["binding"]["activity_timeout"]),
                schedule_to_close_timeout=timedelta(
                    seconds=intent["binding"]["activity_timeout"] * 3 + 5
                ),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            return {"ok": False, "code": "session_control_unavailable"}
        finally:
            self._deployment_control_waiting = None

    def _deployment_response(self, entry, response):
        body = {key: value for key, value in response.items() if key != "call_end"}
        ack = response.get("call_end")
        if ack is None:
            entry.record_error("session_control_unavailable")
            return None
        body = decode_control_body(body, entry.intent["submission"]["manifest"])
        entry.call_ended(ack, body)
        if body.get("ok") is not True:
            from .temporal_session_deployment_state import PERMANENT_REFUSALS

            code = body.get("code", "session_control_unavailable")
            entry.record_error(code)
            if (
                code in PERMANENT_REFUSALS
                and not entry.start_issued
                and entry.view()["reservation"] is None
            ):
                entry.install_refusal_barrier(code)
            return None
        return body

    async def _deployment_step(self):
        observed = self.wake_revision
        if self.state.active is None:
            return observed
        entry = self.state.deployment_turn()
        try:
            recovered = self.state.recover_deployment_result()
            if self.state.active is None:
                return observed
            if any(call["end"] is None for call in entry.calls.values()):
                return observed
            if entry.view()["phase"] != "started":
                if not recovered:
                    if (
                        entry.view()["phase"]
                        in {"intent-accepted", "capacity-deferred", "reserve-unknown"}
                        and entry.refusal_barrier is None
                    ):
                        entry.reserve_issued()
                    response = await self._deployment_control("register", entry)
                    body = self._deployment_response(entry, response)
                    if body is not None:
                        self.state.adopt_deployment_registration(
                            body["result"], response["call_end"]
                        )
                    elif entry.refusal_barrier is not None:
                        # Complete this original refusal handshake without requiring an unrelated command.
                        response = await self._deployment_control("register", entry)
                        body = self._deployment_response(entry, response)
                        if body is not None:
                            self.state.adopt_deployment_registration(
                                body["result"], response["call_end"]
                            )
                if self.state.active is not None:
                    self.state.recover_deployment_result()
                if self.state.active is None:
                    return observed
                if entry.view()["phase"] == "held-unbound" and entry.issue_start():
                    intent = entry.intent
                    origin = {
                        name: intent[name]
                        for name in ORIGIN_FIELDS
                        - {
                            "coordinator_first_execution_epoch",
                            "coordinator_original_execution_epoch",
                        }
                    }
                    origin["coordinator_first_execution_epoch"] = intent[
                        "coordinator_execution_epoch"
                    ]
                    origin["coordinator_original_execution_epoch"] = intent[
                        "coordinator_execution_epoch"
                    ]
                    accepted = {
                        "scope": intent["scope"],
                        "command_id": intent["run_command_id"],
                        **{
                            key: intent["submission"][key]
                            for key in ("request", "manifest", "activity_timeout")
                        },
                        "deployment_admission": {
                            "version": 2,
                            "root": entry.view()["reservation"]["root_admission"],
                            "lineage": [],
                            "session_origin": origin,
                        },
                    }
                    try:
                        await workflow.start_child_workflow(
                            PARENT_WORKFLOW_NAME
                            if intent["submission"]["request"]["definition"]["kind"]
                            in {"graph", "team", "dynamic"}
                            else WORKFLOW_NAME,
                            accepted,
                            id=intent["run_id"],
                            task_queue=intent["submission"]["task_queue"],
                            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                            retry_policy=None,
                        )
                    except Exception:
                        # Issuance is irreversible; only fresh original SDK/Registry evidence can resolve it.
                        entry.record_error("session_start_uncertain")
                    response = await self._deployment_control("register", entry)
                    body = self._deployment_response(entry, response)
                    if body is not None:
                        self.state.adopt_deployment_registration(
                            body["result"], response["call_end"]
                        )
            if self.state.active is not None:
                self.state.recover_deployment_result()
            if (
                self.state.active is not None
                and entry.view()["phase"] == "started"
                and not any(call["end"] is None for call in entry.calls.values())
            ):
                # Capture immediately before observe, so a hint during the await remains dirty.
                observed = self.wake_revision
                response = await self._deployment_control("observe", entry)
                body = self._deployment_response(entry, response)
                if body is not None:
                    self.state.adopt_deployment_observation(body, response["call_end"])
                elif self.state.active is not None:
                    self.state.recover_deployment_result()
        except Exception as exc:
            entry.record_error(getattr(exc, "code", "session_evidence_invalid"))
        return observed

    @workflow.run
    async def run(self, accepted: dict):
        while True:
            if self.state.deployment_context is not None:
                observed = await self._deployment_step()
                await workflow.wait_condition(lambda wake=observed: self.wake_revision != wake)
                continue
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
        if self.state.deployment_context is not None:
            try:
                entry = self.state.deployment_turn(request)
                await workflow.wait_condition(
                    lambda: (
                        entry.view()["phase"] in {"started", "capacity-deferred", "start-refused"}
                    )
                )
                return entry.view()
            except Exception as exc:
                raise ApplicationError(
                    "Unknown original deployment Turn",
                    type=getattr(exc, "code", "validation_error"),
                    non_retryable=True,
                ) from None
        if request.get("scope") != self.state.scope or not any(
            t["run"]["run_id"] == request.get("run_id") for t in self.state.records
        ):
            raise ApplicationError(
                "Unknown scoped Turn", type="authorization_denied", non_retryable=True
            )
        await workflow.wait_condition(lambda: request["run_id"] in self.state.started_runs)
        return {"run_id": request["run_id"], "started": True}

    @workflow.update(name="retry_deployment_turn")
    async def retry_deployment_turn(self, request: dict) -> dict:
        try:
            result = self.state.deployment_retry(request)
            if result["wake_recorded"]:
                self.wake_revision += 1
            return result
        except Exception as exc:
            raise ApplicationError(
                "Original deployment Turn retry rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    def _deployment_call(self, identity):
        return self.state.deployment_turn({name: identity[name] for name in START_SELECTOR_FIELDS})

    @workflow.update(name="session_deployment_call_start")
    async def session_deployment_call_start(self, request: dict) -> dict:
        try:
            if type(request) is not dict or set(request) != {"identity"}:
                raise ValueError("Invalid Session call start")
            return self._deployment_call(request["identity"]).begin_call(request["identity"])
        except Exception as exc:
            raise ApplicationError(
                "Original Session call rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.update(name="session_deployment_call_end")
    async def session_deployment_call_end(self, request: dict) -> dict:
        try:
            entry = self._deployment_call(request["identity"])
            before = entry.recovered_result()
            ack = entry.end_call(request)
            after = entry.recovered_result()
            if (
                after is not None
                and before != after
                and getattr(self, "_deployment_control_waiting", None)
                != entry.intent["intent_digest"]
            ):
                self.wake_revision += 1
            return ack
        except Exception as exc:
            raise ApplicationError(
                "Original Session call end rejected",
                type=getattr(exc, "code", "validation_error"),
                non_retryable=True,
            ) from None

    @workflow.signal(name="wake")
    def wake(self, request: dict):
        if self.state.deployment_context is not None:
            try:
                if self.state.deployment_hint(request):
                    self.wake_revision += 1
            except Exception:
                pass
            return
        if request.get("scope") == self.state.scope:
            self.wake_revision += 1

    @workflow.query(name="view")
    def view(self, request: dict) -> dict:
        if request.get("scope") != self.state.scope:
            return {"error": "authorization_denied"}
        try:
            kind = request["kind"]
            if kind.startswith("deployment_session_"):
                selector = {key: value for key, value in request.items() if key != "kind"}
                if kind == "deployment_session_binding":
                    return self.state.deployment_binding(selector)
                if kind == "deployment_session_receipt":
                    return self.state.deployment_receipt(selector)
                if kind == "deployment_session_intent":
                    from .temporal_deployment_admission import _exact

                    _exact(selector, START_SELECTOR_FIELDS - {"intent_digest"})
                    entry = self.state.deployment_turns.get(selector["session_command_id"])
                    if entry is None:
                        return None
                    intent = entry.intent
                    self.state.deployment_turn(
                        {**selector, "intent_digest": intent["intent_digest"]}
                    )
                    return intent
                if kind == "deployment_session_start":
                    return self.state.deployment_view(selector)
                if kind == "deployment_session_lifecycle":
                    return self.state.deployment_turn(selector).lifecycle()
                if kind == "deployment_session_command":
                    return self.state.deployment_command(selector)
            if request["kind"] == "status":
                return self.state.snapshot()
            if request["kind"] == "profile_binding":
                return self.state.profile_binding()
            if request["kind"] == "turns":
                return self.state.turns(after=request["after"], limit=request["limit"])
            return {"error": "validation_error"}
        except Exception as exc:
            return {"error": getattr(exc, "code", "validation_error")}
