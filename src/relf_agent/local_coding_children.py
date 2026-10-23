"""Stop closure follows only the original recorded child ownership tree."""

from .errors import DefinitionMismatch
from .types import digest


def _children(engine, run, seen, depth):
    from .local_delegated_coding import _original_run

    # Original admission bounds the orchestration parent chain at eight,
    # allowing its final non-orchestrated child at Run depth nine.
    if (
        depth > 9
        or (depth == 9 and run.get("orchestration") is not None)
        or run["id"] in seen
        or len(seen) >= 10000
    ):
        raise DefinitionMismatch("Original child ownership is cyclic or unbounded")
    seen.add(run["id"])
    calls = run.get("orchestration", {}).get("children", ())
    if not isinstance(calls, (list, tuple)) or len(calls) > 257:
        raise DefinitionMismatch("Original child ownership records changed")
    ids = set()
    for call in calls:
        try:
            if call["id"] in ids:
                raise DefinitionMismatch("Original child ownership records changed")
            ids.add(call["id"])
            child = _original_run(engine, call["run_id"])
            binding = child["parent_call"]
            expected = {
                "parent_id": run["id"],
                "call_id": call["id"],
                "reservation": call["reservation"],
                **({"limits_member": call["member"]} if "limits_member" in binding else {}),
            }
            if (
                binding != expected
                or child["parent_id"] != run["id"]
                or child["call_id"] != call["id"]
                or child["manifest"].get("parent_call") != binding
                or child["release_digest"]
                != digest({"definition": child["definition"], "manifest": child["manifest"]})
            ):
                raise DefinitionMismatch("Original child ownership or pinned release changed")
        except (KeyError, TypeError) as exc:
            raise DefinitionMismatch("Original child ownership records changed") from exc
        yield child, depth + 1


def stops_settled(engine, run):
    """Physical closure is separate from child budget/effect settlement."""
    from .local_delegated_coding import delegated_stop_settled

    seen, pending, settled = set(), [(run, 1)], True
    while pending:
        current, depth = pending.pop()
        settled = delegated_stop_settled(current) and settled
        pending.extend(_children(engine, current, seen, depth))
    return settled


async def stop_children(engine, run_id):
    """Stop recorded original children, never dispatch a replacement child."""
    from .local_delegated_coding import _original_run, _stop_original_work

    root = _original_run(engine, run_id)
    seen, pending, children = set(), [(root, 1)], []
    while pending:
        current, depth = pending.pop()
        descendants = list(_children(engine, current, seen, depth))
        children.extend(child for child, _ in descendants)
        pending.extend(descendants)
    cleanup = engine._coding_cleanup_token is not None
    for child in reversed(children):
        # The original stop helper validates the complete ancestor release
        # before each required physical stop; idle children need no native I/O.
        if cleanup:
            await _stop_original_work(engine, child["id"])
            continue
        if child["state"] not in {"succeeded", "failed", "cancelled"}:
            engine.cancel(
                child["id"], command_id=f"parent-cancel:{child['parent_id']}:{child['call_id']}"
            )
        await _stop_original_work(engine, child["id"])
        current = _original_run(engine, child["id"])
        if (
            current["state"] == "cancelling"
            and child["id"] not in engine._active
            and not engine._operation_active(child["id"])
            and stops_settled(engine, current)
        ):
            # Existing drive adopts cancellation and original receipts only:
            # the durable cancelling state prevents any new business work.
            await engine.drive(child["id"])
    return stops_settled(engine, _original_run(engine, run_id))
