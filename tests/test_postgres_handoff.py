"""Shared receipt contracts; SQL behavior is validated against real PostgreSQL."""

import asyncio
import importlib
import importlib.util
import uuid
from contextlib import asynccontextmanager

import pytest

from ralf_agent.errors import IdempotencyConflict, ValidationError
from ralf_agent.handoff import HandoffError, validate_inbox, validate_outbox
from ralf_agent.messaging import InMemoryMessageBus, MessageEnvelope
from ralf_agent.types import Scope

from .test_postgres_adapter import BoundaryConnection
from .test_postgres_adapter import postgres_dsn as _postgres_dsn

postgres_dsn = _postgres_dsn


def adapter(name):
    assert importlib.util.find_spec("ralf_agent.postgres_handoff"), "Missing shared handoff adapter"
    return getattr(importlib.import_module("ralf_agent.postgres_handoff"), name)


@pytest.mark.parametrize("name", ["PostgresInbox", "PostgresOutbox"])
def test_borrowed_and_owned_lifetime_and_safe_failure(name):
    async def run():
        connection = BoundaryConnection()
        borrowed = adapter(name)(connection, backend_id="borrowed")
        with pytest.raises(HandoffError) as exc:
            await borrowed.initialize()
        assert "secret" not in str(exc.value) and "SELECT" not in str(exc.value)
        await borrowed.aclose()
        assert not connection.closed
        owned = adapter(name)(connection, backend_id="owned", owns_connection=True)
        await owned.aclose()
        assert connection.closed

    asyncio.run(run())


@pytest.mark.parametrize("value", [False, 0, -1, 1000001, "1"])
def test_invalid_capacity_fails_before_io(value):
    with pytest.raises(ValidationError):
        adapter("PostgresInbox")(BoundaryConnection(), backend_id="test", max_entries=value)


def test_owned_close_reentry_fails_and_retains_safe_retry():
    class Connection(BoundaryConnection):
        first = True
        store = None

        async def close(self):
            if self.first:
                self.first = False
                await self.store.aclose()
            self.closed = True

    async def run():
        connection = Connection()
        connection.store = adapter("PostgresInbox")(
            connection, backend_id="reentry", owns_connection=True
        )
        with pytest.raises(HandoffError):
            await asyncio.wait_for(connection.store.aclose(), 0.2)
        assert not connection.closed
        await connection.store.aclose()
        assert connection.closed

    asyncio.run(run())


@asynccontextmanager
async def pair(dsn, name="PostgresInbox", max_entries=10000):
    first = await adapter(name).connect(dsn, backend_id="shared", max_entries=max_entries)
    second = await adapter(name).connect(dsn, backend_id="shared", max_entries=max_entries)
    scope = Scope("pg-handoff-" + uuid.uuid4().hex, "owner")
    try:
        await asyncio.gather(first.initialize(), second.initialize())
        yield first, second, scope
    finally:
        if not first.connection.closed:
            await first.connection.execute(
                f"DELETE FROM {first.table} WHERE workspace=%s", (scope.workspace,)
            )
        await first.aclose()
        await second.aclose()


def test_real_postgres_inbox_cross_connection_identity_completion_and_scope(postgres_dsn):
    async def run():
        async with pair(postgres_dsn) as (first, second, scope):
            validate_inbox(first)
            message = MessageEnvelope("id';--", "topic", {"input": "任务"})
            assert await first.accept(scope, message) is None
            assert await second.accept(scope, message) is None
            assert (await second.pending(scope))[0].to_dict() == message.to_dict()
            result = {"run_id": "original"}
            await first.complete(scope, message, result)
            await second.complete(scope, message, result)
            result["run_id"] = "changed-local"
            assert await second.result(scope, message.message_id) == {"run_id": "original"}
            assert await first.pending(scope) == []
            assert await second.accept(scope, message) == {"run_id": "original"}
            assert await second.result(Scope(scope.workspace, "other"), message.message_id) is None
            with pytest.raises(IdempotencyConflict):
                await second.accept(
                    scope, MessageEnvelope(message.message_id, "changed", message.payload)
                )
            with pytest.raises(IdempotencyConflict):
                await second.complete(scope, message, {"run_id": "replacement"})

    asyncio.run(run())


def test_real_postgres_capacity_is_atomic_across_connections_and_allows_replay(postgres_dsn):
    async def run():
        async with pair(postgres_dsn, max_entries=1) as (first, second, scope):
            messages = [MessageEnvelope(str(i), "topic", {}) for i in range(2)]
            outcomes = await asyncio.gather(
                first.accept(scope, messages[0]),
                second.accept(scope, messages[1]),
                return_exceptions=True,
            )
            assert sum(isinstance(result, HandoffError) for result in outcomes) == 1
            original = (await first.pending(scope))[0]
            await second.complete(scope, original, {"done": True})
            assert await first.accept(scope, original) == {"done": True}
            with pytest.raises(HandoffError, match="capacity"):
                await second.accept(scope, MessageEnvelope("new", "topic", {}))

    asyncio.run(run())


def test_real_postgres_outbox_replays_after_publication_before_receipt(postgres_dsn):
    async def run():
        async with pair(postgres_dsn, name="PostgresOutbox") as (first, second, scope):
            validate_outbox(first)
            bus = InMemoryMessageBus()
            try:
                await bus.ensure_group(scope, "topic", "group")
                message = MessageEnvelope("message", "topic", {"value": 1})
                assert await first.enqueue(scope, message) == message.message_id
                # Actual broker publication completed; process-local receipt is absent.
                original = await bus.publish(scope, message)
                assert await second.flush(bus, scope) == 1
                assert await first.result(scope, message.message_id) == {"broker_id": original}
                assert len(await bus.receive(scope, "topic", "group", "worker", limit=10)) == 1
                assert await first.flush(bus, scope) == 0
            finally:
                await bus.aclose()

    asyncio.run(run())
