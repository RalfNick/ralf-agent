"""Original scoped Action admission; effects remain owned by the original Run."""

from .errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict, ValidationError
from .temporal_deployment_admission import _exact, _sha, _text
from .temporal_manual_recovery import manual_payload
from .types import digest

FIELDS = {"scope", "command_id", "kind", "target", "payload_digest"}
PROOF_FIELDS = {
    "version",
    "scope",
    "namespace",
    "registry_execution_epoch",
    "target",
    "execution_epoch",
    "submission_digest",
    "action_id",
    "action_digest",
    "tool_request_digest",
    "schedule_event_id",
    "started_event_id",
    "proof_digest",
}


def _reject():
    raise DefinitionMismatch("Original scoped Action evidence changed")


def receipt(state, request):
    from .temporal_state import detached

    identity = {k: request[k] for k in ("kind", "target", "payload_digest")}
    previous = state.identities.get(request["command_id"])
    if previous is None:
        return None
    if previous != identity:
        raise IdempotencyConflict("Scoped command ID already identifies other content")
    value = {
        "command_id": request["command_id"],
        "target": request["target"],
        "record_state": "durably_recorded",
        "apply_state": "not_applied",
    }
    binding = getattr(state, "scoped_manual_bindings", {}).get(request["command_id"])
    if binding is not None:
        value["control_binding"] = detached(binding)
    return value


def prepare(state, request):
    from .temporal_state import detached

    state._require_scoped_mode()
    _exact(request, FIELDS | {"recovery"})
    if request["scope"] != state.scope:
        raise AuthorizationDenied("Manual control belongs to another Scope")
    for key in ("command_id", "target"):
        _text(request[key])
    _sha(request["payload_digest"])
    identity = {k: request[k] for k in ("kind", "target", "payload_digest")}
    previous = state.identities.get(request["command_id"])
    if previous is not None and previous != identity:
        raise IdempotencyConflict("Scoped command ID already identifies other content")
    recovery = request["recovery"]
    _exact(recovery, {"version", "registry_execution_epoch", "namespace", "payload"})
    if type(recovery["version"]) is not int or recovery["version"] != 1:
        _reject()
    _text(recovery["registry_execution_epoch"])
    _text(recovery["namespace"])
    payload = manual_payload(recovery["payload"], state.scope)
    if request["kind"] != "reconcile" or digest(payload) != request["payload_digest"]:
        _reject()
    identity = {k: request[k] for k in ("kind", "target", "payload_digest")}
    previous = state.identities.get(request["command_id"])
    if previous is not None:
        if previous != identity:
            raise IdempotencyConflict("Scoped command ID already identifies other content")
        return {"receipt": receipt(state, request)}
    candidates = [
        {"command_id": key, "target": record["target"], "payload_digest": record["payload_digest"]}
        for key, record in state.identities.items()
        if record["kind"] == "submit" and record["target"] == request["target"]
    ]
    if len(candidates) != 1:
        _reject()
    return detached({"submission": candidates[0], "payload": payload})


def commit(state, request, proof):
    from .temporal_deployment_admission import _namespace
    from .temporal_state import detached

    prepared = prepare(state, request)
    if "receipt" in prepared:
        return prepared["receipt"]
    _exact(proof, PROOF_FIELDS)
    namespace = _namespace(proof["namespace"])
    if (
        type(proof["version"]) is not int
        or proof["version"] != 1
        or proof["scope"] != state.scope
        or proof["target"] != request["target"]
        or proof["registry_execution_epoch"] != request["recovery"]["registry_execution_epoch"]
        or namespace["name"] != request["recovery"]["namespace"]
        or proof["submission_digest"] != digest(prepared["submission"])
        or proof["action_id"] != prepared["payload"]["action_id"]
        or proof["proof_digest"] != digest({k: v for k, v in proof.items() if k != "proof_digest"})
        or type(proof["schedule_event_id"]) is not int
        or proof["schedule_event_id"] <= 1
        or (
            proof["started_event_id"] is not None
            and (
                type(proof["started_event_id"]) is not int
                or proof["started_event_id"] <= proof["schedule_event_id"]
            )
        )
    ):
        _reject()
    for key in ("action_digest", "tool_request_digest", "submission_digest", "proof_digest"):
        _sha(proof[key])
    _text(proof["execution_epoch"])
    epochs = state.scoped_manual_epochs
    if epochs.get(request["target"], proof["execution_epoch"]) != proof["execution_epoch"]:
        _reject()
    slot = digest([state.scope, request["target"], proof["execution_epoch"], proof["action_id"]])
    if slot in state.scoped_manual_slots:
        raise IdempotencyConflict("Original Action already has its manual confirmation")
    state.identities[request["command_id"]] = detached(
        {k: request[k] for k in ("kind", "target", "payload_digest")}
    )
    epochs[request["target"]] = proof["execution_epoch"]
    state.scoped_manual_slots[slot] = request["command_id"]
    state.scoped_manual_bindings[request["command_id"]] = detached(
        {
            "version": 1,
            "scope": state.scope,
            "namespace": namespace,
            "target": request["target"],
            "target_execution_epoch": proof["execution_epoch"],
        }
    )
    return receipt(state, request)


