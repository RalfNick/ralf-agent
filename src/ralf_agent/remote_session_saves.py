"""Required remote Session saves journaled by the original Run authority.

A remote write and a local commit are separate transactions. An unknown write
holds its Turn; explicit recovery inspects the stable message identity first.
"""

from dataclasses import asdict

from .binding_sessions import SessionView
from .errors import DefinitionMismatch, RalfError
from .memory import memory_call
from .session_receipts import supports_remote_session, validate_inspection
from .session_types import SessionKey, TurnAdmission
from .types import Scope, canonical, digest

TERMINAL = {"succeeded", "failed", "cancelled"}


def _scope(turn):
    return Scope(turn.session.key.workspace, turn.session.key.principal)


def validate_remote_binding(state, revision, local_resource_id):
    key = SessionKey.from_dict(state["key"])
    binding = state["bindings"].get(str(revision))
    if not isinstance(binding, dict):
        raise DefinitionMismatch("Original Session binding unavailable")
    remote = binding.get("remote_session")
    if remote is None:
        if key.resource_id != local_resource_id or "remote_session" in binding:
            raise DefinitionMismatch("Original remote Session evidence unavailable")
        return None
    if (
        type(remote) is not dict
        or set(remote) != {"backend_id", "namespace", "receipt_version"}
        or not isinstance(remote["backend_id"], str)
        or not remote["backend_id"].strip()
        or type(remote["receipt_version"]) is not int
        or remote["receipt_version"] != 1
        or remote["namespace"] != key.namespace
        or key.resource_id != digest(["remote-session-resource-v1", remote["backend_id"]])
    ):
        raise DefinitionMismatch("Original remote Session descriptor differs")
    return remote


def _original(engine, run):
    if "session_turn" not in run:
        if "remote_session_binding" in run or "remote_session_saves" in run:
            raise DefinitionMismatch("Remote save lost its original Turn")
        return None
    from .local_sessions import LocalSessionAuthority

    turn = TurnAdmission.from_dict(run["session_turn"])
    authority = LocalSessionAuthority(engine, turn.run.authority_locator)
    state = authority.validate(turn.session)
    binding = state["bindings"][str(turn.session.binding_revision)]
    remote = binding.get("remote_session")
    if remote is None:
        if "remote_session_binding" in run or "remote_session_saves" in run:
            raise DefinitionMismatch("Original remote Session admission evidence differs")
        return None
    if (
        run.get("remote_session_binding") != remote
        or turn.run.run_id != run["id"]
        or turn.run.release_digest != run["release_digest"]
        or run["session_id"]
        != (
            turn.session.key.storage_key
            if run["definition"]["kind"] in {"graph", "team", "dynamic"}
            else turn.session.key.session_id
        )
        or binding["manifest"] != run["manifest"]
    ):
        raise DefinitionMismatch("Remote Turn differs from its admitted Run")
    return turn, binding, remote


def check_remote_session_run(engine, run):
    original = _original(engine, run)
    if original is None:
        return
    from .agent_harness import AgentHarness
    from .local_sessions import LocalSessionAuthority

    turn, binding, _ = original
    _validated_saves(run, turn, original[2])
    harness = AgentHarness.__new__(AgentHarness)
    object.__setattr__(harness, "_definition_json", canonical(binding["definition"]))
    try:
        key, current = LocalSessionAuthority(engine, turn.run.authority_locator)._pin(
            harness, turn.session.key.session_id, namespace=turn.session.key.namespace
        )
    except RalfError as exc:
        raise DefinitionMismatch("Original remote Session resource is unavailable") from exc
    if key != turn.session.key or current != binding:
        raise DefinitionMismatch("Original remote Session publication changed")


def _message(run, node, result):
    return {
        "role": "assistant",
        "content": result,
        "agent": run["definition"]["steps"][node]["name"],
        "task": run["input"],
    }


def _model(run, node):
    action = next(
        (
            a
            for a in reversed(run["actions"])
            if a["node"] == node
            and a["kind"] == "model"
            and a["status"] == "completed"
            and not a["response"]["tool_calls"]
        ),
        None,
    )
    if action is None:
        raise DefinitionMismatch("Remote save has no adopted model output")
    return action


