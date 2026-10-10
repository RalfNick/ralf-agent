"""Model field selection evidence owned by the original memory-stage authority."""

import asyncio
import copy
import inspect
import time

from .decisions import final_output
from .errors import (
    AuthorizationDenied,
    BudgetExceeded,
    DefinitionMismatch,
    RalfError,
    ValidationError,
)
from .harness import ModelRequest
from .memory_extraction import MemoryAdmissionPolicy, ModelMemoryExtractor
from .model_evidence import (
    _close_lazy,
    settlement_usage,
    snapshot_model_response,
    validate_received_response,
)
from .ports import is_sync_callable
from .types import ModelResponse, canonical, digest

TERMINAL = {"succeeded", "failed", "cancelled"}
CLOSED = TERMINAL | {"cancelling"}


class _ExpiredAdmission(ValidationError):
    pass


def marker(record):
    s = record["selection"]
    return {
        "intent_digest": digest(
            [record["source"], record["policy"], s["request"], s["reservation_id"]]
        ),
        "response_digest": None if s["response"] is None else digest(s["response"]),
        "keys_digest": None if s["keys"] is None else digest(s["keys"]),
    }


def _keys(record):
    policy = record["policy"]
    admission = MemoryAdmissionPolicy(
        **{
            k: policy["admission"][k]
            for k in ("fields", "max_facts", "max_value_chars", "expires_at")
        }
    )
    selector = ModelMemoryExtractor(
        admission,
        provider=policy["selection"]["provider"],
        max_context_chars=policy["selection"]["max_context_chars"],
    )
    response = record["selection"]["response"]
    validate_received_response(response)
    if response["tool_calls"]:
        raise ValidationError("Memory selector cannot propose tools")
    return final_output(response["output"], selector.agent.output_schema)["keys"]


def validate_record(engine, run, record):
    s = record["selection"]
    if (
        type(s) is not dict
        or type(s["schema_version"]) is not int
        or s["schema_version"] != 1
        or s["status"]
        not in {
            "prepared",
            "executing",
            "response_received",
            "completed",
            "failed",
            "skipped",
            "outcome_unknown",
        }
        or s["reservation_id"]
        != "memory-selection:" + digest([run["id"], record["node"], digest(record["source"])])
    ):
        raise DefinitionMismatch("Memory selector has invalid state or original ownership")
    proof = engine.store.managed_stage_reservation(run["id"], s["reservation_id"])
    if inspect.iscoroutine(proof):
        proof.close()
        raise DefinitionMismatch("Memory selection accounting must be synchronous")
    status, response, keys = s["status"], s["response"], s["keys"]
    if proof is not None:
        if (
            type(proof) is not dict
            or proof["id"] != s["reservation_id"]
            or proof["run_id"] != run["id"]
            or type(proof["amount"]) is not int
            or proof["amount"] != 1
            or status in {"prepared", "skipped"}
        ):
            raise DefinitionMismatch("Memory selection dispatch proof contradicts its stage")
        if status in {"completed", "failed"}:
            if (
                response is None
                or proof["state"] != "settled"
                or type(proof["actual"]) is not int
                or proof["actual"] != 1
                or proof["usage"] != settlement_usage(response["usage"])
            ):
                raise DefinitionMismatch("Memory selection response has contradictory settlement")
        elif (
            proof["state"] not in {"reserved", "unknown"}
            or proof["actual"] is not None
            or proof["usage"] is not None
            or (status == "outcome_unknown" and proof["state"] != "unknown")
        ):
            raise DefinitionMismatch("Memory selection lost its held credit")
    elif status not in {"prepared", "failed", "skipped"} or response is not None:
        raise DefinitionMismatch("Memory selection lost its independent dispatch reservation")
    if status == "completed":
        if type(keys) is not list or keys != _keys(record):
            raise DefinitionMismatch("Adopted memory keys differ from its received response")
        if (
            record["status"] not in {"proposing", "failed"}
            and [f["value"]["key"] for f in record["facts"]] != keys
        ):
            raise DefinitionMismatch("Memory fact proposal differs from adopted selection")
    elif keys is not None:
        raise DefinitionMismatch("Unadopted memory selector contains accepted fields")
    if (status == "response_received" and response is None) or (
        response is not None and status not in {"response_received", "completed", "failed"}
    ):
        raise DefinitionMismatch("Memory selector receipt contradicts its state")
    if (
        (
            status in {"prepared", "executing", "response_received"}
            and record["status"] != "proposing"
        )
        or (status in {"failed", "skipped"} and record["status"] != "failed")
        or (
            status == "outcome_unknown"
            and (record["status"] != "outcome_unknown" or record["facts"])
        )
    ):
        raise DefinitionMismatch("Memory aggregate contradicts unfinished selection evidence")


