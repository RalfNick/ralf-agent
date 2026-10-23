"""Fixed ModelProvider cases below original Local execution authority.

Fixtures configure real supplier responses and faults; they never decide a case
or provide an execution receipt. Equal prompts and supplier audit are not model
idempotency evidence. Original Actions, received responses and budgets decide.
"""

import asyncio
import copy
import inspect
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Protocol

from .adapter_contract_catalog import catalog_for
from .adapter_contract_types import AdapterContractCaseResult, AdapterContractCleanupPending
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .ports import is_async_callable
from .runtime_lifecycle import BuildContext
from .types import AgentSpec, ModelResponse, Scope, canonical, digest

_CATALOG = catalog_for("model-provider", "1", "tools")


class ModelAdapterFixture(Protocol):
    def prepare(self, case_id: str, workspace: Path) -> "ModelContractSession":
        """Prepare the actual supplier and resource owner, synchronously or asynchronously."""
        ...


@dataclass(frozen=True)
class ModelContractResource:
    resource: object
    asynchronous: bool = False

    def __post_init__(self):
        if type(self.asynchronous) is not bool:
            raise ValidationError("Model contract resource close mode must be boolean")


@dataclass(frozen=True)
class ModelContractPause:
    wait_entered: Callable
    release: Callable

    def __post_init__(self):
        if not callable(self.wait_entered) or not callable(self.release):
            raise ValidationError("Model contract pause requires callable management hooks")


@dataclass(frozen=True)
class ModelContractSession:
    """Concrete borrowed provider, explicit owners and optional supplier controls.

    configure accepts output/invalid-output/tools; inject_fault accepts
    provider-error/authorization-denied/identity-drift/method-drift/backend-swap/
    response-lost/reset. pause('complete') suspends the actual selected call.
    audit returns only fixed primitive counts. reopen reconnects that same source.
    Management callbacks finish with None, except pause and audit.
    """

    provider: object
    resources: tuple[ModelContractResource, ...] = ()
    configure: Callable | None = None
    inject_fault: Callable | None = None
    pause: Callable | None = None
    audit: Callable | None = None
    reopen: Callable | None = None

    def __post_init__(self):
        if (
            not isinstance(self.resources, (tuple, list))
            or len(self.resources) > 16
            or any(type(value) is not ModelContractResource for value in self.resources)
            or any(
                value is not None and not callable(value)
                for value in (
                    self.configure,
                    self.inject_fault,
                    self.pause,
                    self.audit,
                    self.reopen,
                )
            )
        ):
            raise ValidationError("Model contract fixture requires bounded concrete resources")
        object.__setattr__(self, "resources", tuple(self.resources))


@dataclass
class _CaseControl:
    cancelled: asyncio.Event
    resets: list
    audit_before: dict | None = None


_current_case: ContextVar[_CaseControl | None] = ContextVar("model_contract_case", default=None)


class _Violation(Exception):
    pass


class _Missing(Exception):
    pass


class _RecordedWindow(Exception):
    pass


def _check(condition):
    if not condition:
        raise _Violation()


def _active():
    control = _current_case.get()
    if control is not None and control.cancelled.is_set():
        raise asyncio.CancelledError()


def _required(session, *names):
    if any(getattr(session, name) is None for name in names):
        raise _Missing()


def _dispose(value):
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()


async def _invoke(method, *args):
    value = method(*args)
    return await value if inspect.isawaitable(value) else value


async def _manage(method, *args):
    value = await _invoke(method, *args)
    if value is not None:
        _dispose(value)
        raise _Violation()


async def _configure(session, kind, specification):
    _active()
    _required(session, "configure")
    # Supplier controls receive data specifications, never a ModelResponse.
    canonical(specification)
    await _manage(session.configure, kind, copy.deepcopy(specification))
    _active()


async def _fault(session, kind):
    _active()
    _required(session, "inject_fault")
    control = _current_case.get()
    if kind != "reset" and control is not None and not any(s is session for s in control.resets):
        control.resets.append(session)
    await _manage(session.inject_fault, kind)
    if kind == "reset" and control is not None:
        control.resets[:] = [s for s in control.resets if s is not session]
    _active()


