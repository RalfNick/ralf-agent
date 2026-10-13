"""Input journals and controls belong to the original Local Run transaction."""

import copy

from .errors import DefinitionMismatch, ValidationError
from .types import digest
from .user_input import (
    UserInputPolicy,
    answered_input,
    input_reply_payload,
    input_tool_policy,
    make_input_record,
    validate_input_record,
)

CLOSED = {"succeeded", "failed", "cancelled", "cancelling"}


def pause_state(states, *, fallback="outcome_unknown"):
    states = set(states)
    if states & {"waiting_reconciliation", "outcome_unknown"}:
        return "waiting_reconciliation" if "waiting_reconciliation" in states else "outcome_unknown"
    if "waiting_approval" in states:
        return "waiting_approval"
    if "waiting_input" in states:
        return "waiting_input"
    return fallback


def selected_policy(engine, definition):
    name = definition.get("input_policy")
    if name is None:
        return None
    policy = engine.user_input_policies.get(name)
    pin = engine._user_input_policy_pins.get(name)
    if type(policy) is not UserInputPolicy or pin is None or policy.identity != pin:
        raise DefinitionMismatch("The selected user input policy changed or is unavailable")
    return policy


def manifest_tools(engine, names):
    return {
        name: policy.identity
        for name in names
        if (policy := input_tool_policy(engine.tools.get(name))) is not None
    }


def _authority(engine, run):
    if hasattr(engine, "node_id"):
        owner = engine.parent._authorized(run["id"])
        return owner
    return run


def _tool_source(engine, run, action):
    original = copy.deepcopy(action)
    node = action["node"]
    if hasattr(engine, "node_id"):
        node = engine.node_id
        original["node"] = next(
            i
            for i, entry in enumerate(_authority(engine, run)["plan"]["nodes"])
            if entry["id"] == node
        )
    return {
        "kind": "tool",
        "action_id": action["id"],
        "node": node,
        "proposal_digest": digest(
            {k: original[k] for k in ("id", "node", "tool", "arguments", "digest", "call_id")}
        ),
    }


def validate_journal(engine, run):
    journal = run.get("input_requests")
    if journal is None:
        return
    if (
        type(journal) is not dict
        or len(journal) > 32
        or run["manifest"].get("user_input_protocol") != 1
    ):
        raise DefinitionMismatch("Input journal lacks its original protocol")
    owner = _authority(engine, run)
    ordinals = []
    for key, value in journal.items():
        try:
            record = validate_input_record(value)
            request = record["request"]
            ordinal = request["ordinal"]
            ordinals.append(ordinal)
            if request["source"]["kind"] == "tool":
                action = next(
                    a for a in run["actions"] if a["id"] == request["source"]["action_id"]
                )
                source = _tool_source(engine, run, action)
                configured = (
                    engine._step_manifest(run, action["node"])
                    .get("user_input_tools", {})
                    .get(action["tool"])
                )
                if configured is None:
                    raise DefinitionMismatch("Input tool lost its selected original policy")
                policy = UserInputPolicy.from_dict(configured)
                if action.get("input_pending_id") != key or action["arguments"] != {
                    "prompt": request["prompt"]
                }:
                    raise DefinitionMismatch("Input tool changed its original pending target")
                if record["state"] == "pending" and action["status"] != "waiting_input":
                    raise DefinitionMismatch("Pending input tool is not waiting")
                if record["state"] == "answered" and (
                    action["status"] != "completed"
                    or action.get("result") != record["value"]
                    or action.get("receipt") != _receipt(record)
                ):
                    raise DefinitionMismatch(
                        "Input reply differs from original committed tool evidence"
                    )
            else:
                source = request["source"]
                registration = run["manifest"].get("user_input_policy")
                if registration is None:
                    raise DefinitionMismatch("Planner input lost its selected policy")
                policy = UserInputPolicy.from_dict(registration["policy"])
                revisions = [
                    r
                    for r in run["orchestration"]["revisions"]
                    if r["revision"] == source["revision"]
                ]
                if (
                    len(revisions) != 1
                    or digest(revisions[0]["proposal"]) != source["proposal_digest"]
                ):
                    raise DefinitionMismatch("Planner question lost its original conclusion")
            expected = make_input_record(
                run_id=owner["id"],
                release_digest=owner["release_digest"],
                scope=owner["scope"],
                source=source,
                prompt=request["prompt"],
                policy=policy,
                ordinal=ordinal,
            )["request"]
            if key != request["pending_id"] or expected != request:
                raise DefinitionMismatch("Input request differs from its original owner/source")
        except (KeyError, TypeError, StopIteration, ValidationError) as exc:
            raise DefinitionMismatch("Input journal lost its original bounded evidence") from exc
    if sorted(ordinals) != list(range(1, len(journal) + 1)):
        raise DefinitionMismatch("Input journal changed its original request sequence")


