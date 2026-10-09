"""Original Local authority journals optional memory evidence, never business Actions."""

import asyncio
import copy
import inspect
import time
from dataclasses import asdict

from .decisions import final_output
from .errors import BudgetExceeded, DefinitionMismatch, RalfError, ValidationError
from .memory import memory_call
from .memory_extraction import FactProposal
from .recall import RecallPage, RecallQuery, _fact_records
from .types import canonical, digest

TERMINAL = {"succeeded", "failed", "cancelled"}


def _action(run, source):
    action = next((a for a in run["actions"] if a["id"] == source["action_id"]), None)
    if (
        action is None
        or action["kind"] != "model"
        or action["node"] != source["node"]
        or action["status"] != "completed"
        or action.get("decision_skipped")
        or action["response"]["tool_calls"]
        or digest(action["response"]) != source["response_digest"]
    ):
        raise DefinitionMismatch("Memory stage lost its adopted final model source")
    return action


def _marker(record):
    return {
        "schema_version": 1,
        "source_digest": digest(record["source"]),
        "proposal_digest": digest(
            record["facts"]
            and [
                {k: f[k] for k in ("key", "value", "expires_at", "reservation_id")}
                for f in record["facts"]
            ]
        ),
        "policy_digest": digest(record["policy"]),
    }


def _receipt_data(record, fact):
    return {
        "key": fact["key"],
        "version": 1,
        "value_digest": digest(fact["value"]),
        "source_digest": digest(record["source"]),
    }


def _validate_record(engine, run, record):
    if (
        type(record) is not dict
        or type(record["schema_version"]) is not int
        or record["schema_version"] != 1
        or type(record["node"]) is not int
        or type(record["facts"]) is not list
        or record["status"]
        not in {"proposing", "prepared", "outcome_unknown", "completed", "skipped", "failed"}
    ):
        raise DefinitionMismatch("Memory stage journal has invalid schema or state")
    source = record["source"]
    if (
        source["scope"] != run["scope"]
        or source["run_id"] != run["id"]
        or source["release_digest"] != run["release_digest"]
        or source["node"] != record["node"]
        or record["policy"] != engine._step_manifest(run, record["node"])["managed_memory"]
    ):
        raise DefinitionMismatch("Memory stage journal has invalid original ownership")
    if _action(run, source).get("memory_stage") != _marker(record):
        raise DefinitionMismatch("Memory stage journal lost its independent proposal marker")
    states = []
    for fact in record["facts"]:
        status = fact["status"]
        if status not in {
            "prepared",
            "writing",
            "outcome_unknown",
            "receipt_received",
            "completed",
            "skipped",
        }:
            raise DefinitionMismatch("Memory fact journal has invalid state")
        if fact["key"] != "auto:" + digest(
            [run["id"], record["node"], fact["value"]["key"]]
        ) or fact["reservation_id"] != "memory:" + digest([run["id"], fact["key"]]):
            raise DefinitionMismatch("Memory fact identity differs from adopted proposal")
        receipt = fact["receipt"]
        if status in {"receipt_received", "completed"}:
            if type(receipt) is not dict or receipt != _receipt_data(record, fact):
                raise DefinitionMismatch("Memory fact receipt differs from its original intent")
        elif status == "skipped":
            if receipt not in ({"skipped": "business_closed"}, {"skipped": "expired"}):
                raise DefinitionMismatch("Memory fact skip receipt is invalid")
        elif receipt is not None:
            raise DefinitionMismatch("Unconfirmed memory fact contains a receipt")
        reservation = engine.store.managed_stage_reservation(run["id"], fact["reservation_id"])
        if (
            type(reservation) is not dict
            or reservation["run_id"] != run["id"]
            or reservation["id"] != fact["reservation_id"]
            or type(reservation["amount"]) is not int
            or reservation["amount"] != 1
        ):
            if inspect.iscoroutine(reservation):
                reservation.close()
            raise DefinitionMismatch("Memory fact lost independent reservation ownership")
        if status in {"completed", "skipped"}:
            if (
                reservation["state"] != "settled"
                or type(reservation["actual"]) is not int
                or reservation["actual"] != (1 if status == "completed" else 0)
                or reservation["usage"] != receipt
            ):
                raise DefinitionMismatch("Memory fact completion has contradictory accounting")
        elif (
            reservation["state"] not in {"reserved", "unknown"}
            or (status == "prepared" and reservation["state"] != "reserved")
            or reservation["actual"] is not None
            or reservation["usage"] is not None
        ):
            raise DefinitionMismatch("Pending memory fact no longer owns held credits")
        states.append(status)
    if (
        (record["status"] == "completed" and any(s != "completed" for s in states))
        or (record["status"] in {"failed", "proposing"} and states)
        or (
            record["status"] == "skipped"
            and (
                not states
                or "skipped" not in states
                or any(s not in {"completed", "skipped"} for s in states)
            )
        )
    ):
        raise DefinitionMismatch("Memory stage aggregate state contradicts fact evidence")


