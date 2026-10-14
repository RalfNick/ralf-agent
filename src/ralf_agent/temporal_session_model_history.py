"""Original Run/Session History owns native frames and publication eligibility."""

import copy

from .errors import DefinitionMismatch, ValidationError
from .session_types import SessionRef
from .types import canonical, digest

MAX_TURNS, MAX_CHARS = 128, 8388608


class _CapacityExceeded(ValidationError):
    code = "session_history_capacity"


def _stream_capacity(records, *, pending=False):
    encoded = canonical(records)
    if (
        len(records) + pending > MAX_TURNS
        or len(encoded) + pending > MAX_CHARS
        or len(encoded.encode("utf-8")) + pending > MAX_CHARS
    ):
        raise _CapacityExceeded("Native Session stream capacity exhausted")


def _candidate(native, episodes):
    candidate = copy.deepcopy(native["published"] if native else {})
    for episode in episodes:
        items = candidate.setdefault(episode["stream"], [])
        items.append(episode)
        _stream_capacity(items)
    if native:
        encoded = canonical({**native, "published": candidate})
        if len(encoded) > MAX_CHARS * 16 or len(encoded.encode("utf-8")) > MAX_CHARS * 16:
            raise _CapacityExceeded("Native Session bundle capacity exhausted")
    return candidate


def before_model(request):
    """The original frozen frame/source must have room for another complete episode."""
    value = request["model_history_frame"]
    _stream_capacity(value["turns"], pending=True)
    data = request.get("native_history_snapshot")
    if data is not None:
        # Physical candidates from unsuccessful roots still consume original
        # append revisions; publication eligibility cannot erase that capacity.
        _stream_capacity(data["turns"], pending=True)


def bundle(state):
    return copy.deepcopy(
        [
            episode
            for child in state.children
            if child.get("settled") and child["state"] == "succeeded"
            for episode in child.get("native_history_bundle", [])
        ]
    )


def observed_bundle(proof):
    from .session_model_history import validate_native_history_envelope

    episodes = proof.get("native_history_bundle", proof.get("native_history_episodes", []))
    if type(episodes) is not list or len(episodes) > 4096:
        raise ValidationError("Original child native bundle must be bounded complete evidence")
    return [validate_native_history_envelope(episode) for episode in episodes]


def parent_capacity(state):
    if state.manifest.get("model_history_protocol") == 2:
        _candidate(state.request.get("session_native_history"), bundle(state))


def enabled(manifest):
    return (
        manifest.get("model_history_protocol") == 2
        and manifest.get("model_history", {}).get("identity", {}).get("scope") == "session"
    )


def publication(native):
    return digest(["temporal-native-publication-v1", native["session_ref"], native["published"]])


