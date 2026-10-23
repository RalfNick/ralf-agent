import json
from dataclasses import FrozenInstanceError, asdict

import pytest

from relf_agent import InMemoryAuditSink, Scope, ServiceAudit
from relf_agent.errors import ValidationError


def test_fixed_redacted_schema_and_stable_keyed_references():
    sink = InMemoryAuditSink()
    key = b"a" * 32
    first, restarted = ServiceAudit(sink, key=key), ServiceAudit(sink, key=key)
    values = dict(
        scope=Scope("workspace-secret", "principal-secret"),
        method="message/send",
        outcome="rpc_ok",
        request_id="request-secret",
        task_id="task-secret",
        message_id="message-secret",
        command_id="command-secret",
    )
    first.record(**values)
    restarted.record(**values)
    changed = ServiceAudit(sink, key=b"b" * 32)
    changed.record(**values)
    a, b, c = map(asdict, sink.records)
    assert set(a) == {
        "version",
        "event_id",
        "timestamp",
        "operation",
        "outcome",
        "scope_ref",
        "request_ref",
        "task_ref",
        "message_ref",
        "command_ref",
    }
    assert a["version"] == 1 and a["timestamp"] > 0
    assert a["event_id"] != b["event_id"]
    for field in ("scope_ref", "request_ref", "task_ref", "message_ref", "command_ref"):
        assert len(a[field]) == 64 and a[field] == b[field] != c[field]
    assert a["task_ref"] != a["message_ref"]
    assert "secret" not in json.dumps(a)
    with pytest.raises(FrozenInstanceError):
        sink.records[0].outcome = "secret"


def test_default_buffer_is_bounded_and_drops_only_observations():
    sink = InMemoryAuditSink(max_records=2)
    audit = ServiceAudit(sink)
    for request_id in range(3):
        audit.record(scope=None, method="tasks/get", outcome="unauthorized", request_id=request_id)
    assert len(sink.records) == 2 and sink.dropped == 1
    assert sink.records[0].scope_ref is None
    assert ServiceAudit().sink.records == ()
    assert audit.failures == 0


@pytest.mark.parametrize("size", [True, 0, -1, 100001, 1.5])
def test_invalid_buffer_capacity(size):
    with pytest.raises(ValidationError):
        InMemoryAuditSink(max_records=size)


@pytest.mark.parametrize("key", ["secret", b"short", bytearray(32)])
def test_invalid_key_rejected(key):
    with pytest.raises(ValidationError):
        ServiceAudit(key=key)


def test_sink_failure_and_lazy_result_count_without_details_or_retry():
    class Sink:
        calls = 0

        def emit(self, record):
            self.calls += 1
            raise RuntimeError("private-secret")

    sink = Sink()
    audit = ServiceAudit(sink)
    audit.record(scope=None, method="secret-method", outcome="unauthorized")
    assert audit.failures == 1 and sink.calls == 1

    async def lazy():
        raise RuntimeError("never-executed")

    sink.emit = lambda record: lazy()
    audit.record(scope=None, method="tasks/get", outcome="rpc_ok")
    assert audit.failures == 2


def test_async_sink_rejected_without_calling_it():
    class Sink:
        async def emit(self, record):
            raise AssertionError("not called")

    with pytest.raises(ValidationError):
        ServiceAudit(Sink())


def test_sync_sink_cannot_cancel_accepted_business():
    import asyncio

    class Sink:
        def emit(self, record):
            raise asyncio.CancelledError("private-secret")

    audit = ServiceAudit(Sink())
    audit.record(scope=None, method="message/send", outcome="rpc_ok")
    assert audit.failures == 1


def test_unknown_operation_redaction_and_invalid_internal_outcome():
    audit = ServiceAudit()
    audit.record(scope=None, method="private-secret", outcome="invalid_request")
    assert audit.sink.records[0].operation == "unsupported"
    with pytest.raises(ValidationError):
        audit.record(scope=None, method="tasks/get", outcome="private-secret")
    assert len(audit.sink.records) == 1
