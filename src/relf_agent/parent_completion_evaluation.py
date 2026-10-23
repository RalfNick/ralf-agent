"""Independent oracle for the opted-in inventory parent evaluation.

Only original committed Run records are evidence. The two-member projection
passed to the unchanged inventory scorer selects actual current children; it
does not invent, renumber or execute Runs. Gate verdicts are checked as journal
claims, never used as the business oracle's truth.
"""

import re

from .decisions import final_output
from .errors import ValidationError
from .orchestration_evaluation import _CHECKS, _consumed, _input_model, _score
from .parent_completion import ParentCompletionRequest, ParentCompletionVerdict
from .types import canonical, digest

_JOURNAL_FIELDS = {
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
_TERMINAL = {"succeeded", "failed", "cancelled"}


def _require(condition):
    if not condition:
        raise ValidationError("Parent completion evaluation evidence is inconsistent")


def _release(run):
    _require(
        run["release_digest"]
        == digest(
            {
                "definition": run["definition"],
                "manifest": run["manifest"],
            }
        )
    )


def _bound_worker(parent, child, member, expected_definition):
    """Validate the original member projection, not a fresh binding resolution."""
    name = member["name"]
    path = parent["definition"]["kind"] + "/members/" + name
    wrapper = parent["definition"]["binding_definition"]
    declared = wrapper["agent_bindings"][path]
    entry = parent["manifest"]["agent_bindings"]["steps"][path]
    identity = {
        "kind": "inventory-member-completion-verifier",
        "version": "1",
        "member": name,
        "request_pointer": "/request",
    }
    verifier = {"mode": "ref", "component_id": "inventory-" + name, "version": "1"}
    _require(name in {"researcher", "writer"})
    _require(wrapper["kind"] == "bound_definition")
    _require(canonical(declared) == canonical(entry["descriptor"]))
    _require(canonical(declared["verifier"]) == canonical(verifier))
    _require(
        all(
            canonical(value) == canonical({"mode": "inherit"})
            for role, value in declared.items()
            if role not in {"schema_version", "verifier"}
        )
    )
    _require(
        canonical(entry["resolved"]["verifier"])
        == canonical(
            {
                "role": "verifier",
                "component_id": "inventory-" + name,
                "version": "1",
                "interface_version": 1,
                "scope": parent["scope"],
                "identity": identity,
            }
        )
    )
    _require(canonical(entry["manifest"]["completion_verifier"]) == canonical(identity))
    expected_binding = {
        "kind": "bound_agent",
        "schema_version": 1,
        "bindings": declared,
        "spec": {k: v for k, v in member.items() if k != "kind"},
    }
    _require(
        canonical(child["definition"])
        == canonical(
            {
                **expected_definition,
                "binding_definition": expected_binding,
            }
        )
    )
    _require(
        canonical(child["manifest"]["agent_bindings"])
        == canonical(
            {
                "schema_version": 1,
                "steps": {"agent": entry},
            }
        )
    )
    recorded_release = parent["manifest"]["orchestration"]["members"][name]
    _require(
        canonical({k: v for k, v in child["manifest"].items() if k != "parent_call"})
        == canonical(recorded_release)
    )
    _require(
        canonical(entry["manifest"]["tools"])
        == canonical({tool: parent["manifest"]["tools"][tool] for tool in member["tools"]})
    )


def _leaf_manifest(child):
    manifest = child["manifest"]
    if "agent_bindings" in manifest:
        return manifest["agent_bindings"]["steps"]["agent"]["manifest"]
    return manifest


def _owned_runs(parent, children):
    calls = parent["orchestration"]["children"]
    _require(type(children) is list and len(calls) == len(children))
    by_run = {child["id"]: child for child in children}
    _require(len(by_run) == len(children))
    _require(len({c["id"] for c in calls}) == len(calls))
    _require(len({c["run_id"] for c in calls}) == len(calls))
    _require({c["run_id"] for c in calls} == set(by_run))
    for call in calls:
        child = by_run[call["run_id"]]
        binding = child["parent_call"]
        _require(
            child["parent_id"] == parent["id"]
            and child["call_id"] == call["id"]
            and child["scope"] == parent["scope"]
            and binding["parent_id"] == parent["id"]
            and binding["call_id"] == call["id"]
            and binding["reservation"] == call["reservation"]
            and child["manifest"]["parent_call"] == binding
            and call["state"] == child["state"]
        )
        _release(child)
        if call["role"] == "worker":
            member = parent["definition"]["members"][call["member"]]
            _require(member.get("kind", "agent") == "agent")
            expected_definition = {
                "kind": "agent",
                "name": member["name"],
                "version": member["version"],
                "steps": [{k: v for k, v in member.items() if k != "kind"}],
            }
            if "agent_bindings" in parent["manifest"]:
                _bound_worker(parent, child, member, expected_definition)
            else:
                _require(child["definition"] == expected_definition)
            _require(not call["planning"] and call["proposal"]["member"] == call["member"])
            _require(call["proposal"]["input"] == child["input"])
            # Leaf releases share the parent's configured components but pin
            # only their own declared tools and native leaf kernel.
            excluded = {"kernel", "tools", "parent_call"}
            if "agent_bindings" in parent["manifest"]:
                excluded.add("agent_bindings")
            _require(
                all(
                    value == parent["manifest"].get(name)
                    for name, value in child["manifest"].items()
                    if name not in excluded
                )
            )
            _require(
                _leaf_manifest(child)["tools"]
                == {name: parent["manifest"]["tools"][name] for name in member["tools"]}
            )
        else:
            _require(call["role"] in {"planner", "verifier"})
    return by_run


def _quiescent(parent, children):
    return (
        parent["state"] in _TERMINAL
        and not parent.get("pending")
        and parent["orchestration"].get("quiescent") is True
        and all(call["settled"] is True for call in parent["orchestration"]["children"])
        and all(
            child["state"] in _TERMINAL
            and not child.get("pending")
            and all(a["status"] in {"completed", "failed", "cancelled"} for a in child["actions"])
            and all(
                attempt["status"] in {"completed", "failed", "cancelled"}
                for action in child["actions"]
                for attempt in action.get("attempts", [])
            )
            for child in children
        )
    )


def _current_calls(parent, by_run):
    state, definition = parent["orchestration"], parent["definition"]
    workers = [c for c in state["children"] if c["role"] == "worker"]
    if definition["kind"] == "team":
        _require(state["revision"] == 0)
        return workers
    revision = state["revision"]
    _require(type(revision) is int and 0 <= revision < definition["max_revisions"])
    if definition["plan_mode"] != "dag":
        return [c for c in workers if c["id"].startswith(f"r{revision}.step.")]
    dag = state["dag"]
    by_call = {c["id"]: c for c in workers}
    keys = []
    for node in dag["proposal"]["nodes"]:
        record = dag["nodes"][node["id"]]
        if record["state"] == "skipped":
            continue
        _require(record["state"] == "completed")
        key = record["call_id"]
        call, child = by_call[key], by_run[by_call[key]["run_id"]]
        _require(
            call["member"] == node["member"]
            and call["proposal"]["id"] == node["id"]
            and record["input"] == child["input"]
            and record["result"] == child["result"]
        )
        keys.append(key)
    _require(len(set(keys)) == len(keys))
    return [c for c in workers if c["id"] in keys]


def _original_evidence(child, call, frozen):
    """Rebuild leaf witnesses from the original Actions, independently of gate code."""
    actions = child["actions"]
    _require(child["state"] == "succeeded" and actions)
    _require(len({a["id"] for a in actions}) == len(actions))
    finals = [
        a
        for a in actions
        if (
            a["kind"] == "model"
            and a["status"] == "completed"
            and not a.get("decision_skipped")
            and not a["response"]["tool_calls"]
        )
    ]
    _require(bool(finals))
    final = finals[-1]
    _require(final is actions[-1])
    _require(final["request"]["messages"] == final["snapshot"])
    _require(
        final_output(final["response"]["output"], child["definition"]["steps"][0]["output_schema"])
        == child["result"]
    )
    path = [call["member"]]
    model = {
        "member_path": path,
        "action_id": final["id"],
        "snapshot_digest": digest(final["snapshot"]),
        "input_digest": digest(child["input"]),
        "input_consumed": _input_model(final, child["input"]),
    }
    revision = frozen["state_revision"]
    _require(type(revision) is int and 0 <= revision <= child["revision"])
    evidence = {
        "id": "child:" + digest([child["id"], child["release_digest"]]),
        "call_id": call["id"],
        "role": "worker",
        "member_path": path,
        "run_id": child["id"],
        "release_digest": child["release_digest"],
        "state_revision": revision,
        "planning_revision": call["planning_revision"],
        "input": child["input"],
        "input_digest": digest(child["input"]),
        "input_consumed": model["input_consumed"],
        "result": child["result"],
        "result_digest": digest(child["result"]),
        "final_action_id": final["id"],
        "final_snapshot_digest": model["snapshot_digest"],
        "final_models": [model],
    }
    receipts = []
    for position, action in enumerate(actions):
        if action["kind"] != "tool" or action["status"] != "completed":
            continue
        _require(
            action["effect_observation"]
            == {
                "receipt": action["receipt"],
                "result": action["result"],
            }
        )
        _require(
            action["digest"]
            == digest(
                {
                    "run_id": child["id"],
                    "action_id": action["id"],
                    "tool": _leaf_manifest(child)["tools"][action["tool"]],
                    "arguments": action["arguments"],
                    "scope": child["scope"],
                }
            )
        )
        proposals = [a for a in actions[:position] if a["kind"] == "model"]
        _require(
            bool(proposals)
            and any(
                proposal["name"] == action["tool"]
                and proposal["arguments"] == action["arguments"]
                and (proposal["call_id"] or action["id"]) == action["call_id"]
                for proposal in proposals[-1]["response"]["tool_calls"]
            )
        )
        receipts.append(
            {
                "id": "tool:" + digest([child["id"], action["id"]]),
                "run_id": child["id"],
                "member_path": path,
                "action_id": action["id"],
                "tool": action["tool"],
                "arguments": action["arguments"],
                "result": action["result"],
                "receipt": action["receipt"],
                "effect_key": action["effect_key"],
                "consumed_by": ["model:" + digest([child["id"], final["id"]])]
                if _consumed(actions, action)
                else [],
            }
        )
    return evidence, receipts


def _journal_source(parent, record, key, by_run, current_calls=None):
    _require(type(record) is dict and set(record) == _JOURNAL_FIELDS)
    _require(type(record["schema_version"]) is int and record["schema_version"] == 1)
    source = ParentCompletionRequest.from_dict(record["source"]).to_dict()
    state = parent["orchestration"]
    _require(
        key == "r" + str(source["revision"])
        and record["source_digest"] == digest(source)
        and source["parent_id"] == parent["id"]
        and source["parent_kind"] == parent["definition"]["kind"]
        and source["scope"] == parent["scope"]
        and source["release_digest"] == parent["release_digest"]
        and source["task"] == parent["input"]
        and source["revision"] <= state["revision"]
    )
    registration = parent["manifest"]["orchestration"]["parent_completion"]
    _require(record["policy_registration"] == registration)
    _require(
        registration["effective_agent_release"] is None
        and registration["stage_registration"] is None
    )
    _require(
        all(
            record[name] is None
            for name in (
                "prepared_input",
                "prepared_input_digest",
                "child_key",
                "child_run_id",
                "child_release_digest",
            )
        )
    )
    if source["parent_kind"] == "dynamic":
        adopted = [
            r
            for r in state["revisions"]
            if r["revision"] == source["revision"] and r["proposal"] == source["plan"]
        ]
        _require(bool(adopted))
        _require(
            all(r.get("digest", digest(r["proposal"])) == digest(r["proposal"]) for r in adopted)
        )
        if current_calls is not None:
            _require(source["plan"] == (state.get("dag") or {}).get("proposal", state["proposal"]))
    else:
        _require(source["plan"] == state["proposal"])
    calls_by_id = {c["id"]: c for c in state["children"] if c["role"] == "worker"}
    if current_calls is None:
        calls = [calls_by_id[c["call_id"]] for c in source["children"]]
        _require(len({c["id"] for c in calls}) == len(calls))
    else:
        calls = current_calls
    _require([c["run_id"] for c in source["children"]] == [c["run_id"] for c in calls])
    _require([c["member"] for c in calls] == ["researcher", "writer"])
    evidence, receipts = [], []
    for call, frozen in zip(calls, source["children"], strict=True):
        _require(call["planning_revision"] <= source["revision"])
        if source["parent_kind"] == "dynamic":
            _require(call["id"] == f"r{call['planning_revision']}.step.{call['proposal']['id']}")
        actual, tools = _original_evidence(by_run[call["run_id"]], call, frozen)
        evidence.append(actual)
        receipts.extend(tools)
    _require(source["children"] == evidence and source["receipts"] == receipts)
    constraints = source["constraints"]
    _require(
        constraints["remaining_revisions"]
        == (
            parent["definition"]["max_revisions"] - source["revision"] - 1
            if source["parent_kind"] == "dynamic"
            else 0
        )
    )
    _require(constraints["max_concurrency"] == parent["definition"]["max_concurrency"])
    _require(constraints["verifier_budget"] == registration["identity"]["verifier_budget"])
    budget = constraints["parent_budget"]
    _require(set(budget) == {"limit", "held", "spent"} and budget["held"] == 0)
    _require(all(type(value) is int and value >= 0 for value in budget.values()))
    _require(budget["spent"] <= budget["limit"])
    _require(record["status"] == "adopted")
    verdict = ParentCompletionVerdict.from_dict(record["adopted_verdict"]).to_dict()
    _require(record["gate_verdict"] == record["received_proposal"] == verdict)
    ids = {c["id"] for c in evidence} | {r["id"] for r in receipts}
    _require(set(verdict["evidence_ids"]) <= ids)
    return source, verdict


def score_parent_completion(case, parent, children, kind):
    """Return allowlisted booleans; recovery remains the evaluator's observation.

    The frozen source revision can precede the actual child revision after escrow
    or session commits. All fields that identify the source, final model and tool
    receipt must still equal those independently reconstructed from original Runs.
    """
    checks = dict.fromkeys(_CHECKS + ("current_lineage", "parent_completion"), False)
    try:
        _require(kind in {"plan-and-execute", "team"})
        _require(parent["definition"]["kind"] == ("team" if kind == "team" else "dynamic"))
        _require(parent["definition"]["completion_policy"] == "inventory")
        _require(parent["input"] == {"task": case["task"], "request": case["request"]})
        _require(parent["manifest"]["parent_completion_protocol"] == 1)
        _release(parent)
        by_run = _owned_runs(parent, children)
        current = _current_calls(parent, by_run)
        _require([c["member"] for c in current] == ["researcher", "writer"])
        # This is a scoring projection of actual records, with every Run ID,
        # Action and parent link intact. Historical attempts remain in storage.
        projection = {**parent, "orchestration": {**parent["orchestration"], "children": current}}
        checks.update(_score(case, projection, [by_run[c["run_id"]] for c in current], kind))
        checks["stopped"] = checks["stopped"] and _quiescent(parent, children)
        revision = parent["orchestration"]["revision"]
        journals = parent["parent_completion_stages"]
        _require(type(journals) is dict and all(re.fullmatch(r"r[0-9]+", k) for k in journals))
        key = "r" + str(revision)
        source, verdict = _journal_source(parent, journals[key], key, by_run, current)
        checks["current_lineage"] = True
        registration = journals[key]["policy_registration"]
        identity = registration["gate_registration"]["identity"]
        _require(
            identity
            == {
                "kind": "inventory-parent-completion-gate",
                "version": "1",
                "dataset": case["dataset"],
                "request_pointer": "/request",
                "researcher_path": ["researcher"],
                "writer_path": ["writer"],
                "on_missing": "replan" if kind == "plan-and-execute" else "reject",
            }
        )
        _require(
            registration["identity"]["gate"] == identity
            and registration["identity"]["model_stage"] is None
        )
        for previous_key, record in journals.items():
            if previous_key == key:
                continue
            old, old_verdict = _journal_source(parent, record, previous_key, by_run)
            _require(old["revision"] < revision and old_verdict["status"] == "replan")
        if revision:
            previous = journals["r" + str(revision - 1)]
            old_verdict = previous["adopted_verdict"]
            _require(
                parent["orchestration"]["verification_feedback"]
                == {
                    "revision": revision - 1,
                    "feedback": old_verdict["feedback"],
                    "evidence_ids": old_verdict["evidence_ids"],
                    "source_digest": previous["source_digest"],
                }
            )
        _require(
            verdict["status"] == "accept"
            and parent["state"] == "succeeded"
            and source["candidate"] == parent["result"]
            and source["candidate"] == parent["orchestration"]["completion_candidate"]
            and source["candidate"] == by_run[current[-1]["run_id"]]["result"]
        )
        checks["parent_completion"] = checks["current_lineage"] and all(
            value for name, value in checks.items() if name not in {"recovery", "parent_completion"}
        )
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, ValidationError):
        checks["parent_completion"] = False
    return checks
