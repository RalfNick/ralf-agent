"""Pure original History Coding intent, finite phase grants and native receipts.

No source, process, PostgreSQL or SDK I/O occurs here. The original Tool claim
owns new native permission; recovery invocations can only read/adopt and stop.
"""

import copy

from .errors import AuthorizationDenied, DefinitionMismatch
from .temporal_tool_execution import ordinary
from .types import digest

CODING_QUERY = "coding_state"
CODING_GRANT = "admit_coding_phase"
CODING_RECEIPT = "coding_receipt"
CODING_STOP = "admit_coding_stop"
CODING_OWNER_STOPPED = "coding_owner_stopped"
CODING_STOP_ACTIVITY = "ralf_coding_stop"
PROOF_FIELDS = {
    "scope",
    "run_id",
    "action_id",
    "release_digest",
    "request_digest",
    "execution_epoch",
    "invocation_id",
}


def enabled(manifest):
    return "coding_execution_protocol" in manifest


def selected(manifest, tool):
    return "delegated_runner" in manifest.get("tools", {}).get(tool, {}).get("config", {})


def prepare(state, action, tool_request):
    if not enabled(state.manifest) or not selected(state.step_manifest, action["tool"]):
        return tool_request
    request = copy.deepcopy(tool_request)
    marker = request["tool_manifest"]["config"]["delegated_runner"]
    runner = ordinary(marker["runner"])
    dispatch = {
        name: copy.deepcopy(request[name])
        for name in (
            "scope",
            "run_id",
            "action_id",
            "attempt_id",
            "effect_key",
            "execution_epoch",
            "tool_manifest",
            "arguments",
            "operation_digest",
        )
    }
    native = {
        "dispatch": dispatch,
        "release_digest": state.release_digest,
        "reservation": {"id": request["attempt_id"], "amount": request["tool_manifest"]["cost"]},
        "definition_digest": digest(state.request["definition"]),
        "deadline": None,
    }
    native["request_digest"] = digest(native)
    request["coding_request"] = copy.deepcopy(native)
    if "delegated_execution" in action:
        if action["delegated_execution"]["tool_request"] != request:
            raise DefinitionMismatch("Original Coding intent cannot be replaced")
        return request
    action["delegated_execution"] = {
        "version": 1,
        "request": native,
        "runner": runner,
        "phase": "intent",
        "grants": {},
        "pending_stop": False,
        "fenced": True,
        "native_unknown": False,
        "effect_case": "pending",
        "tool_request": copy.deepcopy(request),
        "stop_invocations": [],
        "stop_needed": False,
        "stop_active": False,
        "stop_retry": False,
        "stop_sequence": 0,
        "stop_query_observed": False,
    }
    state._emit(
        "coding_intent_recorded",
        {"action_id": action["id"], "request_digest": native["request_digest"]},
    )
    return request


