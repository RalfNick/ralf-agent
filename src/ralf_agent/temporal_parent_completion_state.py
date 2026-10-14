"""Original parent History freezes owned child receipts and adopts pure proposals."""

from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest

ACTIVITY = "ralf.temporal.parent_completion.v1"


def validate_protocol(manifest):
    registry = manifest.get("parent_completion_policies")
    if (
        registry is None
        and "parent_completion_protocol" not in manifest
        and manifest.get("binding_protocol") != 9
    ):
        return
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] not in (9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)
        or type(manifest.get("parent_completion_protocol")) is not int
        or manifest["parent_completion_protocol"] != 1
        or type(registry) is not dict
        or not registry
    ):
        raise DefinitionMismatch("Unsupported original parent completion protocol")
    for name, value in registry.items():
        if (
            type(name) is not str
            or not name.strip()
            or type(value) is not dict
            or set(value)
            != {
                "identity",
                "implementation_digest",
                "gate_registration",
                "stage_registration",
                "effective_agent_release",
            }
            or type(value["identity"]) is not dict
            or not value["identity"]
            or type(value["implementation_digest"]) is not str
            or len(value["implementation_digest"]) != 64
            or any(c not in "0123456789abcdef" for c in value["implementation_digest"])
            or type(value["gate_registration"]) is not dict
            or (value["stage_registration"] is None) != (value["effective_agent_release"] is None)
            or value["stage_registration"] is not None
            and (
                type(value["stage_registration"]) is not dict
                or type(value["effective_agent_release"]) is not dict
            )
            or len(canonical(value).encode("utf-8")) > 1_048_576
        ):
            raise DefinitionMismatch("Invalid original parent completion registration")


def initialize(state):
    name = state.definition.get("completion_policy")
    state.parent_completion_enabled = name is not None
    state.parent_completion_stages = {}
    state.parent_completion_pending = None
    state.verification_feedback = None
    state.planning_conclusion = None
    if name is not None and (
        state.kind not in {"dynamic", "team"}
        or state.manifest.get("parent_completion_protocol") != 1
        or name not in state.manifest.get("parent_completion_policies", {})
    ):
        raise DefinitionMismatch("Parent completion policy unavailable in original release")


def _actual_messages(action):
    receipt = action.get("model_receipt", {})
    response = action.get("response", {})
    prepared = receipt.get(
        "prepared_request", response.get("decision_evidence", {}).get("prepared_request")
    )
    if not isinstance(prepared, dict) or type(prepared.get("messages")) is not list:
        raise DefinitionMismatch("Parent source lacks actual prepared final model request")
    return prepared["messages"]


def _input_consumed(messages, input):
    content = input if isinstance(input, str) else canonical(input)
    return (
        type(messages) is list
        and len(messages) >= 2
        and messages[1] == {"role": "user", "content": content}
    )


def _current_messages(action):
    messages = _actual_messages(action)
    frame = action.get("dispatch_request", {}).get("model_history_frame")
    if frame is None:
        return messages
    turns = frame.get("turns")
    if type(turns) is not list or any(type(t.get("history")) is not list for t in turns):
        raise DefinitionMismatch("Final model lost original current-Turn frame")
    offset = 1 + sum(len(turn["history"]) - 1 for turn in turns)
    if offset >= len(messages):
        raise DefinitionMismatch("Final model lost original current-Turn input")
    return [messages[0], *messages[offset:]]


def _worker_path(definition, call):
    member = call["member"]
    if definition["kind"] == "graph":
        if not any(n["id"] == member for n in definition["nodes"]):
            raise DefinitionMismatch("Receipt names no originally declared graph node")
        return [member]
    if member not in definition["members"]:
        raise DefinitionMismatch("Receipt names no originally declared business member")
    return [member]


def _source_children(state):
    """Only current adopted nodes or Team business calls own completion evidence."""
    if state.kind == "dynamic":
        if state.planning_conclusion is not None or state.dag is None:
            return []
        keys = {n.get("call_id") for n in state.dag["nodes"].values()}
        return [c for c in state.children if c["id"] in keys]
    return [
        c
        for c in state.children
        if c.get("role", "worker") == "worker" and c["member"] not in {"@planner", "@verifier"}
    ]


