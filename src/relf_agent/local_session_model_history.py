"""Native history evidence in the original Local Run and success transaction."""

import copy
from dataclasses import asdict

from .binding_sessions import SessionBindingResource, SessionView
from .errors import DefinitionMismatch, ValidationError
from .memory import SQLiteMemory, memory_call
from .recall import RecallQuery
from .session_model_history import native_history_address, native_history_envelope
from .session_types import TurnAdmission
from .storage import SQLiteStore
from .types import canonical, digest


def _uses_session_history(manifest):
    if isinstance(manifest, dict):
        return manifest.get("model_history_protocol") == 2 or any(
            _uses_session_history(value) for value in manifest.values()
        )
    if isinstance(manifest, list):
        return any(_uses_session_history(value) for value in manifest)
    return False


def activate_native_history(engine, manifest):
    if not _uses_session_history(manifest):
        return
    from .local_native_history_publication import _publication_call

    _publication_call(engine.store, "prepare_native_history")


def _same_native_connection(store, backend):
    """An explicit SQLite optimization; generic execution ports need no conn."""
    return (
        isinstance(store, SQLiteStore)
        and type(backend) is SQLiteMemory
        and getattr(backend.store, "conn", None) is getattr(store, "conn", None)
    )


def _registration(engine, sessions):
    from .temporal_session_data import SessionReadRegistration

    if sessions is None:
        raise ValidationError("Session model history requires a Session source")
    if isinstance(sessions, SessionView):
        sessions._check(engine.scope)
        namespace, backend = sessions.namespace, sessions.backend
    else:
        namespace, backend = None, sessions
    cache = engine.__dict__.setdefault("_native_history_resources", {})
    key = (backend.backend_id, namespace)
    registration = cache.get(key)
    if registration is None:
        resource = SessionBindingResource(
            backend, namespaces=(namespace,), default_namespace=namespace
        )
        registration = SessionReadRegistration(
            resource, RecallQuery(max_items=1, scan_limit=1, max_chars=1_000_000)
        )
        cache[key] = registration
    if registration.backend is not backend:
        raise DefinitionMismatch("The original native Session source changed")
    registration.check()
    return registration, namespace


def native_source_identity(engine, sessions):
    registration, namespace = _registration(engine, sessions)
    return {
        "registration": registration.identity,
        "dataset_id": registration.dataset_id,
        "namespace": namespace,
    }


def _root(engine, run):
    original = engine
    while hasattr(original, "parent"):
        original = original.parent
    root, seen = run, set()
    while root.get("parent_id") is not None:
        if root["id"] in seen or len(seen) > 16:
            raise DefinitionMismatch("Native history parent lineage is invalid")
        seen.add(root["id"])
        root = original.store.run(root["parent_id"])
    if hasattr(engine, "parent") and root["id"] == run["id"]:
        root = original.store.run(run["id"])
    return original, root


def _node(run):
    if run["definition"]["kind"] == "graph":
        return "graph/nodes/" + str(run["workflow"]["current"])
    return "agent" if run["definition"]["kind"] == "agent" else f"sequence/steps/{run['node']}"


def _stage(run):
    return run.get("native_model_history", {}).get("stages", {}).get(_node(run))


def current_native_task(run):
    stage = _stage(run)
    return None if stage is None else stage["current_task"]


def record_native_message(engine, run, action):
    """Record adoption order in the original Action, before the episode resets."""
    if engine._step_manifest(run, action["node"]).get("model_history_protocol") != 2:
        return
    action.setdefault("native_history_messages", []).append(
        {"order": len(run["messages"]) - 1, "message": copy.deepcopy(run["messages"][-1])}
    )