def _record(state, payload, *, extra=(), recovery=False, admission=False):
    payload = ordinary(payload)
    if type(payload) is not dict or set(payload) != PROOF_FIELDS | set(extra):
        raise DefinitionMismatch("Coding requires its complete original fixed proof")
    proof = {key: payload[key] for key in PROOF_FIELDS}
    from .temporal_tool_execution_state import record

    tool, action = record(state, proof, admission=True)
    value = action.get("delegated_execution")
    if value is None or not enabled(state.manifest):
        raise DefinitionMismatch("Coding requires original selected native intent")
    if (
        tool["request_digest"] != digest(value["tool_request"])
        or value["tool_request"]["coding_request"] != value["request"]
        or len(action["attempts"]) != 1
    ):
        raise DefinitionMismatch("Coding original request or attempt changed")
    native = value["request"]
    dispatch = native["dispatch"]
    marker = dispatch["tool_manifest"].get("config", {}).get("delegated_runner", {})
    from .temporal_bindings import effective_manifest, effective_step, step_descriptor

    descriptor = step_descriptor(state.request, action["node"])
    original_manifest = effective_manifest(state.manifest, descriptor)
    original_step = effective_step(
        state.request["definition"]["steps"][action["node"]], state.manifest, descriptor
    )
    if (
        dispatch["action_id"] != action["id"]
        or dispatch["run_id"] != state.run_id
        or dispatch["scope"] != state.scope
        or dispatch["execution_epoch"] != state.epoch
        or dispatch["arguments"] != action["arguments"]
        or dispatch["operation_digest"] != action["digest"]
        or action["tool"] not in original_step["tools"]
        or dispatch["tool_manifest"] != original_manifest["tools"][action["tool"]]
        or marker.get("runner") != value["runner"]
        or native["definition_digest"] != digest(state.request["definition"])
        or native["release_digest"] != state.release_digest
        or native["request_digest"]
        != digest({k: v for k, v in native.items() if k != "request_digest"})
    ):
        raise DefinitionMismatch("Original Coding action or native dependencies changed")
    reservation = state.reservations.get(action["attempts"][0]["id"])
    if (
        reservation is None
        or reservation["id"] != value["request"]["reservation"]["id"]
        or reservation["amount"] != value["request"]["reservation"]["amount"]
        or reservation["status"] not in {"reserved", "unknown", "settled"}
    ):
        raise DefinitionMismatch("Coding requires its original reservation")
    claim = tool.get("invocation_id")
    invocation = proof["invocation_id"]
    if (
        not admission
        and claim != invocation
        and not (recovery and invocation in value["stop_invocations"])
    ):
        raise AuthorizationDenied("Coding requires its original Tool claim or admitted stop")
    return tool, action, value, payload


def query(state, proof):
    tool, action, value, _ = _record(state, proof, recovery=True)
    return copy.deepcopy(
        {
            "request": value["request"],
            "runner": value["runner"],
            "state": value,
            "cancelled": state.state in {"cancelling", "cancelled", "failed", "succeeded"}
            or "cancel" in value
            or value["stop_needed"],
            "original_invocation_id": tool.get("invocation_id"),
        }
    )


def grant(state, payload):
    tool, action, value, payload = _record(state, payload, extra=("method", "params", "binding"))
    if (
        state.state != "running"
        or state.active_action != action["id"]
        or action["status"] != "executing"
        or not action["approved"]
        or not tool.get("grant_allowed")
        or tool["execution_stopped"]
        or tool["execution_epoch"] != state.epoch
        or "cancel" in value
        or "unprepared" in value
        or "owner" not in value
        or value["owner"]["invocation_id"] != tool.get("invocation_id")
        or value["stop_needed"]
        or state.reservations[action["attempts"][0]["id"]]["status"] != "reserved"
    ):
        raise AuthorizationDenied("Coding native grant requires active original Tool ownership")
    from .coding_execution_rules import grant as grant_phase

    result = grant_phase(
        value, action, value["runner"], payload["method"], payload["params"], payload["binding"]
    )
    if result["execute"]:
        state._emit(
            "coding_phase_granted", {"action_id": action["id"], "method": payload["method"]}
        )
    return result