def validate_journal(engine, run):
    try:
        records = run.get("memory_stages", {})
        if type(records) is not dict:
            raise DefinitionMismatch("Memory stage journal must be an indexed object")
        for action in run["actions"]:
            if (
                "source_digest" in action.get("memory_stage", {})
                and str(action["node"]) not in records
            ):
                raise DefinitionMismatch("Memory stage lost its mandatory journal")
        for key, record in records.items():
            if key != str(record["node"]):
                raise DefinitionMismatch("Memory stage journal index differs")
            _validate_record(engine, run, record)
    except DefinitionMismatch:
        raise
    except Exception as exc:
        raise DefinitionMismatch(
            "Memory stage journal or accounting evidence is malformed"
        ) from exc


def _check(engine, run_id, record):
    run = engine._authorized(run_id)
    validate_journal(engine, run)
    engine._check_release(run)
    source = record["source"]
    if source["scope"] != asdict(engine.scope) or source["release_digest"] != run["release_digest"]:
        raise DefinitionMismatch("Memory stage source Scope or Release changed")
    if source["run_id"] != run_id or record["node"] != source["node"]:
        raise DefinitionMismatch("Memory stage source ownership changed")
    action = _action(run, source)
    if action.get("memory_stage") != _marker(record):
        raise DefinitionMismatch("Memory stage lost its independent source marker")
    step = engine._agent_step(run, source["node"])
    if canonical(final_output(action["response"]["output"], step["output_schema"])) != canonical(
        source["result"]
    ):
        raise DefinitionMismatch("Memory stage result differs from adopted output")
    policy = engine._components(run, source["node"]).stage_policy
    if policy is None or digest(policy.identity) != digest(record["policy"]):
        raise DefinitionMismatch("Memory stage policy differs from pinned admission")
    policy.check(engine.scope)
    return policy


def _save(engine, run_id, record, event):
    with engine.store.transaction():
        run = engine._authorized(run_id)
        run["memory_stages"][str(record["node"])] = copy.deepcopy(record)
        engine._commit(run, event, {"node": record["node"], "status": record["status"]})


def _error(code):
    return {"code": code}


def _prepare(engine, run_id, result):
    run = engine._authorized(run_id)
    policy = engine._components(run).stage_policy
    if policy is None:
        return None
    policy.check(engine.scope)
    action = next(
        a
        for a in reversed(run["actions"])
        if a["node"] == run["node"]
        and a["kind"] == "model"
        and a["status"] == "completed"
        and not a["response"]["tool_calls"]
        and not a.get("decision_skipped")
    )
    existing = run.get("memory_stages", {}).get(str(run["node"]))
    if existing is not None:
        _check(engine, run_id, existing)
        return existing
    if action.get("memory_stage") != {"schema_version": 1, "required": True}:
        raise DefinitionMismatch("Memory stage required source marker or journal is missing")
    source = {
        "run_id": run_id,
        "node": run["node"],
        "action_id": action["id"],
        "response_digest": digest(action["response"]),
        "result": copy.deepcopy(result),
        "scope": asdict(engine.scope),
        "release_digest": run["release_digest"],
    }
    record = {
        "schema_version": 1,
        "node": run["node"],
        "source": source,
        "policy": policy.identity,
        "facts": [],
        "status": "proposing",
        "error": None,
    }
    with engine.store.transaction():
        current = engine._authorized(run_id)
        current.setdefault("memory_stages", {})[str(run["node"])] = copy.deepcopy(record)
        next(a for a in current["actions"] if a["id"] == action["id"])["memory_stage"] = _marker(
            record
        )
        engine._commit(current, "memory_stage_source_recorded", {"node": run["node"]})
    phase = "selecting"
    try:
        if len(canonical(source)) > 65536:
            raise ValidationError("Memory stage source exceeded evidence bound")
        expiry = policy.admission.identity["expires_at"]
        if expiry is not None and expiry <= time.time():
            raise ValidationError("Memory admission policy has expired")
        proposals = policy.propose(copy.deepcopy(source))
        if type(proposals) is not list:
            if inspect.iscoroutine(proposals) or inspect.isgenerator(proposals):
                proposals.close()
            raise ValidationError("Memory selection must return a concrete list")
        if len(proposals) > policy.admission.identity["max_facts"]:
            raise ValidationError("Memory stage proposal count exceeded allowance")
        admitted = []
        for proposal in proposals:
            validated = policy.admission.validate(proposal, copy.deepcopy(source))
            if type(validated) is not FactProposal:
                if inspect.iscoroutine(validated) or inspect.isgenerator(validated):
                    validated.close()
                raise ValidationError("Memory admission requires a concrete grounded FactProposal")
            # Re-run the base allowlist, independent of a custom validator implementation.
            admitted.append(_validate_grounded(policy, validated, source).to_dict())
        if len({p["key"] for p in admitted}) != len(admitted):
            raise ValidationError("Memory stage contains duplicate logical keys")
        _check(engine, run_id, record)
        facts = []
        for proposal in admitted:
            key = "auto:" + digest([run_id, run["node"], proposal["key"]])
            facts.append(
                {
                    "key": key,
                    "value": {
                        **proposal,
                        "source_run_id": run_id,
                        "source_node": run["node"],
                        "source_digest": digest(source),
                        "release_digest": run["release_digest"],
                        "trust": "completed-result-observation",
                    },
                    "expires_at": expiry,
                    "reservation_id": "memory:" + digest([run_id, key]),
                    "status": "prepared",
                    "receipt": None,
                }
            )
        with engine.store.transaction():
            phase = "reserving"
            for fact in facts:
                engine.store.reserve(run_id, fact["reservation_id"], 1)
            phase = "adopting"
            record["facts"] = facts
            record["status"] = "prepared"
            current = engine._authorized(run_id)
            current["memory_stages"][str(run["node"])] = copy.deepcopy(record)
            next(a for a in current["actions"] if a["id"] == action["id"])["memory_stage"] = (
                _marker(record)
            )
            engine._commit(current, "memory_stage_proposal_adopted", {"node": run["node"]})
    except DefinitionMismatch:
        raise
    except Exception as exc:
        if phase != "selecting" and not (phase == "reserving" and isinstance(exc, BudgetExceeded)):
            raise
        record["status"] = "failed"
        record["error"] = _error(exc.code if isinstance(exc, RalfError) else "validation_error")
        _save(engine, run_id, record, "memory_stage_failed")
    return record


