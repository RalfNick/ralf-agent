"""Original History linkage and physical closure; never a financial authority."""

import copy
import json
from uuid import UUID

from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest

ACTIVITY = "ralf.temporal.coding-composition-admission.v1"


def _link_fields():
    return {
        "version",
        "scope",
        "namespace",
        "parent_run_id",
        "parent_execution_epoch",
        "parent_request_digest",
        "parent_release_digest",
        "call_id",
        "command_id",
        "member",
        "planning_revision",
        "child_run_id",
        "child_projection_digest",
        "cap",
        "depth",
    }


def _view_fields():
    return {
        "version",
        "scope",
        "run_id",
        "execution_epoch",
        "original_execution_epoch",
        "namespace",
        "request",
        "request_digest",
        "manifest",
        "release_digest",
        "revision",
        "state",
        "physical_stopped",
        "action_stops",
        "proof_digest",
    }


def enabled(manifest):
    value = manifest.get("coding_composition_protocol")
    return (
        (manifest.get("binding_protocol") in (12, 13) and "coding_composition_protocol" in manifest)
        or (
            manifest.get("binding_protocol") == 15
            and type(value) is dict
            and type(value.get("version")) is int
            and value["version"] == 3
        )
        or orchestration_enabled(manifest)
    )


def orchestration_enabled(manifest):
    value = manifest.get("coding_composition_protocol")
    return (
        manifest.get("binding_protocol") in (17, 19, 21, 23)
        and type(value) is dict
        and type(value.get("version")) is int
        and value["version"] == {17: 4, 19: 5, 21: 6, 23: 7}[manifest["binding_protocol"]]
    )


def recursive_enabled(manifest):
    value = manifest.get("coding_composition_protocol")
    return (
        manifest.get("binding_protocol") == 23
        and type(value) is dict
        and type(value.get("version")) is int
        and value["version"] == 7
    )


def child_capacity_released(call):
    return call.get("physical_no_start") is True or (
        call.get("settled") is True
        and call.get("physical_stop_proof", {}).get("physical_stopped") is True
    )


def coding_runner_keys(request, manifest):
    """Deduplicate original Runner resources from actual effective Agent grants."""
    from .binding_paths import agent_paths
    from .binding_types import AgentBindingDescriptor
    from .temporal_bindings import effective_step

    resources = set()
    for path, step in agent_paths(request["definition"]).items():
        selected = effective_step(
            step,
            manifest,
            request.get("agent_bindings", {}).get(path, AgentBindingDescriptor().to_dict()),
        )
        for name in selected["tools"]:
            marker = manifest["tools"][name].get("config", {}).get("delegated_runner")
            if marker is not None:
                resources.add(digest(marker["runner"]))
    return frozenset(resources)


def occupied_runner_keys(state):
    resources = set()
    for call in state.children:
        if not child_capacity_released(call):
            resources.update(coding_runner_keys(call["request"], state.manifest))
    return frozenset(resources)


def _require(state):
    if not enabled(state.manifest):
        raise DefinitionMismatch("Original Coding composition publication required")


def _namespace(value, *, partial=False):
    if type(value) is not dict or set(value) != {"name", "id"}:
        raise DefinitionMismatch("Original namespace requires name and UUID")
    if type(value["name"]) is not str or not value["name"].strip() or len(value["name"]) > 256:
        raise DefinitionMismatch("Original namespace name is invalid")
    if value["id"] is None and partial:
        return copy.deepcopy(value)
    try:
        if type(value["id"]) is not str or str(UUID(value["id"])) != value["id"]:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise DefinitionMismatch("Original namespace UUID is invalid") from None
    return copy.deepcopy(value)


def initialize(state, *, namespace):
    if not enabled(state.manifest):
        return
    value = _namespace({"name": namespace, "id": None}, partial=True)
    if hasattr(state, "composition_namespace"):
        if state.composition_namespace["name"] != namespace:
            raise DefinitionMismatch("Original namespace cannot change")
        return
    state.composition_namespace = value
    state.composition_original_epoch = state.epoch
    state.composition_stop_intent = None
    state.composition_admission = None