def validate_native_request(request, manifest):
    value = request.get("session_native_history")
    if value is None:
        return
    if (
        manifest.get("binding_protocol")
        not in (8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)
        or manifest.get("model_history_protocol") != 2
    ):
        raise DefinitionMismatch("Native Session snapshot requires its original History protocol")
    if (
        type(value) is not dict
        or set(value)
        != {
            "version",
            "session_ref",
            "turn_id",
            "turn_seq",
            "root_run_id",
            "path",
            "published",
            "publication_digest",
        }
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValidationError("Native Session snapshot requires exact original fields")
    SessionRef.from_dict(value["session_ref"])
    if (
        type(value["turn_seq"]) is not int
        or value["turn_seq"] < 0
        or type(value["turn_id"]) is not str
        or not value["turn_id"]
        or type(value["root_run_id"]) is not str
        or not value["root_run_id"]
        or type(value["path"]) is not list
        or len(value["path"]) > 64
        or any(type(atom) is not str or not atom or len(atom) > 256 for atom in value["path"])
        or type(value["published"]) is not dict
    ):
        raise ValidationError("Native Session snapshot lost original owner or path")
    turn = request.get("session_turn")
    if turn is not None and any(
        value[name] != turn[name] for name in ("session_ref", "turn_id", "turn_seq")
    ):
        raise DefinitionMismatch("Native snapshot belongs to another original Turn")
    if value["publication_digest"] != publication(value):
        raise DefinitionMismatch("Native snapshot changed original publication evidence")
    from .session_model_history import validate_native_history_envelope

    for stream, records in value["published"].items():
        encoded = canonical(records)
        if (
            type(records) is not list
            or len(records) > MAX_TURNS
            or len(encoded) > MAX_CHARS
            or len(encoded.encode("utf-8")) > MAX_CHARS
        ):
            raise ValidationError("Native Session stream exceeds its complete history allowance")
        for envelope in records:
            validate_native_history_envelope(envelope, stream=stream)
    encoded = canonical(value)
    if len(encoded) > MAX_CHARS * 16 or len(encoded.encode("utf-8")) > MAX_CHARS * 16:
        raise ValidationError("Native Session bundle exceeds its bounded allowance")


def path(request, node):
    prefix = request.get("session_native_history", {}).get("path", [])
    return prefix + (
        ["agent"] if request["definition"]["kind"] == "agent" else ["sequence", "steps", str(node)]
    )


def stream(state):
    native = state.request.get("session_native_history")
    owner = native["session_ref"] if native else [state.scope, state.run_id]
    # Fixed declaration path and epoch survive temporary child Run/call IDs.
    return digest(
        [
            "temporal-native-stream-v1",
            owner,
            path(state.request, state.node),
            state.request["definition"]["steps"][state.node],
            state.step_manifest.get("provider_continuations", {}).get(state.step["provider"]),
        ]
    )


def frame(state):
    native = state.request.get("session_native_history")
    current_stream = stream(state)
    snapshot = (
        {
            "kind": "temporal-session-history",
            "session_ref": native["session_ref"],
            "publication_digest": native["publication_digest"],
        }
        if native
        else {"kind": "temporal-run-history", "run_id": state.run_id}
    )
    data = getattr(state, "native_history_snapshots", {}).get(str(state.node))
    if data is not None:
        snapshot["data"] = copy.deepcopy(data)
    return {
        "version": 1,
        "history": copy.deepcopy(state.messages),
        "turns": copy.deepcopy(native["published"].get(current_stream, []) if native else []),
        "stream": current_stream,
        "snapshot": snapshot,
    }


def request_fields(state):
    if not enabled(state.step_manifest):
        return {}
    fields = {
        "current_task": copy.deepcopy(state.current_task),
        "model_history_frame": frame(state),
    }
    snapshot = getattr(state, "native_history_snapshots", {}).get(str(state.node))
    if snapshot is not None:
        fields["native_history_snapshot"] = copy.deepcopy(snapshot)
    return fields


def validate_request_frame(request):
    original = request.get("model_history_frame")
    if (
        type(original) is not dict
        or original.get("history") != request["messages"]
        or "current_task" not in request
        or request["messages"][1].get("content")
        != (
            request["current_task"]
            if isinstance(request["current_task"], str)
            else canonical(request["current_task"])
        )
    ):
        raise DefinitionMismatch("Native frame lost its original current task or chain")
    from .session_model_history import validate_model_history_frame

    history = [original["history"][0]]
    for turn in original["turns"]:
        history.extend(turn["history"][1:])
    history.extend(original["history"][1:])
    validate_model_history_frame(original, history)
    return original


def freeze(state):
    if not enabled(state.step_manifest):
        return
    from .session_model_history import native_history_envelope

    records = getattr(state, "native_history_episodes", [])
    actual_path = canonical(path(state.request, state.node))
    if any(item["source"]["node"] == actual_path for item in records):
        return
    final = next(
        (
            a
            for a in reversed(state.actions)
            if a["kind"] == "model"
            and a["node"] == state.node
            and a["status"] == "completed"
            and not a.get("response", {}).get("tool_calls")
        ),
        None,
    )
    if final is None or "received_response" not in final:
        raise DefinitionMismatch("Native episode lacks its original adopted final response")
    native = state.request.get("session_native_history", {})
    turn = state.request.get("session_turn", native)
    source = {
        "root_run_id": native.get("root_run_id", state.run_id),
        "run_id": state.run_id,
        "node": actual_path,
        "release_digest": state.release_digest,
        "turn_id": turn.get("turn_id", state.run_id),
        "turn_seq": turn.get("turn_seq", 0),
    }
    envelope = native_history_envelope(
        stream(state), source, state.messages, digest(final["received_response"])
    )
    _candidate(state.request.get("session_native_history"), [*records, envelope])
    data = getattr(state, "native_history_snapshots", {}).get(str(state.node))
    if data is not None:
        _stream_capacity([*data["turns"], envelope])
    records.append(envelope)
    state.native_history_episodes = records
    state._emit(
        "native_history_episode_frozen",
        {"stream": envelope["stream"], "episode_digest": digest(envelope)},
    )


def publish(session, proofs):
    from .session_model_history import validate_native_history_envelope

    candidate = copy.deepcopy(session.native_history)
    for proof in proofs:
        if proof["snapshot"]["state"] != "succeeded":
            # Root success is proved by the caller; unsuccessful members cannot
            # qualify a partially frozen episode for this published bundle.
            continue
        expected = []
        definition = proof["request"]["definition"]
        if definition["kind"] in {"agent", "sequence"}:
            from .temporal_bindings import effective_manifest, step_descriptor

            expected = [
                canonical(path(proof["request"], node))
                for node in range(len(definition["steps"]))
                if enabled(
                    effective_manifest(proof["manifest"], step_descriptor(proof["request"], node))
                )
            ]
        episodes = proof.get("native_history_episodes", [])
        if (
            type(episodes) is not list
            or [e.get("source", {}).get("node") for e in episodes] != expected
        ):
            raise DefinitionMismatch(
                "Native publication does not cover original successful Agent episodes"
            )
        for episode in episodes:
            episode = validate_native_history_envelope(episode)
            source = episode["source"]
            if source != {
                "root_run_id": session.active["run_id"],
                "run_id": proof["snapshot"]["run_id"],
                "node": source["node"],
                "release_digest": proof["release_digest"],
                "turn_id": session.active["turn"]["turn_id"],
                "turn_seq": session.active["turn"]["turn_seq"],
            }:
                raise DefinitionMismatch(
                    "Native episode source differs from original successful History"
                )
            models = [
                a
                for a in proof["snapshot"]["actions"]
                if a["kind"] == "model"
                and canonical(path(proof["request"], a["node"])) == source["node"]
            ]
            from types import SimpleNamespace

            from .temporal_bindings import effective_manifest, effective_step, step_descriptor

            node = models[0]["node"] if models else -1
            if node < 0:
                raise DefinitionMismatch("Native episode has no original Agent model intent")
            descriptor = step_descriptor(proof["request"], node)
            selected = effective_manifest(proof["manifest"], descriptor)
            original_state = SimpleNamespace(
                request=proof["request"],
                scope=proof["scope"],
                run_id=proof["snapshot"]["run_id"],
                node=node,
                step_manifest=selected,
                step=effective_step(definition["steps"][node], proof["manifest"], descriptor),
            )
            if (
                episode["stream"] != stream(original_state)
                or episode["history"][:2] != models[0]["dispatch_request"]["messages"][:2]
            ):
                raise DefinitionMismatch("Native episode changed its original Agent stream or task")
            if "session_data" in selected:
                stages = [
                    stage
                    for stage in proof.get("session_stages", [])
                    if stage["node"] == node and stage["intent"]["message"] == episode
                ]
                if (
                    len(stages) != 1
                    or stages[0]["status"] != "completed"
                    or not stages[0]["execution_stopped"]
                    or stages[0]["received_inspection"]["receipt"]["message"] != episode
                ):
                    raise DefinitionMismatch(
                        "Native publication lacks its original complete external save receipt"
                    )
            final = models[-1] if models else {}
            if (
                final.get("status") != "completed"
                or final.get("response", {}).get("tool_calls")
                or digest(final.get("received_response")) != episode["final_digest"]
            ):
                raise DefinitionMismatch(
                    "Native episode lacks its original successful final receipt"
                )
            evidence = [
                a["native_history_message"]
                for a in proof["snapshot"]["actions"]
                if "native_history_message" in a
                and canonical(path(proof["request"], a["node"])) == source["node"]
            ]
            # Actions are declared before tool dispatch; adoption order is recorded separately.
            evidence.sort(key=lambda message: message["order"])
            if episode["history"][2:] != [item["message"] for item in evidence]:
                raise DefinitionMismatch("Native episode changed original adopted message evidence")
            items = candidate.setdefault(episode["stream"], [])
            items.append(episode)
            _stream_capacity(items)
    return candidate


def native_read_identity(manifest, request):
    from .session_model_history import native_history_address
    from .temporal_session_data_state import session_storage_key

    source = manifest["session_data"]
    value = request["model_history_frame"]
    return {
        "version": 1,
        "scope": request["scope"],
        "stream": value["stream"],
        "address": session_storage_key(
            source["namespace"], native_history_address(value["stream"])
        ),
        "registration_digest": digest(source),
    }


def validate_native_snapshot(snapshot, manifest, request):
    if not enabled(manifest) or "session_data" not in manifest:
        if "native_history_snapshot" in snapshot:
            raise DefinitionMismatch("Unexpected native Session source evidence")
        return
    expected = native_read_identity(manifest, request)
    value = snapshot.get("native_history_snapshot")
    if (
        type(value) is not dict
        or set(value) != set(expected) | {"snapshot_id", "revision", "turns"}
        or any(value.get(k) != v for k, v in expected.items())
        or type(value["revision"]) is not int
        or not 0 <= value["revision"] <= MAX_TURNS
        or type(value["snapshot_id"]) is not str
        or type(value["turns"]) is not list
    ):
        raise DefinitionMismatch("Native read lost original source/stream identity")
    import json

    try:
        original = json.loads(value["snapshot_id"])
    except (TypeError, ValueError, RecursionError):
        raise ValidationError("Native snapshot requires a finite committed revision") from None
    if type(original) is not dict or type(original.get("revision")) is not int:
        raise ValidationError("Native snapshot requires a typed committed revision")
    if original["revision"] != value["revision"] or len(value["turns"]) != value["revision"]:
        raise DefinitionMismatch("Native snapshot does not cover its original committed revision")
    from .session_model_history import validate_native_history_envelope

    records = [validate_native_history_envelope(t, stream=value["stream"]) for t in value["turns"]]
    published = request["model_history_frame"]["turns"]
    eligible = [
        item for item in records if any(item["source"] == turn["source"] for turn in published)
    ]
    if eligible != published:
        raise DefinitionMismatch("Native data changed or omitted original published Turn evidence")
    cached = request.get("native_history_snapshot")
    if cached is not None and cached != value:
        raise DefinitionMismatch("Native read replaced its originally accepted snapshot")


async def load_native(runtime, request):
    if not enabled(runtime.manifest) or "session_data" not in runtime.manifest:
        return {}
    from .binding_sessions import SessionView
    from .native_session_history import read_native_history
    from .session_model_history import native_history_address
    from .temporal_session_data import selected_registration, verify_dataset
    from .types import Scope

    expected = native_read_identity(runtime.manifest, request)
    cached = request.get("native_history_snapshot")
    if cached is not None:
        result = {"native_history_snapshot": copy.deepcopy(cached)}
        validate_native_snapshot(result, runtime.manifest, request)
        return result
    original = selected_registration(runtime, request)
    await verify_dataset(runtime, request)
    original.check()
    view = SessionView(
        original.backend,
        Scope(**request["scope"]),
        runtime.manifest["session_data"]["namespace"],
        original.backend.backend_id,
    )
    data = await read_native_history(
        view, view.scope, native_history_address(expected["stream"]), stream=expected["stream"]
    )
    runtime.validate_release(request["runtime_manifest"])
    original.check()
    await verify_dataset(runtime, request)
    result = {"native_history_snapshot": {**expected, **data}}
    validate_native_snapshot(result, runtime.manifest, request)
    return result
