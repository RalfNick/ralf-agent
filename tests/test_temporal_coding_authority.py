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


def test_resource_projection_uses_one_verified_response_and_reads_again_on_next_call():
    from ralf_agent.temporal_coding_authority import TemporalCodingAuthority

    async def run():
        envelope, request = setup()
        events, responses = [], []

        async def validate():
            events.append("validate")

        async def query(name, payload):
            events.append("query")
            number = len(responses) + 1
            value = {
                "request": request["coding_request"],
                "runner": {"kind": "runner"},
                "state": {"grants": {"prepare": {"claim": number}}, "prepared": {"slot": number}},
                "cancelled": False,
            }
            responses.append(value)
            return value

        async def update(name, payload):
            raise AssertionError("Resource observation cannot update History")

        authority = TemporalCodingAuthority(
            request=request, invocation_id="claim", query=query, update=update, validate=validate
        )
        first = await authority.resource_state(envelope, {"kind": "runner"})
        assert first == {
            "prepare_grant": {"claim": 1},
            "prepared": {"slot": 1},
            "binding": None,
            "thread": None,
            "turn": None,
        }
        first["prepared"]["slot"] = "changed-result"
        assert responses[0]["state"]["prepared"] == {"slot": 1}
        second = await authority.resource_state(envelope, {"kind": "runner"})
        assert second["prepare_grant"] == {"claim": 2}
        assert second["prepared"] == {"slot": 2}
        assert events == ["validate", "query", "validate"] * 2

    asyncio.run(run())


@pytest.mark.parametrize("dispatch", ["changed", "missing"])
def test_resource_projection_refuses_foreign_dispatch_before_any_callback(dispatch):
    from ralf_agent.temporal_coding_authority import TemporalCodingAuthority

    async def run():
        envelope, request = setup()

        async def never(*args):
            raise AssertionError("Foreign dispatch reached an SDK callback")

        authority = TemporalCodingAuthority(
            request=request, invocation_id="claim", query=never, update=never, validate=never
        )
        foreign = (
            DispatchEnvelope(
                envelope.context,
                envelope.tool_manifest,
                {"task": "foreign"},
                envelope.operation_digest,
            )
            if dispatch == "changed"
            else None
        )
        with pytest.raises(DefinitionMismatch):
            await authority.resource_state(foreign, {"kind": "runner"})

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["runner", "response", "callback"])
def test_resource_projection_refuses_mismatched_response_or_changed_callback(fault):
    from ralf_agent.temporal_coding_authority import TemporalCodingAuthority

    async def run():
        envelope, request = setup()
        events = []

        async def validate():
            events.append("validate")

        async def update(*args):
            raise AssertionError("Foreign callback executed")

        async def query(name, payload):
            events.append("query")
            if fault == "callback":
                authority._validate = update
            return {
                "request": request["coding_request"],
                "runner": {"kind": "foreign" if fault == "runner" else "runner"},
                "state": None if fault == "response" else {"grants": {}},
                "cancelled": False,
            }

        authority = TemporalCodingAuthority(
            request=request, invocation_id="claim", query=query, update=update, validate=validate
        )
        with pytest.raises(DefinitionMismatch):
            await authority.resource_state(envelope, {"kind": "runner"})
        assert events.count("query") == 1

    asyncio.run(run())


@pytest.mark.parametrize("arguments", [(None,), (None, None, None)])
def test_private_state_refuses_incomplete_dispatch_pair_before_callbacks(arguments):
    from ralf_agent.temporal_coding_authority import TemporalCodingAuthority

    async def run():
        _, request = setup()

        async def never(*args):
            raise AssertionError("Incomplete dispatch pair reached an SDK callback")

        authority = TemporalCodingAuthority(
            request=request, invocation_id="claim", query=never, update=never, validate=never
        )
        with pytest.raises(DefinitionMismatch):
            await authority._state(*arguments)

    asyncio.run(run())