def initialize_namespace(state, payload):
    _require(state)
    state.authorize(payload.get("scope"))
    if (
        type(payload) is not dict
        or set(payload)
        != {
            "scope",
            "run_id",
            "execution_epoch",
            "manifest_digest",
            "namespace",
        }
        or (
            payload["run_id"] != state.run_id
            or payload["execution_epoch"] != state.epoch
            or payload["manifest_digest"] != digest(state.manifest)
        )
    ):
        raise DefinitionMismatch("Namespace binding differs from original History")
    value = _namespace(payload["namespace"])
    previous = state.composition_namespace
    if previous["name"] != value["name"] or (previous["id"] is not None and previous != value):
        raise DefinitionMismatch("Original namespace binding is immutable")
    if previous["id"] is None:
        if getattr(state, "children", []):
            raise DefinitionMismatch("Namespace must be fixed before original child intents")
        state.composition_namespace = value
        state._emit("coding_composition_namespace_bound", {"namespace": value})
    return {"run_id": state.run_id, "recorded": True}


def project_child_link(parent, call, request):
    _require(parent)
    namespace = _namespace(parent.composition_namespace)
    kinds = {"graph", "team", "dynamic"} if orchestration_enabled(parent.manifest) else {"graph"}
    recursive = recursive_enabled(parent.manifest)
    if recursive:
        source_depth = _link(parent.request)["depth"] if "coding_parent" in parent.request else 0
        if (
            type(parent.depth) is not int
            or parent.depth != source_depth
            or type(call["depth"]) is not int
            or call["depth"] != parent.depth + 1
            or call["depth"] >= parent.policy.max_depth
            or parent.kind not in kinds
        ):
            raise DefinitionMismatch("Original Coding child depth differs from its parent policy")
    elif parent.depth != 0 or call["depth"] != 1 or parent.kind not in kinds:
        raise DefinitionMismatch("Coding composition permits one original Agent child level")
    child_kinds = {"agent", "sequence", "graph", "team", "dynamic"} if recursive else {"agent"}
    if request["definition"]["kind"] not in child_kinds or "coding_parent" in request:
        raise DefinitionMismatch("Coding child requires its original Agent projection")
    if orchestration_enabled(parent.manifest) and call["member"] in {"@planner", "@verifier"}:
        planner = call["member"] == "@planner"
        if (
            planner
            and (parent.kind != "dynamic" or parent.stage != "plan" or call["call_id"] != "planner")
            or not planner
            and (
                not parent.parent_completion_enabled
                or parent.parent_completion_pending is None
                or call["call_id"] != "verdict"
            )
        ):
            raise DefinitionMismatch("Hidden child differs from its original parent policy slot")
        from .spec_codec import decode_spec
        from .types import submission_request

        expected = submission_request(
            decode_spec(parent._member(call["member"])), call["input"], budget=call["cap"]
        )
        if canonical(request["definition"]) != canonical(expected["definition"]):
            raise DefinitionMismatch("Hidden child changed its original fixed Agent")
    result = copy.deepcopy(request)
    result["coding_parent"] = {
        "version": 1,
        "scope": copy.deepcopy(parent.scope),
        "namespace": namespace,
        "parent_run_id": parent.run_id,
        "parent_execution_epoch": parent.epoch,
        "parent_request_digest": digest(parent.request),
        "parent_release_digest": parent.release_digest,
        "call_id": call["id"],
        "command_id": call["command_id"],
        "member": call["member"],
        "planning_revision": call.get("planning_revision", parent.planning_revision),
        "child_run_id": call["run_id"],
        "child_projection_digest": digest(request),
        "cap": call["cap"],
        "depth": call["depth"],
    }
    # The original parent stores precisely the request a child receives after
    # the SDK JSON conversion; tuple-backed Agent fields retain their identity
    # digest while gaining the same immutable wire representation.
    return json.loads(canonical(result))