def native_history_frame(engine, run):
    if engine._step_manifest(run).get("model_history_protocol") != 2:
        return None
    stage = _stage(run)
    if stage is None:
        raise DefinitionMismatch("Native model input lost its accepted source snapshot")
    marker = run.get("native_model_history", {}).get("markers", {}).get(_node(run))
    if marker != digest(stage):
        raise DefinitionMismatch("Native model input changed its accepted source snapshot")
    if run["messages"][1]["content"] != stage["current_task"]:
        raise DefinitionMismatch("Native model input changed its original current task")
    return {
        "version": 1,
        "history": copy.deepcopy(run["messages"]),
        "turns": copy.deepcopy(stage["past"]),
        "stream": stage["stream"],
        "snapshot": copy.deepcopy(stage["snapshot"]),
    }


async def prepare_native_history(engine, run_id):
    from .native_session_history import read_native_history

    run = engine._authorized(run_id)
    if engine._step_manifest(run).get("model_history_protocol") != 2:
        return
    components = engine._components(run)
    registration, namespace = _registration(engine, components.sessions)
    target = native_source_identity(engine, components.sessions)
    if target != engine._step_manifest(run).get("native_session_source"):
        raise DefinitionMismatch("Native Session source differs from its original release")
    if _stage(run) is not None:
        native_history_frame(engine, run)
        return
    original, root = _root(engine, run)
    turn = TurnAdmission.from_dict(root["session_turn"]) if "session_turn" in root else None
    stream = digest(
        [
            "native-model-stream-v1",
            asdict(engine.scope),
            target,
            root["session_id"],
            0 if turn is None else turn.session.binding_revision,
            root["release_digest"],
            run["session_id"],
            _node(run),
            engine._step_manifest(run)["providers"],
            engine._agent_step(run)["instructions"],
        ]
    )
    address = native_history_address(stream)
    view = registration.resource.select({"namespace": namespace}, engine.scope)
    dataset = await memory_call(registration.backend.inspect_session_identity)
    registration.check()
    if digest(["ralf-session-dataset-v1", dataset]) != registration.dataset_id:
        raise DefinitionMismatch("Native Session dataset changed")
    snapshot = await read_native_history(view, engine.scope, address, stream=stream)
    registration.check()
    if snapshot["revision"] >= 128:
        raise ValidationError("Native history stream has no capacity for another complete Turn")
    from .local_native_history_publication import published_turns

    expected = published_turns(original, stream, snapshot)
    current = engine._authorized(run_id)
    engine._check_release(current)
    if current["state"] in {"succeeded", "failed", "cancelled", "cancelling"}:
        return
    if current["messages"] != run["messages"] or current["node"] != run["node"]:
        raise DefinitionMismatch("Native source read changed its original episode")
    stage = {
        "stream": stream,
        "address": address,
        "target": target,
        "snapshot": snapshot,
        "past": expected,
        "current_task": current["messages"][1]["content"],
        "source": {
            "root_run_id": root["id"],
            "run_id": run_id,
            "node": _node(run),
            "release_digest": run["release_digest"],
            "turn_id": root["id"] if turn is None else turn.turn_id,
            "turn_seq": 0 if turn is None else turn.turn_seq,
        },
    }
    with engine.store.transaction():
        current = engine._authorized(run_id)
        journal = current.setdefault(
            "native_model_history",
            {"stages": {}, "markers": {}, "episodes": {}, "episode_markers": {}},
        )
        if _node(current) in journal["stages"]:
            raise DefinitionMismatch("Native snapshot was already accepted")
        journal["stages"][_node(current)] = copy.deepcopy(stage)
        journal["markers"][_node(current)] = digest(stage)
        current["current_task"] = stage["current_task"]
        engine._commit(current, "native_history_snapshot_adopted", {"stream": stream})