def _intent(run, node, result, turn, remote):
    return {
        "node": node,
        "scope": asdict(_scope(turn)),
        "address": turn.session.key.storage_key,
        "backend_id": remote["backend_id"],
        "message_id": f"{run['id']}:{node}:result",
        "message": _message(run, node, result),
        "model_action_id": _model(run, node)["id"],
        "attempts": 0,
        "receipt": None,
    }


def _validate_intent(run, value, turn, remote):
    from .decisions import final_output

    if type(value) is not dict or type(value.get("node")) is not int:
        raise DefinitionMismatch("Remote save intent is invalid")
    node = value["node"]
    if not 0 <= node < len(run["definition"]["steps"]):
        raise DefinitionMismatch("Remote save node differs")
    model = _model(run, node)
    result = final_output(
        model["response"]["output"], run["definition"]["steps"][node]["output_schema"]
    )
    expected = _intent(run, node, result, turn, remote)
    if (
        set(value) != set(expected)
        or any(value[k] != v for k, v in expected.items() if k not in {"attempts", "receipt"})
        or type(value["attempts"]) is not int
        or value["attempts"] < 0
    ):
        raise DefinitionMismatch("Remote save intent differs from adopted output")
    if value["receipt"] is not None:
        try:
            evidence = validate_inspection(
                value["receipt"], _scope(turn), value["address"], value["message_id"]
            )
        except RalfError as exc:
            raise DefinitionMismatch("Remote save receipt is invalid") from exc
        if evidence["receipt"] is None or canonical(evidence["receipt"]["message"]) != canonical(
            value["message"]
        ):
            raise DefinitionMismatch("Remote save receipt differs from intended message")
    return value


def remote_saves_settled(engine, run):
    original = _original(engine, run)
    if original is None:
        return True
    turn, _, remote = original
    saves = _validated_saves(run, turn, remote)
    for value in saves.values():
        if value["receipt"] is None:
            return False
    if run["state"] == "succeeded":
        if run["definition"]["kind"] in {"graph", "team", "dynamic"}:
            return set(saves) == {"turn"} and saves["turn"]["message"]["content"] == run["result"]
        if set(saves) != {str(i) for i in range(len(run["definition"]["steps"]))}:
            return False
        if saves[str(len(saves) - 1)]["message"]["content"] != run["result"]:
            return False
    return True


def _validated_saves(run, turn, remote):
    if run["definition"]["kind"] in {"graph", "team", "dynamic"}:
        from .remote_composite_saves import validate_saves

        return validate_saves(run, turn, remote)
    saves = run.get("remote_session_saves")
    if type(saves) is not dict:
        raise DefinitionMismatch("Remote save journal is invalid")
    intents = {}
    for action in run["actions"]:
        if "remote_session_save" not in action:
            continue
        marker = action["remote_session_save"]
        if (
            action["kind"] != "model"
            or action["status"] != "completed"
            or type(marker) is not dict
            or set(marker) != {"node", "message_id"}
            or type(marker["node"]) is not int
            or marker["node"] != action["node"]
            or marker["message_id"] != f"{run['id']}:{action['node']}:result"
            or str(marker["node"]) in intents
        ):
            raise DefinitionMismatch("Independent remote save intent evidence is invalid")
        intents[str(marker["node"])] = action["id"]
    if set(saves) != set(intents):
        raise DefinitionMismatch("Remote save journal differs from independent model intent")
    for key, value in saves.items():
        _validate_intent(run, value, turn, remote)
        if key != str(value["node"]) or value["model_action_id"] != intents[key]:
            raise DefinitionMismatch("Remote save journal node key differs")
    return saves


def pending_remote_saves(engine, run):
    original = _original(engine, run)
    if original is None:
        return []
    turn, _, remote = original
    pending = []
    for value in _validated_saves(run, turn, remote).values():
        if value["receipt"] is None:
            pending.append(
                {
                    "kind": "reconciliation",
                    "source": "remote_session",
                    "node": value["node"],
                    "message_id": value["message_id"],
                }
            )
    return pending