def source(state, candidate):
    from .parent_completion import ParentCompletionRequest
    from .temporal_bindings import request_release_digest
    from .temporal_coding_composition_state import orchestration_enabled
    from .temporal_parent_state import child_run_id
    from .temporal_state import detached

    children, receipts, seen, input_replies = [], [], set(), []
    fixed_results = orchestration_enabled(state.manifest)
    policy = state.manifest["parent_completion_policies"][state.definition["completion_policy"]]

    def visit(
        call, definition, parent_id, prefix, depth=0, root_revision=None, owner_revision=None
    ):
        if (
            depth >= state.policy.max_depth
            or len(children) >= policy["identity"]["max_evidence_children"]
        ):
            raise ValidationError("Parent completion source child/depth bound exhausted")
        if call.get("role", "worker") != "worker" or call["member"] in {"@planner", "@verifier"}:
            return
        expected_command = "ralf-child:" + digest([state.scope, parent_id, call["id"]])
        if (
            call["command_id"] != expected_command
            or call["run_id"] != child_run_id(state.scope, expected_command)
            or call["run_id"] in seen
        ):
            raise DefinitionMismatch("Parent completion child lost original ownership")
        seen.add(call["run_id"])
        owner_revision = state.planning_revision if owner_revision is None else owner_revision
        internal_revision = call.get("planning_revision", 0)
        if (
            type(internal_revision) is not int
            or not 0 <= internal_revision <= owner_revision
            or call["id"] != f"{internal_revision}:{call['call_id']}"
        ):
            raise DefinitionMismatch("Child receipt changed original planning lineage")
        if root_revision is None:
            root_revision = call.get("planning_revision", state.planning_revision)
        snapshot, flow = call.get("snapshot", {}), call.get("observed_flow", {})
        if not (
            call.get("settled")
            and snapshot.get("state") == "succeeded"
            and flow.get("quiescent")
            and flow.get("remote_stop_confirmed")
            and not snapshot.get("pending")
            and not any(
                flow.get(name, False)
                for name in (
                    "evidence_ack_pending",
                    "reconciliation_pending",
                    "unknown_remote_execution",
                )
            )
        ):
            raise ValidationError("Parent source requires succeeded quiescent children")
        path = prefix + _worker_path(definition, call)
        run_id, release = call["run_id"], request_release_digest(call["request"], state.manifest)
        if call.get("observed_release_digest") != release:
            raise DefinitionMismatch("Parent source changed original observed child release")
        if state.manifest.get("user_input_protocol") == 1:
            from .temporal_user_input import observed_journal

            journal = observed_journal(
                {
                    "snapshot": snapshot,
                    "workflow": flow,
                    "scope": state.scope,
                    "manifest": state.manifest,
                    "release_digest": release,
                    "input_requests": call.get("input_requests", {}),
                    "planning_input_sources": call.get("planning_input_sources", {}),
                },
                call["request"],
            )
            input_replies.extend(
                value for value in journal.values() if value["state"] == "answered"
            )
        actions = snapshot["actions"]
        kind = call["request"]["definition"]["kind"]
        finals = [
            a
            for a in actions
            if a["kind"] == "model"
            and a["status"] == "completed"
            and not a.get("response", {}).get("tool_calls")
        ]
        final_models = []
        if kind in {"agent", "sequence"}:
            for node in range(len(call["request"]["definition"]["steps"])):
                models = [a for a in finals if a["node"] == node]
                if not models:
                    raise DefinitionMismatch("Parent source lacks original final model receipt")
                final = models[-1]
                messages = _actual_messages(final)
                node_input = (
                    call["input"]
                    if node == 0
                    else [a for a in finals if a["node"] == node - 1][-1]["response"]["output"]
                )
                model_path = path if kind == "agent" else path + ["steps", str(node)]
                final_models.append(
                    {
                        "member_path": model_path,
                        "action_id": final["id"],
                        "snapshot_digest": digest(messages),
                        "input_digest": digest(node_input),
                        "input_consumed": _input_consumed(_current_messages(final), node_input),
                    }
                )
        native = kind == "agent"
        final = final_models[-1] if native else None
        if fixed_results and "adopted_result" not in call:
            raise DefinitionMismatch("Parent source lacks original adopted business result")
        business_result = call["adopted_result"] if fixed_results else snapshot["result"]
        children.append(
            {
                "id": "child:" + digest([run_id, release]),
                "call_id": call["call_id"],
                "role": "worker",
                "member_path": path,
                "run_id": run_id,
                "release_digest": release,
                "state_revision": snapshot["state_revision"],
                "planning_revision": root_revision,
                "input": detached(call["input"]),
                "input_digest": digest(call["input"]),
                "input_consumed": final["input_consumed"] if final else None,
                "result": detached(business_result),
                "result_digest": digest(business_result),
                "final_action_id": final["action_id"] if final else None,
                "final_snapshot_digest": final["snapshot_digest"] if final else None,
                "final_models": final_models,
            }
        )
        for index, action in enumerate(actions):
            if action["kind"] != "tool" or action["status"] != "completed":
                continue
            if action["tool"] in state.manifest.get("user_input_tools", {}):
                continue
            consumed = []
            for model in final_models:
                target = next(a for a in actions if a["id"] == model["action_id"])
                messages = _current_messages(target)
                if actions.index(target) > index and any(
                    m.get("role") == "tool"
                    and m.get("tool_call_id") == action["call_id"]
                    and m.get("content") == canonical(action["result"])
                    for m in messages or []
                ):
                    consumed.append("model:" + digest([run_id, model["action_id"]]))
            receipts.append(
                {
                    "id": "tool:" + digest([run_id, action["id"]]),
                    "run_id": run_id,
                    "member_path": path
                    if kind == "agent"
                    else path + ["steps", str(action["node"])],
                    "action_id": action["id"],
                    "tool": action["tool"],
                    "arguments": detached(action["arguments"]),
                    "result": detached(action["result"]),
                    "receipt": detached(action["receipt"]),
                    "effect_key": action["effect_key"],
                    "consumed_by": consumed,
                }
            )
        if kind in {"graph", "dynamic", "team"}:
            nested = flow.get("children")
            if type(nested) is not list:
                raise DefinitionMismatch("Nested source lacks original child History evidence")
            if kind == "dynamic":
                if flow.get("dag") is None:
                    if type(snapshot["result"]) is not dict or snapshot["result"].get(
                        "status"
                    ) not in {"refused", "needs_input"}:
                        raise DefinitionMismatch("Nested dynamic source lacks its adopted plan")
                    nested = []
                else:
                    keys = {n.get("call_id") for n in flow["dag"]["nodes"].values()}
                    nested = [c for c in nested if c["id"] in keys]
            for child in nested:
                visit(
                    child,
                    call["request"]["definition"],
                    run_id,
                    path,
                    depth + 1,
                    root_revision,
                    flow.get("planning_revision", 0),
                )

    for call in _source_children(state):
        visit(call, state.definition, state.run_id, [])
    from .temporal_user_input import clarifications

    input_replies = [*clarifications(state), *input_replies]
    request = ParentCompletionRequest(
        parent_id=state.run_id,
        parent_kind=state.kind,
        scope=state.scope,
        release_digest=state.release_digest,
        revision=state.planning_revision,
        task=state.request["input"],
        plan=state.planning_conclusion
        if state.planning_conclusion is not None
        else state.dag["proposal"]
        if state.dag
        else None,
        candidate=detached(candidate),
        children=children,
        receipts=receipts,
        constraints={
            "remaining_steps": min(
                state.policy.max_children, state.definition.get("max_steps", 256)
            )
            - len(state.children),
            "remaining_revisions": max(
                0, state.definition.get("max_revisions", 1) - state.planning_revision - 1
            )
            if state.kind == "dynamic"
            else 0,
            "max_concurrency": state.max_concurrency,
            "verifier_budget": policy["identity"]["verifier_budget"],
            "parent_budget": state.budget,
        },
        **({"clarifications": input_replies} if input_replies else {}),
    ).to_dict()
    if (
        len(canonical(request).encode("utf-8")) > policy["identity"]["max_source_bytes"]
        or len(receipts) > policy["identity"]["max_receipts"]
    ):
        raise ValidationError("Parent completion source exceeds original finite bounds")
    return request