def _validate_grounded(policy, proposal, source):
    from .memory_extraction import MemoryAdmissionPolicy

    return MemoryAdmissionPolicy(
        **{
            k: v
            for k, v in policy.admission.identity.items()
            if k in {"fields", "max_facts", "max_value_chars", "expires_at"}
        }
    ).validate(proposal, source)


async def _inspect(engine, run_id, record, fact):
    policy = _check(engine, run_id, record)

    async def verify(found):
        if type(found) is not dict or found.get("key") != fact["key"]:
            raise DefinitionMismatch("Exact memory inspection returned a different key")
        _fact_records([found])
        if (
            type(found.get("version")) is not int
            or found["version"] != 1
            or canonical(found.get("value")) != canonical(fact["value"])
            or found.get("expires_at") != fact["expires_at"]
        ):
            raise DefinitionMismatch("Memory stage CAS receipt conflicts with its intent")
        result = await memory_call(
            policy.memory.validate_facts, engine.scope, policy.namespace, [found]
        )
        _check(engine, run_id, record)
        if result is not None:
            raise ValidationError("Memory fact validation must complete with None")
        return _receipt_data(record, fact)

    if record["policy"]["inspection"] == "exact-v1":
        found = await memory_call(
            policy.memory.inspect_fact, engine.scope, policy.namespace, fact["key"]
        )
        _check(engine, run_id, record)
        return None if found is None else await verify(found)
    continuation = fact.get("inspection", {})
    cursor, snapshot, seen = continuation.get("cursor"), continuation.get("snapshot"), set()
    for _ in range(32):
        try:
            page = await memory_call(
                policy.memory.recall,
                engine.scope,
                policy.namespace,
                RecallQuery(
                    text=fact["key"], max_items=16, max_chars=65536, scan_limit=256, cursor=cursor
                ),
            )
        except ValidationError:
            if cursor is not None:
                fact["inspection"] = {}
                _save(engine, run_id, record, "memory_inspection_snapshot_reset")
            raise
        _check(engine, run_id, record)
        if (
            type(page) is not RecallPage
            or len(page.items) > 16
            or page.scanned > 256
            or page.used_chars > 65536
        ):
            raise ValidationError("Memory stage inspection exceeded bounded recall contract")
        if snapshot is not None and page.snapshot_id != snapshot:
            raise ValidationError("Memory stage inspection changed snapshot")
        snapshot = page.snapshot_id
        for found in page.items:
            if found.get("key") == fact["key"]:
                return await verify(found)
        cursor = page.next_cursor
        if cursor is None:
            fact["inspection"] = {}
            return None
        if cursor in seen:
            raise ValidationError("Memory stage inspection repeated cursor")
        seen.add(cursor)
        fact["inspection"] = {"cursor": cursor, "snapshot": snapshot}
        _save(engine, run_id, record, "memory_inspection_progress")
    raise ValidationError("Memory stage inspection scan allowance exhausted")


