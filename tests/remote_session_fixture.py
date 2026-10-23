"""Async data port over a separate real SQLite database, never a Run authority."""

import asyncio
import copy
import json
from dataclasses import asdict

from relf_agent import SQLiteMemory, SQLiteStore
from relf_agent.errors import MemoryBackendError


class RemoteMemory:
    session_receipt_version = 1

    def __init__(self, path):
        self.store = SQLiteStore(path)
        self.memory = SQLiteMemory(self.store)
        self.backend_id = self.memory.backend_id
        self.append_calls = self.read_calls = self.inspect_calls = 0
        self.fail_after_append = 0
        self.receipt_override = None
        self.started, self.release = None, None

    async def read(self, scope, session_id):
        self.read_calls += 1
        return self.memory.read(scope, session_id)

    async def read_page(self, scope, session_id, query):
        return self.memory.read_page(scope, session_id, query)

    async def append(self, scope, session_id, message, *, expected_revision, message_id):
        self.append_calls += 1
        result = self.memory.append(
            scope, session_id, message, expected_revision=expected_revision, message_id=message_id
        )
        if self.started is not None:
            self.started.set()
            await self.release.wait()
        if self.fail_after_append:
            self.fail_after_append -= 1
            raise MemoryBackendError("Response lost after remote commit")
        return result

    async def inspect_message(self, scope, session_id, message_id):
        self.inspect_calls += 1
        with self.store.transaction():
            prefix = scope.workspace, scope.principal, session_id
            state = self.store.conn.execute(
                "SELECT revision FROM memory_session_index_state WHERE workspace=? AND principal=? AND session=?",
                prefix,
            ).fetchone()
            row = self.store.conn.execute(
                "SELECT seq,data FROM memory_session_items WHERE workspace=? AND principal=? AND session=? AND message_id=?",
                (*prefix, message_id),
            ).fetchone()
        value = {
            "scope": asdict(scope),
            "session_id": session_id,
            "message_id": message_id,
            "revision": state[0] if state else 0,
            "receipt": {"revision": row[0], "message": json.loads(row[1])} if row else None,
        }
        return self.receipt_override(copy.deepcopy(value)) if self.receipt_override else value

    def pause(self):
        self.started, self.release = asyncio.Event(), asyncio.Event()

    def close(self):
        self.store.close()