def _business_plan(state):
    from .temporal_state import detached

    return detached(
        {
            "plan_revision": state.plan_revision,
            "dag": state.dag,
            "planning_conclusion": state.planning_conclusion,
        }
    )


def _restore_root_session_budget(state, stage, budget):
    """Normalize only the original one-credit aggregate write after a real receipt."""
    from .temporal_session_save_state import _receipt

    root = state.session_stages.get("root")
    if root is None:
        raise DefinitionMismatch("Parent publication lost original root Session save stage")
    intent = root["intent"]
    if (
        stage.get("publication_intent_digest") != digest(intent)
        or root.get("source_kind") != "parent-aggregate"
        or root.get("status") != "completed"
        or root.get("execution_stopped") is not True
        or intent["run_id"] != state.run_id
        or intent["result"] != stage["source"]["candidate"]
        or intent["source_response_digest"] != digest(state.root_aggregate)
        or _receipt(root, root["received_inspection"])["receipt"] is None
    ):
        raise DefinitionMismatch("Parent publication lacks its exact stopped Session receipt")
    write = next(a for a in state.actions if a["id"] == root["write_action"])
    response = write["response"]
    if response.get("ok") is True:
        stopped_write = (
            response.get("execution_stopped") is True
            and type(response.get("revision")) is int
            and response["revision"] == intent["expected_revision"] + 1
        )
    else:
        # Original append replies may be lost. The original History admission,
        # validated handler-end proof and exact receipt still own that write.
        proof, grant = write.get("execution_end_proof"), write.get("dispatch_grant")
        stopped_write = (
            response.get("ok") is False
            and response.get("dispatched") is True
            and type(proof) is dict
            and proof
            == {
                "scope": state.scope,
                "action_id": write["id"],
                "request_digest": write["request_digest"],
                "release_digest": state.release_digest,
            }
            and type(grant) is dict
            and grant.get("allowed") is True
            and grant
            == {
                "run_id": state.run_id,
                "action_id": write["id"],
                "release_digest": state.release_digest,
                "allowed": True,
            }
            and any(
                event["kind"] == "session_execution_ended"
                and event["data"] == {"action_id": write["id"]}
                for event in state.event_log
            )
        )
    reservation_id = write["attempts"][0]["id"]
    reservation = state.reservations[reservation_id]
    allowance_id = state.root_write_allowance
    allowance = state.reservations[allowance_id]
    original = next(
        r
        for r in stage["source"]["constraints"]["parent_budget"]["reservations"]
        if r["id"] == allowance_id
    )
    if (
        write["kind"] != "managed_session"
        or write["phase"] != "session-write"
        or write["status"] != "completed"
        or not stopped_write
        or reservation
        != {"id": reservation_id, "amount": 1, "status": "settled", "actual": 1, "usage": {}}
        or allowance != {"id": allowance_id, "amount": 1, "status": "settled", "actual": 0}
        or original != {"id": allowance_id, "amount": 1, "status": "reserved"}
    ):
        raise DefinitionMismatch(
            "Parent Session accounting differs from original one-credit intent"
        )
    budget["reservations"] = [
        original if r["id"] == allowance_id else r
        for r in budget["reservations"]
        if r["id"] != reservation_id
    ]
    budget["spent"] -= 1
    budget["reserved"] += 1


