"""Independent SQLite Facts data and explicit application assembly.

Facts are stored here, without delegating storage to SDK Memory. Original Local
Run, Action and memory stage authority remains with the selected SDK engine.
"""

import asyncio
import base64
import json
import math
import os
import re
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from weakref import WeakKeyDictionary

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .recall import RecallPage, RecallQuery
from .types import Scope, canonical, digest

_UNSET = object()


def _text(value, label, maximum=1024):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(label + " requires bounded non-empty text")


def _address(scope, namespace, key=_UNSET):
    if not isinstance(scope, Scope):
        raise ValidationError("Reference Facts requires trusted Scope")
    _text(namespace, "Fact namespace", 128)
    if key is not _UNSET:
        _text(key, "Fact key")
    return scope.workspace, scope.principal, namespace


def _expiry(value):
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValidationError("Fact expiration requires finite Unix seconds")
    try:
        value = float(value)
    except OverflowError:
        raise ValidationError("Fact expiration requires finite Unix seconds") from None
    if not math.isfinite(value):
        raise ValidationError("Fact expiration requires finite Unix seconds")
    return value


def _detached(value):
    try:
        return json.loads(canonical(value))
    except (UnicodeError, RecursionError):
        raise ValidationError("Reference Facts requires finite JSON data") from None


def _record(row):
    return {
        "key": row["key"],
        "value": json.loads(row["value"]),
        "version": row["version"],
        "expires_at": row["expires_at"],
    }