async def _audit(session):
    value = await _invoke(session.audit)
    _check(type(value) is dict and set(value) <= _CATALOG.observation_keys)
    # Validate and detach now: a later audit can return the same mutable dict.
    value = AdapterContractCaseResult("P01", "passed", "verified", value).observations
    return value


async def _case_audit(session):
    _active()
    value = await _audit(session)
    _active()
    return value


def _delta(before, after, *keys):
    if any(key not in before or key not in after for key in keys):
        raise _Missing()
    _check(all(after[key] >= before[key] for key in keys))
    return {key: after[key] - before[key] for key in keys}


def _identity(provider):
    identity = getattr(provider, "identity", None)
    _check(type(identity) is dict and bool(identity))
    canonical(identity)
    _check(is_async_callable(getattr(provider, "complete", None)))
    return copy.deepcopy(identity)


def _generic():
    return {"items": [None, False, 0, "中文🙂", {"nested": [1, 2]}]}


async def _finish(task):
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
        except Exception:
            break
    return interrupted


class _PausedCallPending(Exception):
    def __init__(self, task, release):
        super().__init__("Original Model handler cleanup remains incomplete")
        self.task, self.release = task, release

    async def cleanup(self):
        await _manage(self.release)
        await _finish(self.task)
        if not self.task.cancelled():
            self.task.exception()


async def _pause(session):
    _active()
    _required(session, "pause")
    value = await _invoke(session.pause, "complete")
    _check(type(value) is ModelContractPause)
    _active()
    return value


async def _entered(pause, operation):
    waiter = asyncio.create_task(_manage(pause.wait_entered))
    control = _current_case.get()
    cancellation = asyncio.create_task(control.cancelled.wait()) if control is not None else None
    try:
        tasks = (waiter, operation) if cancellation is None else (waiter, operation, cancellation)
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        _active()
        if operation in done:
            operation.result()
            raise _Violation()
        waiter.result()
        _check(not operation.done())
    finally:
        for observer in (waiter, cancellation):
            if observer is not None:
                if not observer.done():
                    observer.cancel()
                await _finish(observer)
                if not observer.cancelled():
                    observer.exception()


async def _suspended(session, operation, check):
    pause = await _pause(session)
    task = asyncio.create_task(operation())
    try:
        await _entered(pause, task)
        await check(task, pause)
    finally:
        try:
            await _manage(pause.release)
        except (Exception, asyncio.CancelledError):
            raise _PausedCallPending(task, pause.release) from None
        await _finish(task)
        if not task.cancelled():
            task.exception()


def _provider_suspended(session, engine, run_id):
    """Verify the original executing provider frame, not just a fixture signal."""
    action = _model(engine.store.run(run_id))[0]
    _check(action["status"] == "executing" and action["attempts"][-1]["status"] == "executing")
    task = engine._inflight.get(run_id)
    _check(task is not None and not task.done())
    method = session.provider.complete
    while isinstance(method, partial):
        method = method.func
    code = getattr(getattr(method, "__func__", method), "__code__", None)
    frame, seen = task.get_coro(), set()
    while inspect.iscoroutine(frame) and id(frame) not in seen:
        seen.add(id(frame))
        if frame.cr_code is code:
            _check(inspect.getcoroutinestate(frame) == inspect.CORO_SUSPENDED)
            return
        frame = frame.cr_await
    raise _Violation()


def _tools(workspace):
    from .tools import ToolRegistry

    path = workspace / "business.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS invocations (key TEXT, tool TEXT)")

    def read(number: int = 7):
        return {"number": number, "source": "original-business-read"}

    def write(value: str = "approved", context=None):
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("INSERT INTO invocations VALUES (?,?)", (context.effect_key, "write"))
            db.execute("INSERT OR IGNORE INTO effects VALUES (?,?)", (context.effect_key, value))
        return {"written": value, "effect_key": context.effect_key}

    registry = ToolRegistry()
    registry.register_function(read, name="contract.read", effect="read_only")
    registry.register_function(
        write,
        name="contract.write",
        effect="idempotent_write",
        requires_approval=True,
        context_parameter="context",
    )
    return registry


def _effect_counts(workspace):
    with closing(sqlite3.connect(workspace / "business.sqlite")) as db:
        return (
            db.execute("SELECT COUNT(*) FROM effects").fetchone()[0],
            db.execute("SELECT COUNT(*) FROM invocations").fetchone()[0],
        )