def check_source(state, stage, candidate, *, publication=False):
    """Rebuild current original business evidence at each authority commit boundary."""
    from .temporal_bindings import request_release_digest

    frozen = stage["source"]
    recorded = next(
        e["data"]
        for e in state.event_log
        if e["kind"] == "parent_completion_source_recorded"
        and e["data"]["revision"] == frozen["revision"]
    )
    if (
        stage["source_digest"] != digest(frozen)
        or recorded["source_digest"] != stage["source_digest"]
        or candidate != frozen["candidate"]
        or request_release_digest(state.request, state.manifest) != frozen["release_digest"]
        or state.planning_revision != frozen["revision"]
        or _business_plan(state) != stage["business_plan"]
        or state.queue
        or not state.children_quiescent
        or state.remote_uncertain
        or state.dag is not None
        and any(n["state"] not in {"completed", "skipped"} for n in state.dag["nodes"].values())
    ):
        raise DefinitionMismatch("Parent completion original plan or quiescence changed")
    expected_ids = [*stage["original_child_ids"]]
    verifier = None
    if stage["child_key"] is not None:
        expected_ids.append(stage["child_key"])
        verifier = next(c for c in state.children if c["id"] == stage["child_key"])
        if (
            verifier.get("role") != "verifier"
            or verifier["state"] != "succeeded"
            or verifier["run_id"] != stage["child_run_id"]
            or verifier["input"] != stage["prepared_input"]
            or verifier["request"]["input"] != stage["prepared_input"]
            or type(verifier["spent"]) is not int
            or not 0 <= verifier["spent"] <= verifier["cap"]
            or verifier["cap"] != stage["registration"]["identity"]["verifier_budget"]
            or request_release_digest(verifier["request"], state.manifest)
            != stage["child_release_digest"]
        ):
            raise DefinitionMismatch("Parent completion changed its unique verifier accounting")
    if [c["id"] for c in state.children] != expected_ids:
        raise DefinitionMismatch("Parent completion gained unrelated child work")
    current = source(state, candidate)
    budget = current["constraints"]["parent_budget"]
    if verifier is not None:
        current["constraints"]["remaining_steps"] += 1
        budget["spent"] -= verifier["spent"]
        budget["remaining"] += verifier["spent"]
        budget["reservations"] = [r for r in budget["reservations"] if r["id"] != verifier["id"]]
    if publication and state.root_aggregate is not None:
        _restore_root_session_budget(state, stage, budget)
    prior = {c["id"]: c for c in frozen["children"]}
    for child in current["children"]:
        original = prior.get(child["id"])
        if original is not None and child["state_revision"] >= original["state_revision"]:
            child["state_revision"] = original["state_revision"]
    if current != frozen:
        raise DefinitionMismatch("Parent completion original business source changed")


