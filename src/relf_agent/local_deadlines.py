"""Persistent deadline facts and observer timers over the original Local authority."""

import asyncio
import copy
import math
import time
import uuid

from .errors import DefinitionMismatch, NotFound, ValidationError
from .governance import LocalExecutionPolicy
from .ports import _invoke_sync_none, is_sync_callable
from .types import digest

TERMINAL = {"succeeded", "failed", "cancelled"}


def epoch(value):
    try:
        valid = type(value) in (int, float) and value > 0 and math.isfinite(value)
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise ValidationError("Deadline requires finite positive UTC epoch seconds")
    return value


def registration(store):
    from .task_controls import _binding

    version = getattr(store, "local_deadline_version", None)
    if version is None:
        return None
    method = getattr(store, "prepare_local_deadlines", None)
    if type(version) is not int or version != 1 or not is_sync_callable(method):
        raise ValidationError("Local deadlines require the completed optional Store capability")
    return store, store.backend_id, _binding(method)


def check_store(engine):
    from .binding_artifacts import _same_binding

    current, original = registration(engine.store), engine._deadline_store_pin
    if (
        current is None
        or original is None
        or current[0] is not original[0]
        or current[1] != original[1]
        or not _same_binding(current[2], original[2])
    ):
        raise DefinitionMismatch("Original deadline Store capability changed or is unavailable")


def policy_identity(engine):
    policy = engine.execution_policy
    if policy is not engine._execution_policy_pin:
        raise DefinitionMismatch("Original Local execution policy changed")
    current = None if policy is None else policy.identity
    if current != engine._execution_policy_identity:
        raise DefinitionMismatch("Original Local execution policy identity changed")
    return copy.deepcopy(current)


def publish(engine, manifest, run=None):
    policy = policy_identity(engine)
    if policy is not None or (run is not None and "local_deadlines" in run):
        manifest.update(local_deadline_protocol=1, execution_policy=policy)
    return manifest


def accept(engine, data, requested_deadline_at=None):
    identity = policy_identity(engine)
    parent = data.get("parent_call")
    parent_deadline = (
        engine._authorized(parent["parent_id"]).get("local_deadlines", {}).get("run_expires_at")
        if parent is not None
        else None
    )
    if identity is None and requested_deadline_at is None and parent_deadline is None:
        return
    check_store(engine)
    _invoke_sync_none(engine.store.prepare_local_deadlines, "Local deadline preparation")
    check_store(engine)
    accepted_at = epoch(time.time())
    policy = (
        LocalExecutionPolicy() if identity is None else LocalExecutionPolicy.from_identity(identity)
    )
    candidates = [value for value in (requested_deadline_at, parent_deadline) if value is not None]
    if policy.run_timeout_seconds is not None:
        candidates.append(accepted_at + policy.run_timeout_seconds)
    data["local_deadlines"] = {
        "version": 1,
        "accepted_at": accepted_at,
        "requested_deadline_at": requested_deadline_at,
        "parent_run_expires_at": parent_deadline,
        "run_expires_at": min(candidates) if candidates else None,
    }
    data["local_deadlines_digest"] = digest(data["local_deadlines"])
    publish(engine, data["manifest"], data)
    data["release_digest"] = digest(
        {"definition": data["definition"], "manifest": data["manifest"]}
    )


def validate(engine, run):
    value = run.get("local_deadlines")
    if value is None:
        if "local_deadline_protocol" in run["manifest"]:
            # A parallel node frame has no second deadline journal.
            from .node_coding_projection import original_engine

            if original_engine(engine) is engine:
                raise DefinitionMismatch("Original Local deadline facts are missing")
        return
    check_store(engine)
    if (
        type(value) is not dict
        or set(value)
        != {
            "version",
            "accepted_at",
            "requested_deadline_at",
            "parent_run_expires_at",
            "run_expires_at",
        }
        or type(value["version"]) is not int
        or value["version"] != 1
        or run.get("local_deadlines_digest") != digest(value)
        or run["manifest"].get("local_deadline_protocol") != 1
    ):
        raise DefinitionMismatch("Original Local deadline journal changed")
    for name, number in value.items():
        if name != "version" and number is not None:
            epoch(number)
    identity = run["manifest"]["execution_policy"]
    policy = (
        LocalExecutionPolicy() if identity is None else LocalExecutionPolicy.from_identity(identity)
    )
    for action in run["actions"]:
        fields = {"approval_requested_at", "approval_expires_at", "approval_deadline_digest"}
        present = fields.intersection(action)
        required = action["status"] == "waiting_approval" and (
            policy.approval_timeout_seconds is not None or value["run_expires_at"] is not None
        )
        if not present and not required:
            continue
        if present != fields:
            raise DefinitionMismatch("Original approval deadline facts are missing")
        requested = epoch(action["approval_requested_at"])
        expires = epoch(action["approval_expires_at"])
        approval_values = [value["run_expires_at"]]
        if policy.approval_timeout_seconds is not None:
            approval_values.append(requested + policy.approval_timeout_seconds)
        approval_values = [number for number in approval_values if number is not None]
        if (
            not approval_values
            or expires != min(approval_values)
            or action["approval_deadline_digest"] != digest([requested, expires])
        ):
            raise DefinitionMismatch("Original approval deadline changed")
    candidates = [
        number
        for number in (value["requested_deadline_at"], value["parent_run_expires_at"])
        if number is not None
    ]
    if policy.run_timeout_seconds is not None:
        candidates.append(value["accepted_at"] + policy.run_timeout_seconds)
    if value["run_expires_at"] != (min(candidates) if candidates else None):
        raise DefinitionMismatch("Original Local deadline resolution changed")
    if run.get("parent_call") is not None:
        parent = engine._authorized(run["parent_call"]["parent_id"])
        if value["parent_run_expires_at"] != parent.get("local_deadlines", {}).get(
            "run_expires_at"
        ):
            raise DefinitionMismatch("Original parent deadline changed")


