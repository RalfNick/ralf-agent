"""Observer diagnostics reveal static failure locations without changing its ACK."""

import asyncio
import logging

import pytest
from temporalio.service import RPCError, RPCStatusCode

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_session_deployment_control import owned_control_body
from ralf_agent.types import digest
from tests.test_temporal_session_deployment_control import validation

SECRET = "private-dsn-and-payload-marker"
LOGGER = "ralf_agent.temporal_session_deployment_control"


def failed_body(error):
    proof, client = validation()

    async def body():
        try:
            raise error
        finally:
            client.body_stopped = True

    result = asyncio.run(owned_control_body(proof, body))
    expected = {"ok": False, "code": getattr(error, "code", "session_control_failed")}
    assert {k: v for k, v in result.items() if k != "call_end"} == expected
    assert result["call_end"] == client.original_end_ack
    assert result["call_end"]["recorded"] is True
    assert result["call_end"]["body_result_digest"] == digest(expected)
    assert client.events.count("session_deployment_call_end") == 1
    assert len(client.calls) == 1
    return result


def test_unknown_rpc_failure_logs_static_type_status_and_frames_only(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    failed_body(RPCError(SECRET, RPCStatusCode.RESOURCE_EXHAUSTED, SECRET.encode()))
    records = [r for r in caplog.records if r.name == LOGGER]
    assert len(records) == 1
    record = records[0]
    detail = record.session_control_failure
    assert detail["exception_module"] == "temporalio.service"
    assert detail["exception_type"] == "RPCError"
    assert detail["rpc_status"] == "RESOURCE_EXHAUSTED"
    assert detail["frames"] and detail["frames"][-1]["function"] == "body"
    assert "RPCError" in record.getMessage() and "RESOURCE_EXHAUSTED" in record.getMessage()
    assert SECRET not in repr(record.__dict__)
    assert record.exc_info is None and record.stack_info is None
    assert record.args == ()


def test_diagnostics_bound_static_names_and_traceback_without_source_or_locals(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    error_type = type("Failure" + "x" * 160, (Exception,), {"__module__": "m" * 160})
    error = error_type(SECRET)
    namespace = {"error": error}
    code = compile(
        "def nested(depth):\n"
        "    private_local = error.args\n"
        "    if depth:\n"
        "        return nested(depth - 1)\n"
        "    raise error\n"
        "try:\n"
        "    nested(32)\n"
        "except Exception:\n"
        "    pass\n",
        "/" + SECRET + "/" + "f" * 160 + ".py",
        "exec",
    )
    exec(code, namespace)
    failed_body(error)
    record = next(r for r in caplog.records if r.name == LOGGER)
    detail = record.session_control_failure
    assert len(detail["exception_module"]) <= 128
    assert len(detail["exception_type"]) <= 128
    assert 1 <= len(detail["frames"]) <= 16
    for frame in detail["frames"]:
        assert set(frame) == {"file", "function", "line"}
        assert len(frame["file"]) <= 128 and "/" not in frame["file"]
        assert len(frame["function"]) <= 128
        assert type(frame["line"]) is int
    assert SECRET not in repr(record.__dict__)


@pytest.mark.parametrize("logger_error", [RuntimeError, asyncio.CancelledError])
def test_broken_logging_handler_cannot_change_original_response_or_end_ack(logger_error):
    class Broken(logging.Handler):
        def emit(self, record):
            raise logger_error(SECRET)

    logger = logging.getLogger(LOGGER)
    original_handlers, original_propagate, original_level = (
        logger.handlers[:],
        logger.propagate,
        logger.level,
    )
    logger.handlers, logger.propagate, logger.level = [Broken()], False, logging.WARNING
    try:
        failed_body(RuntimeError(SECRET))
    finally:
        logger.handlers, logger.propagate, logger.level = (
            original_handlers,
            original_propagate,
            original_level,
        )


def test_known_ralf_failure_keeps_original_code_without_generic_diagnostic(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    failed_body(DefinitionMismatch(SECRET))
    assert not [r for r in caplog.records if r.name == LOGGER]
