"""Explicit closed-parent recovery over its original owned child Runs."""

from .errors import DefinitionMismatch
from .managed_memory import _enabled


async def recover_terminal_children(engine, run_id):
    parent = engine._authorized(run_id)
    if not _enabled(parent["manifest"]):
        return
    for call in parent["orchestration"]["children"]:
        child_id = call["run_id"]
        if child_id == run_id or engine.parent_run_id(child_id) != run_id:
            raise DefinitionMismatch("Memory recovery child lost its original ownership")
        child = engine._authorized(child_id)
        if (
            not call["settled"]
            and _enabled(child["manifest"])
            and child["state"] in {"succeeded", "failed", "cancelled"}
            and child_id not in engine._active
            and not engine._operation_active(child_id)
        ):
            # Original drive owns its lock and only recovers terminal evidence.
            # Nested parents follow the same path; no alternate scheduling state.
            await engine.drive(child_id)