def prepare(state, candidate):
    from .temporal_state import detached

    if not state.children_quiescent:
        raise ValidationError("Parent completion cannot bypass held child capacity")
    key = "r" + str(state.planning_revision)
    previous = state.parent_completion_stages.get(key)
    if previous is not None:
        if (
            previous["source_digest"] != digest(previous["source"])
            or previous["source"]["candidate"] != candidate
        ):
            raise DefinitionMismatch("Parent completion source changed at original revision")
        return
    frozen = source(state, candidate)
    stage = {
        "source": frozen,
        "source_digest": digest(frozen),
        "business_plan": _business_plan(state),
        "original_child_ids": [c["id"] for c in state.children],
        "registration": detached(
            state.manifest["parent_completion_policies"][state.definition["completion_policy"]]
        ),
        "status": "prepared",
        "gate_verdict": None,
        "prepared_input": None,
        "prepared_input_digest": None,
        "child_key": None,
        "child_run_id": None,
        "child_release_digest": None,
        "received_proposal": None,
        "adopted_verdict": None,
    }
    state.parent_completion_stages[key] = stage
    state.parent_completion_pending = key
    state.stage, state.state = "parent_completion", "running"
    state._emit(
        "parent_completion_source_recorded",
        {"revision": state.planning_revision, "source_digest": stage["source_digest"]},
    )


def next_operation(state):
    from .temporal_coding_composition_state import orchestration_enabled
    from .temporal_state import TERMINAL, detached

    key = state.parent_completion_pending
    if key is None or state.state in TERMINAL:
        return None
    if orchestration_enabled(state.manifest) and (
        not state.children_quiescent or getattr(state, "composition_stop_intent", None) is not None
    ):
        return None
    stage = state.parent_completion_stages[key]
    if stage["status"] not in {"prepared", "proposal_received"}:
        return None
    mode = "prepare" if stage["status"] == "prepared" else "interpret"
    if stage["source_digest"] != digest(stage["source"]):
        raise DefinitionMismatch("Frozen parent source drifted")
    action = {
        "id": state.run_id + ":parent-completion:" + key + ":" + mode,
        "kind": "parent_completion",
        "status": "executing",
        "mode": mode,
    }
    request = {
        "version": 1,
        "mode": mode,
        "policy": state.definition["completion_policy"],
        "runtime_manifest": detached(state.manifest),
        "scope": state.scope,
        "run_id": state.run_id,
        "release_digest": state.release_digest,
        "source": detached(stage["source"]),
        "source_digest": stage["source_digest"],
        "registration": detached(stage["registration"]),
    }
    if mode == "interpret":
        request["output"] = detached(stage["received_proposal"])
    stage["operation"] = {"action_id": action["id"], "request": detached(request)}
    state.actions.append(action)
    state.active_action = action["id"]
    return action, request


def observe_verifier(state, call):
    from .temporal_state import TERMINAL, detached

    key = "r" + str(call["planning_revision"])
    stage = state.parent_completion_stages[key]
    if stage["child_run_id"] != call["run_id"] or stage["child_release_digest"] != call.get(
        "observed_release_digest"
    ):
        raise DefinitionMismatch("Verifier observation changed original Run/release")
    if not call.get("settled") or call["state"] != "succeeded":
        return
    output = detached(call["snapshot"]["result"])
    if stage["received_proposal"] is not None:
        if stage["received_proposal"] != output:
            raise DefinitionMismatch("Verifier changed original received proposal")
        return
    stage.update(received_proposal=output, status="proposal_received")
    state._emit(
        "parent_verification_proposal_received",
        {"child_run_id": call["run_id"], "source_digest": stage["source_digest"]},
    )
    if state.state in TERMINAL:
        stage["status"] = "closed"
        state._emit("late_parent_verification_evidence", {"child_run_id": call["run_id"]})


