"""Original native History owns one private snapshot per admitted member/step."""

from .errors import DefinitionMismatch
from .temporal_session_tree import execution_fields
from .temporal_state import TERMINAL, detached
from .types import digest


def request_fields(state):
    result = execution_fields(state.request)
    if state.request.get("session_lineage", {}).get("links"):
        value = getattr(state, "session_private_snapshots", {}).get(str(state.node))
        if value is not None:
            result["session_private_snapshot"] = detached(value)
    return result


def adopt(state, response):
    if (
        not state.request.get("session_lineage", {}).get("links")
        or state.state in TERMINAL
        or "session_data" not in response
    ):
        return
    from .temporal_session_data_state import validate_snapshot

    value = {name: detached(response[name]) for name in ("session_data", "session_data_references")}
    validate_snapshot(
        value,
        state.step_manifest,
        {
            "scope": state.scope,
            "run_id": state.run_id,
            "step": state.step,
            "session_data_node": state.node,
            **request_fields(state),
        },
    )
    key = str(state.node)
    previous = state.session_private_snapshots.get(key)
    if previous is not None:
        if value != previous:
            raise DefinitionMismatch("Member context changed its original private snapshot")
        return
    state.session_private_snapshots[key] = value
    state._emit(
        "session_private_snapshot_adopted", {"node": state.node, "snapshot_digest": digest(value)}
    )
