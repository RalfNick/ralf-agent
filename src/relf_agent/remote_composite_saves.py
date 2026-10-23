"""Original composite final-result publication over receipt-backed remote data."""

from dataclasses import asdict

from .errors import DefinitionMismatch, RalfError
from .memory import memory_call
from .remote_session_saves import TERMINAL, _inspect, _original, _pause
from .session_composites import KINDS, result_message
from .session_receipts import validate_inspection
from .types import canonical


def _state(run):
    return run["workflow"] if run["definition"]["kind"] == "graph" else run["orchestration"]


def validate_saves(run, turn, remote):
    saves = run.get("remote_session_saves")
    marker = _state(run).get("remote_session_result")
    if type(saves) is not dict or set(saves) - {"turn"}:
        raise DefinitionMismatch("Composite remote save journal is invalid")
    if marker is None:
        if saves or "remote_session_result" in _state(run):
            raise DefinitionMismatch("Composite save lost its accepted final-result evidence")
        return saves
    if (
        type(marker) is not dict
        or set(marker) != {"message_id", "message", "skipped"}
        or set(saves) != {"turn"}
    ):
        raise DefinitionMismatch("Composite save journal differs from its final-result evidence")
    value = saves["turn"]
    if (
        type(value) is not dict
        or set(value)
        != {
            "node",
            "scope",
            "address",
            "backend_id",
            "message_id",
            "message",
            "attempts",
            "receipt",
            "skipped",
        }
        or value["node"] != "turn"
        or value["scope"] != asdict(_scope(turn))
        or value["address"] != turn.session.key.storage_key
        or value["backend_id"] != remote["backend_id"]
        or value["message_id"] != run["id"] + ":turn:result"
        or marker
        != {
            "message_id": value["message_id"],
            "message": value["message"],
            "skipped": value["skipped"],
        }
        or type(value["message"]) is not dict
        or value["message"] != result_message(run, value["message"].get("content"))
        or type(value["attempts"]) is not int
        or value["attempts"] < 0
    ):
        raise DefinitionMismatch("Composite save intent differs from its original Turn")
    if (
        type(value["skipped"]) is not list
        or any(
            not isinstance(node, str)
            or run["definition"]["kind"] != "graph"
            or node not in run["workflow"]["nodes"]
            or run["workflow"]["nodes"][node]["state"] != "skipped"
            for node in value["skipped"]
        )
        or len(set(value["skipped"])) != len(value["skipped"])
    ):
        raise DefinitionMismatch("Composite final skipped decisions differ from accepted nodes")
    canonical(value)
    if value["receipt"] is not None:
        try:
            receipt = validate_inspection(
                value["receipt"], _scope(turn), value["address"], value["message_id"]
            )
        except RalfError as exc:
            raise DefinitionMismatch("Composite save receipt is invalid") from exc
        if receipt["receipt"] is None or canonical(receipt["receipt"]["message"]) != canonical(
            value["message"]
        ):
            raise DefinitionMismatch("Composite receipt differs from its intended result")
    return saves


def _scope(turn):
    from .types import Scope

    return Scope(turn.session.key.workspace, turn.session.key.principal)


def _backend(engine, turn, remote):
    from .session_conversations import select_conversation

    backend = select_conversation(engine, turn.session.key.namespace)[0]
    if backend.backend_id != remote["backend_id"]:
        raise DefinitionMismatch("The executing composite conversation resource changed")
    return backend


def _receipt(engine, run_id, evidence):
    with engine.store.transaction():
        run = engine._authorized(run_id)
        engine._check_release(run)
        turn, _, remote = _original(engine, run)
        value = validate_saves(run, turn, remote)["turn"]
        if evidence["receipt"] is None or canonical(evidence["receipt"]["message"]) != canonical(
            value["message"]
        ):
            raise DefinitionMismatch("Composite remote backend returned a conflicting receipt")
        value["receipt"] = evidence
        engine._commit(
            run,
            "remote_session_save_confirmed",
            {"node": "turn", "message_id": value["message_id"]},
        )