def _receipt(engine, run_id, record, fact, receipt):
    fact["receipt"], fact["status"] = receipt, "receipt_received"
    _save(engine, run_id, record, "memory_fact_receipt_recorded")
    with engine.store.transaction():
        engine.store.settle(fact["reservation_id"], 1, receipt)
        fact["status"] = "completed"
        _save(engine, run_id, record, "memory_fact_receipt_adopted")


def _skip(engine, run_id, record, fact, reason):
    with engine.store.transaction():
        fact["receipt"] = {"skipped": reason}
        engine.store.settle(fact["reservation_id"], 0, fact["receipt"])
        fact["status"] = "skipped"
        _save(engine, run_id, record, "memory_fact_skipped")


async def _execute(engine, run_id, record, *, query_only):
    policy = _check(engine, run_id, record)
    if record["status"] in {"completed", "failed", "skipped"}:
        return
    if record["status"] == "proposing":
        record["status"], record["error"] = "failed", _error("abandoned_pure_proposal")
        _save(engine, run_id, record, "memory_stage_failed")
        return
    async with asyncio.timeout(policy.timeout):
        for fact in record["facts"]:
            _check(engine, run_id, record)
            if fact["status"] in {"completed", "skipped"}:
                continue
            if fact["status"] == "receipt_received":
                _receipt(engine, run_id, record, fact, copy.deepcopy(fact["receipt"]))
                continue
            if fact["status"] in {"writing", "outcome_unknown"}:
                receipt = await _inspect(engine, run_id, record, fact)
                if receipt is not None:
                    _receipt(engine, run_id, record, fact, receipt)
                else:
                    fact["status"] = "outcome_unknown"
                    engine.store.mark_unknown(fact["reservation_id"])
                continue
            if query_only or engine._authorized(run_id)["state"] in TERMINAL | {"cancelling"}:
                _skip(engine, run_id, record, fact, "business_closed")
                continue
            expiry = fact["expires_at"]
            if expiry is not None and expiry <= time.time():
                _skip(engine, run_id, record, fact, "expired")
                continue
            fact["status"] = "writing"
            _save(engine, run_id, record, "memory_fact_intent_recorded")
            try:
                version = await memory_call(
                    policy.memory.put_fact,
                    engine.scope,
                    policy.namespace,
                    fact["key"],
                    copy.deepcopy(fact["value"]),
                    expected_version=0,
                    expires_at=expiry,
                )
                _check(engine, run_id, record)
                if type(version) is not int or version != 1:
                    raise ValidationError("Memory CAS must acknowledge exact first version")
                receipt = await _inspect(engine, run_id, record, fact)
                if receipt is None:
                    raise ValidationError("Memory CAS acknowledgement has no exact valid fact")
                _receipt(engine, run_id, record, fact, receipt)
            except DefinitionMismatch:
                raise
            except RalfError as exc:
                fact["status"], record["error"] = "outcome_unknown", _error(exc.code)
                engine.store.mark_unknown(fact["reservation_id"])
                _save(engine, run_id, record, "memory_fact_outcome_unknown")
    record["status"] = (
        "outcome_unknown"
        if any(
            f["status"] in {"writing", "outcome_unknown", "receipt_received"}
            for f in record["facts"]
        )
        else "completed"
        if all(f["status"] == "completed" for f in record["facts"])
        else "skipped"
    )
    if record["status"] == "completed":
        record["error"] = None
    _save(engine, run_id, record, "memory_stage_finished")


async def _run(engine, run_id, record, *, query_only):
    try:
        await _execute(engine, run_id, record, query_only=query_only)
    except DefinitionMismatch:
        raise
    except (RalfError, TimeoutError, asyncio.CancelledError) as exc:
        for fact in record["facts"]:
            if fact["status"] == "writing":
                fact["status"] = "outcome_unknown"
                engine.store.mark_unknown(fact["reservation_id"])
        record["status"] = "outcome_unknown"
        record["error"] = _error(exc.code if isinstance(exc, RalfError) else "timeout_or_cancelled")
        _save(engine, run_id, record, "memory_stage_interrupted")
        if isinstance(exc, asyncio.CancelledError):
            raise


async def finish_memory_stage(engine, run_id, result):
    record = _prepare(engine, run_id, result)
    if record is not None:
        await _run(engine, run_id, record, query_only=False)


async def recover_terminal_memory(engine, run_id):
    run = engine._authorized(run_id)
    records = run.get("memory_stages", {})
    for action in run["actions"]:
        if "memory_stage" in action and "source_digest" in action["memory_stage"]:
            if str(action["node"]) not in records:
                raise DefinitionMismatch("Memory stage lost its mandatory journal")
    for record in records.values():
        await _run(engine, run_id, copy.deepcopy(record), query_only=True)
