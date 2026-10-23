"""Pure original tree ancestry evidence; it grants no execution or data lease."""

from .errors import DefinitionMismatch, ValidationError
from .session_types import SessionRef, integer
from .spec_codec import decode_spec
from .temporal_session_state import detached
from .types import Scope, canonical, digest, submission_request

MAX_LINEAGE_BYTES = 1_048_576


def require_tree_admission(request, manifest):
    """An external composite must own an admitted Turn before creating a Run."""
    from .temporal_bindings import selected_session_data

    if (
        "session_tree_protocol" in manifest
        and request["definition"]["kind"] in {"graph", "team", "dynamic"}
        and "session_lineage" not in request
        and selected_session_data(request, manifest)
    ):
        raise ValidationError(
            "Advanced external Session data requires an original admitted Session Turn"
        )


def root_source(manifest):
    """Resolve only the host's original root resource, without member inference.

    This metadata helper does not admit a composite external Session release.
    The save protocol and physical dataset remain mandatory for any selected data.
    """
    source = manifest.get("session_data")
    if source is None:
        return None
    from .temporal_session_data_state import validate_protocol as validate_reads
    from .temporal_session_save_state import validate_protocol as validate_saves

    try:
        validate_reads(manifest)
        validate_saves(manifest)
    except (ValidationError, KeyError, TypeError):
        raise DefinitionMismatch(
            "Root Session source lost its original resource contract"
        ) from None
    policy = manifest.get("session_save_protocol")
    if policy is None:
        raise DefinitionMismatch("Root Session source requires its original save protocol")
    dataset = policy["dataset_ids"].get(digest(source["physical"]))
    if dataset is None:
        raise DefinitionMismatch("Root Session source lost actual dataset identity")
    return detached(
        {"dataset_id": dataset, "namespace": source["namespace"], "physical": source["physical"]}
    )


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValidationError("Session lineage requires bounded nonempty identity atoms")


def _selected(parent, manifest, member, call_id, proposal):
    _text(member)
    _text(call_id)
    kind = parent["kind"]
    if kind == "graph":
        if member != call_id or proposal is not None:
            raise ValidationError("Graph lineage must name its original declared node")
        node = next((n for n in parent["nodes"] if n["id"] == member), None)
        if node is None or node["agent"] is None:
            raise ValidationError("Session lineage names no declared Agent node")
        return decode_spec(node["agent"]), ["graph", "nodes", member]
    if kind not in {"team", "dynamic"}:
        raise ValidationError("Only actual composite parents project member lineage")
    if member == "@verifier":
        if (
            call_id != "verdict"
            or proposal is not None
            or manifest.get("parent_completion_protocol") != 1
        ):
            raise ValidationError("Verifier lineage requires original parent policy intent")
        release = manifest["parent_completion_policies"][parent["completion_policy"]][
            "effective_agent_release"
        ]
        if release is None:
            raise ValidationError("Original parent policy has no managed verifier stage")
        from .types import AgentSpec

        return AgentSpec(**release["definition"]["steps"][0]), [kind, "verifier", call_id]
    if member == "@planner":
        if kind != "dynamic" or proposal is not None:
            raise ValidationError("Planner lineage requires its original dynamic parent")
        planner = manifest["orchestration"]["planners"][parent["planner"]].get("agent")
        if planner is None:
            raise ValidationError("No model planner declared in original release")
        return decode_spec(planner), ["dynamic", "planner", call_id]
    if member not in parent["members"]:
        raise ValidationError("Session lineage names an undeclared member")
    if kind == "team":
        if proposal is not None:
            raise ValidationError("Team lineage cannot import a dynamic proposal")
        path = ["team", "members", member, "calls", call_id]
    else:
        from .dag_planning import DAGProposal

        plan = DAGProposal.from_dict(proposal)
        plan.validate_members(parent["members"])
        if not any(n["id"] == call_id and n["member"] == member for n in plan.nodes):
            raise ValidationError("Dynamic lineage names no adopted node/member")
        path = ["dynamic", "nodes", call_id, "members", member]
    return decode_spec(parent["members"][member]), path


def _child_bindings(parent, member, child, manifest=None):
    from .temporal_bindings import project_child

    # project_child's legacy path projection is checked against the declaration
    # here; this helper does not activate tree execution or copy arbitrary lineage.
    source = {k: v for k, v in parent.items() if k != "session_lineage"}
    if member == "@verifier":
        return manifest["parent_completion_policies"][parent["definition"]["completion_policy"]][
            "effective_agent_release"
        ]["agent_bindings"]
    return project_child(source, member, {"definition": child}).get("agent_bindings", {})


