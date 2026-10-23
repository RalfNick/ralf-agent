"""Bounded owned Session4 drain; original Histories keep every business authority."""

import asyncio
from uuid import uuid4

from .errors import CloseIncomplete, DefinitionMismatch
from .session_types import SessionKey, SessionRef
from .temporal import TemporalEngine
from .temporal_deployment_admission import _exact
from .temporal_deployment_submissions import _query, _update
from .temporal_session_client import TemporalSessionClient
from .temporal_session_deployment_client import DeploymentSessionClient
from .temporal_session_deployment_dto import validate_intent, validate_start_view
from .temporal_session_deployment_state import selected
from .types import canonical, digest


def _reject():
    raise DefinitionMismatch("Original owned Session close identity changed")


async def close(runtime, *, client, scope, task_queue, wait_timeout=30):
    """Stop fresh acceptance; retain the receiver while original debt remains.

    The Assembly must call this before shutting down its original Worker or
    context execution owner, and retain this Task on a bounded close timeout.
    Existing observation/end ACK factories remain available during this drain.
    """
    from .temporal_session_activities import namespace_id
    from .temporal_startup_options import validate_seconds

    if type(wait_timeout) not in (int, float) or wait_timeout < 0:
        _reject()
    if wait_timeout:
        validate_seconds(wait_timeout)
    manifest = runtime.orchestration_release
    runtime.validate_release(manifest)
    if not selected(manifest) or client is None:
        _reject()
    engine = TemporalEngine(client, scope=scope, task_queue=task_queue, release=manifest)
    api = DeploymentSessionClient(TemporalSessionClient(engine, await namespace_id(client)))
    context = await api._context()
    registry = context[4]
    request = {
        "scope": context[1],
        "admission_policy": context[3],
        "namespace": context[2],
        "manifest_digest": digest(manifest),
    }
    response = await registry.execute_update(
        "close_deployment_sessions", request, id="ralf-session-close:" + uuid4().hex
    )
    await api._check(context)
    _exact(response, {"manifest_digest", "close_requested", "candidates"})
    if (
        response["manifest_digest"] != request["manifest_digest"]
        or response["close_requested"] is not True
        or type(response["candidates"]) is not list
    ):
        _reject()
    groups = {}
    for record in response["candidates"]:
        _exact(record, {"reservation", "session_submission", "session_receipt"})
        submission = record["session_submission"]
        key = SessionKey.from_dict(submission["session_key"])
        api._record(record, submission["logical_payload"])
        if (
            submission["payload"]["scope"] != context[1]
            or digest(submission["binding"]["manifest"]) != request["manifest_digest"]
        ):
            _reject()
        groups.setdefault(key.key_id, (key, []))[1].append(record)
    deadline = asyncio.get_running_loop().time() + wait_timeout
    controlled, woken = set(), set()
    while True:
        obligations = []
        for key, records in groups.values():
            try:
                runtime.validate_release(manifest)
                await _original(api, context, key, records, engine, runtime, controlled, woken)
            except Exception as exc:
                obligations.append(
                    {
                        "session_key": key.key_id,
                        "code": getattr(exc, "code", "session_close_unknown"),
                        "details": exc.report if isinstance(exc, CloseIncomplete) else None,
                    }
                )
        runtime.validate_release(manifest)
        await api._check(context)
        if not obligations:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise CloseIncomplete({"deployment_sessions": obligations})
        await asyncio.sleep(min(0.05, max(0, deadline - asyncio.get_running_loop().time())))


