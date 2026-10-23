"""Deterministic memory rules; only the original Workflow persists this state."""

from .errors import DefinitionMismatch, ValidationError
from .memory_extraction import FactProposal, MemoryAdmissionPolicy, source_value
from .model_evidence import settlement_usage
from .temporal_state import TERMINAL, detached
from .types import digest


def prepare(state, action, result):
    registration = state.step_manifest.get("managed_memory")
    if registration is None:
        return False
    source = {
        "run_id": state.run_id,
        "node": state.node,
        "action_id": action["id"],
        "response_digest": digest(action["response"]),
        "result": detached(result),
        "scope": detached(state.scope),
        "release_digest": state.release_digest,
    }
    stage = {
        "node": state.node,
        "source": source,
        "policy": detached(registration["policy"]),
        "step_bindings": state.step_bindings,
        "status": "preparing",
        "phase": "plan",
        "facts": [],
        "index": 0,
        "operations": [],
    }
    state.memory_stages[str(state.node)] = stage
    state.pending_completion = str(state.node)
    action["memory_stage"] = {"source_digest": digest(source), "required": True}
    state._emit("memory_source_recorded", {"node": state.node, "source_digest": digest(source)})
    return True


def _finish(state, stage, status="completed", code=None):
    stage["status"], stage["phase"] = status, None
    if code:
        stage["error"] = {"code": code}
    state._emit("memory_stage_finished", {"node": stage["node"], "status": status})
    if state.pending_completion == str(stage["node"]):
        state.pending_completion = None
        if state.state not in TERMINAL:
            state.complete_node(stage["source"]["result"])


def _unknown(state, action):
    action["status"] = "outcome_unknown"
    if action["attempts"]:
        action["attempts"][0]["status"] = "unknown"
        state.reservations[action["attempts"][0]["id"]]["status"] = "unknown"
    state.remote_uncertain = True


def _request(state, stage, action):
    result = {
        "runtime_manifest": detached(state.manifest),
        "scope": detached(state.scope),
        "run_id": state.run_id,
        "release_digest": state.release_digest,
        "action_id": action["id"],
        "phase": action["phase"],
        "source": detached(stage["source"]),
        "policy": detached(stage["policy"]),
        "step_bindings": detached(stage["step_bindings"]),
    }
    if action["phase"] in {"read", "memory-write", "verify"}:
        result["fact"] = detached(stage["facts"][stage["index"]])
    if action["phase"] == "select":
        result["selection_request"] = detached(stage["selection_request"])
    if action["phase"] == "adopt":
        result["received_response"] = detached(stage.get("received_response"))
    return result


def next_stage(state):
    key = state.pending_completion
    if key is None and state.memory_recovery:
        key = state.memory_recovery.pop(0)
    if key is None:
        return None
    stage = state.memory_stages[key]
    if stage["phase"] is None:
        unresolved = [i for i, f in enumerate(stage["facts"]) if f["status"] == "outcome_unknown"]
        if not unresolved:
            return None
        stage["phase"], stage["index"] = "verify", unresolved[0]
    phase = stage["phase"]
    if state.state in TERMINAL and phase not in {"verify"}:
        _finish(state, stage, "closed")
        return None
    if phase in {"select", "memory-write"} and state.budget["remaining"] < 1:
        _finish(state, stage, "failed", "budget_exceeded")
        return None
    action = {
        "id": f"{state.run_id}:memory:{stage['node']}:{len(stage['operations'])}",
        "kind": "managed_memory",
        "node": stage["node"],
        "phase": phase,
        "stage_key": key,
        "status": "executing",
        "attempts": [],
    }
    state.actions.append(action)
    stage["operations"].append(action["id"])
    if phase in {"select", "memory-write"}:
        state._reserve(action, 1)
    else:
        state.active_action = action["id"]
    if phase == "memory-write":
        fact = stage["facts"][stage["index"]]
        if fact["status"] != "prepared":
            raise DefinitionMismatch("Memory CAS already dispatched")
        fact.update(status="writing", write_action=action["id"])
    request = _request(state, stage, action)
    action["request_digest"] = digest(request)
    state._emit(
        "memory_intent_recorded",
        {"action_id": action["id"], "phase": phase, "request_digest": digest(request)},
    )
    return action, request


