"""Pure registration/evidence checks for original History decision adoption."""

from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest


def validate_protocol(manifest):
    records = manifest.get("binding_catalog", {}).get("records", {}).values()
    selected = [r for r in records if r.get("role") == "decision_policy"]
    if (
        not selected
        and "decision_protocol" not in manifest
        and "decision_registration" not in manifest
    ):
        return
    if (
        type(manifest.get("decision_protocol")) is not int
        or manifest["decision_protocol"] != 1
        or manifest.get("kernel") != "temporal-3"
    ):
        raise DefinitionMismatch("Unsupported Temporal DecisionPolicy protocol")
    pairs = [(manifest.get("decision_registration"), manifest.get("harness"))] + [
        (
            r.get("configuration", {}).get("decision_registration"),
            r.get("configuration", {}).get("harness"),
        )
        for r in selected
    ]
    for registration, identity in pairs:
        if (
            type(registration) is not dict
            or set(registration) != {"identity", "prepare_digest", "propose_digest"}
            or type(registration.get("identity")) is not dict
            or not registration["identity"]
            or registration["identity"] != identity
            or any(
                type(registration.get(name)) is not str
                or len(registration[name]) != 64
                or any(c not in "0123456789abcdef" for c in registration[name])
                for name in ("prepare_digest", "propose_digest")
            )
        ):
            raise ValidationError("Invalid Temporal DecisionPolicy registration")


def valid_adoption(state, action, response):
    """Return data, so the actual Workflow raises its own sandbox-local error."""
    try:
        canonical(response)
        evidence = response["decision_evidence"]
        if (
            type(response["model_evidence_version"]) is not int
            or response["model_evidence_version"] != 2
            or type(response["ok"]) is not bool
            or type(evidence) is not dict
            or set(evidence)
            != {
                "registration",
                "request_digest",
                "prepared_request",
                "received_response_digest",
                "proposal_digest",
            }
            or evidence["registration"] != state.step_manifest["decision_registration"]
            or evidence["request_digest"] != action["dispatch_request_digest"]
            or evidence["received_response_digest"] != digest(response["received_response"])
            or evidence["proposal_digest"]
            != digest({"output": response["output"], "tool_calls": response["tool_calls"]})
        ):
            return False
        prepared = evidence["prepared_request"]
        if type(prepared) is not dict or set(prepared) != {"messages", "tools"}:
            return False
        messages = prepared["messages"]
        if (
            type(messages) is not list
            or not messages
            or any(type(m) is not dict for m in messages)
            or len(canonical(messages)) > state.step["max_context_chars"]
        ):
            return False
        protect_prepared_history(state, action, messages)
        tools = prepared["tools"]
        if type(tools) is not list:
            return False
        values = [canonical(t) for t in tools]
        authorized = {
            canonical(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": state.manifest["tools"][name]["description"],
                        "parameters": state.manifest["tools"][name]["input_schema"],
                    },
                }
            )
            for name in state.step["tools"]
        }
        return len(set(values)) == len(values) and set(values) <= authorized
    except (KeyError, TypeError, ValueError, ValidationError):
        return False


def tool_defaults_registration(tools):
    """Publish native typed defaults only for the explicit continuation release."""
    import json

    from .tool_functions import TypedFunctionHandler

    return {
        name: {
            "implementation_digest": registration.implementation_digest,
            "defaults": json.loads(registration.handler._defaults_json),
        }
        for name, registration in sorted(tools._tools.items())
        if type(registration.handler) is TypedFunctionHandler
    }


