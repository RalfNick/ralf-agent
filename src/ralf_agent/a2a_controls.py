"""Optional native Run controls; authority receipts are not HTTP-owned state."""

from dataclasses import asdict

from .errors import ValidationError
from .messaging import _json, _text
from .task_controls import TaskControlBridge
from .types import CommandReceipt

EXTENSION = "urn:ralf:a2a:run-controls:v1"
METHODS = {"tasks/approve", "tasks/reconcile", "tasks/resume"}


def control_request(method, params):
    required = {
        "tasks/approve": {"id", "actionId", "targetDigest", "commandId"},
        "tasks/reconcile": {"id", "actionId", "result", "commandId"},
        "tasks/resume": {"id"},
    }
    if method not in required or type(params) is not dict:
        raise ValidationError("Invalid Run control")
    allowed = required[method] | ({"approved"} if method == "tasks/approve" else set())
    if required[method] - set(params) or set(params) - allowed:
        raise ValidationError("Invalid Run control fields")
    for name in ("id", "actionId", "targetDigest", "commandId"):
        if name in params:
            _text(params[name], "Run control " + name)
    if method == "tasks/approve" and type(params.get("approved", True)) is not bool:
        raise ValidationError("Approval requires a boolean")
    _json(params)
    return params


async def apply_control(controls, method, params):
    control_request(method, params)
    name = method.split("/")[1]
    controls.require_run_control(name)
    await controls.status(params["id"])
    if name == "approve":
        receipt = await controls.approve(
            params["id"],
            params["actionId"],
            params["targetDigest"],
            command_id=params["commandId"],
            approved=params.get("approved", True),
        )
    else:
        receipt = await controls.reconcile(
            params["id"], params["actionId"], params["result"], command_id=params["commandId"]
        )
    return {"kind": "ralf.control-receipt", "taskId": params["id"], "receipt": asdict(receipt)}


def validate_control_response(value, method, params):
    control_request(method, params)
    if (
        type(value) is not dict
        or set(value) != {"kind", "taskId", "receipt"}
        or value["kind"] != "ralf.control-receipt"
        or value["taskId"] != params["id"]
        or type(value["receipt"]) is not dict
        or set(value["receipt"])
        != {"command_id", "run_id", "kind", "record_state", "apply_state", "outcome"}
    ):
        raise ValidationError("Invalid Run control response")
    TaskControlBridge._receipt(
        CommandReceipt(**value["receipt"]),
        params["commandId"],
        method.split("/")[1],
        params["id"],
        allow_rejected=True,
    )
    return value
