"""Pure conservative occupancy rules; execution and stop proofs stay independent."""

TERMINAL = {"succeeded", "failed", "cancelled"}
FINAL = {"completed", "failed", "skipped"}


def capacity_obligations(run):
    """True retains a root; malformed or incomplete facts never grant release.

    This does not inspect credits or actual handler ownership. The original
    Store checks reservation rows, and the Engine checks its real task/thread
    owners before release. No external I/O or scheduling is performed here.
    """
    try:
        if type(run) is not dict or run.get("state") not in TERMINAL:
            return True
        actions = run.get("actions")
        if type(actions) is not list or any(_action_pending(action) for action in actions):
            return True
        for name in ("workflow", "orchestration"):
            state = run.get(name, {})
            if type(state) is not dict or state.get("quiescent", True) is not True:
                return True
        if any(
            type(child) is not dict or child.get("settled") is not True
            for child in run.get("orchestration", {}).get("children", [])
        ):
            return True
        if _auxiliary_pending(run):
            return True
        nodes = run.get("workflow", {}).get("nodes", {})
        if type(nodes) is not dict:
            return True
        for node_id, state in nodes.items():
            if type(state) is not dict:
                return True
            frame = state.get("execution")
            if frame is not None:
                if type(frame) is not dict:
                    return True
                if _auxiliary_pending(frame):
                    return True
                if "native_model_history" in frame:
                    from .local_native_history_publication import frame_owner
                    from .local_native_history_save import native_saves_settled

                    if not native_saves_settled(frame_owner(run, node_id, state)):
                        return True
        if "native_model_history" in run:
            from .local_native_history_save import native_saves_settled

            if not native_saves_settled(run):
                return True
        return False
    except (KeyError, TypeError, ValueError, AttributeError):
        return True
    except Exception:
        # Original pure validators can raise typed mismatches. A mismatch is an
        # obligation, never proof that the external write did not happen.
        return True


def _action_pending(action):
    if type(action) is not dict or action.get("kind") not in {"model", "tool"}:
        return True
    status = action.get("status")
    attempts = action.get("attempts", [])
    if type(attempts) is not list or any(type(attempt) is not dict for attempt in attempts):
        return True
    if any(attempt.get("status") not in {"completed", "not_dispatched"} for attempt in attempts):
        return True
    if status == "rejected":
        from .model_evidence import validate_received_response

        if action["kind"] != "model" or not any(
            attempt.get("status") == "completed" for attempt in attempts
        ):
            return True
        validate_received_response(action["received_response"])
    elif status in {
        "ready",
        "waiting_approval",
        "waiting_input",
        "pending",
        "cancelled",
        "not_dispatched",
    }:
        if any(attempt.get("status") != "not_dispatched" for attempt in attempts):
            return True
    elif status not in FINAL:
        return True
    delegated = action.get("delegated_execution")
    if delegated is not None and (
        type(delegated) is not dict
        or delegated.get("pending_stop") is not False
        or delegated.get("fenced") is not True
        or delegated.get("effect_case") not in {"confirmed", "absent", "not_dispatched"}
    ):
        return True
    return False


def _records(owner, field):
    values = owner.get(field, {})
    if type(values) is not dict or any(type(record) is not dict for record in values.values()):
        raise ValueError("Malformed auxiliary journal")
    return values.values()


def _auxiliary_pending(owner):
    contexts = owner.get("context_preparations", {})
    markers = owner.get("context_preparation_markers", {})
    if type(contexts) is not dict or type(markers) is not dict or set(contexts) != set(markers):
        return True
    if any(
        type(owner.get(field, {})) is not dict or set(owner.get(field, {})) - set(contexts)
        for field in ("context_preparation_receipts", "context_preparation_snapshots")
    ):
        return True
    artifacts = owner.get("context_artifacts", {})
    intents = owner.get("context_artifact_intents", {})
    if type(artifacts) is not dict or type(intents) is not dict or set(artifacts) != set(intents):
        return True
    if any(
        type(owner.get(field, {})) is not dict or set(owner.get(field, {})) - set(artifacts)
        for field in ("context_artifact_receipts", "context_artifact_dispatches")
    ):
        return True
    for record in _records(owner, "memory_stages"):
        if record.get("status") not in FINAL or type(record.get("facts")) is not list:
            return True
        if any(
            type(fact) is not dict or fact.get("status") not in {"completed", "skipped"}
            for fact in record["facts"]
        ):
            return True
        selection = record.get("selection")
        if selection is not None and (
            type(selection) is not dict or selection.get("status") not in FINAL
        ):
            return True
    for record in _records(owner, "context_preparations"):
        if record.get("status") not in FINAL:
            return True
    for record in _records(owner, "context_artifacts"):
        status, dispatched = record.get("status"), record.get("dispatched")
        if type(dispatched) is not bool:
            return True
        if status == "prepared" and dispatched is False:
            continue
        if status != "verified" or dispatched is not True:
            return True
    for record in _records(owner, "remote_session_saves"):
        attempts = record.get("attempts")
        if type(attempts) is not int or attempts < 0:
            return True
        if record.get("receipt") is None:
            return True
        if type(record["receipt"]) is not dict:
            return True
        from .session_receipts import validate_inspection
        from .types import Scope, canonical

        if record["scope"] != owner["scope"]:
            return True
        evidence = validate_inspection(
            record["receipt"], Scope(**record["scope"]), record["address"], record["message_id"]
        )
        if evidence["receipt"] is None or canonical(evidence["receipt"]["message"]) != canonical(
            record["message"]
        ):
            return True
    for record in _records(owner, "parent_completion_stages"):
        if record.get("status") in {"adopted", "closed"}:
            continue
        from .types import digest

        if (
            owner.get("state") in {"failed", "cancelled"}
            and record.get("status") == "prepared"
            and type(record.get("schema_version")) is int
            and record["schema_version"] == 1
            and type(record.get("source")) is dict
            and record["source"].get("parent_id") == owner.get("id")
            and record["source"].get("scope") == owner.get("scope")
            and record.get("source_digest") == digest(record["source"])
            and all(
                field in record and record[field] is None
                for field in (
                    "child_key",
                    "child_run_id",
                    "child_release_digest",
                    "received_proposal",
                    "adopted_verdict",
                )
            )
        ):
            # A failed pure gate never accepted a verifier child. The original
            # terminal state retires this proposal without inventing new I/O.
            continue
        return True
    return False