def _validate_facts(stage, values):
    config, source = stage["policy"]["admission"], stage["source"]
    admission = MemoryAdmissionPolicy(
        **{k: config[k] for k in ("fields", "max_facts", "max_value_chars", "expires_at")}
    )
    if type(values) is not list or len(values) > config["max_facts"]:
        raise ValidationError("Invalid adopted memory proposals")
    seen = set()
    for fact in values:
        value = fact["value"]
        name = value["key"]
        if name in seen or name not in config["fields"]:
            raise ValidationError("Invalid adopted memory keys")
        seen.add(name)
        proposal = admission.validate(
            FactProposal(name, value["value"], value["source_path"]), source
        )
        p = proposal.to_dict()
        expected = {
            "key": "auto:" + digest([source["run_id"], source["node"], name]),
            "value": {
                "key": name,
                "value": source_value(source, p["source_path"]),
                "source_path": p["source_path"],
                "source_run_id": source["run_id"],
                "source_node": source["node"],
                "source_digest": digest(source),
                "release_digest": source["release_digest"],
                "trust": "completed-result-observation",
            },
            "expires_at": config["expires_at"],
            "status": "prepared",
        }
        if fact != expected:
            raise DefinitionMismatch("Memory proposal lost original source/target intent")


def accept_stage(state, action_id, response):
    action = next(a for a in state.actions if a["id"] == action_id)
    stage, phase = state.memory_stages[action["stage_key"]], action["phase"]
    action.update(
        status="completed" if response.get("ok") else "failed", response=detached(response)
    )
    state.active_action = None
    if phase == "select":
        received = response.get("received_response")
        if received is not None:
            stage["received_response"] = detached(received)
            state._settle(action, settlement_usage(received.get("usage")))
            state._emit(
                "memory_selection_response_recorded",
                {"action_id": action_id, "response_digest": digest(received)},
            )
        elif response.get("dispatched", False):
            _unknown(state, action)
        else:
            state._settle(action, undispatched=True)
    if phase == "memory-write":
        fact = stage["facts"][stage["index"]]
        if response.get("dispatched", True):
            fact["status"] = "outcome_unknown"
            if response.get("execution_uncertain"):
                _unknown(state, action)
            else:
                state.reservations[action["attempts"][0]["id"]]["status"] = "unknown"
        else:
            state._settle(action, undispatched=True)
            fact["status"] = "skipped"
        stage["phase"] = "verify"
        if state.state in TERMINAL:
            _finish(state, stage, "closed")
        return
    if state.state in TERMINAL and phase != "verify":
        _finish(state, stage, "closed")
        return
    if not response.get("ok"):
        _finish(
            state,
            stage,
            "outcome_unknown" if response.get("dispatched") else "failed",
            response.get("code", "memory_failed"),
        )
        return
    try:
        if phase == "plan":
            if response.get("source_digest") != digest(stage["source"]):
                raise DefinitionMismatch("Memory plan lost original source")
            if "selection" in stage["policy"]:
                stage["selection_request"], stage["phase"] = (
                    detached(response["selection_request"]),
                    "select",
                )
            else:
                _validate_facts(stage, response["facts"])
                stage["facts"], stage["phase"] = detached(response["facts"]), "read"
        elif phase == "select":
            stage["phase"] = "adopt"
        elif phase == "adopt":
            _validate_facts(stage, response["facts"])
            stage["facts"], stage["phase"] = detached(response["facts"]), "read"
        elif phase in {"read", "verify"}:
            fact = stage["facts"][stage["index"]]
            if response["found"]:
                if response.get("fact") != {
                    k: detached(fact[k]) for k in ("key", "value", "expires_at")
                }:
                    raise DefinitionMismatch("Memory receipt differs from original intent")
                fact.update(status="completed", receipt=detached(response))
                if "write_action" in fact:
                    write = next(a for a in state.actions if a["id"] == fact["write_action"])
                    state._settle(write)
                state._emit("memory_fact_receipt_recorded", {"key": fact["key"]})
                stage["index"] += 1
                stage["phase"] = "read" if state.state not in TERMINAL else "verify"
            elif phase == "read" and fact["status"] == "prepared":
                stage["phase"] = "memory-write"
            else:
                _finish(state, stage, "outcome_unknown", "memory_fact_unverified")
                return
        if (
            stage["facts"] == []
            and stage["phase"] == "read"
            or stage["index"] >= len(stage["facts"])
            and phase in {"read", "verify"}
        ):
            _finish(state, stage)
        elif state.state in TERMINAL and stage["phase"] == "verify":
            remaining = [
                i for i, f in enumerate(stage["facts"]) if f["status"] == "outcome_unknown"
            ]
            if remaining:
                stage["index"] = remaining[0]
                state.memory_recovery.insert(0, action["stage_key"])
            else:
                _finish(state, stage)
    except (ValidationError, DefinitionMismatch, KeyError, TypeError) as exc:
        _finish(state, stage, "failed", getattr(exc, "code", "validation_error"))


def request_recovery(state):
    for key, stage in state.memory_stages.items():
        if (
            any(f["status"] == "outcome_unknown" for f in stage["facts"])
            and key not in state.memory_recovery
        ):
            state.memory_recovery.append(key)