def prepare(policy, record):
    s = {
        "schema_version": 1,
        "request": None,
        "reservation_id": "memory-selection:"
        + digest([record["source"]["run_id"], record["node"], digest(record["source"])]),
        "status": "prepared",
        "response": None,
        "keys": None,
        "error": None,
    }
    try:
        request = policy.request(copy.deepcopy(record["source"]))
        if not isinstance(request, ModelRequest):
            _close_lazy(request)
            raise ValidationError("Memory selection request must be ModelRequest")
        if (
            request.tools
            or len(canonical(request.messages)) > policy.max_context_chars
            or len(canonical(record["source"])) > 65536
        ):
            raise ValidationError("Memory selection request exceeds its granted boundary")
        s["request"] = {"messages": copy.deepcopy(request.messages), "tools": []}
    except (DefinitionMismatch, AuthorizationDenied):
        raise
    except Exception:
        s["status"], s["error"] = "failed", {"code": "memory_selector_input_invalid"}
        record["status"], record["error"] = "failed", copy.deepcopy(s["error"])
    return s


def _save(engine, run_id, record, event):
    from .managed_memory_stage import _save as save_stage

    save_stage(engine, run_id, record, event)


def _check(engine, run_id, record):
    from .managed_memory_stage import _check as check_stage

    return check_stage(engine, run_id, record)


def _actual_provider(engine, provider, record):
    if (
        engine._component_identity(provider, ("complete",), False, "Memory selector")
        != record["policy"]["selector_provider"]
    ):
        raise DefinitionMismatch("The actual memory selector differs from the pinned release")


def _failed(engine, run_id, record, status, code):
    record["selection"]["status"], record["selection"]["error"] = status, {"code": code}
    record["status"], record["error"] = (
        ("outcome_unknown" if status == "outcome_unknown" else "failed"),
        {"code": code},
    )
    _save(engine, run_id, record, "memory_selection_failed")


def _dispatch(engine, run_id, record):
    with engine.store.transaction():
        policy = _check(engine, run_id, record)
        if engine._authorized(run_id)["state"] in CLOSED:
            return False
        expiry = policy.admission.identity["expires_at"]
        if expiry is not None and expiry <= time.time():
            raise _ExpiredAdmission("Memory admission expired before dispatch")
        engine.store.reserve(run_id, record["selection"]["reservation_id"], 1)
        record["selection"]["status"] = "executing"
        _save(engine, run_id, record, "memory_selection_dispatched")
        _check(engine, run_id, record)
    return True


def _adopt(engine, run_id, record, *, terminal=False):
    s = record["selection"]
    if not terminal:
        _check(engine, run_id, record)
    try:
        if terminal:
            raise ValidationError("Business closed before selection adoption")
        keys = _keys(record)
        status, error = "completed", None
    except ValidationError:
        keys, status, error = (
            None,
            "failed",
            {"code": "business_closed" if terminal else "invalid_memory_selection"},
        )
    with engine.store.transaction():
        engine.store.settle(s["reservation_id"], 1, settlement_usage(s["response"]["usage"]))
        s["keys"], s["status"], s["error"] = keys, status, error
        if status == "failed":
            record["status"], record["error"] = "failed", error
        _save(engine, run_id, record, "memory_selection_adopted")


def recover_terminal(engine, run_id, record):
    status = record["selection"]["status"]
    if status == "response_received":
        _adopt(engine, run_id, record, terminal=True)
    elif status == "executing":
        with engine.store.transaction():
            engine.store.mark_unknown(record["selection"]["reservation_id"])
            _failed(engine, run_id, record, "outcome_unknown", "interrupted_memory_selection")
    elif status == "prepared":
        _failed(engine, run_id, record, "skipped", "business_closed")
    elif status == "completed" and record["status"] == "proposing":
        record["status"], record["error"] = "failed", {"code": "business_closed"}
        _save(engine, run_id, record, "memory_selection_closed")
    return record