async def verify(runtime, client, value, info):
    """Read only original SDK records; never issue a business/control Update."""
    from .task_controls import _binding
    from .temporal_parent_state import CONTROL_ACTIVITY
    from .temporal_session_activities import namespace_id
    from .temporal_state import (
        COMMAND_REGISTRY_NAME,
        TOOL_ACTIVITY,
        WORKFLOW_NAME,
        detached,
        validate_manifest,
        validate_request,
    )

    _exact(
        value, {"mode", "scope", "registry_execution_epoch", "namespace", "submission", "payload"}
    )
    value = detached(value)
    if value["mode"] != "scoped_manual" or getattr(info, "activity_type", None) != CONTROL_ACTIVITY:
        _reject()
    scope, submission = value["scope"], value["submission"]
    _exact(submission, {"command_id", "target", "payload_digest"})
    payload = manual_payload(value["payload"], scope)
    for key in ("command_id", "target"):
        _text(submission[key])
    _sha(submission["payload_digest"])
    target = submission["target"]
    registry_id = "ralf-temporal-commands-" + digest(scope)
    if target != "ralf-temporal-" + digest([scope, submission["command_id"]]):
        _reject()
    registry_epoch = value["registry_execution_epoch"]
    namespace = value["namespace"]
    ports = [
        (runtime, "validate_release"),
        (client, "get_workflow_handle"),
        (client.data_converter, "decode"),
    ]
    service = getattr(client, "workflow_service", None)
    if service is not None:
        ports.append((service, "describe_namespace"))
    fields = ("workflow_id", "workflow_run_id", "workflow_namespace", "task_queue", "activity_type")
    claim = tuple(getattr(info, n, None) for n in fields)
    pins = tuple(_binding(getattr(o, n)) for o, n in ports)
    converter = client.data_converter
    release = detached(runtime.manifest)

    def check():
        if (
            client.namespace != namespace
            or getattr(client, "workflow_service", None) is not service
            or tuple(getattr(info, n, None) for n in fields) != claim
            or client.data_converter is not converter
            or tuple(_binding(getattr(o, n)) for o, n in ports) != pins
            or info.workflow_id != registry_id
            or info.workflow_run_id != registry_epoch
            or info.workflow_namespace != namespace
        ):
            _reject()
        runtime.validate_release(release)

    async def namespace_check(expected=None):
        check()
        current = {"name": namespace, "id": await namespace_id(client)}
        check()
        if expected is not None and current != expected:
            _reject()
        return current

    check()
    actual_namespace = await namespace_check()
    from .temporal_deployment_admission import _namespace

    _namespace(actual_namespace)
    handles = []

    async def description(identifier, epoch=None):
        check()
        handle = client.get_workflow_handle(identifier, **({"run_id": epoch} if epoch else {}))
        check()
        for name in ("describe", "query", "fetch_history_events"):
            ports.append((handle, name))
        nonlocal pins
        pins = pins + tuple(
            _binding(getattr(handle, n)) for n in ("describe", "query", "fetch_history_events")
        )
        d = await handle.describe()
        check()
        if (
            d.id != identifier
            or d.namespace != namespace
            or (epoch is not None and d.run_id != epoch)
            or d.raw_info.first_run_id != d.run_id
        ):
            _reject()
        handles.append((identifier, d.run_id))
        return handle, d

    async def history(handle, d, kind, *, first_only=False):
        events = []
        async for event in handle.fetch_history_events():
            check()
            if not events:
                if event.event_id != 1 or not event.HasField(
                    "workflow_execution_started_event_attributes"
                ):
                    _reject()
                a = event.workflow_execution_started_event_attributes
                if (
                    a.first_execution_run_id != d.run_id
                    or a.original_execution_run_id != d.run_id
                    or a.continued_execution_run_id
                    or a.workflow_type.name != kind
                    or d.workflow_type != kind
                    or a.task_queue.name != d.task_queue
                ):
                    _reject()
            events.append(event)
            if first_only:
                break
        if not events:
            _reject()
        decoded = await converter.decode(
            events[0].workflow_execution_started_event_attributes.input.payloads
        )
        check()
        if len(decoded) != 1 or type(decoded[0]) is not dict:
            _reject()
        return decoded[0], events

    rh, rd = await description(registry_id, registry_epoch)
    if rd.task_queue != info.task_queue:
        _reject()
    original_registry, _ = await history(rh, rd, COMMAND_REGISTRY_NAME, first_only=True)
    if original_registry != {"scope": scope}:
        _reject()
    th, td = await description(target)
    # Pin the epoch for every subsequent read; a reset never redirects the proof.
    th, td = await description(target, td.run_id)
    accepted, events = await history(th, td, WORKFLOW_NAME)
    accepted_fields = {"scope", "command_id", "request", "manifest", "activity_timeout"}
    if set(accepted) not in (accepted_fields, accepted_fields | {"depth"}):
        _reject()
    if "depth" in accepted and (type(accepted["depth"]) is not int or accepted["depth"] < 0):
        _reject()
    manifest = validate_manifest(accepted["manifest"])
    validate_request(accepted["request"], manifest)
    if (
        accepted["scope"] != scope
        or accepted["command_id"] != submission["command_id"]
        or digest(accepted["request"]) != submission["payload_digest"]
        or "deployment_admission_protocol" in manifest
    ):
        _reject()
    diagnostics = detached(await th.query("view", {"kind": "diagnostics", "scope": scope}))
    check()
    if (
        type(diagnostics) is not dict
        or digest(diagnostics.get("manifest")) != digest(manifest)
        or diagnostics.get("snapshot", {}).get("run_id") != target
    ):
        _reject()
    actions = [a for a in diagnostics["snapshot"]["actions"] if a.get("id") == payload["action_id"]]
    if len(actions) != 1:
        _reject()
    action = actions[0]
    if (
        action.get("kind") != "tool"
        or action.get("status") != "outcome_unknown"
        or "delegated_execution" in action
        or not action.get("attempts")
    ):
        _reject()
    tool = {
        "runtime_manifest": manifest,
        "scope": scope,
        "run_id": target,
        "action_id": action["id"],
        "attempt_id": action["attempts"][0]["id"],
        "effect_key": action["effect_key"],
        "execution_epoch": td.run_id,
        "tool": action["tool"],
        "tool_manifest": manifest["tools"][action["tool"]],
        "arguments": action["arguments"],
        "operation_digest": action["digest"],
    }
    if "tool_execution_protocol" in manifest:
        tool["release_digest"] = diagnostics["release_digest"]
        owners = [
            o
            for o in diagnostics["workflow"].get("tool_executions", [])
            if o.get("action_id") == action["id"]
        ]
        if (
            len(owners) != 1
            or owners[0].get("grant_allowed") is not True
            or owners[0].get("request_digest") != digest(tool)
            or owners[0].get("execution_epoch") != td.run_id
        ):
            _reject()
        import re

        if (
            type(owners[0].get("invocation_id")) is not str
            or re.fullmatch("[a-f0-9]{32}", owners[0]["invocation_id"]) is None
        ):
            _reject()
    else:
        # Old unsafe no-marker Runs do not acquire a new recovery allowance.
        marked = False
        for e in events:
            if e.HasField("marker_recorded_event_attributes"):
                m = e.marker_recorded_event_attributes
                if m.marker_name == "core_patch" and "patch-data" in m.details:
                    decoded = await converter.decode(m.details["patch-data"].payloads)
                    check()
                    marked |= decoded == [
                        {"id": "ralf-unowned-tool-end-evidence-v1", "deprecated": False}
                    ]
        if action.get("execution_unconfirmed") is not True or not marked:
            _reject()
    scheduled = [
        e
        for e in events
        if e.HasField("activity_task_scheduled_event_attributes")
        and e.activity_task_scheduled_event_attributes.activity_id == tool["attempt_id"]
    ]
    if len(scheduled) != 1:
        _reject()
    event = scheduled[0]
    call = event.activity_task_scheduled_event_attributes
    if call.activity_type.name != TOOL_ACTIVITY or call.task_queue.name != td.task_queue:
        _reject()
    actual = await converter.decode(call.input.payloads)
    check()
    if type(actual) is not list or len(actual) != 1 or digest(actual) != digest([tool]):
        _reject()
    started = [
        e.event_id
        for e in events
        if e.HasField("activity_task_started_event_attributes")
        and e.activity_task_started_event_attributes.scheduled_event_id == event.event_id
    ]
    if len(started) > 1:
        _reject()
    # Re-read latest unbound descriptions: no reset during proof may be adopted.
    for identifier, epoch in tuple(handles):
        _, d = await description(identifier)
        if d.run_id != epoch:
            _reject()
    await namespace_check(actual_namespace)
    proof = {
        "version": 1,
        "scope": scope,
        "namespace": actual_namespace,
        "registry_execution_epoch": registry_epoch,
        "target": target,
        "execution_epoch": td.run_id,
        "submission_digest": digest(submission),
        "action_id": action["id"],
        "action_digest": action["digest"],
        "tool_request_digest": digest(tool),
        "schedule_event_id": event.event_id,
        "started_event_id": started[0] if started else None,
    }
    return detached({**proof, "proof_digest": digest(proof)})


