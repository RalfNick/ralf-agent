"""Colocated composite Turn publication; the existing Run owns success."""

import inspect

from .agent_harness import AgentHarness
from .binding_sessions import SessionView
from .errors import DefinitionMismatch, ValidationError
from .memory import SQLiteMemory
from .run_supervisor import TERMINAL
from .session_types import TurnAdmission
from .types import canonical, digest

KINDS = {"graph", "team", "dynamic"}


def composite_turn_busy(engine, root, hosting):
    todo, seen, busy = [(root, 0)], set(), False
    while todo:
        run, depth = todo.pop()
        if run["id"] in seen or len(seen) >= 4096 or depth > 16:
            raise DefinitionMismatch("Composite Turn ownership exceeds bounded traversal")
        seen.add(run["id"])
        busy |= (
            run["state"] not in TERMINAL
            or engine._operation_active(run["id"])
            or bool(engine._drive_users.get(run["id"]))
            or hosting is not None
            and hosting(run["id"])
            or run.get("workflow", {}).get("quiescent") is False
            or run.get("orchestration", {}).get("quiescent") is False
            or any(
                a["kind"] == "tool"
                and a["status"] in {"executing", "outcome_unknown", "receipt_received"}
                for a in run["actions"]
            )
        )
        # Parallel node actions stay in the parent's original Action journal;
        # frame lifecycle still holds the lane until it has actually stopped.
        for node in run.get("workflow", {}).get("nodes", {}).values():
            frame = node.get("execution")
            if (
                frame is not None
                and frame.get("state") not in TERMINAL
                and not (run["state"] in TERMINAL and node.get("state") in TERMINAL)
            ):
                busy = True
        calls = run.get("orchestration", {}).get("children", [])
        if not isinstance(calls, list):
            raise DefinitionMismatch("Composite child intents must be persisted records")
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("run_id"), str):
                raise DefinitionMismatch("Invalid composite child intent")
            child = engine._authorized(call["run_id"])
            if child.get("parent_id") != run["id"] or child.get("call_id") != call.get("id"):
                raise DefinitionMismatch("Composite child has no original parent ownership")
            todo.append((child, depth + 1))
    return busy


def composite_manifest(engine, definition):
    bound = "binding_definition" in definition
    if definition["kind"] == "graph":
        plan = engine._workflow.compile(definition)
        return (
            engine._bindings.manifest(definition, plan=plan)
            if bound
            else engine._workflow.manifest(plan)
        )
    return (
        engine._bindings.manifest(definition)
        if bound
        else engine._orchestration.manifest(definition)
    )


def conversation_backend(engine):
    backend = engine.sessions
    if isinstance(backend, SessionView):
        backend._check(engine.scope)
        if backend.namespace is not None:
            raise ValidationError("Composite conversation requires the host default namespace")
        backend = backend.backend
    if type(backend) is not SQLiteMemory or backend.store.conn is not getattr(
        engine.store, "conn", None
    ):
        raise ValidationError("Composite conversation requires colocated SQLiteMemory")
    return backend


def result_message(run, result):
    return {
        "role": "assistant",
        "content": result,
        "agent": run["definition"]["name"],
        "task": run["input"],
    }


def save_composite_turn_result(engine, run, result):
    if "session_turn" not in run or run["definition"]["kind"] not in KINDS:
        return
    if not engine.store.conn.in_transaction:
        raise ValidationError("Composite conversation save requires the success transaction")
    from .local_sessions import LocalSessionAuthority
    from .session_conversations import check_conversation_run

    check_conversation_run(engine, run)
    turn = TurnAdmission.from_dict(run["session_turn"])
    authority = LocalSessionAuthority(engine, turn.run.authority_locator)
    state = authority.validate(turn.session)
    binding = state["bindings"][str(turn.session.binding_revision)]
    harness = AgentHarness.__new__(AgentHarness)
    object.__setattr__(harness, "_definition_json", canonical(binding["definition"]))
    key, current = authority._pin(
        harness, turn.session.key.session_id, namespace=turn.session.key.namespace
    )
    if key != turn.session.key or current != binding or current["manifest"] != run["manifest"]:
        raise DefinitionMismatch(
            "Composite conversation differs from its original Turn publication"
        )
    from .session_conversations import select_conversation

    backend = select_conversation(engine, key.namespace)[0]
    revision, _ = backend.read(engine.scope, key.storage_key)
    message, message_id = result_message(run, result), run["id"] + ":turn:result"
    value = backend.append(
        engine.scope, key.storage_key, message, expected_revision=revision, message_id=message_id
    )
    if type(value) is not int or value < 1:
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError("Atomic conversation append requires a completed revision")
    if not authority.store.confirmed_result(engine.scope, key.storage_key, message_id, message):
        raise ValidationError("Required composite conversation result was not saved")
    # The same transaction rolls this evidence back if final Run commit fails.
    engine.store.emit(
        run["id"],
        "session_turn_result_committed",
        {"turn_id": turn.turn_id, "message_id": message_id, "digest": digest(message)},
    )