def root_lineage(request, run_id, namespace_id, binding, scope):
    from .temporal_session_state import validate_binding, validate_history

    validate_binding(binding, scope)
    validate_history(request, binding["manifest"], scope)
    _text(run_id)
    _text(namespace_id)
    turn = request.get("session_turn")
    if turn is None or request.get("session_observer") is not None:
        raise ValidationError("Root lineage requires its original accepted Session Turn")
    ref = SessionRef.from_dict(turn["session_ref"])
    if ref.definition_digest != digest(binding):
        raise DefinitionMismatch("Session lineage lost original binding revision")
    if request["definition"] != binding["request"]["definition"] or request.get(
        "agent_bindings", {}
    ) != binding["request"].get("agent_bindings", {}):
        raise DefinitionMismatch("Session lineage changed original root declaration")
    value = {
        "version": 1,
        "root_turn": turn,
        "root_run_id": run_id,
        "namespace_id": namespace_id,
        "root_binding": binding,
        "links": [],
        "path": [],
    }
    probe = {**request, "session_lineage": value}
    validate_lineage(probe, binding["manifest"], scope)
    return detached(value)


def project_lineage(
    parent_request,
    parent_run_id,
    member,
    call_id,
    child_request,
    *,
    proposal=None,
    planning_revision=0,
):
    lineage = parent_request.get("session_lineage")
    if type(lineage) is not dict:
        raise ValidationError("Member projection requires original accepted root lineage")
    ref = SessionRef.from_dict(lineage["root_turn"]["session_ref"])
    scope = {"workspace": ref.key.workspace, "principal": ref.key.principal}
    manifest = lineage["root_binding"]["manifest"]
    accepted = validate_lineage(parent_request, manifest, scope)
    if accepted["run_id"] != parent_run_id:
        raise DefinitionMismatch("Lineage projection came from another actual parent")
    integer(planning_revision, minimum=0)
    member_spec, atoms = _selected(
        parent_request["definition"], manifest, member, call_id, proposal
    )
    expected = submission_request(
        member_spec, child_request["input"], budget=child_request["budget"]
    )
    if expected["definition"] != child_request["definition"]:
        raise DefinitionMismatch("Child lineage differs from actual declared Agent definition")
    bindings = _child_bindings(parent_request, member, expected["definition"], manifest)
    if child_request.get("agent_bindings", {}) != bindings:
        raise DefinitionMismatch("Child lineage changed original member selections")
    key = (
        f"r{planning_revision}.verifier.verdict"
        if member == "@verifier"
        else f"{planning_revision}:{call_id}"
    )
    command_id = "ralf-child:" + digest([scope, parent_run_id, key])
    value = detached(lineage)
    value["links"].append(
        {
            "parent_run_id": parent_run_id,
            "member": member,
            "call_id": call_id,
            "planning_revision": planning_revision,
            "proposal": detached(proposal),
            "child_run_id": "ralf-temporal-" + digest([scope, command_id]),
        }
    )
    value["path"] = [*value["path"], *atoms]
    validate_lineage(
        {**child_request, "session_lineage": value}, manifest, scope, parent_run_id=parent_run_id
    )
    return value


