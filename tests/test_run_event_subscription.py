import asyncio
import importlib
import json

import pytest

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    RunEvent,
    RunSnapshot,
    Scope,
    SQLiteRunReader,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError


def api(name):
    module = importlib.import_module("ralf_agent")
    assert hasattr(module, name), "Missing event subscription API: " + name
    return getattr(module, name)


def snapshot(run_id="r", state="running"):
    return RunSnapshot(run_id, state, 1, None, None, (), ())


class Reader:
    scope = Scope()

    def __init__(self, events=()):
        self.records, self.calls, self.state, self.closed = list(events), 0, "running", False

    def events(self, run_id, *, after=0, limit=1000):
        self.calls += 1
        return [e for e in self.records if e.seq > after][:limit]

    def status(self, run_id):
        return snapshot(run_id, self.state)

    def close(self):
        self.closed = True


class AsyncReader(Reader):
    async def events(self, run_id, *, after=0, limit=1000):
        return super().events(run_id, after=after, limit=limit)

    async def status(self, run_id):
        return super().status(run_id)


def test_cursor_roundtrip_and_sse_cannot_inject_event_lines():
    cursor = api("EventCursor")(Scope("w", "p"), "run\nx", 1)
    assert api("EventCursor").from_token(cursor.token) == cursor
    event = RunEvent("run\nx", 1, "kind\nevent: injected", {"text": "line\ndata: injected"})
    envelope = api("EventEnvelope")(Scope("w", "p"), event)
    envelope.event.data["text"] = "changed"
    assert envelope.event.data == event.data
    text = envelope.to_sse()
    assert text.count("\n\n") == 1 and len(text.splitlines()) == 4
    assert text.startswith("id: " + cursor.token + "\nevent: ralf.run\ndata: ")
    body = json.loads(text.splitlines()[2][6:])
    assert body["event"]["data"] == event.data


@pytest.mark.parametrize("token", ["!", "", "e30", "eyJhZnRlciI6dHJ1ZX0", "a" * 5000])
def test_invalid_cursor_token_is_a_typed_error(token):
    with pytest.raises(ValidationError):
        api("EventCursor").from_token(token)


@pytest.mark.parametrize("reader_type", [Reader, AsyncReader])
def test_snapshot_reader_pages_and_resume_cursor(reader_type):
    async def run():
        records = [RunEvent("r", i, "step", {"i": i}) for i in range(1, 6)]
        reader = reader_type(records)
        stream = api("RunEventSubscription")(reader, "r", page_size=2, follow=False)
        first = await anext(stream)
        assert first.event == records[0] and stream.cursor == first.cursor
        await stream.aclose()
        resumed = api("RunEventSubscription")(
            reader, "r", after=first.cursor, page_size=2, follow=False
        )
        rows = [e async for e in resumed]
        assert [e.event for e in rows] == records[1:] and resumed.cursor.after == 5
        assert reader.closed is False

    asyncio.run(run())


def test_reader_scope_and_binding_are_verified_before_buffered_delivery():
    async def run():
        reader = Reader([RunEvent("r", 1, "a", {}), RunEvent("r", 2, "b", {})])
        stream = api("RunEventSubscription")(reader, "r", follow=False)
        assert (await anext(stream)).event.seq == 1
        reader.scope = Scope("different", "principal")
        with pytest.raises(AuthorizationDenied):
            await anext(stream)
        assert stream.cursor.after == 1
        await stream.aclose()
        reader.scope = Scope()
        stream = api("RunEventSubscription")(reader, "r", follow=False)
        await anext(stream)
        reader.events = lambda *a, **kw: []
        with pytest.raises(DefinitionMismatch):
            await anext(stream)
        await stream.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("cursor", ["scope", "run"])
def test_foreign_cursor_is_rejected_before_reader_io(cursor):
    reader = Reader()
    old = api("EventCursor")(
        Scope("other", "p") if cursor == "scope" else Scope(),
        "other" if cursor == "run" else "r",
        1,
    )
    with pytest.raises(AuthorizationDenied):
        api("RunEventSubscription")(reader, "r", after=old)
    assert reader.calls == 0


@pytest.mark.parametrize(
    "invalid", ["gap", "duplicate", "wrong_run", "bool_seq", "raw", "too_many", "too_large"]
)
def test_bad_event_page_is_refused_atomically(invalid):
    class Broken(Reader):
        def events(self, run_id, *, after=0, limit=1000):
            values = [RunEvent("r", 1, "a", {})]
            if invalid == "gap":
                values = [RunEvent("r", 2, "a", {})]
            if invalid == "duplicate":
                values += values
            if invalid == "wrong_run":
                values = [RunEvent("wrong", 1, "a", {})]
            if invalid == "bool_seq":
                values = [RunEvent("r", True, "a", {})]
            if invalid == "raw":
                values = [{"run_id": "r"}]
            if invalid == "too_many":
                values = [RunEvent("r", i, "a", {}) for i in range(1, 5)]
            if invalid == "too_large":
                values = [RunEvent("r", 1, "a", {"x": "x" * 4_000_001})]
            return values

    async def run():
        stream = api("RunEventSubscription")(Broken(), "r", page_size=3, follow=False)
        with pytest.raises(ValidationError):
            await anext(stream)
        assert stream.cursor.after == 0
        await stream.aclose()

    asyncio.run(run())


