"""Bounded input observations from the original scoped execution controls."""

from dataclasses import asdict
from types import SimpleNamespace

from .errors import DefinitionMismatch
from .user_input import PendingInput


def snapshot_inputs(snapshot, scope, *, release_digest=None, aggregate=False):
    """Project questions only when the snapshot is their original owner."""
    inputs, seen = [], set()
    for item in snapshot.pending:
        if item.get("kind") != "input":
            continue
        owner = item.get("owner")
        if type(owner) is not dict:
            raise DefinitionMismatch("Input request is missing its original owner")
        if owner.get("run_id") != snapshot.run_id and aggregate:
            continue  # Parent caches are reread through their actual child controls.
        question = PendingInput.from_dict(
            {key: value for key, value in item.items() if key not in {"kind", "run_id", "call_id"}}
        )
        if (
            question.owner
            != {
                "run_id": snapshot.run_id,
                "release_digest": release_digest or question.owner["release_digest"],
                "scope": asdict(scope),
            }
            or question.pending_id in seen
        ):
            raise DefinitionMismatch("Input request differs from its original scoped owner")
        seen.add(question.pending_id)
        if len(seen) > 4096:
            raise DefinitionMismatch("Input controls exceed bounded question projection")
        inputs.append({"kind": "input", **question.to_dict()})
    return inputs


async def pending_inputs(controls, run_id):
    """Read original diagnostics; this observer never hosts or drives a Run."""
    controls.require_input_discovery()
    if "diagnostics" not in controls._bindings:
        return snapshot_inputs(await controls.status(run_id), controls.scope)
    todo, seen, pending, questions = [(run_id, 0, None, None)], set(), [], set()
    discovered = {run_id}
    while todo:
        owner, depth, expected_release, expected_manifest = todo.pop()
        if owner in seen or len(seen) >= 4096 or depth > 16:
            raise DefinitionMismatch("Input controls exceed bounded original ownership")
        seen.add(owner)
        info = await controls.input_diagnostics(owner)
        if (
            expected_release is not None
            and info.release_digest != expected_release
            or expected_manifest is not None
            and info.manifest != expected_manifest
        ):
            raise DefinitionMismatch("Input child differs from its original parent release")
        workflow = info.workflow or {}
        backend = workflow.get("backend")
        inputs = snapshot_inputs(
            info.snapshot,
            controls.scope,
            release_digest=info.release_digest,
            aggregate=backend == "temporal-parent",
        )
        for question in inputs:
            if question["pending_id"] in questions or len(questions) >= 4096:
                raise DefinitionMismatch("Input controls exceed bounded original questions")
            questions.add(question["pending_id"])
            pending.append(question)
        calls = workflow.get("children", [])
        if type(calls) is not list or len(seen) + len(todo) + len(calls) > 4096:
            raise DefinitionMismatch("Input child diagnostics exceed bounded ownership")
        if calls and depth >= 16:
            raise DefinitionMismatch("Input child diagnostics exceed bounded depth")
        if backend == "temporal-parent":
            from .temporal_agent_controls import child_identity, validate_pruning

            for call in calls:
                child, release = child_identity(controls.scope, owner, info, call)
                if child in discovered or len(discovered) >= 4096:
                    raise DefinitionMismatch("Input child ownership is cyclic or duplicated")
                discovered.add(child)
                if not call["started"] or call["settled"]:
                    validate_pruning(call, SimpleNamespace(run_id=child))
                    continue
                todo.append((child, depth + 1, release, info.manifest))
        elif calls:
            if controls._async or "parent_run_id" not in controls._bindings:
                raise DefinitionMismatch("Input children require original verifiable ownership")
            for call in calls:
                if type(call) is not dict or type(call.get("run_id")) is not str:
                    raise DefinitionMismatch("Input child has no original Run identity")
                child = call["run_id"]
                if child in discovered or len(discovered) >= 4096:
                    raise DefinitionMismatch("Input child ownership is cyclic or duplicated")
                discovered.add(child)
                if await controls.input_parent(child) != owner:
                    raise DefinitionMismatch("Input child differs from its original parent")
                todo.append((child, depth + 1, None, None))
    return pending
