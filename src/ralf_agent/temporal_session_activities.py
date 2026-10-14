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


async def validate_tree_activity(client, request, *, workflow_id):
    """Bind portable lineage to this actual Activity and namespace before I/O."""
    if request.get("runtime_manifest", {}).get("binding_protocol") == 13:
        from .temporal_coding_composition_control import validate_activity

        await validate_activity(client, request, workflow_id=workflow_id)
    lineage = request.get("session_lineage")
    if lineage is None:
        return
    from .temporal_session_tree import validate_lineage

    if client is None:
        raise DefinitionMismatch("Session tree requires its original Temporal client")
    accepted = validate_lineage(
        {**request["session_declaration"], "session_lineage": lineage},
        lineage["root_binding"]["manifest"],
        request["scope"],
    )
    if (
        workflow_id != request["run_id"]
        or accepted["run_id"] != workflow_id
        or await namespace_id(client) != lineage["namespace_id"]
    ):
        raise DefinitionMismatch("Session tree Activity changed actual Run or namespace")


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