def validate_lineage(request, manifest, scope, *, parent_run_id=None):
    from .temporal_session_identity import data_resource_id, selected_source
    from .temporal_session_state import validate_binding, validate_history

    Scope(**scope)
    value = request.get("session_lineage")
    if (
        type(value) is not dict
        or set(value)
        != {"version", "root_turn", "root_run_id", "namespace_id", "root_binding", "links", "path"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["links"]) is not list
        or len(value["links"]) > 8
        or len(canonical(value).encode("utf-8")) > MAX_LINEAGE_BYTES
    ):
        raise ValidationError("Session lineage requires bounded exact original evidence")
    _text(value["root_run_id"])
    _text(value["namespace_id"])
    binding = value["root_binding"]
    validate_binding(binding, scope)
    if digest(binding["manifest"]) != digest(manifest):
        raise DefinitionMismatch("Session lineage changed original root release")
    validate_history({"session_history": [], "session_turn": value["root_turn"]}, manifest, scope)
    ref = SessionRef.from_dict(value["root_turn"]["session_ref"])
    source = selected_source(binding["request"], manifest)
    expected_resource = data_resource_id(value["namespace_id"], source)
    if (
        ref.definition_digest != digest(binding)
        or ref.coordination_ref
        != digest(["temporal-session-coordination-v1", ref.key.resource_id, scope])
        or ref.key.resource_id != expected_resource
        or source is not None
        and ref.key.namespace != source["namespace"]
    ):
        raise DefinitionMismatch("Session lineage changed original root binding or authority")
    current = detached(binding["request"])
    current_id, path, last_parent = value["root_run_id"], [], None
    for link in value["links"]:
        if type(link) is not dict or set(link) != {
            "parent_run_id",
            "member",
            "call_id",
            "planning_revision",
            "proposal",
            "child_run_id",
        }:
            raise ValidationError("Session lineage requires exact original child evidence")
        if link["parent_run_id"] != current_id:
            raise DefinitionMismatch("Session lineage changed actual parent ownership")
        integer(link["planning_revision"], minimum=0)
        spec, atoms = _selected(
            current["definition"], manifest, link["member"], link["call_id"], link["proposal"]
        )
        child = submission_request(spec, None, budget=1)
        bindings = _child_bindings(current, link["member"], child["definition"], manifest)
        if bindings:
            child["agent_bindings"] = bindings
        key = (
            f"r{link['planning_revision']}.verifier.verdict"
            if link["member"] == "@verifier"
            else f"{link['planning_revision']}:{link['call_id']}"
        )
        command = "ralf-child:" + digest([scope, current_id, key])
        child_id = "ralf-temporal-" + digest([scope, command])
        if child_id != link["child_run_id"]:
            raise DefinitionMismatch("Session lineage changed original child identity")
        current, current_id, last_parent = child, child_id, current_id
        path.extend(atoms)
    if (
        path != value["path"]
        or len(path) > 64
        or digest(current["definition"]) != digest(request["definition"])
        or current.get("agent_bindings", {}) != request.get("agent_bindings", {})
        or parent_run_id is not None
        and last_parent != parent_run_id
    ):
        raise DefinitionMismatch("Session lineage differs from original path or member declaration")
    kind = current["definition"]["kind"]
    return {
        "root_ref": ref.to_dict(),
        "root_run_id": value["root_run_id"],
        "run_id": current_id,
        "parent_run_id": last_parent,
        "path": path,
        "definition_digest": digest(current["definition"]["steps"][0])
        if kind == "agent"
        else digest(current["definition"]),
    }


def member_projection(request, manifest, scope, node):
    """Resolve an actual native leaf from accepted ancestry and fixed selections."""
    from .temporal_bindings import step_descriptor, validate_descriptor

    accepted = validate_lineage(request, manifest, scope)
    definition = request["definition"]
    if (
        accepted["parent_run_id"] is None
        or definition["kind"] not in {"agent", "sequence"}
        or type(node) is not int
        or not 0 <= node < len(definition["steps"])
    ):
        raise ValidationError("Private member projection requires an actual native leaf")
    descriptor = step_descriptor(request, node)
    validate_descriptor(manifest, descriptor, scope)
    path = list(accepted["path"])
    if definition["kind"] == "sequence":
        path.extend(["sequence", "steps", str(node)])
    if len(path) > 64:
        raise ValidationError("Private member path exceeds bounded topology allowance")
    return {
        **accepted,
        "path": path,
        "definition_digest": digest(definition["steps"][node]),
        "bindings": descriptor,
    }


def execution_fields(request):
    """Copy protected accepted Session fields, preserving legacy request bytes."""
    result = {}
    if "session_data_binding" in request:
        result.update({k: detached(request[k]) for k in ("session_turn", "session_data_binding")})
    if "session_lineage" in request:
        result.update(
            session_lineage=detached(request["session_lineage"]),
            session_declaration={
                "definition": detached(request["definition"]),
                "agent_bindings": detached(request.get("agent_bindings", {})),
            },
        )
        if "session_root_snapshot" in request:
            result["session_root_snapshot"] = detached(request["session_root_snapshot"])
    return result


def validate_root_snapshot(request, manifest, scope):
    """A descendant consumes original root evidence; it never rereads root data."""
    from .temporal_session_data_state import validate_snapshot

    lineage = request["session_lineage"]
    if not lineage["links"]:
        return
    selected = root_source(manifest)
    snapshot = request.get("session_root_snapshot")
    if selected is None:
        if snapshot is not None:
            raise DefinitionMismatch("History-only root cannot import external root evidence")
        return
    if type(snapshot) is not dict or snapshot.get("ok") is not True:
        raise DefinitionMismatch("Member lost original accepted root snapshot")
    root = detached(lineage)
    root.update(links=[], path=[])
    ref = SessionRef.from_dict(root["root_turn"]["session_ref"])
    validate_snapshot(
        snapshot,
        manifest,
        {
            "scope": scope,
            "run_id": root["root_run_id"],
            "session_source": "root",
            "session_data_node": "root",
            "session_lineage": root,
            "session_declaration": root["root_binding"]["request"],
            "query": manifest["session_data"]["query"],
            "address": ref.key.storage_key,
        },
    )