def _engine(session, workspace, engines, *, engine_type=None, tools=None, policy=None, path=None):
    from .engine import LocalEngine
    from .storage import SQLiteStore
    from .tools import ToolRegistry

    _active()
    engine = (engine_type or LocalEngine)(
        SQLiteStore(path or workspace / f"consumer-{len(engines)}.sqlite"),
        providers={"default": session.provider},
        tools=tools or ToolRegistry(),
        policy=policy,
        scope=Scope("model-contract", "owner"),
        runtime_profile={
            "kind": "runtime-profile",
            "name": "model-contract",
            "version": "1",
            "digest": digest({"model-contract": "1"}),
        },
    )
    engines.append(engine)
    return engine


def _admit(engine, runs, *, task=None, tools=(), schema=None, command=None):
    _active()
    spec = AgentSpec(
        "model-contract", "Use the actual supplied request", tools, output_schema=schema
    )
    payload = _generic() if task is None else task
    command = command or f"submit-{len(runs)}"
    handle = engine.submit(spec, payload, command_id=command, budget=8)
    runs.append((engine, handle.run_id))
    return handle, spec, payload


async def _drive(engine, run_id):
    _active()
    value = await engine.drive(run_id)
    _active()
    return value


def _model(record):
    return [action for action in record["actions"] if action["kind"] == "model"]


def _reservation(engine, attempt):
    row = engine.store.conn.execute("SELECT * FROM reservations WHERE id=?", (attempt,)).fetchone()
    _check(row is not None)
    return dict(row)


def _settled_run(engine, run_id, expected):
    _check(engine.store.budget(run_id) == {"limit": 8, "held": 0, "spent": expected})
    reservations = list(
        engine.store.conn.execute("SELECT * FROM reservations WHERE run_id=?", (run_id,))
    )
    _check(len(reservations) == expected)
    _check(all(row["state"] == "settled" and row["actual"] == 1 for row in reservations))


async def _completed(session, engine, runs, observations, *, output=None, usage=None, schema=None):
    output = _generic() if output is None and schema is None else output
    await _configure(session, "output", {"output": output, "usage": usage})
    handle, _, _ = _admit(engine, runs, schema=schema)
    result = await _drive(engine, handle.run_id)
    _check(result.state == "succeeded" and result.result == output)
    record = engine.store.run(handle.run_id)
    action = _model(record)[0]
    _check(len(record["actions"]) == 1 and action["status"] == "completed")
    _check(action["received_response"] == {"output": output, "tool_calls": [], "usage": usage})
    _check(action["attempts"] == [{"id": action["id"] + ":1", "status": "completed"}])
    _check(engine.store.budget(handle.run_id) == {"limit": 8, "held": 0, "spent": 1})
    reservation = _reservation(engine, action["attempts"][0]["id"])
    _check(reservation["state"] == "settled" and reservation["actual"] == 1)
    _check(json.loads(reservation["usage"]) == (usage or {"usage": "unknown"}))
    observations["settlement_checks"] = observations.get("settlement_checks", 0) + 1
    return handle, action


async def _drift(session, workspace, observations, engines, runs):
    _required(session, "configure", "inject_fault", "pause")
    await _configure(session, "output", {"output": _generic()})
    for fault, key in (("identity-drift", "identity_checks"), ("method-drift", "method_checks")):
        engine = _engine(session, workspace, engines)
        handle, _, _ = _admit(engine, runs)
        before = await _case_audit(session)
        await _fault(session, fault)
        try:
            result = await _drive(engine, handle.run_id)
            _check(result.state == "failed" and result.error == {"code": "definition_mismatch"})
        except DefinitionMismatch:
            pass
        _check(not engine.store.run(handle.run_id)["actions"])
        _check(engine.store.budget(handle.run_id) == {"limit": 8, "held": 0, "spent": 0})
        _check(_delta(before, await _case_audit(session), "model_calls")["model_calls"] == 0)
        await _fault(session, "reset")
        handle, _, _ = _admit(engine, runs)

        async def check(task, pause, *, fault=fault, engine=engine, handle=handle):
            _provider_suspended(session, engine, handle.run_id)
            await _fault(session, fault)
            await _manage(pause.release)
            result = await asyncio.shield(task)
            _check(result.state == "failed" and result.error == {"code": "definition_mismatch"})
            action = _model(engine.store.run(handle.run_id))[0]
            _check(action["status"] == "response_received")
            _check(action["received_response"]["output"] == _generic())
            _check(action["attempts"][0]["status"] == "completed")
            _settled_run(engine, handle.run_id, 1)

        await _suspended(
            session, lambda engine=engine, handle=handle: _drive(engine, handle.run_id), check
        )
        await _fault(session, "reset")
        observations[key] = 2
    observations["rejection_checks"] = 4


