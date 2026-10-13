"""Original Local parent authority freezes evidence and adopts completion verdicts."""

import copy
import json
from dataclasses import asdict

from .binding_definitions import AgentDefinition
from .binding_runtime import artifact_free_context, unwrap_definition
from .decisions import final_output
from .errors import CompletionRejected, DefinitionMismatch, ValidationError
from .types import canonical, digest, submission_request

CLOSED = {"succeeded", "failed", "cancelled", "cancelling"}
JOURNAL_FIELDS = {
    "schema_version",
    "source",
    "source_digest",
    "policy_registration",
    "gate_verdict",
    "prepared_input",
    "prepared_input_digest",
    "child_key",
    "child_run_id",
    "child_release_digest",
    "received_proposal",
    "adopted_verdict",
    "status",
}


def role(call):
    return call.get("role", "planner" if call.get("planning") else "worker")


def selected(engine, definition):
    name = definition.get("completion_policy")
    if name is None:
        return None
    policy = engine.parent_completion_policies.get(name)
    if policy is None:
        raise DefinitionMismatch("The declared parent completion policy is unavailable")
    from .parent_completion_protocol import validate_policy

    validate_policy(policy, parent_kind=definition["kind"])
    return policy


def stage_release(engine, stage):
    agent = stage.agent
    if isinstance(agent, AgentDefinition):
        definition = unwrap_definition(agent.to_dict())
        components, _ = engine._bindings.resolve(asdict(agent.spec), agent.bindings)
        context = components.context
        if not artifact_free_context(context):
            raise ValidationError("Verification Agent requires an actually pure Context")
        manifest = engine._bindings.manifest(definition)
        effective = next(iter(manifest["agent_bindings"]["steps"].values()))["manifest"]
        if (
            components.stage_policy is not None
            or components.knowledge is not None
            or components.memory is not None
        ):
            raise ValidationError("Verification Agent cannot inherit auxiliary I/O stages")
        engine._component_identity(components.context, ("assemble",), True, "Verifier context")
    else:
        definition = submission_request(agent, None)["definition"]
        context = engine.context
        if not artifact_free_context(context):
            raise ValidationError("Verification Agent requires an actually pure Context")
        manifest = engine._manifest(definition["steps"])
        effective = manifest
        if (
            engine.stage_policy is not None
            or engine.knowledge is not None
            or engine.memory is not None
        ):
            raise ValidationError("Verification Agent requires explicit auxiliary isolation")
        engine._component_identity(engine.context, ("assemble",), True, "Verifier context")
    if "managed_context" in effective or "managed_memory" in effective:
        raise ValidationError("Verification context cannot dispatch auxiliary model stages")
    return json.loads(canonical({"definition": definition, "manifest": manifest}))


def registration(engine, definition):
    policy = selected(engine, definition)
    if policy is None:
        return None
    from .parent_completion_protocol import policy_registration

    value = policy_registration(policy)
    value["effective_agent_release"] = (
        None if policy.model_stage is None else stage_release(engine, policy.model_stage)
    )
    return value


def validate_journal(engine, run):
    stages = run.get("parent_completion_stages")
    if stages is None:
        return
    if run["manifest"].get("parent_completion_protocol") != 1 or type(stages) is not dict:
        raise DefinitionMismatch("Parent completion journal lost its original protocol")
    policy = selected(engine, run["definition"])
    expected = registration(engine, run["definition"])
    if policy is None:
        raise DefinitionMismatch("Parent completion journal has no declared policy")
    try:
        for key, value in stages.items():
            _validate_record(engine, run, key, value, policy, expected)
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise DefinitionMismatch("Invalid original parent completion journal") from exc


