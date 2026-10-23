"""Pure optional reference selection shared by bounded context implementations."""

import copy


def _complete_turn(turn):
    """A clipped turn needs a user request, final answer and paired tool evidence."""
    if len(turn) == 1 and _result_record(turn[0]):
        return True
    if not turn or turn[0].get("role") != "user" or turn[-1].get("role") != "assistant":
        return False
    pending, seen = set(), set()
    for message in turn:
        role = message.get("role")
        if role == "assistant":
            if pending:
                return False
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                return False
            for call in calls:
                identity = call.get("id") if isinstance(call, dict) else None
                if not isinstance(identity, str) or not identity or identity in seen:
                    return False
                pending.add(identity)
                seen.add(identity)
        elif role == "tool":
            identity = message.get("tool_call_id")
            if not isinstance(identity, str) or identity not in pending:
                return False
            pending.remove(identity)
        elif role != "user" or pending:
            return False
    return not pending


def _result_record(message):
    # Native Session stores one completed answer with its originating task.
    return (
        message.get("role") == "assistant"
        and "task" in message
        and "content" in message
        and not message.get("tool_calls")
    )


def select_references(references, fits):
    """Keep fitting references unchanged; project an oversized Session to a suffix.

    Never skip the newest turn to include an older one. A suffix contains only
    complete turns, in their original order. This does not compact stored data.
    """
    selected, projections = [], []
    for index, source in enumerate(references):
        reference = copy.deepcopy(source)
        if fits([*selected, reference]):
            selected.append(reference)
            continue
        history = reference.get("session") if isinstance(reference, dict) else None
        if not isinstance(history, list) or not all(isinstance(m, dict) for m in history):
            continue
        turns = []
        for message in history:
            if (
                message.get("role") == "user"
                or _result_record(message)
                or not turns
                or _result_record(turns[-1][0])
            ):
                turns.append([])
            turns[-1].append(message)
        retained, count = [], 0
        for turn in reversed(turns):
            if not _complete_turn(turn):
                break
            candidate = turn + retained
            projected = {**reference, "session": candidate}
            if not fits([*selected, projected]):
                break
            retained, count = candidate, count + 1
        if retained:
            selected.append({**reference, "session": retained})
        projections.append(
            {
                "reference_index": index,
                "selected_messages": len(retained),
                "omitted_messages": len(history) - len(retained),
                "selected_turns": count,
                "omitted_turns": len(turns) - count,
            }
        )
    return selected, projections