class ReferenceFactsSource:
    """An explicitly opened independent dataset, with pinned live file identity."""

    def __init__(self, path):
        self.path = self._original_path = str(Path(path).resolve())
        self._closed, self._file_unavailable = False, False
        self._file_descriptor = None
        self._dependents = []
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS facts_resource (singleton INTEGER PRIMARY KEY CHECK(singleton=1),dataset_id TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS facts (workspace TEXT,principal TEXT,namespace TEXT,key TEXT,value TEXT NOT NULL,version INTEGER NOT NULL,expires_at REAL,PRIMARY KEY(workspace,principal,namespace,key));"
                "CREATE TABLE IF NOT EXISTS facts_generations (workspace TEXT,principal TEXT,namespace TEXT,generation INTEGER NOT NULL,PRIMARY KEY(workspace,principal,namespace));"
                "CREATE TABLE IF NOT EXISTS audit (kind TEXT PRIMARY KEY,count INTEGER NOT NULL);"
            )
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO facts_resource VALUES (1,?)", (uuid.uuid4().hex,)
                )
                self._dataset_id = connection.execute(
                    "SELECT dataset_id FROM facts_resource WHERE singleton=1"
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
        self.backend_id = "external-sqlite-facts-v1:" + digest(
            [self._original_path, self._dataset_id]
        )

    def _check_file(self):
        if self._file_unavailable:
            raise DefinitionMismatch("The original reference Facts file is unavailable")
        try:
            value = os.stat(self._original_path, follow_symlinks=False)
        except OSError:
            self._file_unavailable = True
            raise DefinitionMismatch("The original reference Facts file is unavailable") from None
        if not stat.S_ISREG(value.st_mode) or (value.st_dev, value.st_ino) != self._file_identity:
            self._file_unavailable = True
            raise DefinitionMismatch("The actual reference Facts file changed")

    def _check(self):
        if self.path != self._original_path:
            raise DefinitionMismatch("The actual reference Facts path changed")
        if self._closed:
            raise ValidationError("Reference Facts source is closed")
        self._check_file()

    @contextmanager
    def _connection(self, *, write=False):
        self._check_file()
        connection = sqlite3.connect(self._original_path)
        connection.row_factory = sqlite3.Row
        try:
            self._check_file()
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            row = connection.execute(
                "SELECT dataset_id FROM facts_resource WHERE singleton=1"
            ).fetchone()
            if row is None or row[0] != self._dataset_id:
                self._file_unavailable = True
                raise DefinitionMismatch("The original reference Facts dataset changed")
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
    def _count(connection, kind, amount=1):
        connection.execute(
            "INSERT INTO audit VALUES (?,?) ON CONFLICT(kind) DO UPDATE SET count=count+excluded.count",
            (kind, amount),
        )

    def count(self, kind, amount=1):
        self._check()
        with self._connection(write=True) as connection:
            self._count(connection, kind, amount)

    @staticmethod
    def _generation(connection, prefix):
        connection.execute(
            "INSERT INTO facts_generations VALUES (?,?,?,1) ON CONFLICT(workspace,principal,namespace) DO UPDATE SET generation=generation+1",
            prefix,
        )

    def backend_error(self):
        self._check()
        with self._connection() as connection:
            connection.execute("SELECT value FROM unavailable_facts_backend")

    def facts(self, scope, namespace):
        self._check()
        prefix = _address(scope, namespace)
        with self._connection(write=True) as connection:
            self._count(connection, "facts_calls")
            rows = connection.execute(
                "SELECT key,value,version,expires_at FROM facts WHERE workspace=? AND principal=? AND namespace=? AND (expires_at IS NULL OR expires_at>?) ORDER BY key",
                (*prefix, time.time()),
            ).fetchall()
        return [_record(row) for row in rows]

    def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        self._check()
        prefix = _address(scope, namespace, key)
        if type(expected_version) is not int or expected_version < 0:
            raise ValidationError("Fact CAS requires a nonnegative integer version")
        encoded, expiry = canonical(_detached(value)), _expiry(expires_at)
        self.count("put_calls")
        with self._connection(write=True) as connection:
            row = connection.execute(
                "SELECT version FROM facts WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                (*prefix, key),
            ).fetchone()
            actual = row[0] if row else 0
            if actual != expected_version:
                raise ValidationError("Reference Fact version conflict")
            version = actual + 1
            connection.execute(
                "INSERT INTO facts VALUES (?,?,?,?,?,?,?) ON CONFLICT(workspace,principal,namespace,key) DO UPDATE SET value=excluded.value,version=excluded.version,expires_at=excluded.expires_at",
                (*prefix, key, encoded, version, expiry),
            )
            self._generation(connection, prefix)
            self._count(connection, "write_count")
        return version

    def inspect_fact(self, scope, namespace, key):
        self._check()
        prefix = _address(scope, namespace, key)
        with self._connection(write=True) as connection:
            self._count(connection, "inspection_calls")
            self._count(connection, "receipt_checks")
            row = connection.execute(
                "SELECT key,value,version,expires_at FROM facts WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                (*prefix, key),
            ).fetchone()
        return _record(row) if row else None

    def recall(self, scope, namespace, query):
        self._check()
        prefix = _address(scope, namespace)
        if not isinstance(query, RecallQuery):
            raise ValidationError("Reference Facts recall requires RecallQuery")
        config = {key: value for key, value in asdict(query).items() if key != "cursor"}
        binding = digest(
            {
                "backend": self.backend_id,
                "scope": asdict(scope),
                "namespace": namespace,
                "query": config,
            }
        )
        with self._connection(write=True) as connection:
            self._count(connection, "recall_calls")
            generation = connection.execute(
                "SELECT generation FROM facts_generations WHERE workspace=? AND principal=? AND namespace=?",
                prefix,
            ).fetchone()
            snapshot = {
                "dataset": self._dataset_id,
                "generation": generation[0] if generation else 0,
            }
            after = 0
            if query.cursor is not None:
                try:
                    if re.fullmatch(r"[A-Za-z0-9_-]+", query.cursor) is None:
                        raise ValueError()
                    cursor = json.loads(
                        base64.urlsafe_b64decode(query.cursor + "=" * (-len(query.cursor) % 4))
                    )
                    if (
                        type(cursor) is not dict
                        or set(cursor) != {"v", "b", "s", "p"}
                        or type(cursor["v"]) is not int
                        or cursor["v"] != 1
                        or cursor["b"] != binding
                        or cursor["s"] != snapshot
                        or type(cursor["p"]) is not int
                        or not 0 <= cursor["p"] <= 2**63 - 1
                    ):
                        raise ValueError()
                    after = cursor["p"]
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    raise ValidationError(
                        "Reference Facts cursor belongs to another query or changed snapshot"
                    ) from None
            rows = connection.execute(
                "SELECT rowid AS position,key,value,version,expires_at FROM facts WHERE workspace=? AND principal=? AND namespace=? AND rowid>? ORDER BY rowid LIMIT ?",
                (*prefix, after, query.scan_limit),
            ).fetchall()
            items, scanned, skipped, position, used = [], 0, 0, after, 2
            now = time.time()
            for row in rows:
                if len(items) >= query.max_items:
                    break
                scanned += 1
                position, item = row["position"], _record(row)
                matches = item["expires_at"] is None or item["expires_at"] > now
                if query.text is not None:
                    matches = matches and (
                        query.text in item["key"] or query.text in canonical(item["value"])
                    )
                size = len(canonical(item)) + bool(items)
                if not matches or used + size > query.max_chars:
                    skipped += 1
                    continue
                items.append(item)
                used += size
            has_more = (
                scanned > 0
                and connection.execute(
                    "SELECT 1 FROM facts WHERE workspace=? AND principal=? AND namespace=? AND rowid>? LIMIT 1",
                    (*prefix, position),
                ).fetchone()
                is not None
            )
            cursor = (
                base64.urlsafe_b64encode(
                    canonical({"v": 1, "b": binding, "s": snapshot, "p": position}).encode()
                )
                .decode()
                .rstrip("=")
                if has_more
                else None
            )
            for kind, amount in (("used_chars", used), ("scanned", scanned), ("skipped", skipped)):
                self._count(connection, kind, amount)
        return RecallPage(items, cursor, used, scanned, skipped, canonical(snapshot), True)

    def validate_facts(self, scope, namespace, items):
        self._check()
        prefix = _address(scope, namespace)
        if not isinstance(items, list) or any(type(item) is not dict for item in items):
            raise ValidationError("Fact validation requires a completed record list")
        references = _detached(items)
        keys = set()
        for item in references:
            if not {"key", "value", "version", "expires_at"} <= set(item):
                raise ValidationError("Fact validation requires complete references")
            _text(item["key"], "Fact key")
            if type(item["version"]) is not int or item["version"] < 1 or item["key"] in keys:
                raise ValidationError("Fact validation requires unique positive versions")
            _expiry(item["expires_at"])
            keys.add(item["key"])
        self.count("validate_calls")
        with self._connection() as connection:
            now = time.time()
            for item in references:
                row = connection.execute(
                    "SELECT key,value,version,expires_at FROM facts WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                    (*prefix, item["key"]),
                ).fetchone()
                if (
                    row is None
                    or canonical(_record(row)) != canonical(item)
                    or (row["expires_at"] is not None and row["expires_at"] <= now)
                ):
                    raise ValidationError("Reference Fact is no longer current")

    def mutate_fact(self, scope, namespace, key, mode):
        self._check()
        prefix = _address(scope, namespace, key)
        if mode not in {"delete", "expire", "change"}:
            raise ValidationError("Unknown reference Facts mutation")
        with self._connection(write=True) as connection:
            if mode == "delete":
                connection.execute(
                    "DELETE FROM facts WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                    (*prefix, key),
                )
            elif mode == "expire":
                connection.execute(
                    "UPDATE facts SET expires_at=1 WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                    (*prefix, key),
                )
            else:
                connection.execute(
                    "UPDATE facts SET value='\"changed\"',version=version+1 WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                    (*prefix, key),
                )
            self._generation(connection, prefix)

    def reopen(self):
        self._check()
        # Every operation closes its connection. This deliberately opens another
        # actual connection and observes the same pinned durable dataset.
        with self._connection(write=True) as connection:
            connection.execute("SELECT count(*) FROM facts").fetchone()
            self._count(connection, "reopen_calls")

    def audit(self):
        # Original lifecycle evidence remains readable after successful close.
        with self._connection() as connection:
            counts = dict(connection.execute("SELECT kind,count FROM audit"))
            count, version = connection.execute(
                "SELECT count(*),coalesce(max(version),0) FROM facts"
            ).fetchone()
        return {
            **{
                key: counts.get(key, 0)
                for key in (
                    "facts_calls",
                    "put_calls",
                    "recall_calls",
                    "validate_calls",
                    "inspection_calls",
                    "close_calls",
                    "backend_switches",
                    "consumer_runs",
                    "model_calls",
                    "write_count",
                    "receipt_checks",
                    "reopen_calls",
                    "rejection_checks",
                    "scope_checks",
                    "namespace_checks",
                    "used_chars",
                    "scanned",
                    "skipped",
                    "duplicate_checks",
                    "settlement_checks",
                )
            },
            "fact_count": count,
            "version": version,
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
                    pass  # Never write evidence to a substituted dataset.
        finally:
            if self._file_descriptor is not None:
                os.close(self._file_descriptor)
                self._file_descriptor = None
            self._closed = True

    async def aclose(self):
        self.close()


class ReferenceSQLiteFactsStore:
    """Structural core Facts port, without implicit managed extensions."""

    def __init__(self, source):
        if not isinstance(source, ReferenceFactsSource):
            raise ValidationError("Reference Facts adapter requires its independent source")
        self.source = self._original_source = source
        self.backend_id = source.backend_id
        self._fault, self._fault_puts = None, 0

    def _check(self):
        if self.source is not self._original_source or self.source.backend_id != self.backend_id:
            raise DefinitionMismatch("The actual reference Facts backend changed")
        self.source._check()
        if self._fault == "authorization-denied":
            raise AuthorizationDenied("Reference Facts access denied")
        if self._fault == "backend-error":
            self.source.backend_error()

    def facts(self, scope, namespace):
        self._check()
        value = self.source.facts(scope, namespace)
        self._check()
        return value

    def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        self._check()
        _address(scope, namespace, key)
        observation = not namespace.endswith(":commands")
        if self._fault == "put-after-first" and observation and self._fault_puts >= 1:
            raise ConnectionError("Private reference Facts partial write interruption")
        version = self.source.put_fact(
            scope, namespace, key, value, expected_version=expected_version, expires_at=expires_at
        )
        if observation:
            self._fault_puts += 1
        self._check()
        if self._fault == "put-ack-lost":
            self._fault = None
            raise ConnectionError("Private reference Facts acknowledgement lost")
        return version


class ReferenceSQLiteManagedFactsStore(ReferenceSQLiteFactsStore):
    """Bounded recall, current validation and exact current inspection."""

    fact_inspection_version = 1

    def recall(self, scope, namespace, query):
        self._check()
        page = self.source.recall(scope, namespace, query)
        self._check()
        return page

    def validate_facts(self, scope, namespace, items):
        self._check()
        self.source.validate_facts(scope, namespace, items)
        self._check()

    def inspect_fact(self, scope, namespace, key):
        self._check()
        value = self.source.inspect_fact(scope, namespace, key)
        self._check()
        return value


class AsyncReferenceSQLiteFactsStore(ReferenceSQLiteFactsStore):
    """Native async facade, with an actual suspended put handler hook."""

    def __init__(self, source):
        super().__init__(source)
        self._pauses = {}

    async def _pause(self, name):
        gate = self._pauses.pop(name, None)
        if gate is not None:
            gate[0].set()
            await gate[1].wait()
            self._check()

    async def facts(self, scope, namespace):
        return super().facts(scope, namespace)

    async def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        self._check()
        # Detach admitted input before the actual suspension.
        value = _detached(value)
        await self._pause("put_fact")
        return super().put_fact(
            scope, namespace, key, value, expected_version=expected_version, expires_at=expires_at
        )


class AsyncReferenceSQLiteManagedFactsStore(AsyncReferenceSQLiteFactsStore):
    fact_inspection_version = 1

    async def recall(self, scope, namespace, query):
        self._check()
        value = self.source.recall(scope, namespace, query)
        self._check()
        return value

    async def validate_facts(self, scope, namespace, items):
        self._check()
        self.source.validate_facts(scope, namespace, items)
        # The actual validation is complete before holding its returned None.
        # Consumers must still refuse references whose original expiry elapsed.
        await self._pause("validate_facts")
        self._check()

    async def inspect_fact(self, scope, namespace, key):
        self._check()
        value = self.source.inspect_fact(scope, namespace, key)
        self._check()
        return value


class OfflineFactsFixture:
    """Pure construction; prepare explicitly opens isolated independent data."""

    def prepare(self, case_id, workspace):
        from .facts_adapter_contract import (
            FactsContractAddress,
            FactsContractPause,
            FactsContractResource,
            FactsContractSession,
        )

        source = ReferenceFactsSource(Path(workspace) / "facts.sqlite")
        try:
            adapter = AsyncReferenceSQLiteManagedFactsStore(source)
            addresses = tuple(
                FactsContractAddress(Scope(w, principal), namespace)
                for w in ("contract-alpha", "contract-beta")
                for principal in ("author-a", "author-b")
                for namespace in ("first", "second")
            )

            def fault(kind):
                if kind == "backend-swap":
                    source.count("backend_switches")
                    alternate = ReferenceFactsSource(Path(workspace) / "alternate.sqlite")
                    source._dependents.append(alternate)
                    adapter.source = alternate
                elif kind == "reset":
                    adapter.source, adapter._fault, adapter._fault_puts = source, None, 0
                    while source._dependents:
                        source._dependents[-1].close()
                        source._dependents.pop()
                elif kind in {
                    "backend-error",
                    "authorization-denied",
                    "put-after-first",
                    "put-ack-lost",
                }:
                    adapter._fault, adapter._fault_puts = kind, 0
                else:
                    raise ValidationError("Unsupported reference Facts fault")

            def pause(operation):
                if operation not in {"put_fact", "validate_facts"}:
                    raise ValidationError(
                        "Reference Facts pause requires a writable or validation operation"
                    )
                entered, release = asyncio.Event(), asyncio.Event()
                adapter._pauses[operation] = entered, release

                async def wait_entered():
                    await entered.wait()

                return FactsContractPause(wait_entered, release.set)

            return FactsContractSession(
                store=adapter,
                addresses=addresses,
                resources=(FactsContractResource(source, asynchronous=True),),
                inject_fault=fault,
                pause=pause,
                audit=source.audit,
                reopen=source.reopen,
                mutate_fact=source.mutate_fact,
            )
        except BaseException:
            source.close()
            raise


def offline_facts_fixture():
    """Explicitly select offline testing without opening a dataset."""
    return OfflineFactsFixture()


class ReferenceFactsReader:
    """Deterministic Provider reports its committed Facts context, not quality."""

    def __init__(self, source):
        self.source = source

    @property
    def identity(self):
        return {"kind": "external-facts-reader", "version": "1", "source": self.source.backend_id}

    async def complete(self, messages, tools):
        from .providers import ModelResponse

        self.source.count("model_calls")
        facts = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str) and content.startswith("Reference memory;"):
                for reference in json.loads(content.partition("\n")[2]):
                    if isinstance(reference, dict) and {
                        "key",
                        "value",
                        "version",
                        "expires_at",
                    } <= set(reference):
                        facts.append(reference)
        return ModelResponse(output={"answer": "Facts reference received", "facts": facts})


def register_facts_reference_components(registry, source=None, *, asynchronous=False, owned=True):
    """Register factories without I/O; BuildContext owns lazy source creation."""
    if type(asynchronous) is not bool or type(owned) is not bool:
        raise ValidationError("Reference Facts ownership and assembly require booleans")
    if source is None and not owned:
        raise ValidationError("Borrowed registration requires the host's original source")
    if source is not None and not isinstance(source, ReferenceFactsSource):
        raise ValidationError("Reference Facts factory requires its independent source")
    sources = WeakKeyDictionary()

    def config(values):
        if set(values) - {"path", "managed", "namespace", "fields"}:
            raise ValidationError(
                "Reference Facts factory accepts path, managed, namespace and fields"
            )
        if "path" in values:
            _text(values["path"], "Reference Facts path", 4096)
        if type(values.get("managed", True)) is not bool:
            raise ValidationError("Reference Facts managed selection requires boolean")
        if "namespace" in values:
            _text(values["namespace"], "Managed Facts namespace", 128)
        if "fields" in values:
            from .memory_extraction import MemoryAdmissionPolicy

            MemoryAdmissionPolicy(values["fields"])

    def selected(context, values):
        if source is not None:
            return (
                (context.own_async(source) if asynchronous else context.own(source))
                if owned
                else source
            )
        path = context.path(values.get("path", ".ralf/facts.sqlite"))
        if context not in sources:
            created = ReferenceFactsSource(path)
            try:
                sources[context] = (
                    context.own_async(created) if asynchronous else context.own(created)
                )
            except BaseException:
                created.close()
                raise
        elif sources[context]._original_path != path:
            raise ValidationError("Shared reference Facts factories require one original path")
        return sources[context]

    def memory(values, context):
        cls = (
            (
                AsyncReferenceSQLiteManagedFactsStore
                if values.get("managed", True)
                else AsyncReferenceSQLiteFactsStore
            )
            if asynchronous
            else (
                ReferenceSQLiteManagedFactsStore
                if values.get("managed", True)
                else ReferenceSQLiteFactsStore
            )
        )
        return cls(selected(context, values))

    async def async_memory(values, context):
        return memory(values, context)

    def provider(values, context):
        return ReferenceFactsReader(selected(context, values))

    async def async_provider(values, context):
        return provider(values, context)

    def stage(values, context):
        from .managed_memory import ManagedMemoryPolicy
        from .memory_extraction import MemoryAdmissionPolicy

        if not values.get("managed", True):
            raise ValidationError("Managed Facts policy requires the managed port")
        return ManagedMemoryPolicy(
            memory(values, context),
            scope=context.scope,
            namespace=values.get("namespace", "reader"),
            admission=MemoryAdmissionPolicy(values.get("fields")),
        )

    async def async_stage(values, context):
        return stage(values, context)

    register = registry.register_async if asynchronous else registry.register
    register(
        "memory_store", "external-facts", async_memory if asynchronous else memory, validator=config
    )
    register(
        "provider",
        "external-facts-reader",
        async_provider if asynchronous else provider,
        validator=config,
    )
    register(
        "stage_policy",
        "external-facts-stage",
        async_stage if asynchronous else stage,
        validator=config,
    )