def _link(request):
    value = request.get("coding_parent")
    if (
        type(value) is not dict
        or set(value) != _link_fields()
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise DefinitionMismatch("Coding child lacks its complete original parent link")
    _namespace(value["namespace"])
    base = {k: v for k, v in request.items() if k != "coding_parent"}
    from .temporal_parent_state import child_run_id

    if (
        value["child_projection_digest"] != digest(base)
        or type(value["depth"]) is not int
        or not 1 <= value["depth"] <= 8
        or type(value["planning_revision"]) is not int
        or value["planning_revision"] < 0
        or type(value["cap"]) is not int
        or value["cap"] != request["budget"]
        or value["child_run_id"] != child_run_id(value["scope"], value["command_id"])
        or request["definition"]["kind"] not in {"agent", "sequence", "graph", "team", "dynamic"}
    ):
        raise DefinitionMismatch("Original Coding child projection changed")
    return value


def validate_child_link(
    state, *, namespace, parent_namespace, parent_run_id, parent_epoch, original_epoch
):
    _require(state)
    if original_epoch != state.epoch:
        raise DefinitionMismatch("Replacement SDK execution cannot own original Coding History")
    state.composition_original_epoch = original_epoch
    if "coding_parent" not in state.request:
        if parent_run_id is not None:
            raise DefinitionMismatch("Unlinked Coding execution cannot be a child")
        if recursive_enabled(state.manifest) and getattr(state, "depth", 0) != 0:
            raise DefinitionMismatch("Original Coding root SDK depth changed")
        return
    link = _link(state.request)
    if recursive_enabled(state.manifest):
        from .governance import TemporalExecutionPolicy

        policy = (
            TemporalExecutionPolicy.from_identity(state.manifest["execution_policy"])
            if "execution_policy" in state.manifest
            else TemporalExecutionPolicy()
        )
        if link["depth"] >= policy.max_depth or (
            hasattr(state, "depth") and state.depth != link["depth"]
        ):
            raise DefinitionMismatch("Original Coding SDK child depth changed")
    elif link["depth"] != 1 or state.request["definition"]["kind"] != "agent":
        raise DefinitionMismatch("Coding composition permits one original Agent child level")
    if (
        link["scope"] != state.scope
        or link["child_run_id"] != state.run_id
        or namespace != link["namespace"]["name"]
        or parent_namespace != namespace
        or parent_run_id != link["parent_run_id"]
        or parent_epoch != link["parent_execution_epoch"]
    ):
        raise DefinitionMismatch("SDK parent differs from original Coding child owner")
    state.composition_namespace = copy.deepcopy(link["namespace"])


def _proof(evidence):
    if (
        type(evidence) is not dict
        or set(evidence) != _view_fields()
        or type(evidence["version"]) is not int
        or evidence["version"] != 1
    ):
        raise DefinitionMismatch("Original physical stop requires complete typed History proof")
    if (
        evidence["proof_digest"]
        != digest({k: v for k, v in evidence.items() if k != "proof_digest"})
        or evidence["request_digest"] != digest(evidence["request"])
        or evidence["original_execution_epoch"] != evidence["execution_epoch"]
        or type(evidence["execution_epoch"]) is not str
        or not evidence["execution_epoch"]
        or type(evidence["revision"]) is not int
        or evidence["revision"] < 0
        or type(evidence["physical_stopped"]) is not bool
        or type(evidence["action_stops"]) is not list
        or (
            evidence["physical_stopped"]
            and evidence["state"] not in {"cancelled", "failed", "succeeded"}
        )
    ):
        raise DefinitionMismatch("Original physical stop proof is inconsistent")
    _namespace(evidence["namespace"])
    for action in evidence["action_stops"]:
        if (
            type(action) is not dict
            or set(action)
            != {
                "action_id",
                "attempts",
                "effect_key",
                "native_request_digest",
                "native_fenced",
                "pending_stop",
                "owner",
            }
            or type(action["action_id"]) is not str
            or type(action["attempts"]) is not list
        ):
            raise DefinitionMismatch("Original action stop proof is invalid")
        if evidence["physical_stopped"]:
            owner = action["owner"]
            if owner is not None and (
                type(owner) is not dict or owner.get("execution_stopped") is not True
            ):
                raise DefinitionMismatch("Physical closure contradicts original actual Tool owner")
            if action["native_request_digest"] is not None and (
                action["native_fenced"] is not True
                or action["pending_stop"] is not False
                or owner is None
            ):
                raise DefinitionMismatch("Physical closure contradicts original native intent")
            if owner is None and action["attempts"]:
                raise DefinitionMismatch("Original dispatched Tool lacks actual closure")
    from .temporal_bindings import request_release_digest

    if evidence["release_digest"] != request_release_digest(
        evidence["request"], evidence["manifest"]
    ):
        raise DefinitionMismatch("Original physical stop release changed")
    return evidence


def _child(state, run_id, evidence):
    _require(state)
    evidence = _proof(evidence)
    call = next((c for c in state.children if c["run_id"] == run_id), None)
    if call is None or (
        evidence["run_id"] != run_id
        or evidence["scope"] != state.scope
        or evidence["request"] != call["request"]
        or evidence["request_digest"] != call["child_request_digest"]
        or evidence["manifest"] != state.manifest
        or evidence["namespace"] != state.composition_namespace
    ):
        raise DefinitionMismatch("Physical evidence differs from original child intent")
    link = _link(evidence["request"])
    if recursive_enabled(state.manifest):
        if (
            type(call.get("depth")) is not int
            or link["depth"] != call["depth"]
            or link["depth"] != state.depth + 1
            or link["depth"] >= state.policy.max_depth
        ):
            raise DefinitionMismatch("Original child physical depth differs from its parent")
    elif link["depth"] != 1 or evidence["request"]["definition"]["kind"] != "agent":
        raise DefinitionMismatch("Coding composition permits one original Agent child level")
    if (
        link["parent_run_id"] != state.run_id
        or link["parent_execution_epoch"] != state.epoch
        or link["parent_request_digest"] != digest(state.request)
        or link["parent_release_digest"] != state.release_digest
        or link["cap"] != call["cap"]
        or link["call_id"] != call["id"]
        or link["command_id"] != call["command_id"]
        or link["member"] != call["member"]
        or link["planning_revision"] != call.get("planning_revision", 0)
    ):
        raise DefinitionMismatch("Physical evidence belongs to another original parent")
    return call


def pin_child_execution(state, run_id, evidence):
    if type(evidence) is dict and set(evidence) == {
        "namespace",
        "execution_epoch",
        "original_execution_epoch",
        "request_digest",
        "parent_run_id",
        "parent_execution_epoch",
    }:
        _require(state)
        call = next((c for c in state.children if c["run_id"] == run_id), None)
        if call is None or (
            evidence["namespace"] != state.composition_namespace
            or evidence["parent_run_id"] != state.run_id
            or evidence["parent_execution_epoch"] != state.epoch
            or evidence["request_digest"] != call["child_request_digest"]
            or type(evidence["execution_epoch"]) is not str
            or not evidence["execution_epoch"]
            or evidence["original_execution_epoch"] != evidence["execution_epoch"]
        ):
            raise DefinitionMismatch("Original SDK child-start evidence changed")
        _namespace(evidence["namespace"])
    else:
        call = _child(state, run_id, evidence)
    if not call.get("dispatch_started"):
        raise DefinitionMismatch("Child SDK execution requires original dispatch intent")
    value = {
        "namespace": copy.deepcopy(evidence["namespace"]),
        "execution_epoch": evidence["execution_epoch"],
        "original_execution_epoch": evidence["original_execution_epoch"],
    }
    previous = call.get("child_execution")
    if previous is not None and previous != value:
        raise DefinitionMismatch("Original child SDK execution cannot be replaced")
    if previous is None:
        call["child_execution"] = value
        state._emit("coding_composition_child_epoch_bound", {"run_id": run_id, **value})
    return {"run_id": run_id, "recorded": True}


def _owners_stopped(state):
    from .temporal_coding_state import stopped

    if (
        state.active_action is not None
        or state.remote_uncertain
        or not stopped(state)
        or getattr(state, "active_reconciliation", None) is not None
        or getattr(state, "active_evidence_ack", None) is not None
    ):
        return False
    if any(
        v.get("execution_stopped") is not True
        for v in getattr(state, "tool_executions", {}).values()
    ):
        return False
    for stage in getattr(state, "session_stages", {}).values():
        if "write_action" in stage and stage.get("execution_stopped") is not True:
            return False
    for stage in getattr(state, "context_read_stages", {}).values():
        if (
            stage.get("execution_end_proof") is None
            and stage.get("fenced") is not True
            and stage.get("handler_not_started") is not True
        ):
            return False
    # Untyped lost memory/context/model work retains its original stop obligation.
    for action in state.actions:
        if action.get("kind") != "tool" and action.get("status") in {
            "executing",
            "outcome_unknown",
        }:
            if (
                "execution_end_proof" not in action
                and action.get("response", {}).get("execution_stopped") is not True
            ):
                return False
    return True


def _children_stopped(state):
    return all(
        c.get("physical_no_start") is True
        or c.get("physical_stop_proof", {}).get("physical_stopped") is True
        for c in getattr(state, "children", [])
    )


def request_parent_stop(state, *, terminal_state, reason):
    _require(state)
    if terminal_state not in {"cancelled", "failed"}:
        raise ValidationError("Parent stopping requires a cancellation/failure intent")
    if state.composition_stop_intent is None:
        state.composition_stop_intent = {
            "terminal_state": terminal_state,
            "reason": copy.deepcopy(reason),
            "child_intent_ids": [c["id"] for c in state.children],
        }
        state.state = "cancelling"
        from .temporal_user_input import close_pending

        close_pending(state)
        for call in state.children:
            if not call.get("dispatch_started"):
                call.update(physical_no_start=True, state="cancelled", settled=True, spent=0)
        state._emit("coding_composition_stop_intent", copy.deepcopy(state.composition_stop_intent))
    refresh_parent_stop(state)
    return {"state_revision": state.revision, "remote_stop_confirmed": state.quiescent}


def refresh_parent_stop(state):
    intent = getattr(state, "composition_stop_intent", None)
    if (
        intent is not None
        and state.state == "cancelling"
        and _owners_stopped(state)
        and _children_stopped(state)
    ):
        state.state, state.error = intent["terminal_state"], copy.deepcopy(intent["reason"])
        state._emit("coding_composition_physical_stopped", {"terminal_state": state.state})


def physical_stop_view(state):
    _require(state)
    from .temporal_state import TERMINAL

    records = []
    for action in state.actions:
        if action.get("kind") != "tool":
            continue
        native = action.get("delegated_execution")
        owner = getattr(state, "tool_executions", {}).get(action["id"])
        records.append(
            {
                "action_id": action["id"],
                "attempts": copy.deepcopy(action.get("attempts", [])),
                "effect_key": None
                if native is None
                else native["request"]["dispatch"]["effect_key"],
                "native_request_digest": None
                if native is None
                else native["request"]["request_digest"],
                "native_fenced": None if native is None else native["fenced"],
                "pending_stop": None if native is None else native["pending_stop"],
                "owner": copy.deepcopy(owner),
            }
        )
    result = {
        "version": 1,
        "scope": copy.deepcopy(state.scope),
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "original_execution_epoch": state.composition_original_epoch,
        "namespace": copy.deepcopy(state.composition_namespace),
        "request": copy.deepcopy(state.request),
        "request_digest": digest(state.request),
        "manifest": copy.deepcopy(state.manifest),
        "release_digest": state.release_digest,
        "revision": state.revision,
        "state": state.state,
        "physical_stopped": state.state in TERMINAL
        and _owners_stopped(state)
        and _children_stopped(state),
        "action_stops": records,
    }
    result["proof_digest"] = digest(result)
    return result


def adopt_child_stop(state, run_id, evidence):
    call = _child(state, run_id, evidence)
    execution = call.get("child_execution")
    if execution is None or execution != {
        "namespace": evidence["namespace"],
        "execution_epoch": evidence["execution_epoch"],
        "original_execution_epoch": evidence["original_execution_epoch"],
    }:
        raise DefinitionMismatch("Child physical closure requires original fixed SDK epoch")
    previous = call.get("physical_stop_proof")
    if previous is not None:
        if evidence["revision"] < previous["revision"]:
            return {"run_id": run_id, "recorded": True}
        if (evidence["revision"] == previous["revision"] and evidence != previous) or (
            previous["physical_stopped"] and not evidence["physical_stopped"]
        ):
            raise DefinitionMismatch("Original child physical evidence changed inconsistently")
        if evidence == previous:
            return {"run_id": run_id, "recorded": True}
    call["physical_stop_proof"] = copy.deepcopy(evidence)
    if orchestration_enabled(state.manifest) and hasattr(state, "_adopt_child_result"):
        state._adopt_child_result(call)
    state._emit(
        "coding_composition_child_stop_observed",
        {"run_id": run_id, "physical_stopped": evidence["physical_stopped"]},
    )
    refresh_parent_stop(state)
    return {"run_id": run_id, "recorded": True}


def coding_requests(state):
    _require(state)
    from .temporal_coding_state import _record

    values = []
    for action in state.actions:
        native = action.get("delegated_execution")
        if native is None:
            continue
        tool = state.tool_executions.get(action["id"])
        if tool is None:
            raise DefinitionMismatch("Original Coding Tool owner intent missing")
        request = native["tool_request"]
        # admission=True validates the entire original action even before its
        # exclusive owner exists, without recording a grant or native permission.
        proof = {
            "scope": state.scope,
            "run_id": state.run_id,
            "action_id": action["id"],
            "release_digest": state.release_digest,
            "request_digest": tool["request_digest"],
            "execution_epoch": state.epoch,
            "invocation_id": tool.get("invocation_id", "0" * 32),
        }
        _record(state, proof, admission=True)
        values.append(copy.deepcopy(request))
        if len(values) > 10000:
            raise DefinitionMismatch("Original Coding cleanup request allowance exceeded")
    return values


def original_children(state):
    _require(state)
    return copy.deepcopy(getattr(state, "children", []))


def validate_parent_update(state, payload):
    _require(state)
    state.authorize(payload.get("scope"))
    if (
        type(payload) is not dict
        or set(payload)
        != {
            "scope",
            "run_id",
            "execution_epoch",
            "request_digest",
            "release_digest",
            "child_run_id",
            "evidence",
        }
        or (
            payload["run_id"] != state.run_id
            or payload["execution_epoch"] != state.epoch
            or payload["request_digest"] != digest(state.request)
            or payload["release_digest"] != state.release_digest
        )
    ):
        raise DefinitionMismatch("Original parent receipt adoption proof changed")
    return payload["child_run_id"], payload["evidence"]


def adopt_admission(state, response):
    _require(state)
    if (
        type(response) is not dict
        or set(response) != {"namespace", "execution_epoch", "admitted"}
        or type(response["admitted"]) is not bool
        or response["execution_epoch"] != state.epoch
    ):
        raise DefinitionMismatch("Original root admission receipt is invalid")
    initialize_namespace(
        state,
        {
            "scope": state.scope,
            "run_id": state.run_id,
            "execution_epoch": state.epoch,
            "manifest_digest": digest(state.manifest),
            "namespace": response["namespace"],
        },
    )
    previous = state.composition_admission
    if previous is not None and previous != response:
        # Durable close can revoke the existing admission, never reopen it.
        if previous["admitted"] is not True or response["admitted"] is not False:
            raise DefinitionMismatch("Original root admission cannot be replaced")
    if previous != response:
        state.composition_admission = copy.deepcopy(response)
        state._emit("coding_composition_root_admission", {"admitted": response["admitted"]})
    if not response["admitted"]:
        request_parent_stop(
            state, terminal_state="cancelled", reason={"code": "owned_close_requested"}
        )