async def _lifecycle(session, workspace, observations, engines, runs):
    _required(session, "configure", "pause")
    await _configure(session, "output", {"output": _generic()})
    engine = _engine(session, workspace, engines)
    handle, _, _ = _admit(engine, runs)
    before = await _case_audit(session)
    if "close_calls" not in before:
        raise _Missing()

    async def check(task, pause):
        _provider_suspended(session, engine, handle.run_id)

        async def observe():
            return await asyncio.shield(task)

        observer = asyncio.create_task(observe())
        await asyncio.sleep(0)
        observer.cancel()
        await _finish(observer)
        _check(observer.cancelled() and not task.done())
        _check((await _case_audit(session))["close_calls"] == before["close_calls"])
        await _manage(pause.release)
        result = await asyncio.shield(task)
        _check(result.state == "succeeded" and result.result == _generic())
        observations.update(cancelled=True, handler_finished=True)

    await _suspended(session, lambda: _drive(engine, handle.run_id), check)


async def _recorded(session, workspace, observations, engines, runs):
    from .engine import LocalEngine

    _required(session, "configure", "reopen")
    await _configure(session, "output", {"output": _generic()})

    class InterruptEngine(LocalEngine):
        def _adopt_model_response(self, run_id, action_id):
            raise _RecordedWindow()

    path = workspace / "recorded.sqlite"
    engine = _engine(session, workspace, engines, engine_type=InterruptEngine, path=path)
    handle, spec, payload = _admit(engine, runs, command="original-submit")
    before = await _case_audit(session)
    try:
        await _drive(engine, handle.run_id)
    except _RecordedWindow:
        pass
    else:
        raise _Violation()
    original = engine.store.run(handle.run_id)
    action = _model(original)[0]
    _check(
        action["status"] == "response_received" and action["attempts"][0]["status"] == "completed"
    )
    budget = engine.store.budget(handle.run_id)
    reservation = _reservation(engine, action["attempts"][0]["id"])
    _check(budget == {"limit": 8, "held": 0, "spent": 1} and reservation["state"] == "settled")
    await engine.wait_for_threads()
    engine.close()
    engines.remove(engine)
    runs.remove((engine, handle.run_id))
    await _manage(session.reopen)
    engine = _engine(session, workspace, engines, path=path)
    runs.append((engine, handle.run_id))
    _check(engine.store.run(handle.run_id) == original)
    _check(engine.submit(spec, payload, command_id="original-submit", budget=8) == handle)
    result = await _drive(engine, handle.run_id)
    recovered = engine.store.run(handle.run_id)
    _check(result.state == "succeeded" and result.result == _generic())
    _check(recovered["id"] == original["id"] and recovered["manifest"] == original["manifest"])
    for field in ("id", "snapshot", "request", "received_response", "attempts"):
        _check(recovered["actions"][0][field] == action[field])
    _check(engine.store.budget(handle.run_id) == budget)
    _check(_reservation(engine, action["attempts"][0]["id"]) == reservation)
    _check(_delta(before, await _case_audit(session), "model_calls")["model_calls"] == 1)
    observations.update(duplicate_checks=1, reservation_checks=2, settlement_checks=2)


async def _tool_run(
    session, engine, runs, observations, *, name, arguments, call_id=None, command=None
):
    await _configure(session, "tools", {"name": name, "arguments": arguments, "call_id": call_id})
    handle, spec, payload = _admit(engine, runs, tools=(name,), command=command)
    result = await _drive(engine, handle.run_id)
    return handle, spec, payload, result


