"""Replaceable actual Tool ownership stays independent of the observing Task."""

import asyncio
import threading

import pytest

import relf_agent as r
from relf_agent.errors import CloseIncomplete, RalfError
from relf_agent.tools import current_thread_tracker
from relf_agent.types import digest


def api():
    owner = getattr(r, "ToolExecutionOwner", None)
    assert owner is not None and getattr(r, "ToolExecutionPort", None) is not None
    return owner


def proof(action="tool"):
    return {
        "scope": {"workspace": "local", "principal": "local-user"},
        "action_id": action,
        "release_digest": digest({"release": 1}),
        "request_digest": digest({"request": 1}),
        "execution_epoch": "original-epoch",
    }


def test_public_tool_owner_completed_operation_and_end_ack():
    cls = api()

    async def run():
        owner = cls(version="app-1")
        ends = []

        async def operation():
            return "completed"

        async def ended(value):
            ends.append(value)

        assert await owner.execute(operation, proof=proof(), on_end=ended) == "completed"
        assert await owner.wait(wait_timeout=2) is True
        assert ends == [proof()]
        identity = owner.identity
        assert identity["kind"] == "tool-execution-owner" and identity["max_calls"] == 8
        identity["max_calls"] = 1
        assert owner.identity["max_calls"] == 8
        await owner.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("value", [True, 0, -1, 257, "8", None])
def test_invalid_tool_capacity_refuses(value):
    cls = api()
    with pytest.raises(RalfError):
        cls(version="1", max_calls=value)


@pytest.mark.parametrize("value", [None, True, "", "\u3000", "x" * 257])
def test_invalid_behavior_version_refuses(value):
    cls = api()
    with pytest.raises(RalfError):
        cls(version=value)


def test_observer_cancel_keeps_actual_thread_and_end_notification_owned():
    cls = api()
    started, release, stopped = threading.Event(), threading.Event(), threading.Event()

    def handler():
        started.set()
        try:
            assert release.wait(5)
            return "actual result"
        finally:
            stopped.set()

    async def run():
        owner, ends = cls(version="1", max_calls=1), []

        async def operation():
            return await current_thread_tracker.get().run(handler, group="tool")

        async def ended(value):
            assert stopped.is_set()
            ends.append(value)

        observer = asyncio.create_task(owner.execute(operation, proof=proof(), on_end=ended))
        assert await asyncio.to_thread(started.wait, 2)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        try:
            assert not stopped.is_set() and ends == []
            assert await owner.wait(wait_timeout=0) is False
            with pytest.raises(CloseIncomplete):
                await owner.aclose(wait_timeout=0)
            with pytest.raises(RalfError):
                await owner.execute(operation, proof=proof("second"), on_end=ended)
        finally:
            release.set()
        await owner.aclose(wait_timeout=2)
        assert ends == [proof()] and stopped.is_set()

    asyncio.run(run())


def test_failed_end_ack_keeps_capacity_and_retries_original_proof():
    cls = api()

    async def run():
        owner, available, received = cls(version="1", max_calls=1), False, []

        async def operation():
            return "done"

        async def ended(value):
            received.append(value)
            if not available:
                raise ConnectionError("original acknowledgement unavailable")

        assert await owner.execute(operation, proof=proof(), on_end=ended) == "done"
        await asyncio.sleep(0.01)
        with pytest.raises(CloseIncomplete):
            await owner.aclose(wait_timeout=0)
        with pytest.raises(RalfError):
            await owner.execute(operation, proof=proof("other"), on_end=ended)
        available = True
        await owner.aclose(wait_timeout=2)
        assert received and all(value == proof() for value in received)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["scope", "action", "digest", "epoch"])
def test_invalid_proof_cannot_start_tool(kind):
    cls = api()
    value, started = proof(), []
    value[
        {
            "scope": "scope",
            "action": "action_id",
            "digest": "request_digest",
            "epoch": "execution_epoch",
        }[kind]
    ] = None

    async def run():
        owner = cls(version="1")

        async def operation():
            started.append(True)

        with pytest.raises(RalfError):
            await owner.execute(operation, proof=value)
        await owner.aclose()

    asyncio.run(run())
    assert started == []
