"""Root success publishes native evidence; Session data never grants eligibility."""

import copy
import inspect
from contextlib import AbstractAsyncContextManager, AbstractContextManager

from .binding_manifests import step_manifest
from .errors import DefinitionMismatch, RalfError, ValidationError
from .ports import is_sync_callable
from .session_model_history import _MAX_BYTES, _json_data, validate_native_history_envelope
from .session_receipts import validate_inspection
from .session_types import TurnAdmission
from .storage import SQLiteStore
from .types import canonical, digest

_PUBLICATION_METHODS = (
    "prepare_native_history",
    "native_history_publications",
    "publish_native_history",
)


def _close_deferred_publication(value):
    """Close lazy evidence without entering a context or awaiting business work."""
    pending, seen = [value], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        try:
            if inspect.iscoroutine(current) or inspect.isgenerator(current):
                current.close()
            elif inspect.isasyncgen(current):
                closing = current.aclose()
                try:
                    closing.send(None)
                except StopIteration:
                    pass
                finally:
                    closing.close()
            elif isinstance(current, (AbstractContextManager, AbstractAsyncContextManager)):
                pending.append(getattr(current, "gen", None))
            elif inspect.isawaitable(current):
                close = getattr(current, "close", None)
                if callable(close):
                    close()
            elif isinstance(current, dict):
                pending.extend(current.values())
            elif isinstance(current, (list, tuple)):
                pending.extend(current)
        except Exception:
            # Cleanup of an invalid adapter result cannot replace typed refusal.
            continue


def _publication_call(store, name, *args):
    """Only completed original Store facts may establish native publication."""
    value = None
    try:
        version = getattr(store, "native_history_version", None)
        if (
            type(version) is not int
            or version != 1
            or any(
                not is_sync_callable(getattr(store, method, None))
                for method in _PUBLICATION_METHODS
            )
        ):
            raise ValidationError("Session model history requires synchronous publication ports")
        if name not in _PUBLICATION_METHODS:
            raise ValidationError("Unsupported native publication port operation")
        value = getattr(store, name)(*args)
        if name != "native_history_publications":
            if value is not None:
                raise ValidationError("Native publication mutation must return completed None")
            return None
        if (
            type(value) is not list
            or len(value) > 128
            or any(type(record) is not dict for record in value)
        ):
            raise ValidationError("Native publication lookup requires a bounded completed list")
        records = _json_data(value, "Native publication records", max_chars=3 * _MAX_BYTES)
        if len(canonical(records).encode("utf-8")) > 3 * _MAX_BYTES:
            raise ValidationError("Native publication records exceed their evidence byte limit")
        return records
    except RalfError:
        _close_deferred_publication(value)
        raise
    except Exception:
        _close_deferred_publication(value)
        raise ValidationError("Native publication port operation failed") from None


def _expected_nodes(owner):
    kind = owner["definition"]["kind"]
    if kind in {"agent", "sequence"}:
        return {
            "agent" if kind == "agent" else f"sequence/steps/{index}"
            for index in range(len(owner["definition"]["steps"]))
            if step_manifest(owner["manifest"], index).get("model_history_protocol") == 2
        }
    if kind == "graph":
        return {
            "graph/nodes/" + node["id"]
            for index, node in enumerate(owner["plan"]["nodes"])
            if node["agent"] is not None
            and owner["workflow"]["nodes"][node["id"]]["state"] == "completed"
            and step_manifest(owner["manifest"], index).get("model_history_protocol") == 2
            and "execution" not in owner["workflow"]["nodes"][node["id"]]
        }
    return set()


def _coverage(owner):
    expected = _expected_nodes(owner)
    journal = owner.get("native_model_history", {})
    if any(
        set(journal.get(key, {})) != expected
        for key in ("stages", "markers", "episodes", "episode_markers")
    ):
        raise DefinitionMismatch("Native publication does not cover original successful episodes")


def frame_owner(owner, node_id, state):
    frame = copy.deepcopy(state["execution"])
    index = next(i for i, node in enumerate(owner["plan"]["nodes"]) if node["id"] == node_id)
    frame["actions"] = [
        dict(copy.deepcopy(a), node=0) for a in owner["actions"] if a["node"] == index
    ]
    return frame