def adopt(state, payload):
    tool, action, value, payload = _record(
        state, payload, extra=("kind", "evidence"), recovery=True
    )
    if payload["kind"] == "owner":
        evidence = payload["evidence"]
        validate_owner(evidence, tool.get("invocation_id"))
        if "owner" in value:
            if value["owner"] != evidence:
                raise DefinitionMismatch("Original Coding process owner cannot be replaced")
            return {"action_id": action["id"], "recorded": True}
        recovering_owner = payload["invocation_id"] in value["stop_invocations"]
        if value["grants"] or (
            (value["stop_needed"] or tool["execution_stopped"]) and not recovering_owner
        ):
            raise AuthorizationDenied("Original process owner must precede native permission")
        value["owner"] = copy.deepcopy(evidence)
    elif payload["kind"] == "namespace_absent":
        evidence = payload["evidence"]
        preparation = value["grants"].get("prepare")
        if (
            payload["invocation_id"] not in value["stop_invocations"]
            or not value["stop_needed"]
            or preparation is None
            or set(value["grants"]) != {"prepare"}
            or any(value.get(key) is not None for key in ("prepared", "stop", "thread", "turn"))
            or type(evidence) is not dict
            or set(evidence)
            != {
                "identity",
                "generation",
                "container_present",
                "namespace_confirmed",
                "owner",
                "process_present",
            }
            or evidence["container_present"] is not False
            or evidence["namespace_confirmed"] is not True
            or evidence["process_present"] is not False
            or "owner" not in value
            or evidence["owner"] != value["owner"]
            or value["owner"]["invocation_id"] != tool.get("invocation_id")
            or evidence["identity"] != preparation["binding"]["environment"]
            or evidence["generation"]
            != preparation["binding"]["environment"].get("expected_generation")
        ):
            raise AuthorizationDenied(
                "Namespace absence requires original process death and unprepared original grant"
            )
        if "namespace_absent" in value and value["namespace_absent"] != evidence:
            raise DefinitionMismatch("Original namespace absence evidence changed")
        value["namespace_absent"] = copy.deepcopy(evidence)
        value["pending_stop"], value["fenced"] = False, True
        value["phase"] = "namespace_absent"
    elif payload["kind"] == "unprepared":
        evidence = payload["evidence"]
        if (
            payload["invocation_id"] not in value["stop_invocations"]
            or not value["stop_needed"]
            or value["grants"]
            or any(value.get(key) is not None for key in ("prepared", "stop", "thread", "turn"))
            or type(evidence) is not dict
            or set(evidence) != {"namespace_binding", "prepare_granted"}
            or evidence["prepare_granted"] is not False
        ):
            raise AuthorizationDenied(
                "Unprepared resource tombstone requires original admitted recovery without grants"
            )
        binding = evidence["namespace_binding"]
        if (
            type(binding) is not dict
            or set(binding) != {"request", "runner", "dispatch", "environment"}
            or binding["request"] != value["request"]
            or binding["runner"] != value["runner"]
            or binding["dispatch"] != value["request"]["dispatch"]
            or type(binding["environment"]) is not dict
            or binding["environment"].get("expected_generation")
            != digest({"dispatch": value["request"]["dispatch"], "runner": value["runner"]})[:32]
        ):
            raise DefinitionMismatch("Unprepared tombstone changed its original namespace")
        if value["runner"].get("kind") == "codex-coding-runner":
            from pathlib import Path

            dispatch = value["request"]["dispatch"]
            namespace = binding["environment"]
            resource_key = digest(
                {"scope": dispatch["scope"], "effect_key": dispatch["effect_key"]}
            )
            if (
                namespace.get("root", {}).get("path")
                != str(Path(value["runner"]["root"]["path"]) / resource_key)
                or namespace.get("docker_host") != value["runner"]["docker_host"]
                or namespace.get("profile") != value["runner"]["profile"]
                or namespace.get("retire_on_stop") is not True
            ):
                raise DefinitionMismatch(
                    "Unprepared tombstone replaced original namespace dependencies"
                )
        if "unprepared" in value and value["unprepared"] != evidence:
            raise DefinitionMismatch("Original unprepared resource tombstone changed")
        value["unprepared"] = copy.deepcopy(evidence)
    else:
        from .coding_execution_rules import adopt as adopt_receipt

        adopt_receipt(value, value["runner"], payload["kind"], payload["evidence"])
    state._emit(
        "coding_receipt_adopted",
        {
            "action_id": action["id"],
            "kind": payload["kind"],
            "evidence_digest": digest(payload["evidence"]),
        },
    )
    refresh(state)
    return {"action_id": action["id"], "recorded": True}