def validate_continuation_protocol(manifest):
    """Joint 6/7 retain original feature markers without implicitly enabling them."""
    from types import SimpleNamespace

    from jsonschema import Draft202012Validator

    from .model_continuation import provider_continuation_identity

    fields = {"model_continuation_protocol", "provider_continuations", "continuation_tool_defaults"}
    if manifest.get("binding_protocol") not in (6, 7, 8) and not fields & set(manifest):
        return
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"]
        not in (6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)
        or type(manifest.get("model_continuation_protocol")) is not int
        or manifest["model_continuation_protocol"] != 1
        or manifest.get("dispatch_admission") != "history-1"
        or manifest.get("decision_protocol") != 1
        or "decision_registration" not in manifest
        or type(manifest.get("provider_continuations")) is not dict
        or set(manifest["provider_continuations"]) != set(manifest.get("providers", {}))
        or type(manifest.get("continuation_tool_defaults")) is not dict
        or not set(manifest["continuation_tool_defaults"]) <= set(manifest.get("tools", {}))
    ):
        raise DefinitionMismatch("Unsupported original model continuation protocol")
    for identity in manifest["provider_continuations"].values():
        try:
            provider_continuation_identity(SimpleNamespace(continuation_identity=identity))
        except ValidationError:
            raise DefinitionMismatch("Invalid pinned model continuation owner") from None
    for name, value in manifest["continuation_tool_defaults"].items():
        tool = manifest["tools"][name]
        schema = tool["input_schema"]
        if (
            type(value) is not dict
            or set(value) != {"implementation_digest", "defaults"}
            or value["implementation_digest"] != tool.get("implementation_digest")
            or type(value["defaults"]) is not dict
            or not set(value["defaults"]) <= set(schema.get("properties", {}))
            or set(value["defaults"]) & set(schema.get("required", []))
        ):
            raise DefinitionMismatch("Continuation defaults differ from their original tool")
        from .responses_format import LOCAL_SCHEMA_REGISTRY
        from .temporal_state import validate_schema_references

        validate_schema_references(schema)
        validator = Draft202012Validator(schema, registry=LOCAL_SCHEMA_REGISTRY)
        for parameter, default in value["defaults"].items():
            if not validator.evolve(schema=schema["properties"][parameter]).is_valid(default):
                raise DefinitionMismatch("Continuation default differs from parameter Schema")
        canonical(value)


def continuation_adoption(state, response, received):
    """History validates the raw decision and derives the exact effective Action args."""
    from .harness import DecisionProposal
    from .model_continuation import validate_continuation
    from .types import ToolCall

    enabled = state.manifest.get("model_continuation_protocol") == 1
    if received is None:
        if enabled:
            raise ValidationError("Model continuation requires completed original evidence")
        return None
    if "continuation" not in received:
        if "continuation_proposal" in response:
            raise ValidationError("Continuation proposal lacks original continuation evidence")
        return None
    raw = response.get("continuation_proposal")
    if (
        type(raw) is not dict
        or set(raw) != {"output", "tool_calls"}
        or type(raw["tool_calls"]) is not list
    ):
        raise ValidationError("Continuation requires the original Harness proposal")
    try:
        proposal = DecisionProposal(
            raw["output"], tuple(ToolCall(**call) for call in raw["tool_calls"])
        )
    except (TypeError, KeyError):
        raise ValidationError("Continuation Harness proposal is malformed") from None
    continuation = validate_continuation(
        received,
        proposal,
        state.step_manifest.get("provider_continuations", {}).get(state.step["provider"]),
        enabled=enabled,
    )
    effective = []
    for call in raw["tool_calls"]:
        defaults = (
            state.manifest.get("continuation_tool_defaults", {})
            .get(call["name"], {})
            .get("defaults", {})
        )
        effective.append({**call, "arguments": {**defaults, **call["arguments"]}})
    if digest({"output": response["output"], "tool_calls": response["tool_calls"]}) != digest(
        {"output": raw["output"], "tool_calls": effective}
    ):
        raise ValidationError("Continuation tool Actions differ from original native defaults")
    return continuation


def _prepared_receipt(state, action, receipt):
    prepared = receipt.get("prepared_request")
    if (
        type(receipt.get("model_receipt_version")) is not int
        or receipt["model_receipt_version"] != 1
        or receipt.get("request_digest") != action["dispatch_request_digest"]
        or receipt.get("decision_registration") != state.step_manifest.get("decision_registration")
        or type(prepared) is not dict
        or set(prepared) != {"messages", "tools"}
        or type(prepared["messages"]) is not list
        or not prepared["messages"]
        or any(type(m) is not dict for m in prepared["messages"])
        or len(canonical(prepared["messages"])) > state.step["max_context_chars"]
        or type(prepared["tools"]) is not list
    ):
        raise ValidationError("Model receipt lost its original prepared request")
    protect_prepared_history(state, action, prepared["messages"])
    authorized = {
        canonical(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": state.manifest["tools"][name]["description"],
                    "parameters": state.manifest["tools"][name]["input_schema"],
                },
            }
        )
        for name in state.step["tools"]
    }
    tools = [canonical(t) for t in prepared["tools"]]
    if len(set(tools)) != len(tools) or not set(tools) <= authorized:
        raise ValidationError("Model receipt prepared tools exceed original grants")


