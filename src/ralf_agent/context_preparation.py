"""Auxiliary context evidence in the original Local execution authority."""

import asyncio
import copy
import inspect

from .context_summaries import ContextSummary
from .decisions import final_output
from .errors import BudgetExceeded, DefinitionMismatch, RalfError, ValidationError
from .managed_context import ManagedContextPipeline
from .model_evidence import (
    _close_lazy,
    settlement_usage,
    snapshot_model_response,
    validate_received_response,
)
from .ports import is_sync_callable
from .types import ModelResponse, digest

TERMINAL = {"succeeded", "failed", "cancelled"}
FINAL = {"completed", "failed", "skipped", "outcome_unknown"}


def _key(run):
    return f"{run['node']}:{run['decisions']}"


def _intent(record):
    return digest(
        {
            k: record[k]
            for k in (
                "schema_version",
                "node",
                "decision",
                "source",
                "policy",
                "plan",
                "references",
                "request",
                "reservation_id",
            )
        }
    )


def _schema(limit):
    return {
        "type": "object",
        "required": ["text"],
        "additionalProperties": False,
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": limit, "pattern": r"\S"}
        },
    }


def validate_journal(engine, run):
    """Query-only validation also works with offline/replaced execution components."""
    try:
        records = run.get("context_preparations", {})
        markers = run.get("context_preparation_markers", {})
        receipts = run.get("context_preparation_receipts", {})
        snapshots = run.get("context_preparation_snapshots", {})
        if any(type(v) is not dict for v in (records, markers, receipts, snapshots)) or set(
            markers
        ) != set(records):
            raise DefinitionMismatch("Context stage lost its independent intent journal")
        for k, r in records.items():
            if (
                type(r) is not dict
                or type(r["schema_version"]) is not int
                or r["schema_version"] != 1
                or type(r["node"]) is not int
                or type(r["decision"]) is not int
                or r["node"] < 0
                or r["decision"] < 0
                or k != f"{r['node']}:{r['decision']}"
                or r["status"] not in FINAL | {"prepared", "executing", "response_received"}
                or markers[k] != _intent(r)
            ):
                raise DefinitionMismatch("Context stage state or intent is invalid")
            source = r["source"]
            if (
                source
                != {
                    "run_id": run["id"],
                    "scope": run["scope"],
                    "release_digest": run["release_digest"],
                    "history_digest": digest(r["plan"]["history"]),
                }
                or r["policy"] != engine._step_manifest(run, r["node"])["managed_context"]
                or r["plan"]["references"] != r["references"]["references"]
            ):
                raise DefinitionMismatch("Context stage lost original source ownership")
            from .context_pipeline import _groups

            _, groups = _groups(r["plan"]["history"])
            selected = r["plan"]["selected"]
            if (
                type(selected) is not list
                or any(type(i) is not int for i in selected)
                or selected != sorted(set(selected))
                or not selected
                or selected[-1] != len(groups) - 1
                or selected[0] < 0
                or r["plan"]["groups"] != [g for i, g in enumerate(groups) if i not in selected]
                or r["plan"]["coverage"] != [digest(g) for g in r["plan"]["groups"]]
            ):
                raise DefinitionMismatch("Context stage changed complete source groups")
            response = r["response"]
            if (response is None and k in receipts) or (
                response is not None and receipts.get(k) != digest(response)
            ):
                raise DefinitionMismatch("Context stage lost its independent response receipt")
            snapshot = r["snapshot"]
            if r["status"] in FINAL:
                if (
                    type(snapshot) is not dict
                    or snapshots.get(k) != digest(snapshot)
                    or snapshot["manifest"]["digest"] != digest(snapshot["messages"])
                ):
                    raise DefinitionMismatch("Context stage lost its frozen business snapshot")
                if r["status"] != "completed" and snapshot != r["plan"]["fallback"]:
                    raise DefinitionMismatch("Failed context stage changed its fixed fallback")
            elif snapshot is not None or k in snapshots:
                raise DefinitionMismatch("Unfinished context stage has an adopted snapshot")
            model = r["policy"]["policy"]["mode"] == "model"
            reservation_id = r["reservation_id"]
            proof = (
                engine.store.managed_stage_reservation(run["id"], reservation_id)
                if reservation_id
                else None
            )
            if inspect.iscoroutine(proof):
                proof.close()
                raise DefinitionMismatch("Context accounting must be synchronous")
            if r["status"] == "prepared" and proof is not None:
                raise DefinitionMismatch(
                    "Prepared context stage already owns a dispatch reservation"
                )
            if proof is not None:
                if (
                    not model
                    or reservation_id != "context:" + digest([run["id"], k])
                    or proof["id"] != reservation_id
                    or proof["run_id"] != run["id"]
                    or type(proof["amount"]) is not int
                    or proof["amount"] != 1
                ):
                    raise DefinitionMismatch("Context stage reservation ownership differs")
                if r["status"] in {"completed", "failed"}:
                    if (
                        response is None
                        or proof["state"] != "settled"
                        or type(proof["actual"]) is not int
                        or proof["actual"] != 1
                        or proof["usage"] != settlement_usage(response["usage"])
                    ):
                        raise DefinitionMismatch("Context response has contradictory settlement")
                elif (
                    proof["state"] not in {"reserved", "unknown"}
                    or proof["actual"] is not None
                    or proof["usage"] is not None
                    or (r["status"] == "outcome_unknown" and proof["state"] != "unknown")
                    or r["status"] == "skipped"
                ):
                    raise DefinitionMismatch("Context stage lost its held credit")
            elif reservation_id is not None and r["status"] not in {
                "prepared",
                "skipped",
                "failed",
            }:
                raise DefinitionMismatch("Dispatched context stage lost its reservation")
            elif r["status"] in {"executing", "response_received", "outcome_unknown"} or (
                model and response is not None
            ):
                raise DefinitionMismatch("Context call lost its independent accounting")
            if (r["status"] == "response_received" and response is None) or (
                response is not None
                and r["status"] not in {"response_received", "completed", "failed"}
            ):
                raise DefinitionMismatch("Context call receipt contradicts its state")
        if set(receipts) - set(records) or set(snapshots) - set(records):
            raise DefinitionMismatch("Context evidence lost its owning stage")
        for a in run["actions"]:
            marker = a.get("context_preparation")
            if marker is not None:
                r = records[marker["key"]]
                if (
                    a["kind"] != "model"
                    or a["node"] != r["node"]
                    or marker["intent_digest"] != markers[marker["key"]]
                    or r["status"] not in FINAL
                    or a["context_manifest"].get("context_preparation") != marker
                ):
                    raise DefinitionMismatch("Business Action lost its fixed context stage")
    except DefinitionMismatch:
        raise
    except Exception as exc:
        raise DefinitionMismatch("Context stage journal or accounting is malformed") from exc