def admit_stop(state, proof):
    proof = ordinary(proof)
    if type(proof) is not dict or set(proof) != PROOF_FIELDS:
        raise DefinitionMismatch("Coding stop requires its original complete proof")
    from .temporal_tool_execution_state import record

    tool, action = record(state, proof, admission=True)
    value = action.get("delegated_execution")
    if value is None or not enabled(state.manifest):
        raise DefinitionMismatch("Coding stop cannot create native intent")
    # Validate immutable request/reservation through the same gate after recording
    # only this bounded read/stop identity; it never replaces the business claim.
    invocation = proof["invocation_id"]
    if invocation not in value["stop_invocations"]:
        if len(value["stop_invocations"]) >= 256:
            raise AuthorizationDenied("Original Coding stop admission capacity exhausted")
        value["stop_invocations"].append(invocation)
        try:
            _record(state, proof, recovery=True)
        except Exception:
            value["stop_invocations"].remove(invocation)
            raise
    else:
        _record(state, proof, recovery=True)
    value["stop_needed"] = True
    value.setdefault("cancel", {"code": "original_stop_requested"})
    state._emit("coding_stop_admitted", {"action_id": action["id"]})
    return {
        "action_id": action["id"],
        "admitted": True,
        "original_invocation_id": tool.get("invocation_id"),
        "request": copy.deepcopy(value["request"]),
        "runner": copy.deepcopy(value["runner"]),
    }


def request_stop(state, reason):
    for action in state.actions:
        value = action.get("delegated_execution")
        if value is not None:
            value.setdefault("cancel", copy.deepcopy(reason))
            if not stopped_action(state, action):
                value["stop_needed"], value["stop_retry"] = True, False


def stopped_action(state, action):
    value = action["delegated_execution"]
    return (
        value["fenced"] is True
        and value["pending_stop"] is False
        and state.tool_executions[action["id"]]["execution_stopped"] is True
    )


def stopped(state):
    return all(
        stopped_action(state, action) for action in state.actions if "delegated_execution" in action
    )


def refresh(state):
    if enabled(state.manifest) and state.state == "cancelling" and stopped(state):
        state.state = "cancelled"
        state._emit("coding_cancel_stopped", {"remote_stop_confirmed": True})


def unknown(state, action_id):
    action = next(a for a in state.actions if a["id"] == action_id)
    value = action.get("delegated_execution")
    if value is not None:
        value.update(
            native_unknown=True,
            effect_case="unknown",
            stop_needed=True,
            stop_retry=False,
            stop_query_observed=False,
        )


def next_stop(state):
    refresh(state)
    for action in state.actions:
        value = action.get("delegated_execution")
        if value is None or not value["stop_needed"] or value["stop_active"] or value["stop_retry"]:
            continue
        if (
            action["status"] == "outcome_unknown"
            and "result_candidate" in value
            and accepts_result(state, action, value["result_candidate"])
        ):
            state.accept_tool(
                action["id"],
                {
                    "ok": True,
                    "result": value["result_candidate"],
                    "source": "original-history-native-candidate",
                },
                reconciled=True,
            )
        if stopped_action(state, action) and (
            action["status"] != "outcome_unknown" or value["stop_query_observed"]
        ):
            value["stop_needed"] = False
            continue
        value["stop_active"] = True
        value["stop_sequence"] += 1
        state._emit("coding_stop_scheduled", {"action_id": action["id"]})
        return {
            "id": f"coding-stop:{action['id']}:{value['stop_sequence']}",
            "kind": "coding_stop",
            "coding_action_id": action["id"],
        }, copy.deepcopy(value["tool_request"])
    return None


def accept_stop(state, action_id, response):
    action = next(a for a in state.actions if a["id"] == action_id)
    value = action["delegated_execution"]
    value["stop_active"] = False
    if (
        response.get("ok") is True
        and "result" in response
        and accepts_result(state, action, response["result"])
    ):
        state.accept_tool(action_id, response, reconciled=True)
    # An Activity return/timeout proves neither a native fence nor actual owner
    # end. Only fixed receipt/end Updates can discharge those independent gates.
    value["stop_query_observed"] = response.get("ok") is True
    value["stop_retry"] = not stopped_action(state, action) or not value["stop_query_observed"]
    state._emit(
        "coding_stop_observed", {"action_id": action_id, "settled": not value["stop_retry"]}
    )
    refresh(state)


def retry_stops(state):
    for action in state.actions:
        if "delegated_execution" in action:
            value = action["delegated_execution"]
            value["stop_retry"] = False
            if action["status"] == "outcome_unknown":
                value["stop_query_observed"] = False
                value["stop_needed"] = True