async def _tool_cases(case_id, session, workspace, observations, engines, runs):
    _required(session, "configure")
    registry = _tools(workspace)
    if case_id == "P12":

        def deny(scope, spec, arguments):
            raise AuthorizationDenied("private business policy refused")

        engine = _engine(session, workspace, engines, tools=registry, policy=deny)
        handle, _, _, result = await _tool_run(
            session,
            engine,
            runs,
            observations,
            name="contract.write",
            arguments={"value": "denied"},
        )
        _check(result.state == "failed" and result.error == {"code": "authorization_denied"})
        _check(_effect_counts(workspace) == (0, 0))
        _check(not result.pending)
        _settled_run(engine, handle.run_id, 1)
        observations.update(rejection_checks=1, settlement_checks=1)
        return
    engine = _engine(session, workspace, engines, tools=registry)
    if case_id == "P11":
        for call_id in (None, "explicit-call"):
            handle, _, _, result = await _tool_run(
                session,
                engine,
                runs,
                observations,
                name="contract.read",
                arguments={},
                call_id=call_id,
            )
            _check(result.state == "succeeded")
            record = engine.store.run(handle.run_id)
            proposals = [a for a in record["actions"] if a["kind"] == "tool"]
            _check(len(proposals) == 1 and proposals[0]["arguments"] == {"number": 7})
            _check(proposals[0]["call_id"] == (call_id or proposals[0]["id"]))
            _check(proposals[0]["result"] == {"number": 7, "source": "original-business-read"})
            _check(_model(record)[0]["received_response"]["tool_calls"][0]["arguments"] == {})
            _settled_run(engine, handle.run_id, 3)
        handle, _, _, result = await _tool_run(
            session,
            engine,
            runs,
            observations,
            name="contract.read",
            arguments={"number": "invalid"},
        )
        _check(result.state == "failed" and result.error == {"code": "validation_error"})
        _check(not [a for a in result.actions if a["kind"] == "tool"])
        _settled_run(engine, handle.run_id, 1)
        observations.update(rejection_checks=1, settlement_checks=7)
        return
    handle, spec, payload, result = await _tool_run(
        session,
        engine,
        runs,
        observations,
        name="contract.write",
        arguments={},
        call_id="write-proposal",
        command="original-submit",
    )
    _check(result.state == "waiting_approval" and len(result.pending) == 1)
    _check(_effect_counts(workspace) == (0, 0))
    pending = result.pending[0]
    action = next(a for a in result.actions if a["id"] == pending["action_id"])
    _check(action["arguments"] == {"value": "approved"} and action["call_id"] == "write-proposal")
    before = await _case_audit(session)
    # Approval signs this original operation digest and resolves effective defaults.
    receipt = engine.approve(handle.run_id, action["id"], pending["digest"], command_id="approve")
    _check(
        engine.approve(handle.run_id, action["id"], pending["digest"], command_id="approve")
        == receipt
    )
    result = await _drive(engine, handle.run_id)
    _check(result.state == "succeeded" and _effect_counts(workspace) == (1, 1))
    record = engine.store.run(handle.run_id)
    completed = next(a for a in record["actions"] if a["id"] == action["id"])
    _check(completed["status"] == "completed" and completed["approved"] is True)
    _check(completed["receipt"] is not None)
    _settled_run(engine, handle.run_id, 3)
    original = copy.deepcopy(record)
    _check((await _drive(engine, handle.run_id)).state == "succeeded")
    _check(engine.submit(spec, payload, command_id="original-submit", budget=8) == handle)
    _check(engine.store.run(handle.run_id) == original)
    _check(_effect_counts(workspace) == (1, 1))
    _check(_delta(before, await _case_audit(session), "model_calls")["model_calls"] == 1)
    if case_id == "P14":
        followup = _model(record)[1]["request"]["messages"]
        messages = [m for m in followup if m["role"] == "tool"]
        _check(len(messages) == 1 and messages[0]["tool_call_id"] == completed["call_id"])
        _check(json.loads(messages[0]["content"]) == completed["result"])
    if case_id == "P15":
        _check(
            engine.approve(handle.run_id, action["id"], pending["digest"], command_id="approve")
            == receipt
        )
        _check((await _drive(engine, handle.run_id)).state == "succeeded")
        _check(_effect_counts(workspace) == (1, 1))
    observations.update(approval_count=1, duplicate_checks=3, write_count=1, settlement_checks=3)


