"""CONTROL diagnostics preserve responses without exposing exception or request bodies."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from temporalio import activity

from relf_agent import temporal_control_activities as control
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.temporal_parent_state import CONTROL_ACTIVITY

SECRET = "sensitive-request-and-exception-body"


def callback(monkeypatch, operation):
    runtime = SimpleNamespace(parent_completion_policies={}, orchestration_release={})
    client = object()
    info = SimpleNamespace(
        workflow_id="original-parent",
        workflow_run_id="original-epoch",
        workflow_namespace="original-namespace",
        activity_id="original-control",
        activity_type=CONTROL_ACTIVITY,
        attempt=1,
    )
    monkeypatch.setattr(activity, "info", lambda: info)

    async def invoke(actual_runtime, actual_client, value, actual_info):
        assert actual_runtime is runtime and actual_client is client and actual_info is info
        return await operation(value)

    monkeypatch.setattr(control, "control", invoke)
    return next(
        f
        for f in control.registered_parent_activities(runtime, client)
        if activity._Definition.from_callable(f).name == CONTROL_ACTIVITY
    )


def diagnostics(caplog):
    return [r for r in caplog.records if hasattr(r, "child_control_failure")]


def test_registered_control_failure_keeps_original_reply_and_adds_safe_diagnostic(
    monkeypatch, caplog
):
    async def fail(value):
        raise RuntimeError(SECRET)

    fn = callback(monkeypatch, fail)
    caplog.set_level(logging.WARNING)
    result = asyncio.run(fn({"mode": "register", "input": SECRET, "scope": {"workspace": SECRET}}))
    assert result == {"ok": False, "code": "child_control_failed"}
    records = diagnostics(caplog)
    assert len(records) == 1, "Original CONTROL failure is missing its bounded safe diagnostic"
    record = records[0]
    detail = record.child_control_failure
    assert detail["mode"] == "register"
    assert detail["exception_module"] == "builtins" and detail["exception_type"] == "RuntimeError"
    assert 1 <= len(detail["frames"]) <= 16
    assert any(f["function"] == "fail" for f in detail["frames"])
    assert all("/" not in f["file"] and "\\" not in f["file"] for f in detail["frames"])
    assert SECRET not in record.getMessage() and SECRET not in repr(detail)
    assert record.exc_info is None and record.stack_info is None


@pytest.mark.parametrize("mode", ["observe", "cancel", "recover", SECRET, {"private": SECRET}])
def test_only_fixed_operation_names_enter_diagnostics(monkeypatch, caplog, mode):
    async def fail(value):
        raise RuntimeError(SECRET)

    caplog.set_level(logging.WARNING)
    assert asyncio.run(callback(monkeypatch, fail)({"mode": mode, "input": SECRET})) == {
        "ok": False,
        "code": "child_control_failed",
    }
    record = diagnostics(caplog)[0]
    assert record.child_control_failure["mode"] == (
        mode if type(mode) is str and mode in {"observe", "cancel", "recover"} else "unknown"
    )
    assert SECRET not in record.getMessage()


@pytest.mark.parametrize("kind", [ValidationError, DefinitionMismatch])
def test_known_ralf_failure_preserves_its_original_code_without_new_log(monkeypatch, caplog, kind):
    async def fail(value):
        raise kind(SECRET)

    caplog.set_level(logging.WARNING)
    assert asyncio.run(callback(monkeypatch, fail)({"mode": "register"})) == {
        "ok": False,
        "code": kind.code,
    }
    assert diagnostics(caplog) == []


@pytest.mark.parametrize("code", ["definition_mismatch", SECRET])
def test_real_rpc_wrapper_records_enum_and_only_whitelisted_application_code(
    monkeypatch, caplog, code
):
    from temporalio.exceptions import ApplicationError
    from temporalio.service import RPCError, RPCStatusCode

    async def fail(value):
        try:
            raise ApplicationError(SECRET, {"private-details": SECRET}, type=code)
        except ApplicationError as cause:
            raise RPCError(SECRET, RPCStatusCode.UNAVAILABLE, SECRET.encode()) from cause

    caplog.set_level(logging.WARNING)
    assert asyncio.run(callback(monkeypatch, fail)({"mode": "register", "input": SECRET})) == {
        "ok": False,
        "code": "child_control_failed",
    }
    record = diagnostics(caplog)[0]
    detail = record.child_control_failure
    assert detail["rpc_status"] == "UNAVAILABLE"
    assert 1 <= len(detail["causes"]) <= 4
    assert detail["causes"][0]["code"] == (code if code == "definition_mismatch" else "unknown")
    assert SECRET not in record.getMessage() and SECRET not in repr(detail)
    assert record.exc_info is None


@pytest.mark.parametrize("fault", ["status", "cause", "untrusted-cause"])
def test_hostile_exception_metadata_cannot_replace_the_original_reply(monkeypatch, caplog, fault):
    class Hostile(RuntimeError):
        @property
        def status(self):
            if fault == "status":
                raise BaseException(SECRET)
            return {"private-status": SECRET}

        @property
        def cause(self):
            if fault == "cause":
                raise BaseException(SECRET)
            return {"private-cause": SECRET}

    async def fail(value):
        raise Hostile(SECRET)

    caplog.set_level(logging.WARNING)
    assert asyncio.run(callback(monkeypatch, fail)({"mode": "observe"})) == {
        "ok": False,
        "code": "child_control_failed",
    }
    assert all(SECRET not in r.getMessage() for r in caplog.records)


def test_deep_trace_and_cyclic_causes_remain_bounded(monkeypatch, caplog):
    failure = RuntimeError(SECRET)
    failure.__cause__ = failure

    def descend(depth):
        if depth:
            return descend(depth - 1)
        raise failure

    async def fail(value):
        descend(24)

    caplog.set_level(logging.WARNING)
    assert asyncio.run(callback(monkeypatch, fail)({"mode": "recover"})) == {
        "ok": False,
        "code": "child_control_failed",
    }
    record = diagnostics(caplog)[0]
    detail = record.child_control_failure
    assert 1 <= len(detail["frames"]) <= 16 and len(detail["causes"]) <= 4
    assert all(
        len(f["file"]) <= 128
        and len(f["function"]) <= 128
        and type(f["line"]) is int
        and "/" not in f["file"]
        and "\\" not in f["file"]
        for f in detail["frames"]
    )
    assert SECRET not in record.getMessage()


@pytest.mark.parametrize(
    "logger_failure", [RuntimeError("broken diagnostic"), asyncio.CancelledError()]
)
def test_logging_failure_does_not_change_the_business_failure_reply(monkeypatch, logger_failure):
    async def fail(value):
        raise RuntimeError(SECRET)

    calls = []

    def broken(*args, **kwargs):
        calls.append(True)
        raise logger_failure

    monkeypatch.setattr(logging.getLogger(control.__name__), "warning", broken)
    assert asyncio.run(callback(monkeypatch, fail)({"mode": "cancel"})) == {
        "ok": False,
        "code": "child_control_failed",
    }
    assert calls == [True]


def test_success_is_unchanged_and_emits_no_failure_log(monkeypatch, caplog):
    result = {"state": "running"}

    async def succeed(value):
        return result

    caplog.set_level(logging.WARNING)
    reply = asyncio.run(callback(monkeypatch, succeed)({"mode": "observe"}))
    assert reply == {"ok": True, "result": result} and reply["result"] is result
    assert diagnostics(caplog) == []


def test_original_cancellation_propagates_the_same_exception_without_diagnostics(
    monkeypatch, caplog
):
    error = asyncio.CancelledError(SECRET)

    async def cancel(value):
        raise error

    caplog.set_level(logging.WARNING)
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(callback(monkeypatch, cancel)({"mode": "register"}))
    assert caught.value is error and diagnostics(caplog) == []
