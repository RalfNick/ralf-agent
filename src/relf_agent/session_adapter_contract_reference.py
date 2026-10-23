"""Explicit independent SQLite Session data and editable application factories.

This adapter stores Session messages itself. It is an offline contract example;
original RALF Run and Turn execution remain with the selected Local authority.
"""

import asyncio
import json
import os
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from weakref import WeakKeyDictionary

from .errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict, ValidationError
from .types import Scope, canonical, digest


def _address(scope, session_id):
    if not isinstance(scope, Scope):
        raise ValidationError("Reference Session requires trusted Scope")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValidationError("Reference Session requires a non-empty storage address")


def _message(scope, session_id, message, expected_revision, message_id):
    _address(scope, session_id)
    if type(message) is not dict:
        raise ValidationError("Reference Session requires a finite dictionary message")
    value = json.loads(canonical(message))
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValidationError("Reference Session requires a nonnegative integer revision")
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValidationError("Reference Session requires a non-empty message identity")
    return value


class ReferenceSessionSource:
    """Explicitly opened application-owned data source with no Run authority."""

    def __init__(self, path):
        self.path = str(Path(path).resolve())
        self._original_path = self.path
        self._closed = False
        self._file_unavailable = False
        self._file_descriptor = None
        self._dependents = []
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS session_resource "
                "(singleton INTEGER PRIMARY KEY CHECK(singleton=1),dataset_id TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS session_streams "
                "(workspace TEXT,principal TEXT,address TEXT,revision INTEGER NOT NULL,"
                "PRIMARY KEY(workspace,principal,address));"
                "CREATE TABLE IF NOT EXISTS session_messages "
                "(workspace TEXT,principal TEXT,address TEXT,message_id TEXT,"
                "revision INTEGER NOT NULL,message TEXT NOT NULL,"
                "PRIMARY KEY(workspace,principal,address,message_id),"
                "UNIQUE(workspace,principal,address,revision));"
                "CREATE TABLE IF NOT EXISTS audit (kind TEXT PRIMARY KEY,count INTEGER);"
            )
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO session_resource VALUES (1,?)", (uuid.uuid4().hex,)
                )
                self._dataset_id = connection.execute(
                    "SELECT dataset_id FROM session_resource WHERE singleton=1"
                ).fetchone()[0]
        finally:
            connection.close()
        descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            value = os.fstat(descriptor)
            self._file_identity = value.st_dev, value.st_ino
            self._check_file()
        except BaseException:
            os.close(descriptor)
            raise
        self._file_descriptor = descriptor
        self.backend_id = "external-sqlite-session-v1:" + digest(
            [self._original_path, self._dataset_id]
        )

    def _check_file(self):
        if self._file_unavailable:
            raise DefinitionMismatch("The original reference Session file is unavailable")
        try:
            value = os.stat(self._original_path, follow_symlinks=False)
        except OSError:
            self._file_unavailable = True
            raise DefinitionMismatch("The original reference Session file is unavailable") from None
        if not stat.S_ISREG(value.st_mode) or (value.st_dev, value.st_ino) != self._file_identity:
            self._file_unavailable = True
            raise DefinitionMismatch("The actual reference Session file changed")

    def _check(self):
        if self.path != self._original_path:
            raise DefinitionMismatch("The actual reference Session path changed")
        if self._closed:
            raise ValidationError("Reference Session source is closed")
        self._check_file()

    @contextmanager
    def _connection(self, *, write=False):
        self._check_file()
        connection = sqlite3.connect(self._original_path)
        try:
            self._check_file()
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            row = connection.execute(
                "SELECT dataset_id FROM session_resource WHERE singleton=1"
            ).fetchone()
            if row is None or row[0] != self._dataset_id:
                self._file_unavailable = True
                raise DefinitionMismatch("The original reference Session dataset changed")
            yield connection
            self._check_file()
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        self._check_file()

    @staticmethod
    def _count(connection, kind):
        connection.execute(
            "INSERT INTO audit VALUES (?,1) ON CONFLICT(kind) DO UPDATE SET count=count+1",
            (kind,),
        )

    def count(self, kind):
        self._check()
        with self._connection(write=True) as connection:
            self._count(connection, kind)

    def backend_error(self):
        self._check()
        with self._connection() as connection:
            # A real SQLite failure on the original source, not a supplied verdict.
            connection.execute("SELECT value FROM unavailable_session_backend")

    def read(self, scope, session_id):
        self._check()
        _address(scope, session_id)
        prefix = (scope.workspace, scope.principal, session_id)
        with self._connection(write=True) as connection:
            self._count(connection, "read_calls")
            row = connection.execute(
                "SELECT revision FROM session_streams WHERE workspace=? AND principal=? AND address=?",
                prefix,
            ).fetchone()
            messages = connection.execute(
                "SELECT message FROM session_messages WHERE workspace=? AND principal=? AND address=? ORDER BY revision",
                prefix,
            ).fetchall()
        return (row[0] if row else 0), [json.loads(value[0]) for value in messages]

    def append(self, scope, session_id, message, *, expected_revision, message_id):
        self._check()
        message = _message(scope, session_id, message, expected_revision, message_id)
        encoded = canonical(message)
        prefix = (scope.workspace, scope.principal, session_id)
        self.count("append_calls")
        with self._connection(write=True) as connection:
            previous = connection.execute(
                "SELECT revision,message FROM session_messages WHERE workspace=? AND principal=? AND address=? AND message_id=?",
                (*prefix, message_id),
            ).fetchone()
            if previous is not None:
                if previous[1] != encoded:
                    raise IdempotencyConflict("Reference Session message identity conflict")
                return previous[0]
            row = connection.execute(
                "SELECT revision FROM session_streams WHERE workspace=? AND principal=? AND address=?",
                prefix,
            ).fetchone()
            revision = row[0] if row else 0
            if expected_revision != revision:
                raise ValidationError("Reference Session revision conflict")
            revision += 1
            connection.execute(
                "INSERT INTO session_messages VALUES (?,?,?,?,?,?)",
                (*prefix, message_id, revision, encoded),
            )
            connection.execute(
                "INSERT INTO session_streams VALUES (?,?,?,?) ON CONFLICT(workspace,principal,address) DO UPDATE SET revision=excluded.revision",
                (*prefix, revision),
            )
            self._count(connection, "save_count")
        return revision

    def inspect_message(self, scope, session_id, message_id):
        self._check()
        _address(scope, session_id)
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValidationError("Reference Session inspection requires message identity")
        prefix = (scope.workspace, scope.principal, session_id)
        with self._connection(write=True) as connection:
            self._count(connection, "inspection_calls")
            self._count(connection, "receipt_checks")
            row = connection.execute(
                "SELECT revision FROM session_streams WHERE workspace=? AND principal=? AND address=?",
                prefix,
            ).fetchone()
            found = connection.execute(
                "SELECT revision,message FROM session_messages WHERE workspace=? AND principal=? AND address=? AND message_id=?",
                (*prefix, message_id),
            ).fetchone()
        return {
            "scope": asdict(scope),
            "session_id": session_id,
            "message_id": message_id,
            "revision": row[0] if row else 0,
            "receipt": {"revision": found[0], "message": json.loads(found[1])} if found else None,
        }

    def reopen(self):
        self._check()
        # Operations use short connections. This hook additionally opens an actual
        # new SQLite connection and reads the pinned durable dataset before return.
        with self._connection(write=True) as connection:
            connection.execute("SELECT count(*) FROM session_messages").fetchone()
            self._count(connection, "reopen_calls")

    def audit(self):
        # Lifecycle observations remain available after successful owned close.
        with self._connection() as connection:
            counts = dict(connection.execute("SELECT kind,count FROM audit"))
            count = connection.execute("SELECT count(*) FROM session_messages").fetchone()[0]
            revision = connection.execute(
                "SELECT coalesce(max(revision),0) FROM session_streams"
            ).fetchone()[0]
        return {
            **{
                key: counts.get(key, 0)
                for key in (
                    "read_calls",
                    "append_calls",
                    "inspection_calls",
                    "close_calls",
                    "backend_switches",
                    "model_calls",
                    "save_count",
                    "receipt_checks",
                    "reopen_calls",
                )
            },
            "message_count": count,
            "revision": revision,
        }

    def close(self):
        if self._closed and not self._dependents:
            return
        try:
            while self._dependents:
                self._dependents[-1].close()
                self._dependents.pop()
            if not self._closed:
                try:
                    self.count("close_calls")
                except DefinitionMismatch:
                    pass  # Never write lifecycle evidence to a replacement file.
        finally:
            if self._file_descriptor is not None:
                os.close(self._file_descriptor)
                self._file_descriptor = None
            self._closed = True

    async def aclose(self):
        self.close()