async def _lost(session, workspace, observations, engines, runs):
    _required(session, "configure", "inject_fault", "reopen")
    registry = _tools(workspace)
    await _configure(
        session, "tools", {"name": "contract.write", "arguments": {}, "call_id": "lost"}
    )
    path = workspace / "lost.sqlite"
    engine = _engine(session, workspace, engines, tools=registry, path=path)
    handle, spec, payload = _admit(
        engine, runs, tools=("contract.write",), command="original-submit"
    )
    before = await _case_audit(session)
    await _fault(session, "response-lost")
    result = await _drive(engine, handle.run_id)
    _check(result.state == "waiting_reconciliation")
    original = engine.store.run(handle.run_id)
    action = _model(original)[0]
    _check(action["status"] == "outcome_unknown" and action.get("received_response") is None)
    _check(action["attempts"] == [{"id": action["id"] + ":1", "status": "unknown"}])
    _check(len(original["actions"]) == 1 and _effect_counts(workspace) == (0, 0))
    reservation = _reservation(engine, action["attempts"][0]["id"])
    budget = engine.store.budget(handle.run_id)
    _check(reservation["state"] == "unknown" and budget == {"limit": 8, "held": 1, "spent": 0})
    await _fault(session, "reset")
    await engine.wait_for_threads()
    engine.close()
    engines.remove(engine)
    runs.remove((engine, handle.run_id))
    await _manage(session.reopen)
    engine = _engine(session, workspace, engines, tools=registry, path=path)
    runs.append((engine, handle.run_id))
    _check(engine.store.run(handle.run_id) == original)
    _check(engine.submit(spec, payload, command_id="original-submit", budget=8) == handle)
    # Reconnection and read-only inspection carry no retry authority. Explicit
    # drive retains the existing separate-attempt resume semantics elsewhere.
    result = engine.status(handle.run_id)
    _check(engine.diagnostics(handle.run_id).budget == budget)
    retained = engine.store.run(handle.run_id)
    _check(result.state == "waiting_reconciliation" and result.error == original["error"])
    _check(
        retained["actions"] == original["actions"] and retained["manifest"] == original["manifest"]
    )
    _check(engine.store.budget(handle.run_id) == budget)
    _check(_reservation(engine, action["attempts"][0]["id"]) == reservation)
    _check(
        _delta(before, await _case_audit(session), "model_calls", "request_count", "response_count")
        == {"model_calls": 1, "request_count": 1, "response_count": 1}
    )
    _check(_effect_counts(workspace) == (0, 0))
    observations.update(duplicate_checks=1, reservation_checks=2, write_count=0)


