"""Pure physical dataset/authority addressing for persistent native Sessions."""

from .binding_types import AgentBindingDescriptor
from .errors import DefinitionMismatch, ValidationError
from .types import digest


def selected_source(request, manifest):
    from .binding_paths import agent_paths
    from .temporal_bindings import effective_manifest, selected_session_data

    if manifest.get("session_tree_protocol") is not None and request["definition"]["kind"] in {
        "graph",
        "team",
        "dynamic",
    }:
        from .temporal_session_tree import root_source

        return root_source(manifest)
    sources = selected_session_data(request, manifest)
    if not sources:
        return None
    if "session_save_protocol" not in manifest or request["definition"]["kind"] not in {
        "agent",
        "sequence",
    }:
        raise ValidationError("Persistent external Session requires original native save protocol")
    paths = agent_paths(request["definition"])
    values = [
        effective_manifest(
            manifest,
            request.get("agent_bindings", {}).get(path, AgentBindingDescriptor().to_dict()),
        ).get("session_data")
        for path in paths
    ]
    if any(v is None for v in values):
        raise ValidationError("Persistent sequence requires the same Session source in every step")
    first = values[0]
    if any(
        v["physical"] != first["physical"] or v["namespace"] != first["namespace"] for v in values
    ):
        raise ValidationError(
            "Persistent sequence requires the same physical Session source/namespace"
        )
    dataset = manifest["session_save_protocol"]["dataset_ids"].get(digest(first["physical"]))
    if type(dataset) is not str or len(dataset) != 64:
        raise DefinitionMismatch("Original Session dataset identity is unavailable")
    return {"dataset_id": dataset, "namespace": first["namespace"], "physical": first["physical"]}


def data_resource_id(namespace_id, source):
    from .temporal_session_state import resource_id

    authority = resource_id(namespace_id)
    return (
        authority
        if source is None
        else digest(["temporal-session-dataset-authority-v1", authority, source["dataset_id"]])
    )


def selected_namespace(source, provided):
    if source is None:
        return provided
    if provided is not None and provided != source["namespace"]:
        raise ValidationError("Session namespace differs from its actual selected data source")
    return source["namespace"]


def validate_turn(request, manifest, scope=None):
    from .session_types import SessionRef

    if not any(
        k in request
        for k in ("session_turn", "session_history", "session_observer", "session_lineage")
    ):
        return
    if "session_lineage" in request:
        from .temporal_session_tree import validate_lineage, validate_root_snapshot

        if "session_tree_protocol" not in manifest:
            raise DefinitionMismatch("Member lineage requires its original tree protocol")
        original = request["session_lineage"]["root_turn"]
        ref = SessionRef.from_dict(original["session_ref"])
        checked_scope = scope or {"workspace": ref.key.workspace, "principal": ref.key.principal}
        accepted = validate_lineage(request, manifest, checked_scope)
        if accepted["parent_run_id"] is not None:
            if (
                request.get("session_observer") != {"coordinator_id": original["coordinator_id"]}
                or "session_turn" in request
            ):
                raise DefinitionMismatch("Member observer changed original root ownership")
            validate_root_snapshot(request, manifest, checked_scope)
            return
        if request.get("session_turn") != original or "session_observer" in request:
            raise DefinitionMismatch("Root lineage lost its original coordinator Turn")
    source = selected_source(request, manifest)
    if source is None:
        return
    if request.get("session_observer") is not None:
        raise ValidationError("External member addresses are not implemented")
    turn = request.get("session_turn")
    if turn is None:
        if "session_history" in request:
            raise ValidationError("External Conversation requires its original Session Turn")
        return
    ref = SessionRef.from_dict(turn["session_ref"])
    expected = request.get("session_data_binding")
    if type(expected) is not dict or set(expected) != {"namespace_id", "dataset_id", "resource_id"}:
        raise DefinitionMismatch("External Session Turn lost actual dataset authority")
    if (
        expected["dataset_id"] != source["dataset_id"]
        or expected["resource_id"] != data_resource_id(expected["namespace_id"], source)
        or ref.key.resource_id != expected["resource_id"]
        or ref.key.namespace != source["namespace"]
        or scope is not None
        and (ref.key.workspace, ref.key.principal) != (scope["workspace"], scope["principal"])
    ):
        raise DefinitionMismatch("External Session Turn changed original physical data identity")