def _receipt(record):
    request = record["request"]
    return {
        "source": "user-input",
        "pending_id": request["pending_id"],
        "target_digest": request["target_digest"],
        "command_id": record["command_id"],
        "reply_digest": record["reply_digest"],
    }


def own_pending(engine, run):
    validate_journal(engine, run)
    return any(r["state"] == "pending" for r in run.get("input_requests", {}).values())


def request_tool(engine, run_id, action_id, policy):
    with engine.store.transaction():
        run = engine._authorized(run_id)
        if run["state"] in CLOSED:
            return True
        validate_journal(engine, run)
        action = next(a for a in run["actions"] if a["id"] == action_id)
        if action.get("input_pending_id") is not None:
            return False
        journal = run.setdefault("input_requests", {})
        if len(journal) >= policy.max_requests:
            raise ValidationError("User input request limit reached")
        owner = _authority(engine, run)
        record = make_input_record(
            run_id=owner["id"],
            release_digest=owner["release_digest"],
            scope=owner["scope"],
            source=_tool_source(engine, run, action),
            prompt=action["arguments"]["prompt"],
            policy=policy,
            ordinal=len(journal) + 1,
        )
        pending_id = record["request"]["pending_id"]
        journal[pending_id] = record
        action["input_pending_id"], action["status"] = pending_id, "waiting_input"
        run["state"] = "waiting_input"
        engine._commit(run, "input_requested", {"pending_id": pending_id})
        return False


def request_planner(engine, run, proposal):
    policy = selected_policy(engine, run["definition"])
    if policy is None or proposal["status"] != "needs_input":
        return False
    state = run["orchestration"]
    if state["revision"] + 1 >= run["definition"]["max_revisions"]:
        from .orchestration import PlanRevisionLimit

        raise PlanRevisionLimit("No planning revision remains for user input continuation")
    journal = run.setdefault("input_requests", {})
    if len(journal) >= policy.max_requests:
        raise ValidationError("User input request limit reached")
    record = make_input_record(
        run_id=run["id"],
        release_digest=run["release_digest"],
        scope=run["scope"],
        source={
            "kind": "planner",
            "revision": state["revision"],
            "proposal_digest": digest(proposal),
        },
        prompt=proposal["reason"],
        policy=policy,
        ordinal=len(journal) + 1,
    )
    journal[record["request"]["pending_id"]] = record
    state["stage"], run["state"] = "waiting_input", "waiting_input"
    engine._commit(run, "input_requested", {"pending_id": record["request"]["pending_id"]})
    return True


def retire(run):
    for record in run.get("input_requests", {}).values():
        if record["state"] == "pending":
            record["state"] = "cancelled"
    for state in run.get("workflow", {}).get("nodes", {}).values():
        if "execution" in state:
            retire(state["execution"])


def _target(engine, run, pending_id):
    if pending_id in run.get("input_requests", {}):
        return engine, run
    if run.get("plan", {}).get("schema_version") == 3:
        from .node_execution import NodeEngine

        for node_id, state in run["workflow"]["nodes"].items():
            if pending_id in state.get("execution", {}).get("input_requests", {}):
                view = NodeEngine(engine, run["id"], node_id)
                return view, view._authorized(run["id"])
    return engine, run