def test_terminal_status_race_drains_the_last_committed_event():
    class Race(Reader):
        def events(self, run_id, *, after=0, limit=1000):
            self.calls += 1
            return [RunEvent("r", 1, "succeeded", {})] if self.calls > 1 and after == 0 else []

        def status(self, run_id):
            return snapshot(state="succeeded")

    async def run():
        stream = api("RunEventSubscription")(Race(), "r", poll_interval=0.01)
        assert [e.event.seq async for e in stream] == [1]

    asyncio.run(run())


def test_close_cancels_and_drains_private_async_read_without_closing_source():
    async def run():
        entered, exited = asyncio.Event(), asyncio.Event()

        class Slow(AsyncReader):
            async def events(self, *args, **kwargs):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    exited.set()

        source = Slow()
        stream = api("RunEventSubscription")(source, "r")
        pending = asyncio.create_task(anext(stream))
        await asyncio.wait_for(entered.wait(), 1)
        await stream.aclose()
        with pytest.raises(StopAsyncIteration):
            await pending
        assert exited.is_set() and source.closed is False

    asyncio.run(run())


def test_caller_cancellation_drains_read_and_single_consumer_is_enforced():
    async def run():
        entered, exited = asyncio.Event(), asyncio.Event()

        class Slow(AsyncReader):
            async def events(self, *args, **kwargs):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    exited.set()

        stream = api("RunEventSubscription")(Slow(), "r")
        pending = asyncio.create_task(anext(stream))
        await entered.wait()
        with pytest.raises(ValidationError):
            await anext(stream)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert exited.is_set()
        await stream.aclose()

    asyncio.run(run())


def test_closing_idle_follow_wakes_consumer():
    async def run():
        entered = asyncio.Event()

        class Ready(AsyncReader):
            async def events(self, *args, **kwargs):
                result = await super().events(*args, **kwargs)
                entered.set()
                return result

        stream = api("RunEventSubscription")(Ready(), "r", poll_interval=60)
        pending = asyncio.create_task(anext(stream))
        await entered.wait()
        await stream.aclose()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, 1)

    asyncio.run(run())


def test_read_timeout_is_explicit_and_leaves_no_pending_operation():
    async def run():
        ended = asyncio.Event()

        class Slow(AsyncReader):
            async def events(self, *args, **kwargs):
                try:
                    await asyncio.Event().wait()
                finally:
                    ended.set()

        stream = api("RunEventSubscription")(Slow(), "r", read_timeout=0.01)
        with pytest.raises(TimeoutError):
            await anext(stream)
        assert ended.is_set()
        await stream.aclose()

    asyncio.run(run())


def test_subscription_has_loop_affinity():
    stream = api("RunEventSubscription")(
        Reader([RunEvent("r", 1, "a", {}), RunEvent("r", 2, "b", {})]), "r", follow=False
    )
    assert asyncio.run(anext(stream)).event.seq == 1
    with pytest.raises(ValidationError):
        asyncio.run(anext(stream))
    asyncio.run(stream.aclose())


@pytest.mark.parametrize(
    "options",
    [
        {"after": True},
        {"page_size": 0},
        {"follow": 1},
        {"poll_interval": float("nan")},
        {"read_timeout": 0},
        {"max_events": False},
    ],
)
def test_invalid_subscription_options_fail_before_read(options):
    reader = Reader()
    with pytest.raises(ValidationError):
        api("RunEventSubscription")(reader, "r", **options)
    assert reader.calls == 0


def test_live_local_subscription_does_not_drive_or_cancel_business_run(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        class SlowProvider:
            identity = {"kind": "live-event-fixture"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                return ModelResponse("done")

        path = tmp_path / "events.sqlite"
        with LocalEngine(
            SQLiteStore(path), providers={"default": SlowProvider()}, tools=ToolRegistry()
        ) as engine:
            handle = engine.submit(AgentSpec("a", "answer"), "q", command_id="first")
            stream = api("RunEventSubscription")(
                SQLiteRunReader(path), handle.run_id, poll_interval=0.01
            )
            assert (await anext(stream)).event.seq == 1
            assert not started.is_set()
            drive = asyncio.create_task(engine.drive(handle.run_id))
            await started.wait()
            await stream.aclose()
            assert not drive.done() and engine.status(handle.run_id).state == "running"
            release.set()
            assert (await drive).state == "succeeded"
            remaining = api("RunEventSubscription")(
                SQLiteRunReader(path), handle.run_id, after=stream.cursor, page_size=1
            )
            actual = [row.event async for row in remaining]
            assert actual == engine.events(handle.run_id, after=stream.cursor.after)

    asyncio.run(run())


def test_cancelling_close_does_not_interrupt_reader_cleanup_and_retry_drains():
    async def run():
        entered, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))

        class Slow(AsyncReader):
            async def events(self, *args, **kwargs):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()
                    cleaned.set()

        stream = api("RunEventSubscription")(Slow(), "r")
        pending = asyncio.create_task(anext(stream))
        await entered.wait()
        closing = asyncio.create_task(stream.aclose())
        await cleaning.wait()
        closing.cancel()
        try:
            await closing
        except asyncio.CancelledError:
            pass
        release.set()
        await stream.aclose()
        with pytest.raises(StopAsyncIteration):
            await pending
        assert cleaned.is_set()

    asyncio.run(run())
