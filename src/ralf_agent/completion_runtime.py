"""Local authority adoption of pure completion proposals; no additional scheduler."""

import copy
import json

from .completion import CompletionRequest, CompletionVerdict
from .errors import CompletionRejected, DefinitionMismatch, RalfError, ValidationError
from .types import canonical, digest
from .workflow_runtime import is_graph


def _task_input(engine, run):
    if is_graph(run):
        return copy.deepcopy(run["workflow"]["nodes"][run["workflow"]["current"]]["input"])
    if run["node"] == 0:
        return copy.deepcopy(run["input"])
    previous = next(
        (
            action
            for action in reversed(run["actions"])
            if action["node"] == run["node"] - 1
            and action["kind"] == "model"
            and action["status"] == "completed"
            and not action["response"]["tool_calls"]
        ),
        None,
    )
    if previous is None:
        raise ValidationError("Sequence completion requires the predecessor's accepted output")
    # It already passed final_output before advancing the sequence. Reproduce
    # JSON normalization only, without revalidating a Schema or fetching refs.
    result = copy.deepcopy(previous["response"]["output"])
    if engine._agent_step(run, run["node"] - 1)["output_schema"] is not None and isinstance(
        result, str
    ):
        try:
            result = json.loads(result)
        except ValueError as exc:
            raise ValidationError("Invalid recorded predecessor output") from exc
    return result


def verify_completion(engine, run_id, result):
    run = engine._authorized(run_id)
    verifier = engine._components(run).verifier
    if verifier is None:
        return True
    engine._check_release(run)
    action = next(
        a
        for a in reversed(run["actions"])
        if a["node"] == run["node"] and a["kind"] == "model" and a["status"] == "completed"
    )
    record = action.get("completion_verification")
    if record is None:
        request = CompletionRequest(
            _task_input(engine, run),
            result,
            [
                {
                    key: copy.deepcopy(a[key])
                    for key in ("id", "tool", "arguments", "result", "receipt", "effect_key")
                }
                for a in run["actions"]
                if a["node"] == run["node"]
                and a["kind"] == "tool"
                and a["status"] == "completed"
                and "input_pending_id" not in a
            ],
        )
        identity = engine._component_identity(verifier, ("verify",), True, "Completion verifier")
        try:
            proposed = engine._component_result(
                verifier.verify(request), CompletionVerdict, "CompletionVerifier.verify"
            )
            # Custom subclasses and lazy return objects cannot smuggle deferred work.
            if type(proposed) is not CompletionVerdict:
                raise ValidationError("Completion verifier requires a concrete verdict")
            verdict = CompletionVerdict(**proposed.to_dict())
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Completion verifier failed to produce a verdict") from exc
        engine._check_release(engine._authorized(run_id))
        if digest(
            engine._component_identity(verifier, ("verify",), True, "Completion verifier")
        ) != digest(identity):
            raise DefinitionMismatch("The executing completion verifier changed")
        record = {
            "schema_version": 1,
            "request": request.to_dict(),
            "request_digest": digest(request.to_dict()),
            "verdict": verdict.to_dict(),
        }
        with engine.store.transaction():
            current = engine._authorized(run_id)
            if current["state"] in {"succeeded", "failed", "cancelled", "cancelling"}:
                return False
            target = next(a for a in current["actions"] if a["id"] == action["id"])
            if target.get("completion_verification") is not None:
                raise ValidationError("Completion verification was already committed")
            target["completion_verification"] = copy.deepcopy(record)
            if verdict.status == "retry":
                if engine._step_manifest(current).get("model_history_protocol") not in {1, 2}:
                    current["messages"].append(
                        {
                            "role": "assistant",
                            "content": result if isinstance(result, str) else canonical(result),
                        }
                    )
                current["messages"].append(
                    {"role": "user", "content": "Completion verification: " + verdict.feedback}
                )
                from .local_session_model_history import record_native_message

                record_native_message(engine, current, target)
            engine._commit(
                current,
                "completion_verified",
                {
                    "action_id": action["id"],
                    "status": verdict.status,
                    "request_digest": record["request_digest"],
                },
            )
    if record["verdict"]["status"] == "reject":
        raise CompletionRejected("The declared completion lacks required evidence")
    return record["verdict"]["status"] == "accept"
