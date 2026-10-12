"""Remote native candidates and exact receipts in the original Local Run journal.

The caller retains the original guarded task and real thread ownership. A receipt
confirms external storage only; root success remains the publication authority.
"""

import asyncio
import copy

from .binding_sessions import session_storage_key
from .errors import DefinitionMismatch, RalfError
from .local_session_model_history import (
    _index,
    _node,
    _registration,
    _same_native_connection,
    native_source_identity,
)
from .memory import memory_call
from .session_model_history import native_history_address, validate_native_history_envelope
from .session_receipts import validate_inspection
from .types import Scope, digest

TERMINAL = {"succeeded", "failed", "cancelled", "cancelling"}


def _original(owner, node, record):
    try:
        journal = owner["native_model_history"]
        stage = journal["stages"][node]
        if (
            type(record) is not dict
            or set(record) != {"envelope", "message_id", "source_action"}
            or journal["episodes"].get(node) != record
            or journal["markers"].get(node) != digest(stage)
            or journal["episode_markers"].get(node) != digest(record)
            or type(stage["snapshot"]["revision"]) is not int
            or stage["snapshot"]["revision"] < 0
            or stage["address"] != native_history_address(stage["stream"])
            or record["envelope"]["source"] != stage["source"]
            or stage["source"]["run_id"] != owner["id"]
            or stage["source"]["node"] != node
            or stage["source"]["release_digest"] != owner["release_digest"]
        ):
            raise DefinitionMismatch("Native save lost its original frozen episode")
        validate_native_history_envelope(record["envelope"], stream=stage["stream"])
        actions = [a for a in owner["actions"] if a["id"] == record["source_action"]]
        index = _index(owner, node)
        messages = [
            message
            for action in owner["actions"]
            if action["node"] == index
            for message in action.get("native_history_messages", [])
        ]
        messages.sort(key=lambda message: message["order"])
        if (
            len(actions) != 1
            or actions[0]["kind"] != "model"
            or actions[0]["status"] != "completed"
            or actions[0]["node"] != index
            or actions[0]["response"]["tool_calls"]
            or digest(actions[0]["response"]) != record["envelope"]["final_digest"]
            or "received_response" not in actions[0]
            or record["envelope"]["history"][1]["content"] != stage["current_task"]
            or [message["order"] for message in messages]
            != list(range(2, len(record["envelope"]["history"])))
            or [message["message"] for message in messages] != record["envelope"]["history"][2:]
            or record["message_id"]
            != "ralf-native-turn-v1:" + digest([stage["source"], actions[0]["id"]])
        ):
            raise DefinitionMismatch("Native save differs from its adopted model action")
        return stage, actions[0]
    except (KeyError, TypeError, ValueError, RalfError) as exc:
        if isinstance(exc, DefinitionMismatch):
            raise
        raise DefinitionMismatch("Native save requires complete original episode evidence") from exc


def _intent(owner, node, record):
    stage, _ = _original(owner, node, record)
    try:
        return {
            "node": node,
            "scope": copy.deepcopy(owner["scope"]),
            "address": session_storage_key(stage["target"]["namespace"], stage["address"]),
            "target": copy.deepcopy(stage["target"]),
            "stage_digest": digest(stage),
            "episode_digest": digest(record),
            "expected_revision": stage["snapshot"]["revision"],
            "message_id": record["message_id"],
            "envelope": copy.deepcopy(record["envelope"]),
            "source_action": record["source_action"],
        }
    except (KeyError, TypeError, RalfError) as exc:
        raise DefinitionMismatch("Native save intent lost its original target") from exc


def _action_marker(intent):
    return {
        "node": intent["node"],
        "message_id": intent["message_id"],
        "intent_digest": digest(intent),
    }


def validate_native_save(owner, node, record):
    """Return storage evidence only when original Run intent and all markers agree."""
    expected = _intent(owner, node, record)
    journal = owner["native_model_history"]
    _, action = _original(owner, node, record)
    value = journal.get("saves", {}).get(node)
    marker = journal.get("save_markers", {}).get(node)
    if value is None:
        if marker is not None or "native_history_save" in action:
            raise DefinitionMismatch("Native save marker has no original intent")
        return None
    if (
        type(value) is not dict
        or set(value) != {*expected, "attempts", "receipt"}
        or any(value[key] != item for key, item in expected.items())
        or type(value["attempts"]) is not int
        or not 0 <= value["attempts"] < 2**63
        or marker != digest(value)
        or action.get("native_history_save") != _action_marker(expected)
    ):
        raise DefinitionMismatch("Native save intent differs from original Run evidence")
    if value["receipt"] is None:
        return None
    try:
        receipt = validate_inspection(
            value["receipt"],
            Scope(**expected["scope"]),
            expected["address"],
            expected["message_id"],
        )
    except (RalfError, TypeError, ValueError) as exc:
        raise DefinitionMismatch("Native save receipt lost its exact scoped identity") from exc
    if (
        value["attempts"] < 1
        or receipt["receipt"] is None
        or receipt["receipt"]["message"] != expected["envelope"]
        or receipt["receipt"]["revision"] != expected["expected_revision"] + 1
    ):
        raise DefinitionMismatch("Native save receipt differs from its fixed CAS and envelope")
    return {**copy.deepcopy(record), "revision": receipt["receipt"]["revision"], "receipt": receipt}