def approval(engine, run, action):
    from .node_coding_projection import original_engine

    owner = original_engine(engine)
    original = owner._authorized(run["id"])
    if "local_deadlines" not in original or "approval_expires_at" in action:
        return
    identity = original["manifest"]["execution_policy"]
    policy = (
        LocalExecutionPolicy() if identity is None else LocalExecutionPolicy.from_identity(identity)
    )
    requested_at = epoch(time.time())
    candidates = [original["local_deadlines"]["run_expires_at"]]
    if policy.approval_timeout_seconds is not None:
        candidates.append(requested_at + policy.approval_timeout_seconds)
    candidates = [value for value in candidates if value is not None]
    if not candidates:
        return
    action.update(approval_requested_at=requested_at, approval_expires_at=min(candidates))
    action["approval_deadline_digest"] = digest([requested_at, action["approval_expires_at"]])
    engine.store.emit(
        run["id"],
        "approval_expiry_recorded",
        {"action_id": action["id"], "expires_at": action["approval_expires_at"]},
    )


def due(run):
    if run["state"] in TERMINAL | {"cancelling"} or "local_deadlines" not in run:
        return None
    values = []
    deadline = run["local_deadlines"]["run_expires_at"]
    if deadline is not None:
        values.append((deadline, "deadline_exceeded", None))
    values.extend(
        (action["approval_expires_at"], "approval_expired", action["id"])
        for action in run["actions"]
        if action["status"] == "waiting_approval" and "approval_expires_at" in action
    )
    return (
        min(values, key=lambda value: (value[0], value[1] != "deadline_exceeded"))
        if values
        else None
    )


def checkpoint(engine, run_id):
    from .node_coding_projection import original_engine

    owner = original_engine(engine)
    run = owner._authorized(run_id)
    target = due(run)
    if target is None or target[0] > time.time():
        return False
    owner._check_release(run)
    with owner.store.transaction():
        run = owner._authorized(run_id)
        target = due(run)
        if target is None or target[0] > time.time():
            return False
        deadline, code, action_id = target
        owner.cancel(run_id, command_id="local-deadline:" + uuid.uuid4().hex)
        run = owner._authorized(run_id)
        run["error"] = {"code": code}
        if code == "approval_expired":
            run["delegated_failure"] = {"code": code, "terminal": "failed"}
            if run["state"] == "cancelled":
                run["state"] = "failed"
        owner._commit(
            run,
            "local_deadline_applied",
            {"code": code, "expires_at": deadline, "action_id": action_id},
        )
        _propagate(owner, run, code)
    return True


def _propagate(owner, source, code):
    seen = {source["id"]}
    while source.get("parent_call") is not None:
        parent_id = owner.parent_run_id(source["id"])
        if parent_id is None or parent_id in seen:
            raise DefinitionMismatch("Deadline ancestor ownership is invalid")
        seen.add(parent_id)
        parent = owner._authorized(parent_id)
        if parent["state"] not in TERMINAL | {"cancelling"}:
            owner._check_release(parent)
            owner.cancel(parent_id, command_id="local-deadline-parent:" + uuid.uuid4().hex)
            parent = owner._authorized(parent_id)
            parent["error"] = {"code": code, "cause_run_id": source["id"]}
            if code == "approval_expired":
                parent["delegated_failure"] = {"code": code, "terminal": "failed"}
                if parent["state"] == "cancelled":
                    parent["state"] = "failed"
            owner._commit(parent, "descendant_deadline_applied", parent["error"])
        owner._orchestration.observe(parent_id)
        source = owner._authorized(parent_id)


def start_watch(engine, run_id):
    from .node_coding_projection import original_engine

    if original_engine(engine) is not engine or engine._lifecycle != "open":
        return
    run = engine._authorized(run_id)
    if "local_deadlines" in run:
        engine._check_release(run)
        engine._deadline_failures.pop(run_id, None)
    target = due(run)
    previous = engine._deadline_tasks.get(run_id)
    if previous is not None:
        if previous[1] == target and not previous[0].done():
            return
        engine._deadline_tasks.pop(run_id, None)
        previous[0].cancel()
    if target is None:
        return

    # Resolve hosting locators while the original authority is still valid.
    # A failed observer cannot safely query a changed Store to find its owners.
    owners = [run_id]
    while (parent_id := engine.parent_run_id(owners[-1])) is not None:
        if parent_id in owners:
            raise DefinitionMismatch("Cyclic deadline observer ownership")
        engine._check_release(engine._authorized(parent_id))
        owners.append(parent_id)

    async def observe():
        while engine._lifecycle == "open":
            try:
                current = due(engine._authorized(run_id))
            except NotFound:
                return
            if current is None:
                return
            delay = current[0] - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            if engine._lifecycle != "open":
                return
            if checkpoint(engine, run_id):
                return

    task = asyncio.create_task(observe())
    engine._deadline_tasks[run_id] = task, target

    def completed(done):
        owned = engine._deadline_tasks.get(run_id, (None,))[0] is done
        error = None if done.cancelled() else done.exception()
        if owned:
            engine._deadline_tasks.pop(run_id, None)
        cancelled_host = done.cancelled() and owned and engine._lifecycle == "open"
        if owned and (error is not None or cancelled_host):
            code = getattr(error, "code", "deadline_host_failed")
            for owner_id in owners:
                engine._deadline_failures[owner_id] = code

    task.add_done_callback(completed)


def close_watches(engine):
    for task, _ in engine._deadline_tasks.values():
        task.cancel()
    engine._deadline_tasks.clear()