async def select_memory(engine, run_id, record):
    from .managed_memory_stage import _check_actual

    policy = _check(engine, run_id, record)
    s = record["selection"]
    if s["status"] == "executing":
        with engine.store.transaction():
            engine.store.mark_unknown(s["reservation_id"])
            _failed(engine, run_id, record, "outcome_unknown", "interrupted_memory_selection")
    elif s["status"] == "prepared":
        provider = engine.providers.get(policy.provider)
        try:
            from .memory_extraction import source_value

            expiry = policy.admission.identity["expires_at"]
            if expiry is not None and expiry <= time.time():
                raise ValidationError("Memory admission has expired")
            # Ensure granted paths still refer to completed source values before dispatch.
            for path in policy.admission.identity["fields"].values():
                source_value(record["source"], path)
            _actual_provider(engine, provider, record)
            validate = getattr(provider, "validate_request", None)
            if validate is not None:
                if not is_sync_callable(validate):
                    raise ValidationError("Memory selector request validation must be synchronous")
                try:
                    engine._component_result(
                        validate(copy.deepcopy(s["request"]["messages"]), []),
                        type(None),
                        "Memory selector validation",
                    )
                except (DefinitionMismatch, AuthorizationDenied):
                    raise
                finally:
                    _check_actual(engine, policy, record)
                    _actual_provider(engine, provider, record)
        except (DefinitionMismatch, AuthorizationDenied):
            raise
        except Exception:
            _failed(engine, run_id, record, "failed", "memory_selector_request_invalid")
            return record
        _check(engine, run_id, record)
        _actual_provider(engine, provider, record)
        try:
            dispatched = _dispatch(engine, run_id, record)
        except BudgetExceeded:
            _failed(engine, run_id, record, "skipped", "memory_selector_budget_exhausted")
            return record
        except _ExpiredAdmission:
            _failed(engine, run_id, record, "failed", "memory_selector_request_invalid")
            return record
        if not dispatched:
            _failed(engine, run_id, record, "skipped", "business_closed")
            return record
        if s["status"] == "executing":
            try:
                response = await asyncio.wait_for(
                    provider.complete(copy.deepcopy(s["request"]["messages"]), []), policy.timeout
                )
                if isinstance(response, ModelResponse):
                    encoded = snapshot_model_response(response)
                else:
                    _close_lazy(response)
                    encoded = {
                        "output": None,
                        "tool_calls": [],
                        "usage": None,
                        "invalid_fields": ["response"],
                    }
            except Exception as exc:
                with engine.store.transaction():
                    engine.store.mark_unknown(s["reservation_id"])
                    _failed(
                        engine,
                        run_id,
                        record,
                        "outcome_unknown",
                        exc.code if isinstance(exc, RalfError) else "memory_selector_unknown",
                    )
            else:
                s["response"], s["status"] = encoded, "response_received"
                _save(engine, run_id, record, "memory_selection_response_received")
            _check_actual(engine, policy, record)
            _check(engine, run_id, record)
            _actual_provider(engine, provider, record)
    if s["status"] == "response_received":
        _adopt(engine, run_id, record, terminal=engine._authorized(run_id)["state"] in CLOSED)
    if s["status"] == "completed" and record["status"] == "proposing":
        if engine._authorized(run_id)["state"] in CLOSED:
            return recover_terminal(engine, run_id, record)
        policy = _check(engine, run_id, record)
        from .managed_memory_stage import _prepare_proposals

        try:
            try:
                proposals = engine._component_result(
                    policy.select(copy.deepcopy(record["source"]), copy.deepcopy(s["response"])),
                    list,
                    "Memory selector adoption",
                )
            finally:
                _check_actual(engine, policy, record)
        except (DefinitionMismatch, AuthorizationDenied):
            raise
        except Exception as exc:
            record["status"], record["error"] = (
                "failed",
                {"code": exc.code if isinstance(exc, RalfError) else "invalid_memory_proposal"},
            )
            _save(engine, run_id, record, "memory_stage_failed")
            return record
        return _prepare_proposals(engine, run_id, record, proposals)
    return record