def accepts_result(state, action, result):
    value = action.get("delegated_execution")
    if value is None:
        return True
    return (
        value["pending_stop"] is False
        and value["fenced"] is True
        and "result_candidate" in value
        and value["result_candidate"] == result
    )


def owner_stopped(state, payload):
    tool, action, value, payload = _record(state, payload, extra=("evidence",), recovery=True)
    evidence = payload["evidence"]
    if (
        payload["invocation_id"] not in value["stop_invocations"]
        or type(evidence) is not dict
        or set(evidence) != {"owner", "process_present", "native_fenced"}
        or "owner" not in value
        or evidence["owner"] != value["owner"]
        or value["owner"]["invocation_id"] != tool.get("invocation_id")
        or evidence["process_present"] is not False
        or evidence["native_fenced"] is not True
        or value["fenced"] is not True
        or value["pending_stop"] is not False
    ):
        raise AuthorizationDenied(
            "Original process death requires admitted stop and exact native fencing"
        )
    if not tool["execution_stopped"]:
        tool["execution_stopped"] = True
        tool["coding_owner_stop_proof"] = copy.deepcopy(payload)
        state._emit(
            "coding_original_owner_stopped",
            {"action_id": action["id"], "owner_digest": digest(value["owner"])},
        )
        from .temporal_tool_execution_state import refresh as refresh_tool

        refresh_tool(state)
        refresh(state)
    return {"action_id": action["id"], "recorded": True}


def requests(state):
    if (
        not enabled(state.manifest)
        or type(state.manifest.get("binding_protocol")) is not int
        or state.manifest["binding_protocol"] != 11
    ):
        raise DefinitionMismatch("Original Coding cleanup requests require explicit protocol 11")
    values = []
    for action in state.actions:
        native = action.get("delegated_execution")
        if native is None:
            continue
        tool = state.tool_executions.get(action["id"])
        request = native["tool_request"]
        if (
            tool is None
            or digest(request) != tool["request_digest"]
            or request["coding_request"] != native["request"]
            or request["scope"] != state.scope
            or request["run_id"] != state.run_id
            or request["release_digest"] != state.release_digest
        ):
            raise DefinitionMismatch(
                "Original cleanup request differs from its History Tool intent"
            )
        values.append(copy.deepcopy(request))
        if len(values) > 10000:
            raise DefinitionMismatch("Original Coding cleanup request allowance exceeded")
    return values


def validate_owner(evidence, invocation):
    if (
        type(evidence) is not dict
        or set(evidence) != {"version", "pid", "start", "deployment", "invocation_id"}
        or type(evidence["version"]) is not int
        or evidence["version"] != 1
        or type(evidence["pid"]) is not int
        or not 1 <= evidence["pid"] <= 2147483647
        or type(evidence["start"]) is not str
        or not evidence["start"].strip()
        or len(evidence["start"]) > 1024
        or type(evidence["deployment"]) is not str
        or len(evidence["deployment"]) != 64
        or set(evidence["deployment"]) - set("0123456789abcdef")
        or evidence["invocation_id"] != invocation
    ):
        raise DefinitionMismatch("Coding owner requires its original fixed process locator")


def admit_dispatch(state, payload):
    payload = ordinary(payload)
    if type(payload) is not dict or set(payload) != PROOF_FIELDS | {"owner"}:
        raise DefinitionMismatch("Coding admission requires atomic original process ownership")
    proof = {name: payload[name] for name in PROOF_FIELDS}
    tool, action, value, _ = _record(state, proof, admission=True)
    owner = payload["owner"]
    validate_owner(owner, payload["invocation_id"])
    if tool.get("invocation_id") == payload["invocation_id"] and value.get("owner", owner) != owner:
        raise DefinitionMismatch("Original Coding admission process owner cannot change")
    if tool.get("invocation_id") is None and "owner" in value:
        raise DefinitionMismatch("Coding process owner has no original atomic Tool claim")
    from .temporal_tool_execution_state import admit

    result = admit(state, proof)
    if result["claimed"] and "owner" not in value:
        value["owner"] = copy.deepcopy(owner)
        state._emit(
            "coding_owner_admitted", {"action_id": action["id"], "owner_digest": digest(owner)}
        )
    return result