def _validate_record(engine, run, key, value, policy, expected):
    from .parent_completion import ParentCompletionRequest, ParentCompletionVerdict
    from .parent_completion_protocol import validate_request_bounds, validate_verdict

    if (
        type(value) is not dict
        or set(value) != JOURNAL_FIELDS
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise DefinitionMismatch("Parent completion journal requires exact protocol fields")
    request = ParentCompletionRequest.from_dict(value["source"])
    validate_request_bounds(policy, request)
    if (
        key != "r" + str(request.revision)
        or value["source_digest"] != digest(value["source"])
        or value["policy_registration"] != expected
        or request.parent_id != run["id"]
        or request.parent_kind != run["definition"]["kind"]
        or request.scope != run["scope"]
        or request.release_digest != run["release_digest"]
        or request.revision > run["orchestration"]["revision"]
    ):
        raise DefinitionMismatch("Parent completion source or registration changed")
    status = value["status"]
    if status not in {"prepared", "child_pending", "proposal_received", "adopted", "closed"}:
        raise DefinitionMismatch("Invalid parent completion journal status")
    gate = value["gate_verdict"]
    if gate is not None:
        validate_verdict(request, ParentCompletionVerdict.from_dict(gate))
    model = gate is not None and gate["status"] == "accept" and policy.model_stage is not None
    if value["prepared_input"] is None:
        if value["prepared_input_digest"] is not None:
            raise DefinitionMismatch("Parent verification input digest lacks its source")
    elif not model or digest(value["prepared_input"]) != value["prepared_input_digest"]:
        raise DefinitionMismatch("Parent verification input changed")
    links = [value[name] for name in ("child_key", "child_run_id", "child_release_digest")]
    linked = all(item is not None for item in links)
    if any(item is not None for item in links) != linked:
        raise DefinitionMismatch("Incomplete parent verification child identity")
    if linked:
        if (
            not model
            or value["prepared_input"] is None
            or value["child_key"] != key + ".verifier.verdict"
        ):
            raise DefinitionMismatch("Verification child lacks its original prepared stage")
        call = next(
            (c for c in run["orchestration"]["children"] if c["id"] == value["child_key"]), None
        )
        child = engine._authorized(value["child_run_id"])
        if (
            call is None
            or role(call) != "verifier"
            or call["run_id"] != child["id"]
            or call["member"] != "@verifier"
            or call["planning"]
            or call["planning_revision"] != request.revision
            or call["proposal"]
            != {"id": "verdict", "member": "@verifier", "input": value["prepared_input"]}
            or child.get("parent_id") != run["id"]
            or child.get("call_id") != value["child_key"]
            or child["scope"] != run["scope"]
            or child["input"] != value["prepared_input"]
            or child["release_digest"] != value["child_release_digest"]
            or child["definition"] != expected["effective_agent_release"]["definition"]
        ):
            raise DefinitionMismatch("The original parent verification child changed")
    received, adopted = value["received_proposal"], value["adopted_verdict"]
    if status == "prepared" and (linked or received is not None or adopted is not None):
        raise DefinitionMismatch("Prepared completion contains later stage evidence")
    if status in {"child_pending", "closed"} and (
        not linked or received is not None or adopted is not None
    ):
        raise DefinitionMismatch("Pending completion lacks its original managed child")
    if status in {"proposal_received", "adopted"}:
        if gate is None or received is None or model != linked:
            raise DefinitionMismatch("Completion proposal lacks its original source")
        if linked and (
            child["state"] != "succeeded" or not call["settled"] or received != child["result"]
        ):
            raise DefinitionMismatch("Completion proposal differs from original settled child")
        if not model and received != gate:
            raise DefinitionMismatch("Pure completion proposal differs from original gate")
    if status == "adopted":
        validate_verdict(request, ParentCompletionVerdict.from_dict(adopted))
        if not model and adopted != gate:
            raise DefinitionMismatch("Adopted pure verdict differs from its original gate")
    elif adopted is not None:
        raise DefinitionMismatch("Unadopted completion contains an adopted verdict")


def _is_conclusion(run):
    return (run["orchestration"].get("proposal") or {}).get("status") in {"needs_input", "refused"}


def _business_calls(run):
    calls = [c for c in run["orchestration"]["children"] if role(c) == "worker"]
    if run["definition"]["kind"] == "dynamic":
        if _is_conclusion(run):
            return []
        if run["definition"].get("plan_mode") == "dag" and run["orchestration"].get("dag"):
            keys = {n.get("call_id") for n in run["orchestration"]["dag"]["nodes"].values()}
            calls = [c for c in calls if c["id"] in keys]
        else:
            prefix = f"r{run['orchestration']['revision']}.step."
            calls = [c for c in calls if c["id"].startswith(prefix)]
    return calls


def _current_task_offset(run, action):
    kind, node = run["definition"]["kind"], action["node"]
    journal = run.get("native_model_history", {})
    key = "agent" if kind == "agent" else f"sequence/steps/{node}"
    if kind == "graph":
        node_id = run["plan"]["nodes"][node]["id"]
        key = "graph/nodes/" + node_id
        frame = run["workflow"]["nodes"][node_id].get("execution", {})
        if "native_model_history" in frame:
            journal, key = frame["native_model_history"], "agent"
    stage = journal.get("stages", {}).get(key)
    if stage is None:
        if "native_history_messages" in action:
            raise DefinitionMismatch("Business model lost its original native Turn source")
        return 1
    if journal.get("markers", {}).get(key) != digest(stage):
        raise DefinitionMismatch("Business model native Turn source changed")
    return 1 + sum(len(turn["history"]) - 1 for turn in stage["past"])


def _input_consumed(action, value, offset):
    messages = action.get("snapshot", [])
    return (
        len(messages) > offset
        and messages[offset].get("role") == "user"
        and messages[offset].get("content")
        == (value if isinstance(value, str) else canonical(value))
    )


def _slot(run, actions, value, path):
    finals = [
        a
        for a in actions
        if a["kind"] == "model"
        and a["status"] == "completed"
        and not a.get("decision_skipped")
        and not a["response"]["tool_calls"]
    ]
    if not finals:
        raise ValidationError("Business evidence lacks its original final model Action")
    final = finals[-1]
    offset = _current_task_offset(run, final)
    witness = {
        "member_path": path,
        "action_id": final["id"],
        "snapshot_digest": digest(final.get("snapshot", [])),
        "input_digest": digest(value),
        "input_consumed": _input_consumed(final, value, offset),
    }
    receipts = []
    for action in actions:
        if action["kind"] != "tool" or action["status"] != "completed":
            continue
        before = actions.index(action) < actions.index(final)
        consumed = before and any(
            m.get("role") == "tool"
            and m.get("tool_call_id") == action.get("call_id")
            and m.get("content") == canonical(action["result"])
            for m in final.get("snapshot", [])[offset + 1 :]
        )
        receipts.append(
            {
                "id": "tool:" + digest([run["id"], action["id"]]),
                "run_id": run["id"],
                "member_path": path,
                "action_id": action["id"],
                "tool": action["tool"],
                "arguments": copy.deepcopy(action["arguments"]),
                "result": copy.deepcopy(action["result"]),
                "receipt": copy.deepcopy(action["receipt"]),
                "effect_key": action["effect_key"],
                "consumed_by": ["model:" + digest([run["id"], final["id"]])] if consumed else [],
            }
        )
    return witness, receipts, final


def evidence(engine, owner, policy):
    children, receipts, seen = [], [], set()

    def visit(parent, call, path, revision):
        if len(children) >= policy.max_evidence_children or len(seen) >= 256:
            raise ValidationError("Parent completion child evidence exceeds its bound")
        child = engine._authorized(call["run_id"])
        if child["id"] in seen:
            raise DefinitionMismatch("Parent completion ownership contains repeated Runs")
        seen.add(child["id"])
        if (
            child.get("parent_id") != parent["id"]
            or child.get("call_id") != call["id"]
            or child["scope"] != owner["scope"]
        ):
            raise DefinitionMismatch("Business child evidence lost its original ownership")
        engine._check_release(child)
        if (
            child["state"] != "succeeded"
            or engine.store.budget(child["id"])["held"]
            or engine._operation_active(child["id"])
            or child["id"] in engine._active
            or not call.get("settled")
        ):
            raise ValidationError("Business child evidence is not completed and quiescent")
        kind = child["definition"]["kind"]
        models = []
        final = None
        if kind == "agent":
            witness, tools, final = _slot(child, child["actions"], child["input"], path)
            models.append(witness)
            receipts.extend(tools)
        elif kind == "sequence":
            incoming = child["input"]
            for index, step in enumerate(child["definition"]["steps"]):
                witness, tools, result = _slot(
                    child,
                    [a for a in child["actions"] if a["node"] == index],
                    incoming,
                    path + ["steps", str(index)],
                )
                models.append(witness)
                receipts.extend(tools)
                incoming = final_output(result["response"]["output"], step["output_schema"])
        elif kind == "graph":
            for index, node in enumerate(child["plan"]["nodes"]):
                state = child["workflow"]["nodes"][node["id"]]
                if state["state"] == "skipped":
                    continue
                if state["state"] != "completed":
                    raise ValidationError("Graph business evidence is unfinished")
                if node.get("agent") is not None:
                    witness, tools, _ = _slot(
                        child,
                        [a for a in child["actions"] if a["node"] == index],
                        state["input"],
                        path + [node["id"]],
                    )
                    models.append(witness)
                    receipts.extend(tools)
                elif node.get("tool") is not None:
                    for action in child["actions"]:
                        if (
                            action["node"] == index
                            and action["kind"] == "tool"
                            and action["status"] == "completed"
                        ):
                            receipts.append(
                                {
                                    "id": "tool:" + digest([child["id"], action["id"]]),
                                    "run_id": child["id"],
                                    "member_path": path + [node["id"]],
                                    "action_id": action["id"],
                                    "tool": action["tool"],
                                    "arguments": copy.deepcopy(action["arguments"]),
                                    "result": copy.deepcopy(action["result"]),
                                    "receipt": copy.deepcopy(action["receipt"]),
                                    "effect_key": action["effect_key"],
                                    "consumed_by": [],
                                }
                            )
        children.append(
            {
                "id": "child:" + digest([child["id"], child["release_digest"]]),
                "call_id": call["id"],
                "role": "worker",
                "member_path": path,
                "run_id": child["id"],
                "release_digest": child["release_digest"],
                "state_revision": child["revision"],
                "planning_revision": revision,
                "input": copy.deepcopy(child["input"]),
                "input_digest": digest(child["input"]),
                "input_consumed": None if final is None else models[0]["input_consumed"],
                "result": copy.deepcopy(child["result"]),
                "result_digest": digest(child["result"]),
                "final_action_id": None if final is None else final["id"],
                "final_snapshot_digest": None
                if final is None
                else digest(final.get("snapshot", [])),
                "final_models": models,
            }
        )
        if len(receipts) > policy.max_receipts:
            raise ValidationError("Parent completion tool evidence exceeds its bound")
        if kind in {"team", "dynamic"}:
            for nested in _business_calls(child):
                visit(child, nested, path + [nested["member"]], revision)

    for call in _business_calls(owner):
        visit(
            owner,
            call,
            [call["member"]],
            call.get("planning_revision", owner["orchestration"]["revision"]),
        )
    return children, receipts


def _source(engine, run, policy, candidate):
    from .parent_completion import ParentCompletionRequest

    state, definition = run["orchestration"], run["definition"]
    children, receipts = evidence(engine, run, policy)
    return ParentCompletionRequest(
        parent_id=run["id"],
        parent_kind=definition["kind"],
        scope=run["scope"],
        release_digest=run["release_digest"],
        revision=state["revision"],
        task=run["input"],
        plan=(state.get("dag") or {}).get("proposal")
        if definition.get("plan_mode") == "dag" and not _is_conclusion(run)
        else state["proposal"],
        candidate=candidate,
        children=children,
        receipts=receipts,
        constraints={
            "remaining_steps": (
                definition["max_steps"]
                if definition["kind"] == "dynamic"
                else len(definition["members"]) + 1
            )
            - len(state["children"]),
            "remaining_revisions": definition.get("max_revisions", 1) - state["revision"] - 1
            if definition["kind"] == "dynamic"
            else 0,
            "max_concurrency": definition["max_concurrency"],
            "verifier_budget": policy.verifier_budget,
            "parent_budget": engine.store.budget(run["id"]),
        },
    )


def _save(engine, run_id, record, event):
    with engine.store.transaction():
        current = engine._authorized(run_id)
        current.setdefault("parent_completion_stages", {})[
            "r" + str(record["source"]["revision"])
        ] = copy.deepcopy(record)
        engine._commit(
            current, event, {"source_digest": record["source_digest"], "status": record["status"]}
        )


def _check_source(engine, run, record, policy):
    if run["orchestration"].get("completion_candidate") != record["source"]["candidate"]:
        raise DefinitionMismatch("Parent completion candidate intent changed")
    current = _source(engine, run, policy, record["source"]["candidate"]).to_dict()
    current["constraints"] = record["source"]["constraints"]
    prior = {c["id"]: c for c in record["source"]["children"]}
    for child in current["children"]:
        original = prior.get(child["id"])
        if original is not None and child["state_revision"] >= original["state_revision"]:
            child["state_revision"] = original["state_revision"]
    if current != record["source"]:
        raise DefinitionMismatch("Parent completion original business source changed")


async def complete(orchestration, run_id, candidate):
    engine = orchestration.engine
    run = orchestration.observe(run_id)
    policy = selected(engine, run["definition"])
    if policy is None:
        await orchestration._finish(run_id, candidate)
        return False
    from .parent_completion import ParentCompletionRequest
    from .parent_completion_protocol import (
        gate_verdict,
        interpret_stage_output,
        prepare_stage_input,
        validate_request_bounds,
    )

    key = "r" + str(run["orchestration"]["revision"])
    record = run.get("parent_completion_stages", {}).get(key)
    if record is None:
        request = _source(engine, run, policy, candidate)
        validate_request_bounds(policy, request)
        record = {
            "schema_version": 1,
            "source": request.to_dict(),
            "source_digest": digest(request.to_dict()),
            "policy_registration": registration(engine, run["definition"]),
            "gate_verdict": None,
            "prepared_input": None,
            "prepared_input_digest": None,
            "child_key": None,
            "child_run_id": None,
            "child_release_digest": None,
            "received_proposal": None,
            "adopted_verdict": None,
            "status": "prepared",
        }
        _save(engine, run_id, record, "parent_completion_source_recorded")
    validate_journal(engine, engine._authorized(run_id))
    _check_source(engine, engine._authorized(run_id), record, policy)
    request = ParentCompletionRequest(
        **{k: v for k, v in record["source"].items() if k != "schema_version"}
    )
    if record["gate_verdict"] is None:
        record["gate_verdict"] = gate_verdict(policy, request).to_dict()
        _save(engine, run_id, record, "parent_completion_gate_recorded")
    if record["status"] in {"prepared", "child_pending"}:
        verdict = record["gate_verdict"]
        if verdict["status"] == "accept" and policy.model_stage is not None:
            if record["prepared_input"] is None:
                record["prepared_input"] = prepare_stage_input(policy, request)
                record["prepared_input_digest"] = digest(record["prepared_input"])
                _save(engine, run_id, record, "parent_verification_input_recorded")
            _check_source(engine, engine._authorized(run_id), record, policy)
            from .orchestration_types import ChildCall

            call = orchestration.delegate(
                run_id,
                ChildCall("verdict", "@verifier", record["prepared_input"]),
                verification=True,
            )
            if record["child_run_id"] is None:
                record.update(
                    status="child_pending",
                    child_key=call["id"],
                    child_run_id=call["run_id"],
                    child_release_digest=engine._authorized(call["run_id"])["release_digest"],
                )
                _save(engine, run_id, record, "parent_verification_child_intent_recorded")
            elif (
                call["id"] != record["child_key"]
                or call["run_id"] != record["child_run_id"]
                or engine._authorized(call["run_id"])["release_digest"]
                != record["child_release_digest"]
            ):
                raise DefinitionMismatch("The original parent verification child changed")
            if engine._authorized(run_id)["state"] in CLOSED:
                return False
            await orchestration._drive_children(run_id, [call])
            run = orchestration.observe(run_id)
            if run["state"] in CLOSED:
                record["status"] = "closed"
                _save(engine, run_id, record, "parent_completion_closed")
                return False
            child = engine._authorized(call["run_id"])
            if (
                child["state"] != "succeeded"
                or not next(c for c in run["orchestration"]["children"] if c["id"] == call["id"])[
                    "settled"
                ]
            ):
                with engine.store.transaction():
                    run = engine._authorized(run_id)
                    run["state"] = "outcome_unknown"
                    engine._commit(run, "parent_verification_waiting")
                return False
            record["received_proposal"] = copy.deepcopy(child["result"])
            record["status"] = "proposal_received"
            _save(engine, run_id, record, "parent_verification_proposal_received")
        else:
            record["received_proposal"] = copy.deepcopy(verdict)
            record["status"] = "proposal_received"
            _save(engine, run_id, record, "parent_verification_proposal_received")
    if record["status"] == "proposal_received":
        engine._check_release(engine._authorized(run_id))
        _check_source(engine, engine._authorized(run_id), record, policy)
        verdict = (
            interpret_stage_output(policy, request, record["received_proposal"]).to_dict()
            if record["gate_verdict"]["status"] == "accept" and policy.model_stage is not None
            else record["received_proposal"]
        )
        record.update(status="adopted", adopted_verdict=copy.deepcopy(verdict))
        _save(engine, run_id, record, "parent_completion_adopted")
    if engine._authorized(run_id)["state"] in CLOSED:
        return False
    verdict = record["adopted_verdict"]
    if verdict["status"] == "reject":
        raise CompletionRejected("The parent result lacks declared business evidence")
    if verdict["status"] == "replan":
        if run["definition"]["kind"] != "dynamic":
            raise ValidationError("Team completion cannot request replanning")
        from .orchestration import PlanRevisionLimit

        latest = engine._authorized(run_id)
        if latest["orchestration"]["revision"] + 1 >= latest["definition"]["max_revisions"]:
            raise PlanRevisionLimit("The plan revision limit was exhausted")
        with engine.store.transaction():
            latest = engine._authorized(run_id)
            state = latest["orchestration"]
            state.update(
                revision=state["revision"] + 1,
                proposal=None,
                request=None,
                stage="select",
                verification_feedback={
                    "revision": record["source"]["revision"],
                    "feedback": verdict["feedback"],
                    "evidence_ids": verdict["evidence_ids"],
                    "source_digest": record["source_digest"],
                },
            )
            engine._commit(latest, "plan_replanning")
        return True
    await orchestration._finish(run_id, record["source"]["candidate"])
    return False
