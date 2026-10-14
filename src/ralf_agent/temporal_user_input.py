"""Pure original-History human input adoption; no external tool execution."""

import copy

from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest
from .user_input import (
    UserInputPolicy,
    answered_input,
    input_tool_policy,
    make_input_record,
    validate_input_record,
)


def registration(runtime):
    tools = {}
    for name, tool in runtime.tools._tools.items():
        policy = input_tool_policy(tool)
        if policy is not None:
            tools[name] = policy.to_dict()
    policies = {name: policy.to_dict() for name, policy in runtime.user_input_policies.items()}
    if not tools and not policies:
        return {}
    return {"user_input_protocol": 1, "user_input_tools": tools, "user_input_policies": policies}


def validate_protocol(manifest):
    fields = {"user_input_protocol", "user_input_tools", "user_input_policies"}
    if not fields & set(manifest) and manifest.get("binding_protocol") != 10:
        return
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] not in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)
        or type(manifest.get("user_input_protocol")) is not int
        or manifest["user_input_protocol"] != 1
        or manifest.get("dispatch_admission") != "history-1"
        or type(manifest.get("user_input_tools")) is not dict
        or type(manifest.get("user_input_policies")) is not dict
        or not (manifest["user_input_tools"] or manifest["user_input_policies"])
    ):
        raise DefinitionMismatch("Unsupported original Temporal user input protocol")
    for name, value in manifest["user_input_tools"].items():
        tool = manifest.get("tools", {}).get(name)
        if type(value) is not dict or tool is None:
            raise DefinitionMismatch("Input tool lacks its original fixed descriptor")
        policy = UserInputPolicy.from_dict(value)
        expected_schema = {
            "type": "object",
            "required": ["prompt"],
            "additionalProperties": False,
            "properties": {
                "prompt": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": policy.max_prompt_chars,
                    "pattern": r"\S",
                }
            },
        }
        if (
            tool.get("input_schema") != expected_schema
            or tool.get("config") != {"user_input": policy.to_dict()}
            or tool.get("cost") != 0
            or tool.get("effect") != "read_only"
            or tool.get("requires_approval") is not False
        ):
            raise DefinitionMismatch("Input tool differs from its original intrinsic descriptor")
    for name, value in manifest["user_input_policies"].items():
        if type(name) is not str or not name.strip() or len(name) > 256:
            raise ValidationError("Input policy requires a bounded registered name")
        UserInputPolicy.from_dict(value)


def initialize(state):
    if state.manifest.get("user_input_protocol") == 1:
        state.input_requests = {}
        state.planning_input_sources = {}


def records(state):
    journal = getattr(state, "input_requests", {})
    if type(journal) is not dict:
        raise DefinitionMismatch("Input journal requires original pending identities")
    values = [validate_input_record(value) for value in journal.values()]
    if any(key != value["request"]["pending_id"] for key, value in journal.items()):
        raise DefinitionMismatch("Input journal changed original pending identity")
    values.sort(key=lambda value: value["request"]["ordinal"])
    if any(
        action.get("input_pending_id") not in journal
        for action in state.actions
        if "input_pending_id" in action
    ):
        raise DefinitionMismatch("Original intrinsic Action lost its input journal")
    for ordinal, value in enumerate(values, 1):
        request = value["request"]
        if (
            request["owner"]
            != {
                "run_id": state.run_id,
                "release_digest": state.release_digest,
                "scope": state.scope,
            }
            or request["ordinal"] != ordinal
        ):
            raise DefinitionMismatch("Input request changed its original History owner")
        source = request["source"]
        if source["kind"] == "tool":
            action = next((a for a in state.actions if a["id"] == source["action_id"]), None)
            if (
                action is None
                or source["node"] != action["node"]
                or source["proposal_digest"] != proposal_digest(action)
            ):
                raise DefinitionMismatch(
                    "Input request changed its original accepted tool proposal"
                )
            policy = tool_policy(state, action["tool"])
            original_prompt = action["arguments"]["prompt"]
            original_source = {
                "kind": "tool",
                "action_id": action["id"],
                "node": action["node"],
                "proposal_digest": proposal_digest(action),
            }
            if action.get("input_pending_id") != request["pending_id"] or action["attempts"]:
                raise DefinitionMismatch(
                    "Intrinsic input Action changed its original execution identity"
                )
            if value["state"] == "answered":
                receipt = {
                    "source": "user-input",
                    "pending_id": request["pending_id"],
                    "target_digest": request["target_digest"],
                    "command_id": value["command_id"],
                    "reply_digest": value["reply_digest"],
                }
                message = {
                    "role": "tool",
                    "tool_call_id": action["call_id"],
                    "content": canonical(value["value"]),
                }
                if (
                    action["status"] != "completed"
                    or action.get("result") != value["value"]
                    or action.get("receipt") != receipt
                    or "native_history_message" in action
                    and action["native_history_message"]["message"] != message
                ):
                    raise DefinitionMismatch(
                        "Input journal differs from its original native tool reply"
                    )
            elif action["status"] != (
                "waiting_input" if value["state"] == "pending" else "cancelled"
            ):
                raise DefinitionMismatch("Input journal differs from its original tool wait")
        else:
            name = state.definition.get("input_policy")
            policy = UserInputPolicy.from_dict(state.manifest["user_input_policies"][name])
            original = getattr(state, "planning_input_sources", {}).get(str(source["revision"]))
            if (
                original != {"status": "needs_input", "reason": request["prompt"]}
                or source["proposal_digest"] != digest(original)
                or source["revision"] > state.planning_revision
            ):
                raise DefinitionMismatch("Input request changed its original planner conclusion")
            original_prompt = original["reason"]
            original_source = {
                "kind": "planner",
                "revision": source["revision"],
                "proposal_digest": digest(original),
            }
        if policy is None:
            raise DefinitionMismatch("Input request lost its originally pinned policy")
        try:
            expected_request = make_input_record(
                run_id=state.run_id,
                release_digest=state.release_digest,
                scope=state.scope,
                source=original_source,
                prompt=original_prompt,
                policy=policy,
                ordinal=ordinal,
            )["request"]
        except ValidationError as exc:
            raise DefinitionMismatch("Input request exceeds its originally pinned policy") from exc
        if request != expected_request:
            raise DefinitionMismatch("Input journal changed its original request")
    return values