def _save(engine, run_id, key, record, event):
    with engine.store.transaction():
        run = engine._authorized(run_id)
        run["context_preparations"][key] = copy.deepcopy(record)
        if record["response"] is not None:
            run.setdefault("context_preparation_receipts", {})[key] = digest(record["response"])
        if record["snapshot"] is not None:
            run.setdefault("context_preparation_snapshots", {})[key] = digest(record["snapshot"])
        engine._commit(run, event, {"key": key, "status": record["status"]})


def _check(engine, run_id, key):
    run = engine._authorized(run_id)
    validate_journal(engine, run)
    engine._check_release(run)
    record = run["context_preparations"][key]
    context = engine._components(run, record["node"]).context
    if (
        not isinstance(context, ManagedContextPipeline)
        or context.identity != record["policy"]["policy"]
    ):
        raise DefinitionMismatch("Executing context policy differs from its fixed release")
    return run, record, context


def _projection(record, messages, manifest):
    bundle = record["references"]
    if bundle["recall_manifest"] is not None:
        manifest["memory_recall"] = bundle["recall_manifest"]
    if bundle["recall_policy"] is not None:
        manifest["memory_recall_policy"] = bundle["recall_policy"]
    return {"messages": copy.deepcopy(messages), "manifest": copy.deepcopy(manifest)}


def _fallback(engine, run_id, key, record, status, code):
    record["status"], record["error"] = status, {"code": code}
    record["snapshot"] = copy.deepcopy(record["plan"]["fallback"])
    _save(engine, run_id, key, record, "context_preparation_fallback")