class ReferenceSQLiteSessionStore:
    """Structural core Session port, without implicit receipt requirements."""

    def __init__(self, source):
        if not isinstance(source, ReferenceSessionSource):
            raise ValidationError("Reference Session adapter requires its own source")
        self.source = self._original_source = source
        self.backend_id = source.backend_id
        self._fault = None

    def _check(self):
        if self.source is not self._original_source or self.source.backend_id != self.backend_id:
            raise DefinitionMismatch("The actual reference Session backend changed")
        self.source._check()
        if self._fault == "authorization-denied":
            raise AuthorizationDenied("Reference Session access denied")
        if self._fault == "backend-error":
            self.source.backend_error()

    def read(self, scope, session_id):
        self._check()
        value = self.source.read(scope, session_id)
        self._check()
        return value

    def append(self, scope, session_id, message, *, expected_revision, message_id):
        self._check()
        value = self.source.append(
            scope, session_id, message, expected_revision=expected_revision, message_id=message_id
        )
        self._check()
        if self._fault == "append-ack-lost":
            self._fault = None
            raise ConnectionError("Private reference Session acknowledgement lost")
        return value


class ReferenceSQLiteReceiptSessionStore(ReferenceSQLiteSessionStore):
    """Explicit version 1 exact scoped Session write receipts."""

    session_receipt_version = 1

    def inspect_message(self, scope, session_id, message_id):
        self._check()
        value = self.source.inspect_message(scope, session_id, message_id)
        self._check()
        return value