async def save_result(engine, run_id, result, *, skipped=()):
    run = engine._authorized(run_id)
    original = _original(engine, run)
    if original is None:
        return None
    turn, _, remote = original
    backend = _backend(engine, turn, remote)
    message = result_message(run, result)
    with engine.store.transaction():
        run = engine._authorized(run_id)
        engine._check_release(run)
        saves = validate_saves(run, turn, remote)
        if not saves:
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return False
            value = {
                "node": "turn",
                "scope": asdict(engine.scope),
                "address": turn.session.key.storage_key,
                "backend_id": remote["backend_id"],
                "message_id": run_id + ":turn:result",
                "message": message,
                "attempts": 0,
                "receipt": None,
                "skipped": list(skipped),
            }
            saves["turn"] = value
            _state(run)["remote_session_result"] = {
                "message_id": value["message_id"],
                "message": message,
                "skipped": value["skipped"],
            }
            for node in skipped:
                if run["workflow"]["nodes"][node]["state"] != "skipped":
                    run["workflow"]["nodes"][node] = {"state": "skipped"}
                    engine.store.emit(run_id, "workflow_node_skipped", {"node_id": node})
            engine._commit(
                run,
                "remote_session_save_intended",
                {"node": "turn", "message_id": value["message_id"]},
            )
        value = validate_saves(run, turn, remote)["turn"]
        if canonical(value["message"]) != canonical(message):
            raise DefinitionMismatch("Composite final result changed after adoption")
        if value["receipt"] is not None:
            return True
    try:
        evidence = await _inspect(engine, run, backend, value)
    except Exception:
        _pause(engine, run_id, "turn")
        return False
    engine._check_release(engine._authorized(run_id))
    if evidence["receipt"] is not None:
        _receipt(engine, run_id, evidence)
        return True
    with engine.store.transaction():
        run = engine._authorized(run_id)
        if run["state"] in TERMINAL or run["state"] == "cancelling":
            return False
        value = run["remote_session_saves"]["turn"]
        value["attempts"] += 1
        engine._commit(
            run, "remote_session_save_dispatched", {"node": "turn", "attempt": value["attempts"]}
        )
    try:
        await memory_call(
            backend.append,
            engine.scope,
            run["session_id"],
            value["message"],
            expected_revision=evidence["revision"],
            message_id=value["message_id"],
        )
        engine._check_release(engine._authorized(run_id))
        evidence = await _inspect(engine, run, backend, value)
    except DefinitionMismatch:
        raise
    except Exception:
        _pause(engine, run_id, "turn")
        return False
    if evidence["receipt"] is None:
        _pause(engine, run_id, "turn")
        return False
    _receipt(engine, run_id, evidence)
    return True


async def resume_result(engine, run_id):
    run = engine._authorized(run_id)
    if run["definition"]["kind"] not in KINDS or "remote_session_binding" not in run:
        return False
    turn, _, remote = _original(engine, run)
    saves = validate_saves(run, turn, remote)
    if not saves:
        return False
    result = saves["turn"]["message"]["content"]
    saved = await save_result(engine, run_id, result)
    with engine.store.transaction():
        run = engine._authorized(run_id)
        if run["state"] == "cancelling":
            if run.get("orchestration") is not None:
                engine._orchestration.cancel_children(run)
            run["state"] = "cancelled"
            engine._commit(run, "run_cancelled")
    if saved:
        with engine.store.transaction():
            run = engine._authorized(run_id)
            engine._check_release(run)
            if run["state"] not in TERMINAL and run["state"] != "cancelling":
                from .session_composites import save_composite_turn_result

                save_composite_turn_result(engine, run, result)
                run["state"], run["result"] = "succeeded", result
                engine._commit(run, "run_succeeded")
    if run.get("plan", {}).get("schema_version") == 3:
        engine._mark_workflow_quiescent(run_id, supervisor=True)
    return True


async def recover_terminal(engine, run_id):
    run = engine._authorized(run_id)
    original = _original(engine, run)
    if original is None:
        return
    engine._check_release(run)
    turn, _, remote = original
    saves = validate_saves(run, turn, remote)
    if not saves or saves["turn"]["receipt"] is not None:
        return
    backend = _backend(engine, turn, remote)
    try:
        evidence = await _inspect(engine, run, backend, saves["turn"])
    except Exception:
        return
    if evidence["receipt"] is not None:
        _receipt(engine, run_id, evidence)
