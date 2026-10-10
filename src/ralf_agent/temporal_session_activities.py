"""Only register or observe the original Run; no model or tool execution here."""

from .errors import DefinitionMismatch, RalfError, ValidationError
from .types import Scope, digest


async def namespace_id(client):
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest

    result = await client.workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace=client.namespace)
    )
    value = result.namespace_info.id
    if not value:
        raise DefinitionMismatch("Temporal namespace UUID is unavailable")
    return value


def registered_session_activities(runtime, client):
    from temporalio import activity

    from .temporal import TemporalEngine
    from .temporal_session_state import SESSION_ACTIVITY

    @activity.defn(name=SESSION_ACTIVITY)
    async def session_control(value: dict) -> dict:
        try:
            if value.get("mode") not in {"register", "observe"}:
                raise ValidationError("Unsupported Session control operation")
            intent = value["intent"]
            runtime.validate_release(intent["manifest"])
            if await namespace_id(client) != value["namespace_id"]:
                raise DefinitionMismatch("Session control belongs to another namespace resource")
            if intent["run_id"] != "ralf-temporal-" + digest(
                [value["scope"], intent["command_id"]]
            ):
                raise DefinitionMismatch("Session Run identity changed")
            engine = TemporalEngine(
                client,
                task_queue=intent["task_queue"],
                release=intent["manifest"],
                scope=Scope(**value["scope"]),
            )
            if value["mode"] == "register":
                await engine._guard(
                    "submit", intent["command_id"], intent["run_id"], intent["request"]
                )
                result = {"run_id": intent["run_id"], "registered": True}
            else:
                result = await engine._view(intent["run_id"], "session_proof")
                from .temporal_session_state import quiet

                if quiet(result):
                    pending, seen, descendants = [result], {intent["run_id"]}, []
                    while pending:
                        parent = pending.pop()
                        for child in parent["workflow"].get("children", []):
                            if not child.get("dispatch_started"):
                                continue
                            if child["run_id"] in seen or len(seen) >= 4096:
                                raise DefinitionMismatch(
                                    "Session descendants exceed unique traversal bounds"
                                )
                            seen.add(child["run_id"])
                            evidence = await engine._view(child["run_id"], "session_proof")
                            descendants.append(evidence)
                            pending.append(evidence)
                    result["descendants"] = descendants
            runtime.validate_release(intent["manifest"])
            if await namespace_id(client) != value["namespace_id"]:
                raise DefinitionMismatch("Session control namespace changed during I/O")
            return {"ok": True, "result": result}
        except Exception as exc:
            return {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "session_control_failed",
            }

    return [session_control]