class AsyncReferenceSQLiteSessionStore(ReferenceSQLiteSessionStore):
    """Native async facade with an actual suspended original append hook."""

    def __init__(self, source):
        super().__init__(source)
        self._pauses = {}

    async def read(self, scope, session_id):
        return super().read(scope, session_id)

    async def append(self, scope, session_id, message, *, expected_revision, message_id):
        self._check()
        gate = self._pauses.pop("append", None)
        if gate is not None:
            self.source.count("receipt_checks")
            gate[0].set()
            await gate[1].wait()
            self._check()
        return super().append(
            scope, session_id, message, expected_revision=expected_revision, message_id=message_id
        )


class AsyncReferenceSQLiteReceiptSessionStore(AsyncReferenceSQLiteSessionStore):
    session_receipt_version = 1

    async def inspect_message(self, scope, session_id, message_id):
        self._check()
        value = self.source.inspect_message(scope, session_id, message_id)
        self._check()
        return value


class OfflineSessionFixture:
    """Pure construction; prepare explicitly opens isolated independent data."""

    def prepare(self, case_id, workspace):
        from .session_adapter_contract import (
            SessionContractAddress,
            SessionContractPause,
            SessionContractResource,
            SessionContractSession,
        )

        source = ReferenceSessionSource(Path(workspace) / "sessions.sqlite")
        try:
            adapter = AsyncReferenceSQLiteReceiptSessionStore(source)
            addresses = tuple(
                SessionContractAddress(Scope(workspace, principal), address)
                for workspace in ("contract-alpha", "contract-beta")
                for principal in ("author-a", "author-b")
                for address in ("first", "second")
            )

            def fault(kind):
                if kind == "backend-swap":
                    source.count("backend_switches")
                    alternate = ReferenceSessionSource(Path(workspace) / "alternate.sqlite")
                    source._dependents.append(alternate)
                    adapter.source = alternate
                elif kind == "reset":
                    adapter.source = source
                    adapter._fault = None
                    while source._dependents:
                        source._dependents[-1].close()
                        source._dependents.pop()
                elif kind in {"backend-error", "authorization-denied", "append-ack-lost"}:
                    adapter._fault = kind
                else:
                    raise ValidationError("Unsupported reference Session fault")

            def pause(operation):
                if operation != "append":
                    raise ValidationError("Reference Session pause supports append")
                entered, release = asyncio.Event(), asyncio.Event()
                adapter._pauses[operation] = entered, release

                async def wait_entered():
                    await entered.wait()

                return SessionContractPause(wait_entered, release.set)

            return SessionContractSession(
                store=adapter,
                addresses=addresses,
                resources=(SessionContractResource(source, asynchronous=True),),
                inject_fault=fault,
                pause=pause,
                audit=source.audit,
                reopen=source.reopen,
            )
        except BaseException:
            source.close()
            raise