def send_input(
    engine, run_id, pending_id, target_digest, value, command_id, expected_state_revision
):
    engine._ensure_open()
    engine._authorized(run_id)
    payload = input_reply_payload(
        run_id, pending_id, target_digest, value, expected_state_revision=expected_state_revision
    )

    def apply():
        run = engine._authorized(run_id)
        if run["state"] in CLOSED:
            return {"rejected": True, "reason": "target_closed"}
        if expected_state_revision is not None and run["revision"] != expected_state_revision:
            return {"rejected": True, "reason": "version_conflict"}
        view, owner = _target(engine, run, pending_id)
        view._check_release(owner)
        record = owner.get("input_requests", {}).get(pending_id)
        if (
            record is None
            or record["state"] != "pending"
            or record["request"]["target_digest"] != target_digest
        ):
            return {"rejected": True, "reason": "stale_pending_target"}
        try:
            answered = answered_input(record, payload["value"], command_id)
        except ValidationError:
            return {"rejected": True, "reason": "invalid_input"}
        source = record["request"]["source"]
        owner["input_requests"][pending_id] = answered
        if source["kind"] == "tool":
            action = next(a for a in owner["actions"] if a["id"] == source["action_id"])
            view._tool_result(owner, action, answered["value"], _receipt(answered))
            if owner.get("plan", {}).get("schema_version") != 3 and owner.get("workflow"):
                owner["workflow"]["nodes"][owner["workflow"]["current"]]["state"] = "running"
        else:
            state = owner["orchestration"]
            state.update(
                revision=state["revision"] + 1, proposal=None, request=None, stage="select"
            )
            state.pop("verification_feedback", None)
        owner["state"] = "running"
        view._commit(
            owner,
            "input_answered",
            {"pending_id": pending_id, "reply_digest": answered["reply_digest"]},
        )
        return {"state_revision": owner["revision"], "pending_id": pending_id}

    return engine.store.command(engine.scope, command_id, "send_input", payload, run_id, apply)


def planning_clarifications(engine, run):
    """Only the planner's original questions consume its clarification allowance."""
    validate_journal(engine, run)
    return [
        copy.deepcopy(record)
        for record in sorted(
            run.get("input_requests", {}).values(), key=lambda r: r["request"]["ordinal"]
        )
        if record["state"] == "answered" and record["request"]["source"]["kind"] == "planner"
    ]


def answered_lineage(engine, run):
    result, seen = [], set()

    def visit(owner, view):
        if owner["id"] in seen or len(seen) >= 4096:
            raise DefinitionMismatch("Input lineage exceeds original bounded ownership")
        seen.add(owner["id"])
        validate_journal(view, owner)
        result.extend(
            copy.deepcopy(record)
            for record in sorted(
                owner.get("input_requests", {}).values(), key=lambda r: r["request"]["ordinal"]
            )
            if record["state"] == "answered"
        )
        if owner.get("plan", {}).get("schema_version") == 3:
            from .node_execution import NodeEngine

            for node_id, state in owner["workflow"]["nodes"].items():
                if "execution" in state:
                    node_view = NodeEngine(view, owner["id"], node_id)
                    frame = node_view._authorized(owner["id"])
                    validate_journal(node_view, frame)
                    result.extend(
                        copy.deepcopy(record)
                        for record in sorted(
                            frame.get("input_requests", {}).values(),
                            key=lambda r: r["request"]["ordinal"],
                        )
                        if record["state"] == "answered"
                    )
        for call in owner.get("orchestration", {}).get("children", []):
            child = engine._authorized(call["run_id"])
            if (
                child.get("parent_id") != owner["id"]
                or child.get("call_id") != call["id"]
                or child["scope"] != run["scope"]
            ):
                raise DefinitionMismatch("Input lineage lost original child ownership")
            visit(child, engine)

    visit(run, engine)
    return result
