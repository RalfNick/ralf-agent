"""Shared async handoff receipts; PostgreSQL never owns execution state here."""

import asyncio
import json
from contextlib import asynccontextmanager

from .errors import IdempotencyConflict, MemoryBackendError, ValidationError
from .handoff import HandoffError, _completed
from .messaging import MessageEnvelope, _inputs, _integer, _json, _text
from .postgres import _connect, _PostgresAdapter


class _PostgresHandoff(_PostgresAdapter):
    table = ""

    def __init__(self, connection, *, backend_id, owns_connection=False, max_entries=10000):
        _integer(max_entries, "Handoff capacity", 1, 1000000)
        _text(backend_id, "Handoff backend identity")
        if self.table not in {"ralf_handoff_inbox_v1", "ralf_handoff_outbox_v1"}:
            raise ValidationError("Unsupported handoff table")
        super().__init__(connection, backend_id=backend_id, owns_connection=owns_connection)
        self._max_entries = max_entries
        self._table = self.table
        self._closing, self._close_task = False, None

    @classmethod
    async def connect(cls, dsn, *, backend_id=None, max_entries=10000):
        _integer(max_entries, "Handoff capacity", 1, 1000000)
        backend_id = cls.table if backend_id is None else backend_id
        _text(backend_id, "Handoff backend identity")
        try:
            connection = await _connect(dsn)
        except MemoryBackendError:
            raise HandoffError("PostgreSQL handoff connection failed") from None
        try:
            return cls(
                connection, backend_id=backend_id, owns_connection=True, max_entries=max_entries
            )
        except BaseException:
            await connection.close()
            raise

    @property
    def identity(self):
        return {
            "kind": "postgres-handoff",
            "version": "1",
            "table": self._table,
            "backend_id": self.backend_id,
            "max_entries": self._max_entries,
        }

    def _open(self):
        if self._closed or self._closing:
            raise HandoffError("PostgreSQL handoff store is closed or closing")

    @asynccontextmanager
    async def _guard(self, key=None):
        self._open()
        try:
            async with self._transaction(key):
                self._open()
                yield
        except MemoryBackendError:
            raise HandoffError("PostgreSQL handoff operation failed") from None

    async def initialize(self):
        async with self._guard(("handoff-schema", self._table)):
            await self._execute(f"""CREATE TABLE IF NOT EXISTS {self._table} (
                workspace TEXT NOT NULL, principal TEXT NOT NULL, message_id TEXT NOT NULL,
                envelope TEXT NOT NULL, result TEXT, position BIGSERIAL NOT NULL UNIQUE,
                PRIMARY KEY (workspace,principal,message_id))""")
            await self._execute(
                f"CREATE INDEX IF NOT EXISTS {self._table}_pending "
                f"ON {self._table} (workspace,principal,position) WHERE result IS NULL"
            )

    def _prefix(self, scope):
        _inputs(scope, "handoff")
        return scope.workspace, scope.principal

    @staticmethod
    def _message(message):
        if not isinstance(message, MessageEnvelope):
            raise ValidationError("Handoff requires a MessageEnvelope")
        return _json(message.to_dict())

    async def _accept(self, prefix, message, encoded):
        row = await self._execute(
            f"SELECT envelope,result FROM {self._table} "
            "WHERE workspace=%s AND principal=%s AND message_id=%s",
            (*prefix, message.message_id),
            fetch="one",
        )
        if row is not None:
            if row[0] != encoded:
                raise IdempotencyConflict("Handoff message identity conflict")
            return None if row[1] is None else json.loads(row[1])
        count = await self._execute(
            f"SELECT COUNT(*) FROM {self._table} WHERE workspace=%s AND principal=%s",
            prefix,
            fetch="one",
        )
        if count[0] >= self._max_entries:
            raise HandoffError("Handoff capacity reached; retain receipts before archival")
        await self._execute(
            f"INSERT INTO {self._table} (workspace,principal,message_id,envelope) "
            "VALUES (%s,%s,%s,%s)",
            (*prefix, message.message_id, encoded),
        )
        return None

    async def _receive(self, scope, message):
        prefix, encoded = self._prefix(scope), self._message(message)
        async with self._guard(("handoff", self._table, *prefix)):
            return await self._accept(prefix, message, encoded)

    async def _complete(self, scope, message, result):
        prefix, envelope = self._prefix(scope), self._message(message)
        if not isinstance(result, dict):
            raise ValidationError("Handoff completion must be a JSON object")
        encoded = _json(result)
        async with self._guard(("handoff", self._table, *prefix)):
            previous = await self._accept(prefix, message, envelope)
            if previous is not None and _json(previous) != encoded:
                raise IdempotencyConflict("Handoff result identity conflict")
            await self._execute(
                f"UPDATE {self._table} SET result=%s "
                "WHERE workspace=%s AND principal=%s AND message_id=%s",
                (encoded, *prefix, message.message_id),
            )

    async def result(self, scope, message_id):
        prefix = self._prefix(scope)
        _text(message_id, "Message identity")
        async with self._guard():
            row = await self._execute(
                f"SELECT result FROM {self._table} "
                "WHERE workspace=%s AND principal=%s AND message_id=%s",
                (*prefix, message_id),
                fetch="one",
            )
            return None if row is None or row[0] is None else json.loads(row[0])

    async def pending(self, scope, *, limit=100):
        prefix = self._prefix(scope)
        _integer(limit, "Handoff pending limit")
        async with self._guard():
            rows = await self._execute(
                f"SELECT envelope FROM {self._table} "
                "WHERE workspace=%s AND principal=%s AND result IS NULL "
                "ORDER BY position LIMIT %s",
                (*prefix, limit),
                fetch="all",
            )
            return [MessageEnvelope(**json.loads(row[0])) for row in rows]

    async def _close(self):
        async with self._lock:
            if self._owns_connection:
                try:
                    result = await _completed(await self.connection.close(), "PostgreSQL close")
                    if result is not None:
                        raise ValidationError("PostgreSQL close must finish to None")
                except Exception:
                    raise HandoffError("PostgreSQL handoff close failed") from None
            self._closed = True

    async def aclose(self):
        if asyncio.current_task() is self._close_task:
            raise ValidationError("PostgreSQL handoff close cannot reenter itself")
        if self._closed:
            return
        self._closing = True
        if self._close_task is None or self._close_task.done():
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)


class PostgresInbox(_PostgresHandoff):
    table = "ralf_handoff_inbox_v1"

    async def accept(self, scope, message):
        return await self._receive(scope, message)

    async def complete(self, scope, message, result):
        await self._complete(scope, message, result)


class PostgresOutbox(_PostgresHandoff):
    table = "ralf_handoff_outbox_v1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._flush_lock = asyncio.Lock()

    async def enqueue(self, scope, message):
        await self._receive(scope, message)
        return message.message_id

    async def flush(self, bus, scope, *, limit=100):
        self._prefix(scope)
        _integer(limit, "Handoff flush limit")
        async with self._flush_lock:
            count = 0
            for message in await self.pending(scope, limit=limit):
                broker_id = await _completed(
                    await bus.publish(scope, message), "MessageBus.publish"
                )
                _text(broker_id, "Broker identity")
                await self._complete(scope, message, {"broker_id": broker_id})
                count += 1
            return count