async def _case(case_id, session, workspace, observations, engines, runs):
    _active()
    _required(session, "audit")
    before = await _case_audit(session)
    if "close_calls" not in before or "model_calls" not in before:
        raise _Missing()
    _current_case.get().audit_before = before
    original_identity = _identity(session.provider)
    observations.update(ports_valid=True, identity_valid=True)
    if case_id == "P01":
        response = await session.provider.complete(
            [{"role": "user", "content": "contract request"}], []
        )
        from .model_evidence import _close_lazy, snapshot_model_response

        if not isinstance(response, ModelResponse):
            _close_lazy(response)
            raise _Violation()
        received = snapshot_model_response(response)
        _active()
        _check(not received.get("invalid_fields"))
        _check(_identity(session.provider) == original_identity)
        _check(_delta(before, await _case_audit(session), "model_calls")["model_calls"] == 1)
        observations.update(identity_checks=2, method_checks=1)
        return
    if case_id == "P06":
        await _drift(session, workspace, observations, engines, runs)
        return
    if case_id == "P08":
        await _lifecycle(session, workspace, observations, engines, runs)
        return
    if case_id == "P10":
        await _recorded(session, workspace, observations, engines, runs)
        return
    if case_id == "P16":
        await _lost(session, workspace, observations, engines, runs)
        return
    if int(case_id[1:]) >= 11:
        await _tool_cases(case_id, session, workspace, observations, engines, runs)
        return
    engine = _engine(session, workspace, engines)
    if case_id == "P02":
        for output in (None, False, 0, "中文🙂", _generic()):
            for usage in (None, {"input_tokens": 4, "output_tokens": 2, "cost": 0.25}):
                await _completed(
                    session,
                    engine,
                    runs,
                    observations,
                    output=output,
                    usage=usage,
                    schema={"type": "null"} if output is None else None,
                )
    elif case_id == "P03":
        output, task = _generic(), _generic()
        await _configure(session, "output", {"output": output})
        handle, _, _ = _admit(engine, runs, task=task)
        result = await _drive(engine, handle.run_id)
        _check(result.state == "succeeded" and result.result == output)
        original = engine.store.run(handle.run_id)
        output["items"].append("supplier input alias mutation")
        task["items"].append("caller input alias mutation")
        _check(engine.store.run(handle.run_id) == original)
        raw = engine.store.run(handle.run_id)
        raw["actions"][0]["request"]["messages"].append({"role": "user", "content": "mutation"})
        raw["actions"][0]["received_response"]["output"]["items"].append("received alias mutation")
        result.result["items"].append("public result mutation")
        _check(engine.store.run(handle.run_id) == original)
        _check((await _drive(engine, handle.run_id)).result == _generic())
        observations.update(duplicate_checks=1)
    elif case_id == "P04":
        for kind in ("nan", "lazy", "deep"):
            await _configure(session, "invalid-output", {"invalid": kind})
            handle, _, _ = _admit(engine, runs)
            result = await _drive(engine, handle.run_id)
            _check(result.state == "failed" and result.error == {"code": "validation_error"})
            action = _model(engine.store.run(handle.run_id))[0]
            _check(
                action["status"] == "rejected" and action["attempts"][0]["status"] == "completed"
            )
            _check(action["received_response"]["invalid_fields"] == ["output"])
            _check(engine.store.budget(handle.run_id) == {"limit": 8, "held": 0, "spent": 1})
            _check(_reservation(engine, action["attempts"][0]["id"])["state"] == "settled")
        observations.update(rejection_checks=3, settlement_checks=3)
    elif case_id == "P05":
        _required(session, "inject_fault")
        for fault, code in (
            ("provider-error", "provider_error"),
            ("authorization-denied", "authorization_denied"),
        ):
            await _fault(session, fault)
            handle, _, _ = _admit(engine, runs)
            result = await _drive(engine, handle.run_id)
            _check(
                result.state
                == ("waiting_reconciliation" if fault == "provider-error" else "failed")
            )
            _check(result.error == {"code": code})
            action = _model(engine.store.run(handle.run_id))[0]
            _check(
                action["status"] == "outcome_unknown" and action.get("received_response") is None
            )
            _check(action["attempts"][0]["status"] == "unknown")
            _check(engine.store.budget(handle.run_id) == {"limit": 8, "held": 1, "spent": 0})
            _check(_reservation(engine, action["attempts"][0]["id"])["state"] == "unknown")
            await _fault(session, "reset")
        observations.update(rejection_checks=2, reservation_checks=2)
    elif case_id == "P07":
        _required(session, "inject_fault")
        handle, _, _ = _admit(engine, runs)
        before_swap = await _case_audit(session)
        await _fault(session, "backend-swap")
        _check(_identity(session.provider) == original_identity)
        result = await _drive(engine, handle.run_id)
        _check(result.state == "failed" and result.error == {"code": "definition_mismatch"})
        _check(not any(a.get("response") for a in result.actions))
        _check(
            _delta(before_swap, await _case_audit(session), "backend_switches")["backend_switches"]
            == 1
        )
        observations["rejection_checks"] = 1
    else:
        await _completed(session, engine, runs, observations)


def _authority_observations(runs, observations):
    unique = {(id(engine), run_id): (engine, run_id) for engine, run_id in runs}
    records = [engine.store.run(run_id) for engine, run_id in unique.values()]
    models = [action for record in records for action in _model(record)]
    observations.update(
        consumer_runs=len(records),
        received_count=sum(action.get("received_response") is not None for action in models),
        adopted_count=sum(action["status"] == "completed" for action in models),
        tool_calls=sum(
            len(action["attempts"])
            for record in records
            for action in record["actions"]
            if action["kind"] == "tool"
        ),
    )


