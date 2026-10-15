"""Registered control observations/selection; no local scheduler or SQL authority."""

from dataclasses import asdict

from .dag_planning import DAGProposal, PlanningConclusion
from .errors import RalfError, ValidationError
from .orchestration_types import TeamRequest, TeamSelection
from .planning import PlanningRequest, PlanProposal, Verification
from .temporal_parent_state import child_run_id
from .temporal_state import detached, validate_request
from .types import RunSnapshot, Scope, digest


class _RecordedCaller:
    def __init__(self, request, snapshot):
        self.request, self.snapshot = detached(request), detached(snapshot)

    async def call(self, call_id, member, input):
        if (
            call_id != "planner"
            or member != "@planner"
            or input != self.request
            or self.snapshot is None
        ):
            raise ValidationError("Planner may consume only its recorded managed child")
        value = detached(self.snapshot)
        value["pending"], value["actions"] = tuple(value["pending"]), tuple(value["actions"])
        return RunSnapshot(**value)


async def select(runtime, value):
    runtime.validate_release(value["runtime_manifest"])
    definition, kind = value["definition"], value["kind"]
    if kind == "team":
        request = TeamRequest(
            value["input"], definition["members"], value["results"], definition["strategy_config"]
        )
        result = runtime.teams[definition["strategy"]].select(request)
        if not isinstance(result, TeamSelection):
            from .temporal_activities import _close_lazy

            _close_lazy(result)
            raise ValidationError("Team strategy must return TeamSelection")
    else:
        request = PlanningRequest(**value["planning_request"])
        if kind == "plan":
            result = await runtime.planners[definition["planner"]].plan(
                request, _RecordedCaller(request.to_dict(), value.get("planner_snapshot"))
            )
            if not isinstance(result, (PlanProposal, DAGProposal, PlanningConclusion)):
                from .temporal_activities import _close_lazy

                _close_lazy(result)
                raise ValidationError("Planner must return a completed typed proposal")
        elif kind == "verify":
            result = runtime.verifiers[definition["verifier"]].verify(request)
            if not isinstance(result, Verification):
                from .temporal_activities import _close_lazy

                _close_lazy(result)
                raise ValidationError("Verifier must return Verification")
        else:
            raise ValidationError("Unknown parent selection operation")
    runtime.validate_release(value["runtime_manifest"])
    return detached(result.to_dict())


async def control(runtime, client, value, info=None):
    from .temporal_deployment_control_transport import REQUEST_FIELDS, execute
    from .temporal_deployment_protocol import selected as deployment_selected

    if type(value) is dict and set(value) == REQUEST_FIELDS:
        return await execute(runtime, client, value, info)

    if deployment_selected(value["runtime_manifest"]):
        if value["runtime_manifest"]["deployment_admission_protocol"]["version"] == 3:
            from .temporal_deployment_coding_bridge import control as coding_control

            return await coding_control(runtime, client, value, info)
        from .temporal_deployment_execution import control as deployment_control

        return await deployment_control(runtime, client, value, info)
    if value["runtime_manifest"].get("binding_protocol") in (13, 15, 17, 19, 21, 23):
        from .temporal_coding_composition_control import control as composition_control

        return await composition_control(runtime, client, value, info)
    from .temporal import TemporalEngine

    runtime.validate_release(value["runtime_manifest"])
    mode, call = value["mode"], value["child"]
    scope = Scope(**value["scope"])
    if call["run_id"] != child_run_id(value["scope"], call["command_id"]):
        raise ValidationError("Child control identity mismatch")
    validate_request(call["request"], value["runtime_manifest"])
    engine = TemporalEngine(
        client, task_queue=value["task_queue"], release=value["runtime_manifest"], scope=scope
    )
    if mode == "register":
        await engine._guard("submit", call["command_id"], call["run_id"], call["request"])
        result = {"run_id": call["run_id"], "registered": True}
    elif mode == "observe":
        result = {
            **(
                await engine._view(call["run_id"], "diagnostics")
                if value["runtime_manifest"].get("model_history_protocol") == 2
                or value["runtime_manifest"].get("user_input_protocol") == 1
                else asdict(await engine.diagnostics(call["run_id"]))
            ),
            "scope": value["scope"],
        }
    elif mode == "recover" and value["runtime_manifest"]["kernel"] == "temporal-3":
        await engine.drive(call["run_id"], wait_seconds=0)
        result = {"run_id": call["run_id"], "recovery_requested": True}
    elif mode == "cancel":
        command = "ralf-parent-stop:" + digest([value["parent_id"], call["run_id"]])
        result = asdict(await engine.cancel(call["run_id"], command_id=command))
    else:
        raise ValidationError("Unknown child control operation")
    runtime.validate_release(value["runtime_manifest"])
    return detached(result)


def registered_parent_activities(runtime, client):
    from temporalio import activity

    from .temporal_parent_state import CONTROL_ACTIVITY, SELECTION_ACTIVITY
    from .temporal_state import CONTEXT_ACTIVITY

    @activity.defn(name=CONTROL_ACTIVITY)
    async def child_control(value: dict) -> dict:
        try:
            return {"ok": True, "result": await control(runtime, client, value, activity.info())}
        except Exception as exc:
            return {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "child_control_failed",
            }

    from .temporal_coding_composition_control import ACTIVITY as COMPOSITION_ADMISSION_ACTIVITY

    @activity.defn(name=COMPOSITION_ADMISSION_ACTIVITY)
    async def composition_admission(value: dict) -> dict:
        from .temporal_coding_composition_control import root_admission

        try:
            return {
                "ok": True,
                "result": await root_admission(runtime, client, value, activity.info()),
            }
        except Exception as exc:
            return {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "composition_admission_failed",
            }

    @activity.defn(name=SELECTION_ACTIVITY)
    async def selection(value: dict) -> dict:
        try:
            return {"ok": True, "result": await select(runtime, value)}
        except Exception as exc:
            return {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "selection_failed",
            }

    @activity.defn(name=CONTEXT_ACTIVITY)
    async def context(value: dict) -> dict:
        from .temporal_session_activities import validate_tree_activity

        if "context_read_protocol" in value["runtime_manifest"]:
            from .temporal_context_read_activities import callbacks

            guard, ended = callbacks(client, value, activity.info())
            return await runtime.prepare_context(value, dispatch_guard=guard, on_end=ended)
        await validate_tree_activity(client, value, workflow_id=activity.info().workflow_id)
        result = await runtime.prepare_context(value)
        await validate_tree_activity(client, value, workflow_id=activity.info().workflow_id)
        return result

    from .temporal_parent_completion_state import ACTIVITY as PARENT_COMPLETION_ACTIVITY

    @activity.defn(name=PARENT_COMPLETION_ACTIVITY)
    async def parent_completion(value: dict) -> dict:
        return await runtime.verify_parent_completion(value)

    return [
        child_control,
        selection,
        context,
        *([parent_completion] if runtime.parent_completion_policies else []),
        *(
            [composition_admission]
            if runtime.orchestration_release.get("binding_protocol") in (13, 15, 17, 19, 21, 23)
            else []
        ),
    ]