async def _original(api, context, key, records, engine, runtime, controlled, woken):
    handle, epoch = await api._coordinator(context, key)
    for record in records:
        submission = record["session_submission"]
        payload = submission["payload"]
        actual = await _query(
            handle,
            {
                "kind": "deployment_session_receipt",
                "scope": context[1],
                "namespace": context[2],
                "coordinator_execution_epoch": epoch,
                "command_id": payload["command_id"],
            },
        )
        await api._coordinator(context, key, epoch=epoch)
        if actual is None:
            raise CloseIncomplete(
                {"command_id": payload["command_id"], "acceptance": "application_pending"}
            )
        _exact(actual, {"receipt", "session_ref"})
        if SessionRef.from_dict(actual["session_ref"]).key != key:
            _reject()
        if record["session_receipt"] is None:
            indexed = await _update(
                context[4],
                "record_deployment_session_command",
                {
                    "scope": context[1],
                    "admission_policy": context[3],
                    "namespace": context[2],
                    "command_id": payload["command_id"],
                    "payload_digest": digest(submission["logical_payload"]),
                    "receipt": actual["receipt"],
                },
            )
            await api._check(context)
            if indexed["session_receipt"] != actual["receipt"]:
                _reject()
            record["session_receipt"] = actual["receipt"]
        elif canonical(record["session_receipt"]) != canonical(actual["receipt"]):
            _reject()
    status = await _query(handle, {"kind": "status", "scope": context[1]})
    await api._coordinator(context, key, epoch=epoch)
    if SessionRef.from_dict(status["ref"]).key != key or type(status.get("busy")) is not bool:
        _reject()
    debt = status.get("deployment_close")
    _exact(debt, {"pending_calls", "unpublished_turns"})
    if any(type(count) is not int or count < 0 for count in debt.values()):
        _reject()
    if not status["busy"]:
        if status["active_run"] is not None or any(debt.values()):
            raise CloseIncomplete({"session_debt": debt})
        return
    active = status["active_run"]
    original = next(
        (
            record
            for record in records
            if record["session_receipt"]["outcome"].get("turn", {}).get("run") == active
        ),
        None,
    )
    if original is None:
        raise CloseIncomplete({"active": "original_turn_not_in_owned_publication"})
    turn = original["session_receipt"]["outcome"]["turn"]
    selector = {
        "scope": context[1],
        "namespace": context[2],
        "coordinator_execution_epoch": epoch,
        "session_command_id": turn["command_id"],
        "turn_id": turn["turn_id"],
    }
    intent = await _query(handle, {"kind": "deployment_session_intent", **selector})
    await api._coordinator(context, key, epoch=epoch)
    intent = validate_intent(
        intent,
        deployment_id=context[3]["deployment_id"],
        scope=context[1],
        namespace=context[2],
        coordinator_execution_epoch=epoch,
    )
    selector["intent_digest"] = intent["intent_digest"]
    lifecycle = await _query(handle, {"kind": "deployment_session_lifecycle", **selector})
    await api._coordinator(context, key, epoch=epoch)
    _exact(lifecycle, {"start", "start_issued", "refusal_barrier"})
    start = lifecycle["start"]
    if start.get("phase") != "started":
        raise CloseIncomplete(
            {"phase": start.get("phase"), "intent_digest": intent["intent_digest"]}
        )
    record = await _query(
        context[4],
        {
            "kind": "deployment_session_root",
            "scope": context[1],
            "admission_policy": context[3],
            "namespace": context[2],
            "command_id": intent["run_command_id"],
            "payload_digest": digest(intent["submission"]["request"]),
        },
    )
    await api._check(context)
    if record is None or record["intent"] != intent:
        _reject()
    registry_epoch = (await context[4].describe()).run_id
    start = validate_start_view(
        start,
        intent=intent,
        deployment_id=context[3]["deployment_id"],
        registry_execution_epoch=registry_epoch,
        execution_epoch=record["execution_epoch"],
    )
    if any(
        start[name] != record[name] for name in ("reservation", "execution_epoch", "run_receipt")
    ):
        _reject()
    token = intent["intent_digest"]
    if token not in controlled:
        from .temporal_deployment_release import _binding, _certificate

        run = context[0].get_workflow_handle(intent["run_id"], run_id=record["execution_epoch"])
        closure = await _query(run, {"kind": "deployment_closure", "scope": context[1]})
        await api._coordinator(context, key, epoch=epoch)
        _exact(closure, {"version", "deployment", "ready", "reasons", "calls", "seal"})
        retired = None
        if closure["seal"] is not None:
            _certificate(closure["seal"], closure["deployment"])
            bound = {
                **record["reservation"]["root_admission"],
                "state": "held-bound",
                "execution_epoch": record["execution_epoch"],
            }
            retired = await _query(
                context[4],
                {"kind": "deployment_retirement", **_binding(bound, context[3], closure["seal"])},
            )
            await api._check(context)
            if retired is not None and retired != {
                "root": bound,
                "certificate": closure["seal"],
                "released": True,
            }:
                _reject()
        if retired is None:
            if closure["seal"] is None:
                await engine.cancel(
                    intent["run_id"], command_id="ralf-session-close-cancel:" + token
                )
            await engine.drive(intent["run_id"], wait_seconds=0)
        controlled.add(token)
    if token not in woken:
        await handle.execute_update(
            "retry_deployment_turn", selector, id="ralf-session-close-observe:" + uuid4().hex
        )
        await api._coordinator(context, key, epoch=epoch)
        woken.add(token)
    raise CloseIncomplete({"phase": "original_observation_or_ack_pending", "session_debt": debt})
