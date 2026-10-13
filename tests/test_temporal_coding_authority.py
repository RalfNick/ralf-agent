"""Fixed async History callbacks; observing cancellation does not grant work."""

import asyncio
from dataclasses import asdict

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.executors import DispatchEnvelope
from ralf_agent.types import InvocationContext, Scope, digest


def setup():
    envelope = DispatchEnvelope(
        InvocationContext(Scope(), "r", "a", "a:1", "e", "epoch"),
        {"name": "code"},
        {"task": "fix"},
        "op",
    )
    native = {
        "dispatch": asdict(envelope.context)
        | {
            "tool_manifest": envelope.tool_manifest,
            "arguments": envelope.arguments,
            "operation_digest": "op",
        }
    }
    native["request_digest"] = digest(native)
    request = asdict(envelope.context) | {"release_digest": "release", "coding_request": native}
    return envelope, request


def test_history_async_callbacks_are_fixed_and_native_request_is_detached():
    asyncio.run(_history_callbacks())


async def _history_callbacks():
    from ralf_agent.temporal_coding_authority import TemporalCodingAuthority

    envelope, request = setup()
    calls = []

    async def validate():
        calls.append("validate")

    async def query(name, payload):
        return {
            "request": request["coding_request"],
            "runner": {"kind": "runner"},
            "state": {"grants": {}},
            "cancelled": False,
        }

    async def update(name, payload):
        return {"action_id": "a", "recorded": True}

    authority = TemporalCodingAuthority(
        request=request, invocation_id="claim", query=query, update=update, validate=validate
    )
    received = await authority.check(envelope, {"kind": "runner"})
    received.clear()
    assert await authority.cancelled() is False
    await authority.adopt("error", {"code": "fixture"})
    assert len(calls) == 6
    authority._query = update
    with pytest.raises(DefinitionMismatch):
        await authority.cancelled()


def test_changed_dispatch_is_refused_before_history_read():
    asyncio.run(_changed_dispatch())


async def _changed_dispatch():
    from ralf_agent.temporal_coding_authority import TemporalCodingAuthority

    envelope, request = setup()

    async def never(*args):
        raise AssertionError("Foreign dispatch reached History")

    authority = TemporalCodingAuthority(
        request=request, invocation_id="claim", query=never, update=never, validate=never
    )
    envelope = DispatchEnvelope(
        envelope.context, envelope.tool_manifest, {"task": "foreign"}, envelope.operation_digest
    )
    with pytest.raises(DefinitionMismatch):
        await authority.check(envelope, {"kind": "runner"})