def completed_episodes(engine, root):
    """Visit actual successful Runs and node frames with bounded ownership checks."""
    pending, seen, result = [root], set(), []
    while pending:
        owner = pending.pop()
        if owner["id"] in seen or len(seen) >= 4096:
            raise DefinitionMismatch("Native publication lineage exceeded bounded traversal")
        seen.add(owner["id"])
        if owner["state"] != "succeeded":
            continue
        _coverage(owner)
        for node, record in owner.get("native_model_history", {}).get("episodes", {}).items():
            result.append((owner, node, record))
        for node_id, state in owner.get("workflow", {}).get("nodes", {}).items():
            frame = state.get("execution")
            if frame is None or state["state"] != "completed":
                continue
            if frame["state"] != "succeeded":
                raise DefinitionMismatch("Native publication has an incomplete original node")
            frame = frame_owner(owner, node_id, state)
            _coverage(frame)
            for node, record in frame.get("native_model_history", {}).get("episodes", {}).items():
                result.append((frame, node, record))
        for call in reversed(owner.get("orchestration", {}).get("children", [])):
            child = engine.store.run(call["run_id"])
            if child.get("parent_id") != owner["id"] or child.get("call_id") != call["id"]:
                raise DefinitionMismatch("Native child publication lost its original owner")
            pending.append(child)
    return result


def validate_episode(engine, root, owner, node, record):
    from .local_session_model_history import _index, _root
    from .workflow_runtime import agent_step

    try:
        envelope = validate_native_history_envelope(record["envelope"])
        journal = owner["native_model_history"]
        stage = journal["stages"][node]
        index = _index(owner, node)
        action = next(a for a in owner["actions"] if a["id"] == record["source_action"])
        turn = TurnAdmission.from_dict(root["session_turn"]) if "session_turn" in root else None
        source = {
            "root_run_id": root["id"],
            "run_id": owner["id"],
            "node": node,
            "release_digest": owner["release_digest"],
            "turn_id": root["id"] if turn is None else turn.turn_id,
            "turn_seq": 0 if turn is None else turn.turn_seq,
        }
        messages = [
            m
            for a in owner["actions"]
            if a["node"] == index
            for m in a.get("native_history_messages", [])
        ]
        messages.sort(key=lambda m: m["order"])
        if (
            set(record) != {"envelope", "message_id", "source_action"}
            or journal["markers"].get(node) != digest(stage)
            or journal["episode_markers"].get(node) != digest(record)
            or envelope["source"] != source
            or stage["source"] != source
            or envelope["stream"] != stage["stream"]
            or owner["scope"] != root["scope"]
            or owner["scope"] != vars(engine.scope)
            or _root(engine, owner)[1]["id"] != root["id"]
            or step_manifest(owner["manifest"], index).get("model_history_protocol") != 2
            or stage["target"]
            != step_manifest(owner["manifest"], index).get("native_session_source")
            or envelope["history"][0]
            != {"role": "system", "content": agent_step(owner, index)["instructions"]}
            or envelope["history"][1]["content"] != stage["current_task"]
            or record["message_id"] != "ralf-native-turn-v1:" + digest([source, action["id"]])
            or action["kind"] != "model"
            or action["node"] != index
            or action["status"] != "completed"
            or action["response"]["tool_calls"]
            or "received_response" not in action
            or digest(action["response"]) != envelope["final_digest"]
            or [m["order"] for m in messages] != list(range(2, len(envelope["history"])))
            or [m["message"] for m in messages] != envelope["history"][2:]
        ):
            raise DefinitionMismatch("Native episode differs from original adopted evidence")
        return stage
    except (KeyError, TypeError, StopIteration, RalfError) as exc:
        raise DefinitionMismatch("Native episode lost its original adopted evidence") from exc


def validate_publication(engine, root, owner, node, record, evidence):
    from .binding_sessions import session_storage_key

    stage = validate_episode(engine, root, owner, node, record)
    try:
        receipt = validate_inspection(
            evidence["receipt"],
            engine.scope,
            session_storage_key(stage["target"]["namespace"], stage["address"]),
            record["message_id"],
        )
        if (
            set(evidence) != {"envelope", "message_id", "source_action", "revision", "receipt"}
            or any(evidence[key] != value for key, value in record.items())
            or receipt["receipt"] is None
            or receipt["receipt"]["message"] != record["envelope"]
            or evidence["revision"] != stage["snapshot"]["revision"] + 1
            or receipt["receipt"]["revision"] != evidence["revision"]
        ):
            raise DefinitionMismatch("Native publication lost its exact original save receipt")
    except (KeyError, TypeError, RalfError) as exc:
        raise DefinitionMismatch("Native publication lost its exact original save receipt") from exc


