"""Exact private node projections back to the original Local Run authority."""

from .errors import DefinitionMismatch
from .types import digest


def original_engine(engine):
    from .binding_artifacts import _same_binding
    from .engine import LocalEngine
    from .node_execution import NodeEngine, NodeExecutionStore
    from .task_controls import _binding

    if type(engine) is not NodeEngine:
        if isinstance(engine, NodeEngine) or not isinstance(engine, LocalEngine):
            raise DefinitionMismatch("Unsupported Coding authority projection")
        return engine
    pin = engine._coding_projection
    parent, store, run_id, node_id, projection, methods = pin
    if (
        not isinstance(parent, LocalEngine)
        or isinstance(parent, NodeEngine)
        or engine.parent is not parent
        or engine.store is not projection
        or type(projection) is not NodeExecutionStore
        or parent.store is not store
        or projection.authority is not store
        or projection._parent_engine is not parent
        or projection.run_id != run_id
        or projection.node_id != node_id
        or engine.node_id != node_id
        or engine.tools is not parent.tools
        or engine._threads is not parent._threads
        or any(
            not _same_binding(_binding(getattr(projection, name)), binding)
            for name, binding in methods.items()
        )
    ):
        raise DefinitionMismatch("Original node Coding projection changed")
    return parent


def original_action(engine, run, action):
    """Keep native identity in the original flattened action log, never frame zero."""
    parent = original_engine(engine)
    if parent is engine:
        return engine, run, action
    store = engine.store
    if run.get("id") != store.run_id or action.get("node") != 0:
        raise DefinitionMismatch("Coding Action does not belong to its original node")
    original = parent._authorized(run["id"], _cleanup_token=parent._coding_cleanup_token)
    try:
        nodes = original["plan"]["nodes"]
        indexes = [i for i, node in enumerate(nodes) if node["id"] == store.node_id]
        if len(indexes) != 1:
            raise DefinitionMismatch("Original Coding node identity changed")
        frame = original["workflow"]["nodes"][store.node_id]["execution"]
        if run["plan"]["nodes"][0]["id"] != store.node_id or any(
            digest(run[key]) != digest(frame[key])
            for key in ("definition", "manifest", "release_digest", "plan")
        ):
            raise DefinitionMismatch("Original Coding node release changed")
        matches = [a for a in original["actions"] if a["id"] == action["id"]]
        if len(matches) != 1 or matches[0]["node"] != indexes[0]:
            raise DefinitionMismatch("Coding Action does not belong to its original node")
        selected = matches[0]
        if any(
            action.get(key) != selected.get(key)
            for key in ("kind", "tool", "digest", "arguments", "effect_key")
        ):
            raise DefinitionMismatch("Original node Coding Action identity changed")
        return parent, original, selected
    except (KeyError, IndexError, TypeError) as exc:
        raise DefinitionMismatch("Original node Coding projection is unavailable") from exc