async def run_model_case(case_id, fixture, workspace):
    """Run one frozen case and retain original operations through cleanup retry."""
    if type(case_id) is not str or case_id not in _CATALOG.case_ids:
        raise ValidationError("Unknown ModelProvider contract case")
    workspace = Path(workspace)
    observations, engines, runs, suspended = {}, [], [], []
    owner = session = task = None
    adapter_identity = cleanup_pending = None
    status, code, cancelled = "failed", "fixture_prepare_failed", False
    cancellation = asyncio.Event()
    control = _CaseControl(cancellation, [])
    try:
        prepare = getattr(fixture, "prepare", None)
        _check(callable(prepare))
        preparation = asyncio.create_task(_invoke(prepare, case_id, workspace))
        try:
            session = await asyncio.shield(preparation)
        except asyncio.CancelledError:
            cancelled = True
            cancellation.set()
            await _finish(preparation)
            session = preparation.result()
        if type(session) is not ModelContractSession:
            _dispose(session)
            code = "invalid_fixture_session"
            raise _Violation()
        owner = BuildContext(
            None,
            workspace / "unused.sqlite",
            Scope("model-contract", "owner"),
            workspace,
            allow_async=True,
        )
        for entry in session.resources:
            (owner.own_async if entry.asynchronous else owner.own)(entry.resource)
        adapter_identity = digest(_identity(session.provider))
        code = "contract_violation"
        if not cancelled:

            async def original_case():
                token = _current_case.set(control)
                try:
                    await _case(case_id, session, workspace, observations, engines, runs)
                finally:
                    _current_case.reset(token)

            task = asyncio.create_task(original_case())
            await asyncio.shield(task)
            status, code = "passed", "verified"
    except _Missing:
        status, code = "not_verified", "missing_fixture_capability"
    except _PausedCallPending as pending:
        suspended.append(pending)
        status, code = "failed", "cleanup_failed"
    except asyncio.CancelledError:
        cancelled = True
        cancellation.set()
        for engine, run_id in runs:
            if engine in engines:
                engine.cancel(run_id, command_id="contract-observer-cancel")
        if task is not None:
            await _finish(task)
            if not task.cancelled():
                error = task.exception()
                if isinstance(error, _PausedCallPending):
                    suspended.append(error)
    except Exception:
        status = "failed"
    finally:
        if owner is not None:

            async def original_cleanup():
                while suspended:
                    await suspended[-1].cleanup()
                    suspended.pop()
                while control.resets:
                    await _manage(control.resets[-1].inject_fault, "reset")
                    control.resets.pop()
                if engines:
                    _authority_observations(runs, observations)
                while engines:
                    await engines[-1].wait_for_threads()
                    engines[-1].close()
                    engines.pop()
                    observations["runtime_closed"] = True
                await owner.cleanup_async()

            cleanup = asyncio.create_task(original_cleanup())
            try:
                cancelled |= await _finish(cleanup)
                cleanup.result()
                observations["cleanup_complete"] = True
            except (Exception, asyncio.CancelledError):
                status, code = "failed", "cleanup_failed"
                observations["cleanup_complete"] = False
                cleanup_pending = original_cleanup
        if type(session) is ModelContractSession and session.audit is not None:
            try:
                auditing = asyncio.create_task(_audit(session))
                cancelled |= await _finish(auditing)
                audited = auditing.result()
                before = control.audit_before
                if before is not None:
                    for key in (
                        "model_calls",
                        "request_count",
                        "response_count",
                        "close_calls",
                        "backend_switches",
                        "reopen_calls",
                    ):
                        if key in before and key in audited:
                            observations[key] = _delta(before, audited, key)[key]
                    if not session.resources:
                        if "close_calls" in before and "close_calls" in audited:
                            observations["borrowed_closed"] = (
                                audited["close_calls"] > before["close_calls"]
                            )
                            if observations["borrowed_closed"] and cleanup_pending is None:
                                status, code = "failed", "contract_violation"
                        elif status == "passed" and cleanup_pending is None:
                            status, code = "not_verified", "case_not_verified"
            except (Exception, asyncio.CancelledError):
                if cleanup_pending is None:
                    status, code = "failed", "contract_violation"
    result = AdapterContractCaseResult(
        case_id,
        status,
        code,
        observations,
        adapter_digest=adapter_identity,
        configuration_digest=digest({"contract": "model-provider", "version": "1"}),
        execution_authority="local" if observations.get("consumer_runs") else "none",
    )
    if cleanup_pending is not None:
        raise AdapterContractCleanupPending(result, cleanup_pending)
    if cancelled:
        raise asyncio.CancelledError()
    return result