def observed_journal(proof, request):
    from types import SimpleNamespace

    holder = SimpleNamespace(
        run_id=proof["snapshot"]["run_id"],
        release_digest=proof["release_digest"],
        scope=proof["scope"],
        manifest=proof["manifest"],
        definition=request["definition"],
        actions=proof["snapshot"]["actions"],
        input_requests=proof.get("input_requests", {}),
        planning_input_sources=proof.get("planning_input_sources", {}),
        planning_revision=proof["workflow"].get("planning_revision", 0),
    )
    return {value["request"]["pending_id"]: value for value in records(holder)}


def pending(state):
    return [
        {"kind": "input", **value["request"]}
        for value in records(state)
        if value["state"] == "pending" and state.state not in {"succeeded", "failed", "cancelled"}
    ]


def clarifications(state):
    return [value for value in records(state) if value["state"] == "answered"]


def tool_policy(state, name):
    value = state.manifest.get("user_input_tools", {}).get(name)
    return None if value is None else UserInputPolicy.from_dict(value)


def validate_batch(state, proposals):
    if (
        any(tool_policy(state, value["tool"]) is not None for value in proposals)
        and len(proposals) != 1
    ):
        raise ValidationError("An input request must be the sole tool call")


def proposal_digest(action):
    return digest(
        {key: action[key] for key in ("id", "node", "tool", "arguments", "digest", "call_id")}
    )


def authorize_proposal(runtime, proposal, request):
    from .ports import is_sync_callable
    from .temporal_activities import _close_lazy
    from .types import Scope

    calls = [
        call
        for call in proposal.tool_calls
        if input_tool_policy(runtime.tools.get(call.name)) is not None
    ]
    if not calls:
        return {}
    if len(proposal.tool_calls) != 1:
        raise ValidationError("An input request must be the sole tool call")
    call = calls[0]
    tool = runtime.tools.get(call.name)
    authorization = {
        "request_digest": digest(request),
        "tool": call.name,
        "arguments_digest": digest(call.arguments),
        "tool_digest": digest(tool.manifest),
        "policy": copy.deepcopy(runtime.policy_identity),
    }
    if runtime.policy is not None:
        if not is_sync_callable(runtime.policy):
            raise ValidationError("Input authorization policy must execute synchronously")
        result = runtime.policy(
            Scope(**request["scope"]), copy.deepcopy(tool.spec), copy.deepcopy(call.arguments)
        )
        if result is not None:
            _close_lazy(result)
            raise ValidationError("Input authorization requires a completed None")
        runtime.validate_release(request["runtime_manifest"])
    return {"input_authorization": authorization}


def validate_authorization(state, action, response, proposals):
    if not any(tool_policy(state, value["tool"]) is not None for value in proposals):
        return
    proposal = proposals[0]
    expected = {
        "request_digest": action["dispatch_request_digest"],
        "tool": proposal["tool"],
        "arguments_digest": digest(proposal["arguments"]),
        "tool_digest": digest(state.manifest["tools"][proposal["tool"]]),
        "policy": state.manifest["policy"],
    }
    if response.get("input_authorization") != expected:
        raise DefinitionMismatch("Input proposal lacks its original authorization evidence")


def _request(state, source, prompt, policy):
    previous = records(state)
    if len(previous) >= policy.max_requests:
        raise ValidationError("User input request limit exhausted")
    record = make_input_record(
        run_id=state.run_id,
        release_digest=state.release_digest,
        scope=state.scope,
        source=source,
        prompt=prompt,
        policy=policy,
        ordinal=len(previous) + 1,
    )
    state.input_requests[record["request"]["pending_id"]] = record
    state.state = "waiting_input"
    state._emit(
        "input_requested",
        {
            "pending_id": record["request"]["pending_id"],
            "target_digest": record["request"]["target_digest"],
        },
    )
    return record