def accept_receipt(state, action_id, receipt):
    from .harness import DecisionProposal
    from .model_continuation import decode_received_response, validate_continuation
    from .model_evidence import settlement_usage, validate_model_usage
    from .temporal_state import TERMINAL, detached

    action = next(a for a in state.actions if a["id"] == action_id)
    if "received_response" not in receipt:
        if receipt.get("ok") is False:
            state.accept_failure(action_id, receipt)
            return
        state._settle(action, {"usage": "unknown"})
        state._reject_model(action, "validation_error")
        return
    received = detached(receipt["received_response"])
    action.update(received_response=received, model_receipt=detached(receipt), status="received")
    state._settle(action, settlement_usage(received.get("usage")))
    state._emit("model_response_recorded", {"action_id": action_id})
    if state.state in TERMINAL:
        state._emit("late_model_evidence", {"action_id": action_id})
        return
    try:
        decoded = decode_received_response(received)
        validate_model_usage(received["usage"])
        if receipt.get("ok") is not True:
            state._reject_model(action, receipt.get("code", "validation_error"))
            return
        _prepared_receipt(state, action, receipt)
        validate_continuation(
            received,
            DecisionProposal(decoded.output, decoded.tool_calls),
            state.step_manifest["provider_continuations"].get(state.step["provider"]),
            enabled=True,
        )
        stage = {
            "id": action_id + ":adopt",
            "kind": "model_adoption",
            "node": action["node"],
            "model_action_id": action_id,
            "receipt_digest": digest(receipt),
            "status": "ready",
            "attempts": [],
        }
        state.actions.append(stage)
        state._emit(
            "model_adoption_intent_recorded",
            {"action_id": stage["id"], "model_action_id": action_id},
        )
    except ValidationError as exc:
        state._reject_model(action, exc.code)


def next_adoption(state):
    from .temporal_state import detached

    action = next(
        (a for a in state.actions if a["kind"] == "model_adoption" and a["status"] == "ready"), None
    )
    if action is None:
        return None
    original = next(a for a in state.actions if a["id"] == action["model_action_id"])
    request = original["dispatch_request"]
    action["status"] = "executing"
    state.active_action, state.state = action["id"], "running"
    envelope = {
        "runtime_manifest": detached(state.manifest),
        "scope": detached(state.scope),
        "run_id": state.run_id,
        "adoption_action_id": action["id"],
        "model_action_id": original["id"],
        "original_request": detached(request),
        "model_receipt": detached(original["model_receipt"]),
        "step_bindings": detached(request.get("step_bindings", {})),
    }
    action["request_digest"] = digest(envelope)
    return action, envelope


def accept_adoption(state, action_id, response):
    from .temporal_state import TERMINAL, detached

    adoption = next(
        a for a in state.actions if a["id"] == action_id and a["kind"] == "model_adoption"
    )
    model = next(a for a in state.actions if a["id"] == adoption["model_action_id"])
    state._settle(adoption)
    adoption["response"] = detached(response)
    adoption["status"] = "completed" if response.get("ok") is True else "failed"
    if state.state in TERMINAL:
        state._emit("late_model_adoption", {"action_id": action_id})
        return
    if response.get("ok") is not True:
        state._reject_model(model, response.get("code", "validation_error"))
        return
    if (
        type(response.get("model_adoption_version")) is not int
        or response["model_adoption_version"] != 1
        or response.get("model_action_id") != model["id"]
        or response.get("receipt_digest") != adoption["receipt_digest"]
        or digest(response.get("received_response")) != digest(model["received_response"])
    ):
        state._reject_model(model, "validation_error")
        return
    state._accept_model_decision(model["id"], response, already_received=True)