def _adopt(engine, run_id, key, *, terminal=False):
    run = engine._authorized(run_id)
    validate_journal(engine, run)
    record = run["context_preparations"][key]
    response = record["response"]
    # Accounting adopts durable response evidence even if the live provider is gone.
    if terminal:
        messages, manifest = (
            record["plan"]["fallback"]["messages"],
            record["plan"]["fallback"]["manifest"],
        )
        status, error = "failed", {"code": "business_closed"}
    else:
        _, record, context = _check(engine, run_id, key)
        try:
            validate_received_response(response)
            if response["tool_calls"]:
                raise ValidationError("Context summary cannot propose tools")
            text = final_output(response["output"], _schema(context.summary_max_chars))["text"]
            summary = ContextSummary(text, record["plan"]["coverage"])
            messages, manifest = context.finish(copy.deepcopy(record["plan"]), summary)
            record["summary"] = {"text": text, "coverage": record["plan"]["coverage"]}
            status, error = "completed", None
        except ValidationError:
            messages, manifest = (
                record["plan"]["fallback"]["messages"],
                record["plan"]["fallback"]["manifest"],
            )
            status, error = "failed", {"code": "invalid_summary"}
    with engine.store.transaction():
        engine.store.settle(record["reservation_id"], 1, settlement_usage(response["usage"]))
        record["status"], record["error"] = status, error
        record["snapshot"] = _projection(record, messages, manifest)
        _save(engine, run_id, key, record, "context_preparation_adopted")


def _check_actual_provider(engine, provider, record):
    if (
        engine._component_identity(provider, ("complete",), False, "Summary provider")
        != record["policy"]["provider"]
    ):
        raise DefinitionMismatch("The actual summary provider differs from the fixed release")


def _preflight(engine, run_id, key, provider):
    _, record, _ = _check(engine, run_id, key)
    _check_actual_provider(engine, provider, record)
    validate = getattr(provider, "validate_request", None)
    if validate is not None:
        if not is_sync_callable(validate):
            raise ValidationError("Summary request validation must be synchronous")
        request = record["request"]
        try:
            engine._component_result(
                validate(copy.deepcopy(request["messages"]), []),
                type(None),
                "Summary request validation",
            )
        except RalfError:
            raise
        except Exception:
            raise ValidationError("Summary provider rejected its fixed request") from None
        _check(engine, run_id, key)


def _dispatch(engine, run_id, key, record):
    with engine.store.transaction():
        _check(engine, run_id, key)
        current = engine._authorized(run_id)
        if current["state"] in TERMINAL or current["state"] == "cancelling":
            return False
        engine.store.reserve(run_id, record["reservation_id"], 1)
        record["status"] = "executing"
        _save(engine, run_id, key, record, "context_preparation_dispatched")
    return True


async def recover_terminal_context(engine, run_id):
    run = engine._authorized(run_id)
    validate_journal(engine, run)
    for key, record in run.get("context_preparations", {}).items():
        if record["status"] == "response_received":
            _adopt(engine, run_id, key, terminal=True)
        elif record["status"] == "executing":
            with engine.store.transaction():
                engine.store.mark_unknown(record["reservation_id"])
                _fallback(engine, run_id, key, record, "outcome_unknown", "interrupted_summary")
        elif record["status"] == "prepared":
            _fallback(engine, run_id, key, record, "skipped", "business_closed")


