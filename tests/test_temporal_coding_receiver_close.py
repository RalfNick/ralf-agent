"""Borrowed receiver stays alive while the caller retries incomplete close."""

import asyncio
from types import SimpleNamespace

import pytest

from ralf_agent.errors import CloseIncomplete
from tests import test_temporal_deployment_coding_service as fixture


@pytest.mark.parametrize("body_failure", [False, True])
def test_borrowed_receiver_retries_pending_close_inside_original_budget(
    tmp_path, monkeypatch, body_failure
):
    events = []
    waits = []

    class RequestFailed(Exception):
        pass

    class Worker:
        async def __aenter__(self):
            events.append("worker-start")
            return self

        async def __aexit__(self, *args):
            events.append("worker-stop")

    class Admin:
        async def execute(self, *args):
            return self

        async def fetchone(self):
            return (None,)

    class Assembly:
        async def aclose(self, *, wait_timeout):
            assert events[0] == "worker-start" and "worker-stop" not in events
            waits.append(wait_timeout)
            events.append("close")
            if len(waits) == 1:
                raise CloseIncomplete({"owned": "ack pending"})

    system = object.__new__(fixture.CodingSystem)
    system.directory = tmp_path
    system.client = SimpleNamespace()
    system.queue = "owned-original"
    system.runtime = SimpleNamespace()
    system.release = {}
    system.workers = []
    system.admin = Admin()
    system.schema = "original"
    system.assembly = Assembly()
    monkeypatch.setattr(fixture, "build_temporal_worker", lambda *args, **kwargs: Worker())

    async def run():
        async with system.worker():
            if body_failure:
                raise RequestFailed("original body error")

    if body_failure:
        with pytest.raises(RequestFailed):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert events == ["worker-start", "close", "close", "worker-stop"]
    assert len(waits) == 2 and 0 <= waits[1] <= waits[0] <= 60


def test_receiver_retry_keeps_one_total_deadline(tmp_path):
    events = []

    class Assembly:
        async def aclose(self, *, wait_timeout):
            events.append(wait_timeout)
            if len(events) == 1:
                raise CloseIncomplete({"owned": "pending"})
            await asyncio.sleep(10)

    async def run():
        start = asyncio.get_running_loop().time()
        with pytest.raises(TimeoutError):
            await fixture._close_while_serving(Assembly(), tmp_path, wait_timeout=0.08)
        assert asyncio.get_running_loop().time() - start < 0.5

    asyncio.run(run())
    assert len(events) == 2 and 0 < events[1] < events[0] <= 0.08


def test_receiver_retry_does_not_swallow_transport_or_identity_failure(tmp_path):
    class ForeignFailure(Exception):
        pass

    attempts = []

    class Assembly:
        async def aclose(self, *, wait_timeout):
            attempts.append(wait_timeout)
            raise ForeignFailure()

    async def run():
        with pytest.raises(ForeignFailure):
            await fixture._close_while_serving(Assembly(), tmp_path, wait_timeout=1)

    asyncio.run(run())
    assert len(attempts) == 1