def native_saves_settled(owner):
    """Unknown dispatched effects keep their original Run/Turn responsibility."""
    journal = owner.get("native_model_history", {})
    saves = journal.get("saves", {})
    if type(saves) is not dict or type(journal.get("save_markers", {})) is not dict:
        raise DefinitionMismatch("Native save journal requires original mappings")
    if set(journal.get("save_markers", {})) != set(saves):
        raise DefinitionMismatch("Native save markers differ from original intents")
    action_nodes = []
    for action in owner.get("actions", []):
        marker = action.get("native_history_save")
        if marker is not None:
            if type(marker) is not dict or set(marker) != {"node", "message_id", "intent_digest"}:
                raise DefinitionMismatch("Native save has an invalid independent model marker")
            action_nodes.append(marker["node"])
    if len(set(action_nodes)) != len(action_nodes) or set(action_nodes) != set(saves):
        raise DefinitionMismatch("Native saves differ from their independent model intents")
    settled = True
    for node, value in saves.items():
        record = journal.get("episodes", {}).get(node)
        evidence = validate_native_save(owner, node, record)
        if evidence is None and (
            value["attempts"] > 0 or owner["state"] not in {"failed", "cancelled", "cancelling"}
        ):
            settled = False
    return settled


def _check(engine, run_id, intent, *, retired=False):
    owner = engine._authorized(run_id)
    engine._check_release(owner)
    node = intent["node"]
    if not retired and _node(owner) != node:
        raise DefinitionMismatch("Native save changed its original execution node")
    record = owner["native_model_history"]["episodes"][node]
    if _intent(owner, node, record) != intent:
        raise DefinitionMismatch("Native save stage or frozen episode changed during actual I/O")
    validate_native_save(owner, node, record)
    sessions = engine._components(owner, _index(owner, node)).sessions
    registration, _ = _registration(engine, sessions)
    if native_source_identity(engine, sessions) != intent["target"]:
        raise DefinitionMismatch("Native save Session source differs from original release")
    registration.check()
    for fixed in (registration.dataset_fixed, registration.dataset_bridge_fixed):
        if fixed is not None:
            fixed.check()
    return owner, registration


async def _call(engine, run_id, intent, name, *args, retired=False, **kwargs):
    _, registration = _check(engine, run_id, intent, retired=retired)
    value = await memory_call(getattr(registration.backend, name), *args, **kwargs)
    _check(engine, run_id, intent, retired=retired)
    return value


async def _dataset(engine, run_id, intent, *, retired=False):
    value = await _call(engine, run_id, intent, "inspect_session_identity", retired=retired)
    if (
        type(value) is not str
        or digest(["ralf-session-dataset-v1", value]) != intent["target"]["dataset_id"]
    ):
        raise DefinitionMismatch("Native save actual Session dataset changed")


async def _inspect(engine, run_id, intent, *, retired=False):
    raw = await _call(
        engine,
        run_id,
        intent,
        "inspect_message",
        engine.scope,
        intent["address"],
        intent["message_id"],
        retired=retired,
    )
    try:
        value = validate_inspection(raw, engine.scope, intent["address"], intent["message_id"])
    except RalfError as exc:
        raise DefinitionMismatch("Native save received invalid exact inspection evidence") from exc
    if value["receipt"] is not None and (
        value["receipt"]["message"] != intent["envelope"]
        or value["receipt"]["revision"] != intent["expected_revision"] + 1
    ):
        raise DefinitionMismatch("Native save found a conflicting stable message receipt")
    return value


def _pause(engine, run_id, intent, *, conflict=False):
    with engine.store.transaction():
        owner, _ = _check(engine, run_id, intent)
        if owner["state"] not in TERMINAL:
            owner["state"] = "waiting_reconciliation"
        engine._commit(
            owner,
            "native_history_save_cas_conflict" if conflict else "native_history_save_unconfirmed",
            {"node": intent["node"], "message_id": intent["message_id"]},
        )