def configuration(state, info):
    from .temporal_state import detached

    state._require_scoped_mode()
    if info.workflow_id != "ralf-temporal-commands-" + digest(state.scope) or any(
        getattr(info, n, None) != info.run_id
        for n in ("first_execution_run_id", "original_execution_run_id")
    ):
        _reject()
    _text(info.run_id)
    return detached(
        {
            "version": 1,
            "scope": state.scope,
            "namespace": info.namespace,
            "registry_execution_epoch": info.run_id,
        }
    )


async def reserve_manual(engine, handle, request, payload):
    from dataclasses import asdict

    from .temporal import _raise_code
    from .temporal_scoped_reservation import _legacy_configuration, _receipt
    from .temporal_state import detached

    client, scope, release = engine.client, asdict(engine.scope), engine.release
    namespace = client.namespace

    def check():
        if (
            engine._closed
            or engine.client is not client
            or asdict(engine.scope) != scope
            or scope != request["scope"]
            or engine.release != release
            or client.namespace != namespace
        ):
            _reject()

    check()
    value = await handle.query(
        "view", {"kind": "scoped_manual_configuration", "scope": request["scope"]}
    )
    check()
    if _legacy_configuration(value, request["scope"]):
        raise ValidationError("Temporal scoped command registry capacity exhausted")
    _exact(value, {"version", "scope", "namespace", "registry_execution_epoch"})
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["scope"] != request["scope"]
        or value["namespace"] != engine.client.namespace
    ):
        _reject()
    _text(value["registry_execution_epoch"])
    manual_payload(payload, request["scope"])
    strong = {
        **request,
        "recovery": {
            "version": 1,
            "registry_execution_epoch": value["registry_execution_epoch"],
            "namespace": value["namespace"],
            "payload": detached(payload),
        },
    }
    from .temporal_scoped_manual_transport import execute

    result = await execute(client, engine.command_registry_id, strong, original=value)
    check()
    if type(result) is dict and set(result) == {"error"}:
        _raise_code(result["error"])
    return _receipt(result, request)


def binding(value, request, namespace):
    from .temporal_deployment_admission import _namespace
    from .temporal_state import detached

    _exact(value, {"version", "scope", "namespace", "target", "target_execution_epoch"})
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["scope"] != request["scope"]
        or value["target"] != request["target"]
        or (namespace is not None and _namespace(value["namespace"])["name"] != namespace)
        or request["kind"] != "reconcile"
    ):
        _reject()
    _namespace(value["namespace"])
    _text(value["target_execution_epoch"])
    return detached(value)