def adopt(state, stage, value):
    from .parent_completion import ParentCompletionRequest, ParentCompletionVerdict
    from .parent_completion_protocol import validate_verdict
    from .temporal_state import detached

    check_source(state, stage, stage["source"]["candidate"])
    request = ParentCompletionRequest.from_dict(stage["source"])
    verdict = ParentCompletionVerdict(**value)
    validate_verdict(request, verdict)
    if stage["gate_verdict"]["status"] != "accept" and verdict.to_dict() != stage["gate_verdict"]:
        raise DefinitionMismatch("Model stage cannot override failed deterministic gate")
    stage.update(status="adopted", adopted_verdict=verdict.to_dict())
    state.parent_completion_pending = None
    state._emit(
        "parent_completion_adopted",
        {
            "revision": request.revision,
            "source_digest": stage["source_digest"],
            "verdict": verdict.to_dict(),
        },
    )
    if verdict.status == "accept":
        state._complete_parent(detached(request.candidate), verified=True)
    elif verdict.status == "reject":
        state.state, state.error = (
            "failed",
            {"code": "parent_completion_rejected", "feedback": verdict.feedback},
        )
        state._emit("run_failed", state.error)
    elif state.kind == "team":
        raise ValidationError("Team cannot adopt replan")
    elif state.planning_revision + 1 >= state.definition["max_revisions"]:
        state.state, state.error = "failed", {"code": "plan_revision_limit"}
        state._emit("run_failed", state.error)
    else:
        state.verification_feedback = {
            "revision": state.planning_revision,
            "feedback": verdict.feedback,
            "evidence_ids": list(verdict.evidence_ids),
            "source_digest": stage["source_digest"],
        }
        state.planning_revision += 1
        state.stage, state.dag, state.state = "plan", None, "running"
        state.planning_conclusion = None
        state._emit("replanning_requested", detached(state.verification_feedback))


def accept(state, action_id, response):
    from .orchestration_types import ChildCall
    from .temporal_bindings import request_release_digest
    from .temporal_state import TERMINAL, detached

    key = state.parent_completion_pending
    if key is None:
        raise ValidationError("Parent policy has no original pending operation")
    stage = state.parent_completion_stages[key]
    operation = stage["operation"]
    if operation["action_id"] != action_id or state.active_action != action_id:
        raise ValidationError("Parent policy response changed original active intent")
    action = next(a for a in state.actions if a["id"] == action_id)
    state.active_action = None
    action.update(status="completed", response=detached(response))
    if state.state in TERMINAL:
        stage["status"] = "closed"
        state._emit("late_parent_completion_evidence")
        return
    try:
        if response.get("ok") is not True or response.get("request_digest") != digest(
            operation["request"]
        ):
            raise ValidationError("Parent policy response differs from original operation")
        if stage["source_digest"] != digest(stage["source"]):
            raise DefinitionMismatch("Parent policy source drifted before adoption")
        if action["mode"] == "prepare":
            check_source(state, stage, stage["source"]["candidate"])
        if action["mode"] == "interpret":
            adopt(state, stage, response["verdict"])
            return
        stage["gate_verdict"] = detached(response["gate_verdict"])
        if (
            stage["gate_verdict"]["status"] != "accept"
            or stage["registration"]["stage_registration"] is None
        ):
            adopt(state, stage, stage["gate_verdict"])
            return
        prepared = detached(response["prepared_input"])
        if (
            len(canonical(prepared).encode("utf-8"))
            > stage["registration"]["identity"]["max_source_bytes"]
        ):
            raise ValidationError("Prepared parent verifier input exceeds fixed source bounds")
        stage.update(
            prepared_input=prepared, prepared_input_digest=digest(prepared), status="child_pending"
        )
        child = state.delegate(ChildCall("verdict", "@verifier", prepared), verifier=True)
        stage.update(
            child_key=child["id"],
            child_run_id=child["run_id"],
            child_release_digest=request_release_digest(child["request"], state.manifest),
        )
        state._emit(
            "parent_verification_child_intent_recorded",
            {
                "child_key": child["id"],
                "child_run_id": child["run_id"],
                "source_digest": stage["source_digest"],
            },
        )
    except (
        KeyError,
        IndexError,
        StopIteration,
        TypeError,
        ValueError,
        ValidationError,
        DefinitionMismatch,
    ) as exc:
        stage["status"], action["status"] = "failed", "failed"
        state.state, state.error = (
            "failed",
            {"code": response.get("code", getattr(exc, "code", "validation_error"))},
        )
        state._emit("run_failed", state.error)