def published_turns(engine, stream, snapshot):
    try:
        return _published_turns(engine, stream, snapshot)
    except (KeyError, TypeError, ValueError, StopIteration, RalfError) as exc:
        raise DefinitionMismatch(
            "Native source lost its original valid publication evidence"
        ) from exc


def _published_turns(engine, stream, snapshot):
    publications = _publication_call(
        engine.store, "native_history_publications", engine.scope, stream
    )
    published, selected = {}, []
    for evidence in publications:
        source = evidence["envelope"]["source"]
        root = engine.store.run(source["root_run_id"])
        if root["state"] != "succeeded" or root["scope"] != vars(engine.scope):
            raise DefinitionMismatch("Native publication requires original root success")
        matching = [
            (owner, node, record)
            for owner, node, record in completed_episodes(engine, root)
            if record["message_id"] == evidence["message_id"]
        ]
        if len(matching) != 1:
            raise DefinitionMismatch("Native publication lost its unique original episode")
        owner, node, record = matching[0]
        validate_publication(engine, root, owner, node, record, evidence)
        published[digest(evidence["envelope"])] = evidence["envelope"]
    for envelope in snapshot["turns"]:
        key = digest(envelope)
        if key in published:
            selected.append(envelope)
            continue
        source = envelope["source"]
        try:
            root = engine.store.run(source["root_run_id"])
        except RalfError as exc:
            raise DefinitionMismatch("Native candidate has no original root") from exc
        if root["state"] not in {"failed", "cancelled"}:
            raise DefinitionMismatch("Native candidate has no terminal unsuccessful root")
        # Only the original failed Turn's exact frozen record can be ignored.
        owner = engine.store.run(source["run_id"])
        if owner["definition"]["kind"] == "graph" and source["node"].startswith("graph/nodes/"):
            node_id = source["node"][len("graph/nodes/") :]
            state = owner["workflow"]["nodes"].get(node_id, {})
            if "execution" in state:
                owner = frame_owner(owner, node_id, state)
        record = owner.get("native_model_history", {}).get("episodes", {}).get(source["node"])
        if record is None or record["envelope"] != envelope:
            raise DefinitionMismatch("Native candidate differs from its frozen original episode")
        validate_episode(engine, root, owner, source["node"], record)
        from .local_native_history_save import validate_native_save

        if validate_native_save(owner, source["node"], record) is None:
            raise DefinitionMismatch("Failed-root native candidate has no exact original receipt")
    expected = [p["envelope"] for p in publications]
    if selected != expected:
        raise DefinitionMismatch("Native snapshot differs from original publication coverage")
    return expected


def publish_native_history(engine, run):
    from .local_session_model_history import (
        _index,
        _registration,
        _same_native_connection,
        _uses_session_history,
    )

    if (
        not _uses_session_history(run["manifest"])
        or run.get("parent_id") is not None
        or hasattr(engine, "parent")
    ):
        return
    if isinstance(engine.store, SQLiteStore) and not engine.store.conn.in_transaction:
        raise ValidationError("Native publication requires its original success transaction")
    for owner, node, record in completed_episodes(engine, run):
        stage = validate_episode(engine, run, owner, node, record)
        sessions = engine._components(owner, _index(owner, node)).sessions
        registration, namespace = _registration(engine, sessions)
        backend = registration.backend
        if not _same_native_connection(engine.store, backend):
            from .local_native_history_save import validate_native_save

            evidence = validate_native_save(owner, node, record)
            if evidence is None:
                raise DefinitionMismatch(
                    "Remote native publication lacks its exact original receipt"
                )
        else:
            address = registration.resource.select(
                {"namespace": namespace}, engine.scope
            ).storage_key(stage["address"])
            revision = backend.append(
                engine.scope,
                address,
                record["envelope"],
                expected_revision=stage["snapshot"]["revision"],
                message_id=record["message_id"],
            )
            receipt = backend.inspect_message(engine.scope, address, record["message_id"])
            evidence = {**copy.deepcopy(record), "revision": revision, "receipt": receipt}
        validate_publication(engine, run, owner, node, record, evidence)
        _publication_call(
            engine.store,
            "publish_native_history",
            engine.scope,
            stage["stream"],
            record["message_id"],
            copy.deepcopy(evidence),
        )
        publications = _publication_call(
            engine.store, "native_history_publications", engine.scope, stage["stream"]
        )
        exact = [item for item in publications if item.get("message_id") == record["message_id"]]
        if len(exact) != 1 or canonical(exact[0]) != canonical(evidence):
            raise ValidationError(
                "Native publication lookup did not confirm its exact original body"
            )