def validate_model_history_protocol(manifest):
    fields = {"model_history_protocol", "model_history"}
    records = [
        r
        for r in manifest.get("binding_catalog", {}).get("records", {}).values()
        if r.get("role") == "model_history"
    ]
    if (
        manifest.get("binding_protocol") not in (7, 8)
        and not fields & set(manifest)
        and not records
    ):
        return
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"]
        not in (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)
        or type(manifest.get("model_history_protocol")) is not int
        or manifest["model_history_protocol"] not in (1, 2)
        or (
            manifest["binding_protocol"]
            not in (9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)
            and (manifest["model_history_protocol"] == 2) != (manifest["binding_protocol"] == 8)
        )
        or type(manifest.get("model_continuation_protocol")) is not int
        or manifest["model_continuation_protocol"] != 1
    ):
        raise DefinitionMismatch("Unsupported original complete model history protocol")
    registrations = ([manifest["model_history"]] if "model_history" in manifest else []) + [
        r.get("configuration", {}).get("model_history") for r in records
    ]
    if not registrations:
        raise DefinitionMismatch("Model history lacks its originally registered policy")
    session_mode = False
    for registration in registrations:
        native = (
            type(registration) is dict
            and registration.get("identity", {}).get("scope") == "session"
        )
        session_mode |= native
        if (
            type(registration) is not dict
            or set(registration) != {"identity", "implementation"}
            or type(registration.get("identity")) is not dict
            or not registration["identity"]
            or type(registration["identity"].get("allow_tool_result_projection", False)) is not bool
            or type(registration.get("implementation")) is not dict
            or set(registration["implementation"])
            != (
                {"assemble", "validate", "assemble_frame", "validate_frame"}
                if native
                else {"assemble", "validate"}
            )
            or any(
                type(v) is not str or len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
                for v in registration["implementation"].values()
            )
            or len(canonical(registration).encode("utf-8")) > 65536
        ):
            raise DefinitionMismatch("Unsupported original complete model history registration")
    if session_mode != (manifest["model_history_protocol"] == 2):
        raise DefinitionMismatch(
            "Original history marker differs from its selected registered policy"
        )


def protect_prepared_history(state, action, messages):
    if state.step_manifest.get("model_history_protocol") == 2:
        from .session_model_history import validate_model_history_frame

        original = action.get("dispatch_request", {}).get("model_history_frame")
        validate_model_history_frame(
            original,
            messages,
            allow_tool_result_projection=state.step_manifest["model_history"]["identity"].get(
                "allow_tool_result_projection", False
            ),
        )
        return
    if state.step_manifest.get("model_history_protocol") != 1:
        return
    from .model_history import validate_model_history

    original = action.get("dispatch_request", {}).get("messages")
    validate_model_history(
        original,
        messages,
        allow_tool_result_projection=state.step_manifest["model_history"]["identity"].get(
            "allow_tool_result_projection", False
        ),
    )


def model_history_proposal(state, response):
    """Verify pre-default accepted calls before constructing native assistant history."""
    if state.step_manifest.get("model_history_protocol") not in (1, 2):
        return None
    from .harness import DecisionProposal
    from .types import ToolCall

    raw = response.get("history_proposal")
    if (
        type(raw) is not dict
        or set(raw) != {"output", "tool_calls"}
        or type(raw["tool_calls"]) is not list
    ):
        raise ValidationError("Complete history requires its original Harness proposal")
    try:
        DecisionProposal(raw["output"], tuple(ToolCall(**call) for call in raw["tool_calls"]))
    except (TypeError, KeyError):
        raise ValidationError("Complete history Harness proposal is malformed") from None
    effective = [
        {
            **call,
            "arguments": {
                **state.manifest.get("continuation_tool_defaults", {})
                .get(call["name"], {})
                .get("defaults", {}),
                **call["arguments"],
            },
        }
        for call in raw["tool_calls"]
    ]
    if digest({"output": response["output"], "tool_calls": response["tool_calls"]}) != digest(
        {"output": raw["output"], "tool_calls": effective}
    ):
        raise ValidationError("Complete history differs from original tool defaults")
    if "continuation_proposal" in response and response["continuation_proposal"] != raw:
        raise ValidationError("Complete history changed original continuation proposal")
    return raw