def _adopt(engine, run_id, intent, evidence, *, retired=False):
    with engine.store.transaction():
        owner, _ = _check(engine, run_id, intent, retired=retired)
        journal = owner["native_model_history"]
        value = journal["saves"][intent["node"]]
        value["receipt"] = copy.deepcopy(evidence)
        journal["save_markers"][intent["node"]] = digest(value)
        validate_native_save(owner, intent["node"], journal["episodes"][intent["node"]])
        engine._commit(
            owner,
            "native_history_save_confirmed",
            {"node": intent["node"], "message_id": intent["message_id"]},
        )
        return owner["state"] not in TERMINAL


async def ensure_native_history_saved(engine, run_id):
    """Inspect stable identity, write with accepted CAS, then adopt exact receipt.

    Re-entry after dispatch requires the caller's original task and real thread
    to have exited. Same ID/CAS may retry an absent receipt; latest CAS is unused.
    """
    owner = engine._authorized(run_id)
    if engine._step_manifest(owner).get("model_history_protocol") != 2:
        return True
    node = _node(owner)
    record = owner.get("native_model_history", {}).get("episodes", {}).get(node)
    intent = _intent(owner, node, record)
    _, registration = _check(engine, run_id, intent)
    backend = registration.backend
    if _same_native_connection(engine.store, backend):
        return True
    with engine.store.transaction():
        owner, _ = _check(engine, run_id, intent)
        journal = owner["native_model_history"]
        saves, markers = journal.setdefault("saves", {}), journal.setdefault("save_markers", {})
        if node not in saves:
            if owner["state"] in TERMINAL:
                return False
            saves[node] = {**copy.deepcopy(intent), "attempts": 0, "receipt": None}
            markers[node] = digest(saves[node])
            _, action = _original(owner, node, record)
            action["native_history_save"] = _action_marker(intent)
            engine._commit(
                owner,
                "native_history_save_intended",
                {"node": node, "message_id": intent["message_id"]},
            )
    try:
        await _dataset(engine, run_id, intent)
        owner, _ = _check(engine, run_id, intent)
        if validate_native_save(owner, node, record) is not None:
            return owner["state"] not in TERMINAL
        evidence = await _inspect(engine, run_id, intent)
        await _dataset(engine, run_id, intent)
        if evidence["receipt"] is not None:
            return _adopt(engine, run_id, intent, evidence)
        if evidence["revision"] != intent["expected_revision"]:
            _pause(engine, run_id, intent, conflict=True)
            return False
        with engine.store.transaction():
            owner, _ = _check(engine, run_id, intent)
            if owner["state"] in TERMINAL or engine._threads.has_active_for(run_id):
                return False
            journal = owner["native_model_history"]
            value = journal["saves"][node]
            value["attempts"] += 1
            journal["save_markers"][node] = digest(value)
            engine._commit(
                owner,
                "native_history_save_dispatched",
                {"node": node, "attempt": value["attempts"]},
            )
        revision = await _call(
            engine,
            run_id,
            intent,
            "append",
            engine.scope,
            intent["address"],
            copy.deepcopy(intent["envelope"]),
            expected_revision=intent["expected_revision"],
            message_id=intent["message_id"],
        )
        if type(revision) is not int or revision != intent["expected_revision"] + 1:
            raise DefinitionMismatch("Native append ACK differs from original CAS")
        await _dataset(engine, run_id, intent)
        evidence = await _inspect(engine, run_id, intent)
        await _dataset(engine, run_id, intent)
        if evidence["receipt"] is None:
            _pause(engine, run_id, intent)
            return False
        return _adopt(engine, run_id, intent, evidence)
    except DefinitionMismatch:
        raise
    except asyncio.CancelledError:
        _pause(engine, run_id, intent)
        raise
    except Exception:
        _pause(engine, run_id, intent)
        return False


async def recover_terminal_native_saves(engine, run_id):
    """Inspect original retired node IDs; never dispatch a new terminal append."""
    owner = engine._authorized(run_id)
    if owner["state"] not in TERMINAL:
        raise DefinitionMismatch("Terminal native recovery requires an original terminal Run")
    native_saves_settled(owner)
    journal = owner.get("native_model_history", {})
    for node, value in journal.get("saves", {}).items():
        if value["receipt"] is not None or value["attempts"] == 0:
            continue
        intent = _intent(owner, node, journal["episodes"][node])
        try:
            await _dataset(engine, run_id, intent, retired=True)
            evidence = await _inspect(engine, run_id, intent, retired=True)
            await _dataset(engine, run_id, intent, retired=True)
        except DefinitionMismatch:
            raise
        except Exception:
            continue
        if evidence["receipt"] is not None:
            _adopt(engine, run_id, intent, evidence, retired=True)