def freeze_native_history(engine, run_id):
    run = engine._authorized(run_id)
    if engine._step_manifest(run).get("model_history_protocol") != 2:
        return
    frame = native_history_frame(engine, run)
    source = _stage(run)["source"]
    action = next(
        a
        for a in reversed(run["actions"])
        if a["node"] == run["node"]
        and a["kind"] == "model"
        and a["status"] == "completed"
        and not a["response"]["tool_calls"]
    )
    envelope = native_history_envelope(
        frame["stream"], source, frame["history"], digest(action["response"])
    )
    if (
        len(canonical([*_stage(run)["snapshot"]["turns"], envelope]).encode("utf-8"))
        > 8 * 1024 * 1024
    ):
        raise ValidationError("Native history stream has no capacity for its complete episode")
    record = {
        "envelope": envelope,
        "message_id": "ralf-native-turn-v1:" + digest([source, action["id"]]),
        "source_action": action["id"],
    }
    with engine.store.transaction():
        current = engine._authorized(run_id)
        episodes = current["native_model_history"]["episodes"]
        previous = episodes.get(_node(run))
        if previous is not None:
            if previous != record:
                raise DefinitionMismatch("Native completed episode changed")
            return
        episodes[_node(run)] = record
        current["native_model_history"]["episode_markers"][_node(run)] = digest(record)
        engine._commit(current, "native_history_episode_frozen", {"stream": frame["stream"]})


def _index(owner, node):
    if node == "agent":
        return 0
    if node.startswith("sequence/steps/"):
        return int(node.rsplit("/", 1)[1])
    if node.startswith("graph/nodes/"):
        identifier = node[len("graph/nodes/") :]
        return next(
            i for i, entry in enumerate(owner["plan"]["nodes"]) if entry["id"] == identifier
        )
    raise DefinitionMismatch("Native episode has an unknown original node path")


def publish_native_history(engine, run):
    from .local_native_history_publication import publish_native_history as publish

    publish(engine, run)


async def recover_native_tree(engine, run_id):
    """Terminal recovery inspects original actual members without new dispatch."""
    from .local_native_history_save import recover_terminal_native_saves
    from .node_execution import NodeEngine

    if not _uses_session_history(engine._authorized(run_id)["manifest"]):
        return
    pending, seen = [run_id], set()
    while pending:
        identifier = pending.pop()
        if identifier in seen or len(seen) >= 4096:
            raise DefinitionMismatch("Native recovery exceeds its original bounded ownership")
        seen.add(identifier)
        owner = engine._authorized(identifier)
        if owner["state"] not in {"succeeded", "failed", "cancelled"}:
            continue
        if "native_model_history" in owner:
            await recover_terminal_native_saves(engine, identifier)
        for node_id, state in owner.get("workflow", {}).get("nodes", {}).items():
            if "native_model_history" in state.get("execution", {}):
                await recover_terminal_native_saves(
                    NodeEngine(engine, identifier, node_id), identifier
                )
        for call in reversed(owner.get("orchestration", {}).get("children", [])):
            child = engine.store.run(call["run_id"])
            if child.get("parent_id") != identifier or child.get("call_id") != call["id"]:
                raise DefinitionMismatch("Native recovery child lost its original owner")
            pending.append(child["id"])


def pending_native_saves(owner):
    """Report original pending saves, including correctly scoped parallel frames."""
    from .local_native_history_publication import frame_owner
    from .local_native_history_save import native_saves_settled

    owners = [(owner, None)]
    owners.extend(
        (frame_owner(owner, identifier, state), identifier)
        for identifier, state in owner.get("workflow", {}).get("nodes", {}).items()
        if "native_model_history" in state.get("execution", {})
    )
    result = []
    for actual, workflow_node in owners:
        if "native_model_history" not in actual or native_saves_settled(actual):
            continue
        for node, value in actual["native_model_history"].get("saves", {}).items():
            if (
                value["receipt"] is not None
                or value["attempts"] == 0
                and actual["state"] in {"failed", "cancelled", "cancelling"}
            ):
                continue
            item = {
                "kind": "auxiliary",
                "source": "native_history",
                "node": node,
                "status": "outcome_unknown" if value["attempts"] else "prepared",
            }
            if workflow_node is not None:
                item["workflow_node"] = workflow_node
            result.append(item)
    return result
