"""Bounded observation of controls owned by original Temporal child Histories."""

from dataclasses import asdict

from .errors import DefinitionMismatch
from .run_supervisor import TERMINAL
from .temporal_bindings import request_release_digest
from .types import digest


def child_identity(scope, parent_run_id, info, call):
    if (
        not isinstance(call, dict)
        or type(call.get("started")) is not bool
        or type(call.get("settled")) is not bool
        or not isinstance(call.get("id"), str)
        or not isinstance(call.get("request"), dict)
        or not isinstance(call["request"].get("definition"), dict)
    ):
        raise DefinitionMismatch("Temporal child intent requires original typed evidence")
    scope = asdict(scope)
    command_id = "ralf-child:" + digest([scope, parent_run_id, call["id"]])
    run_id = "ralf-temporal-" + digest([scope, command_id])
    if call.get("command_id") != command_id or call.get("run_id") != run_id:
        raise DefinitionMismatch("Temporal child intent differs from its original parent")
    return run_id, request_release_digest(call["request"], info.manifest)


def child_reference(runtime, parent, info, call):
    run_id, release = child_identity(runtime.scope, parent.run_id, info, call)
    return type(parent)(
        parent.authority_locator,
        parent.workspace,
        parent.principal,
        run_id,
        release,
    )


def validate_pruning(call, child):
    """Prune only evidence consistent with the authority's settlement rules."""
    if not call["started"]:
        if (
            call.get("state") not in ({"cancelled"} if call["settled"] else {"queued"})
            or call.get("spent") != 0
            or call.get("uncertain", False) is not False
            or "snapshot" in call
            or "observed_flow" in call
        ):
            raise DefinitionMismatch("Undispatched child intent contradicts recorded execution")
    elif call["settled"]:
        snapshot, flow = call.get("snapshot"), call.get("observed_flow")
        if (
            call.get("state") not in TERMINAL
            or call.get("uncertain", False) is not False
            or type(call.get("spent")) is not int
            or type(call.get("cap")) is not int
            or not 0 <= call["spent"] <= call["cap"]
            or not isinstance(snapshot, dict)
            or snapshot.get("run_id") != child.run_id
            or snapshot.get("state") != call["state"]
            or snapshot.get("pending") != []
            or not isinstance(snapshot.get("actions"), list)
            or any(
                not isinstance(a, dict) or a.get("status") == "outcome_unknown"
                for a in snapshot["actions"]
            )
            or not isinstance(flow, dict)
            or flow.get("quiescent") is not True
            or flow.get("remote_stop_confirmed") is not True
            or any(
                flow.get(field, False) is not False
                for field in (
                    "unknown_remote_execution",
                    "evidence_ack_pending",
                    "reconciliation_pending",
                )
            )
        ):
            raise DefinitionMismatch("Settled child intent contradicts retained execution evidence")


async def pending_controls(runtime, ref, view):
    info = await runtime._observe_with(view, ref, "diagnostics")
    todo, seen, pending = [(ref, info, 0)], {ref.run_id}, []
    while todo:
        owner, info, depth = todo.pop()
        runtime._validate(owner)
        from .control_discovery import snapshot_inputs

        pending.extend(
            {"ref": owner.to_dict(), **question}
            for question in snapshot_inputs(
                info.snapshot,
                runtime.scope,
                release_digest=owner.release_digest,
                aggregate=info.workflow["backend"] == "temporal-parent",
            )
        )
        if info.workflow["backend"] == "temporal":
            pending.extend(
                {**a, "kind": "approval", "ref": owner.to_dict()}
                for a in info.snapshot.pending
                if a.get("kind") != "input"
            )
            pending.extend(
                {
                    "kind": "reconciliation",
                    "ref": owner.to_dict(),
                    "action_id": a["id"],
                    "digest": a["digest"],
                }
                for a in info.snapshot.actions
                if a["kind"] == "tool" and a["status"] == "outcome_unknown"
            )
            continue
        # Parent pending is an aggregate, possibly stale, with no owner release.
        # Read original intents then obtain fresh diagnostics from actual children.
        calls = info.workflow["children"]
        if len(seen) + len(calls) > 4096 or calls and depth >= 16:
            raise DefinitionMismatch("Temporal controls exceed bounded ownership traversal")
        for call in calls:
            child = child_reference(runtime, owner, info, call)
            if child.run_id in seen:
                raise DefinitionMismatch("Temporal child intents are cyclic or duplicated")
            seen.add(child.run_id)
            if not call["started"] or call["settled"]:
                validate_pruning(call, child)
                continue
            value = await runtime._observe_with(view, child, "diagnostics")
            if value.manifest != info.manifest:
                raise DefinitionMismatch("Temporal child manifest differs from its parent")
            todo.append((child, value, depth + 1))
    return pending