def adopt_tool(state, action):
    policy = tool_policy(state, action["tool"])
    if policy is None:
        return False
    record = _request(
        state,
        {
            "kind": "tool",
            "action_id": action["id"],
            "node": action["node"],
            "proposal_digest": proposal_digest(action),
        },
        action["arguments"]["prompt"],
        policy,
    )
    action.update(status="waiting_input", input_pending_id=record["request"]["pending_id"])
    return True


def adopt_planner(state, conclusion):
    name = state.definition.get("input_policy")
    if name is None or conclusion["status"] != "needs_input":
        return False
    if state.planning_revision + 1 >= state.definition["max_revisions"]:
        raise ValidationError("Planner input cannot exceed the original revision allowance")
    policy = UserInputPolicy.from_dict(state.manifest["user_input_policies"][name])
    if (
        state.stage == "waiting_input"
        or str(state.planning_revision) in state.planning_input_sources
    ):
        raise ValidationError("Original planner revision already owns its input request")
    state.planning_input_sources[str(state.planning_revision)] = conclusion
    _request(
        state,
        {
            "kind": "planner",
            "revision": state.planning_revision,
            "proposal_digest": digest(conclusion),
        },
        conclusion["reason"],
        policy,
    )
    state.planning_conclusion = conclusion
    state.stage = "waiting_input"
    return True


def close_pending(state):
    for value in getattr(state, "input_requests", {}).values():
        if value["state"] == "pending":
            value["state"] = "cancelled"
            source = value["request"]["source"]
            if source["kind"] == "tool":
                action = next(a for a in state.actions if a["id"] == source["action_id"])
                action["status"] = "cancelled"


def apply_reply(state, payload, command_id):
    from .temporal_state import detached

    values = records(state)
    if state.state in {"succeeded", "failed", "cancelled", "cancelling"}:
        return {"rejected": True, "reason": "target_closed"}
    record = next(
        (value for value in values if value["request"]["pending_id"] == payload["pending_id"]), None
    )
    if (
        record is None
        or record["state"] != "pending"
        or record["request"]["target_digest"] != payload["digest"]
    ):
        return {"rejected": True, "reason": "stale_pending_target"}
    if (
        "expected_state_revision" in payload
        and payload["expected_state_revision"] != state.revision
    ):
        return {"rejected": True, "reason": "version_conflict"}
    try:
        answered = answered_input(record, payload["value"], command_id)
    except ValidationError:
        return {"rejected": True, "reason": "invalid_input"}
    source = record["request"]["source"]
    if source["kind"] == "tool":
        action = next((a for a in state.actions if a["id"] == source["action_id"]), None)
        if (
            action is None
            or action["status"] != "waiting_input"
            or action.get("input_pending_id") != record["request"]["pending_id"]
            or action["node"] != state.node
        ):
            raise DefinitionMismatch("Input reply lost its original pending tool Action")
        action.update(
            status="completed",
            result=detached(answered["value"]),
            receipt={
                "source": "user-input",
                "pending_id": record["request"]["pending_id"],
                "target_digest": record["request"]["target_digest"],
                "command_id": command_id,
                "reply_digest": answered["reply_digest"],
            },
        )
        message = {
            "role": "tool",
            "tool_call_id": action["call_id"],
            "content": canonical(answered["value"]),
        }
        if state.step_manifest.get("model_history_protocol") == 2:
            action["native_history_message"] = {
                "order": len(state.messages),
                "message": detached(message),
            }
        state.messages.append(message)
    else:
        if state.stage != "waiting_input" or source["revision"] != state.planning_revision:
            raise DefinitionMismatch("Input reply changed original planner revision")
        state.planning_revision += 1
        state.stage, state.dag = "plan", None
        state.planning_conclusion = None
        state.verification_feedback = None
    state.input_requests[record["request"]["pending_id"]] = answered
    state.state, state.error = "running", None
    state._emit(
        "input_applied",
        {
            "pending_id": record["request"]["pending_id"],
            "command_id": command_id,
            "reply_digest": answered["reply_digest"],
        },
    )
    return {"state_revision": state.revision, "pending_id": record["request"]["pending_id"]}


def validate_command(state, payload):
    from .user_input import input_reply_payload

    expected = {"kind", "scope", "run_id", "pending_id", "digest", "value"}
    if "expected_state_revision" in payload:
        if type(payload["expected_state_revision"]) is not int:
            raise ValidationError("Input revision must be an ordinary nonnegative integer")
        expected.add("expected_state_revision")
    if set(payload) != expected or payload["run_id"] != state.run_id:
        raise ValidationError("Input command must target its original Run")
    input_reply_payload(
        payload["run_id"],
        payload["pending_id"],
        payload["digest"],
        payload["value"],
        expected_state_revision=payload.get("expected_state_revision"),
    )