def offline_session_fixture():
    """Select the independent offline fixture explicitly, without doing I/O."""
    return OfflineSessionFixture()


class ReferenceSessionReader:
    """Deterministic history-copying Provider for wiring evidence, not quality."""

    def __init__(self, source):
        self.source = source

    @property
    def identity(self):
        return {"kind": "external-session-reader", "version": "1", "source": self.source.backend_id}

    async def complete(self, messages, tools):
        from .providers import ModelResponse

        self.source.count("model_calls")
        history = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str) and content.startswith("Reference memory;"):
                for reference in json.loads(content.partition("\n")[2]):
                    if isinstance(reference, dict) and isinstance(reference.get("session"), list):
                        history.extend(reference["session"])
        return ModelResponse(output={"answer": "Session reference received", "history": history})


def register_session_reference_components(registry, source=None, *, asynchronous=False, owned=True):
    """Register application code; defer owned source creation to BuildContext."""
    if type(asynchronous) is not bool or type(owned) is not bool:
        raise ValidationError("Reference Session ownership and assembly require booleans")
    if source is None and not owned:
        raise ValidationError("Borrowed registration requires the host's original source")
    sources = WeakKeyDictionary()

    def config(values):
        if set(values) - {"path", "receipts"}:
            raise ValidationError("Reference Session factory accepts path and receipts")
        if "path" in values and (not isinstance(values["path"], str) or not values["path"].strip()):
            raise ValidationError("Reference Session factory requires a non-empty path")
        if type(values.get("receipts", True)) is not bool:
            raise ValidationError("Reference Session receipt selection requires a boolean")

    def selected(context, values):
        if source is not None:
            return (
                (context.own_async(source) if asynchronous else context.own(source))
                if owned
                else source
            )
        path = context.path(values.get("path", ".ralf/sessions.sqlite"))
        if context not in sources:
            created = ReferenceSessionSource(path)
            try:
                sources[context] = (
                    context.own_async(created) if asynchronous else context.own(created)
                )
            except BaseException:
                created.close()
                raise
        elif sources[context]._original_path != path:
            raise ValidationError("Shared reference Session factories require one original path")
        return sources[context]

    def session(values, context):
        cls = (
            ReferenceSQLiteReceiptSessionStore
            if values.get("receipts", True)
            else ReferenceSQLiteSessionStore
        )
        return cls(selected(context, values))

    async def async_session(values, context):
        cls = (
            AsyncReferenceSQLiteReceiptSessionStore
            if values.get("receipts", True)
            else AsyncReferenceSQLiteSessionStore
        )
        return cls(selected(context, values))

    def provider(values, context):
        return ReferenceSessionReader(selected(context, values))

    async def async_provider(values, context):
        return provider(values, context)

    register = registry.register_async if asynchronous else registry.register
    register(
        "session_store",
        "external-session",
        async_session if asynchronous else session,
        validator=config,
    )
    register(
        "provider",
        "external-session-reader",
        async_provider if asynchronous else provider,
        validator=config,
    )