def _backend(engine, run, node, remote):
    backend = engine._components(run, index=node).sessions
    actual = backend.backend if isinstance(backend, SessionView) else backend
    if not supports_remote_session(actual) or actual.backend_id != remote["backend_id"]:
        raise DefinitionMismatch("The executing remote Session backend changed")
    return backend


async def _inspect(engine, run, backend, intent):
    value = await memory_call(
        backend.inspect_message, engine.scope, run["session_id"], intent["message_id"]
    )
    return validate_inspection(value, engine.scope, intent["address"], intent["message_id"])


def _record_receipt(engine, run_id, node, evidence):
    with engine.store.transaction():
        run = engine._authorized(run_id)
        engine._check_release(run)
        turn, _, remote = _original(engine, run)
        value = run["remote_session_saves"][str(node)]
        _validate_intent(run, value, turn, remote)
        if evidence["receipt"] is None or canonical(evidence["receipt"]["message"]) != canonical(
            value["message"]
        ):
            raise DefinitionMismatch("Remote backend receipt conflicts with intended message")
        value["receipt"] = evidence
        engine._commit(
            run, "remote_session_save_confirmed", {"node": node, "message_id": value["message_id"]}
        )


def _pause(engine, run_id, node):
    with engine.store.transaction():
        run = engine._authorized(run_id)
        if run["state"] not in TERMINAL and run["state"] != "cancelling":
            run["state"] = "waiting_reconciliation"
        engine._commit(run, "remote_session_save_unconfirmed", {"node": node})


async def save_remote_result(engine, run_id, result):
    run = engine._authorized(run_id)
    if run["definition"]["kind"] in {"graph", "team", "dynamic"}:
        return None
    original = _original(engine, run)
    if original is None:
        return None
    turn, _, remote = original
    node = run["node"]
    backend = _backend(engine, run, node, remote)
    expected = _intent(run, node, result, turn, remote)
    with engine.store.transaction():
        run = engine._authorized(run_id)
        saves = _validated_saves(run, turn, remote)
        if str(node) not in saves:
            saves[str(node)] = expected
            _model(run, node)["remote_session_save"] = {
                "node": node,
                "message_id": expected["message_id"],
            }
            engine._commit(
                run,
                "remote_session_save_intended",
                {"node": node, "message_id": expected["message_id"]},
            )
        value = _validate_intent(run, saves[str(node)], turn, remote)
        if value["receipt"] is not None:
            return True
    try:
        evidence = await _inspect(engine, run, backend, value)
    except Exception:
        _pause(engine, run_id, node)
        return False
    engine._check_release(engine._authorized(run_id))
    if evidence["receipt"] is not None:
        _record_receipt(engine, run_id, node, evidence)
        return True
    with engine.store.transaction():
        run = engine._authorized(run_id)
        if run["state"] in TERMINAL or run["state"] == "cancelling":
            return False
        value = run["remote_session_saves"][str(node)]
        value["attempts"] += 1
        engine._commit(
            run, "remote_session_save_dispatched", {"node": node, "attempt": value["attempts"]}
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
        _pause(engine, run_id, node)
        return False
    if evidence["receipt"] is None:
        _pause(engine, run_id, node)
        return False
    _record_receipt(engine, run_id, node, evidence)
    return True


async def reconcile_terminal_saves(engine, run_id):
    run = engine._authorized(run_id)
    if run["definition"]["kind"] in {"graph", "team", "dynamic"}:
        from .remote_composite_saves import recover_terminal

        return await recover_terminal(engine, run_id)
    original = _original(engine, run)
    if original is None:
        return
    engine._check_release(run)
    turn, _, remote = original
    for value in _validated_saves(run, turn, remote).values():
        if value["receipt"] is not None:
            continue
        backend = _backend(engine, run, value["node"], remote)
        try:
            evidence = await _inspect(engine, run, backend, value)
        except Exception:
            continue
        if evidence["receipt"] is not None:
            _record_receipt(engine, run_id, value["node"], evidence)