async def prepare_context(engine, run_id, step, context):
    from .context_artifacts import prepare

    if not await prepare(engine, run_id, context):
        return None
    run = engine._authorized(run_id)
    validate_journal(engine, run)
    key = _key(run)
    record = run.get("context_preparations", {}).get(key)
    if record is None:
        loaded = await engine._load_references(run, step)
        if loaded is None:
            return None
        refs, recall, knowledge_refs, _, facts, policy = loaded
        bundle = {
            "references": refs,
            "recall_manifest": recall,
            "knowledge_refs": knowledge_refs,
            "facts": facts,
            "recall_policy": policy.identity if engine.recall_planner is not None else None,
        }
        plan = (
            context.prepare(run["messages"], refs, step["max_context_chars"])
            if isinstance(context, ManagedContextPipeline)
            else None
        )
        plan = engine._component_result(plan, (dict, type(None)), "Context preparation")
        if plan is None:
            messages, manifest = engine._assemble_context(
                run["messages"], refs, step["max_context_chars"], context=context
            )
            temporary = {"references": bundle}
            projection = _projection(temporary, messages, manifest)
            return projection["messages"], projection["manifest"], knowledge_refs, facts
        record = {
            "schema_version": 1,
            "node": run["node"],
            "decision": run["decisions"],
            "source": {
                "run_id": run_id,
                "scope": run["scope"],
                "release_digest": run["release_digest"],
                "history_digest": digest(run["messages"]),
            },
            "policy": engine._step_manifest(run)["managed_context"],
            "plan": plan,
            "references": bundle,
            "request": None,
            "reservation_id": "context:" + digest([run_id, key])
            if context.mode == "model"
            else None,
            "status": "prepared",
            "response": None,
            "snapshot": None,
            "summary": None,
            "error": None,
        }
        record["plan"]["fallback"] = _projection(record, **plan["fallback"])
        try:
            if context.mode == "model":
                request = context.request(copy.deepcopy(plan))
                record["request"] = {"messages": request.messages, "tools": request.tools}
        except ValidationError:
            record["status"], record["snapshot"], record["error"] = (
                "failed",
                copy.deepcopy(record["plan"]["fallback"]),
                {"code": "summary_source_limit"},
            )
        with engine.store.transaction():
            current = engine._authorized(run_id)
            engine._check_release(current)
            if current["state"] in TERMINAL or current["state"] == "cancelling":
                return None
            if current["messages"] != run["messages"] or _key(current) != key:
                raise DefinitionMismatch("Context source changed during preparation")
            current.setdefault("context_preparations", {})[key] = copy.deepcopy(record)
            current.setdefault("context_preparation_markers", {})[key] = _intent(record)
            if record["snapshot"] is not None:
                current.setdefault("context_preparation_snapshots", {})[key] = digest(
                    record["snapshot"]
                )
            engine._commit(current, "context_preparation_intent", {"key": key})
    run, record, context = _check(engine, run_id, key)
    if record["source"]["history_digest"] != digest(run["messages"]):
        raise DefinitionMismatch("Pending context stage lost its fixed history")
    if run["state"] in TERMINAL or run["state"] == "cancelling":
        return None
    if record["status"] == "executing":
        with engine.store.transaction():
            engine.store.mark_unknown(record["reservation_id"])
            _fallback(engine, run_id, key, record, "outcome_unknown", "interrupted_summary")
    elif record["status"] == "prepared":
        if context.mode == "excerpt":
            try:
                summary = context.excerpt(copy.deepcopy(record["plan"]))
                messages, manifest = context.finish(copy.deepcopy(record["plan"]), summary)
                record["summary"] = {"text": summary.text, "coverage": list(summary.group_digests)}
                record["snapshot"], record["status"] = (
                    _projection(record, messages, manifest),
                    "completed",
                )
                _save(engine, run_id, key, record, "context_preparation_adopted")
            except ValidationError:
                _fallback(engine, run_id, key, record, "failed", "invalid_summary")
        else:
            provider = engine.providers.get(context.provider)
            request = record["request"]
            try:
                _preflight(engine, run_id, key, provider)
                if not _dispatch(engine, run_id, key, record):
                    return None
            except BudgetExceeded:
                _fallback(engine, run_id, key, record, "skipped", "summary_budget_exhausted")
            except ValidationError:
                _fallback(engine, run_id, key, record, "failed", "summary_request_invalid")
            if record["status"] == "executing":
                # Once dispatch intent is committed, a missing response is unknown.
                try:
                    response = await asyncio.wait_for(
                        provider.complete(copy.deepcopy(request["messages"]), []), context.timeout
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
                        engine.store.mark_unknown(record["reservation_id"])
                        _fallback(
                            engine,
                            run_id,
                            key,
                            record,
                            "outcome_unknown",
                            exc.code if isinstance(exc, RalfError) else "summary_call_unknown",
                        )
                else:
                    record["response"], record["status"] = encoded, "response_received"
                    _save(engine, run_id, key, record, "context_preparation_response_received")
                    _check(engine, run_id, key)
                    _check_actual_provider(engine, provider, record)
    run = engine._authorized(run_id)
    if run["context_preparations"][key]["status"] == "response_received":
        _adopt(
            engine, run_id, key, terminal=run["state"] in TERMINAL or run["state"] == "cancelling"
        )
    run, record, _ = _check(engine, run_id, key)
    if run["state"] in TERMINAL or run["state"] == "cancelling":
        return None
    snapshot = copy.deepcopy(record["snapshot"])
    snapshot["manifest"]["context_preparation"] = {
        "key": key,
        "intent_digest": run["context_preparation_markers"][key],
    }
    bundle = record["references"]
    return snapshot["messages"], snapshot["manifest"], bundle["knowledge_refs"], bundle["facts"]
