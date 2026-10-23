import asyncio
import contextvars
import copy
import importlib
import importlib.util
import json
import sqlite3
import sys
import threading
import time
import types
from dataclasses import asdict

import pytest

from relf_agent import (
    FactIndexCatalog,
    InMemoryMemory,
    InMemoryVectorIndex,
    RecallQuery,
    Scope,
    SQLiteMemory,
    SQLiteVectorIndex,
)
from relf_agent.embeddings import HashEmbeddingProvider
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.tool_execution import ToolExecutionOwner
from relf_agent.types import digest

SCOPE, NAMESPACE = Scope("generation-tests", "author"), "facts"


def api():
    name = "relf_agent.fact_index_generation"
    assert importlib.util.find_spec(name) is not None, "Missing generation-bound Facts indexing"
    return importlib.import_module(name)


class NativePorts:
    def __init__(self, root, label="native"):
        module = api()
        root.mkdir(parents=True, exist_ok=True)
        self.source = SQLiteMemory(root / "source.sqlite")
        self.vector = SQLiteVectorIndex(root / "vectors.sqlite", dimensions=16)
        self.metadata = SQLiteMemory(root / "catalog.sqlite")
        self.catalog = FactIndexCatalog(self.metadata)
        self.embedding = HashEmbeddingProvider(dimensions=16)
        self.index = module.GenerationIndexedMemoryStore(
            self.source,
            self.embedding,
            self.vector,
            self.catalog,
            scope=SCOPE,
            namespace=NAMESPACE,
            batch_size=2,
        )
        self.owner = ToolExecutionOwner(version="generation-test", max_calls=2)
        self.label = label
        self.sequence = 0

    async def rebuild(self, snapshot, *, max_pages=1):
        self.sequence += 1

        async def operation():
            return await self.index.rebuild_for_snapshot(
                SCOPE, NAMESPACE, snapshot, max_pages=max_pages
            )

        return await self.owner.execute(
            operation,
            proof={
                "scope": asdict(SCOPE),
                "action_id": f"{self.label}:{self.sequence}",
                "release_digest": digest(self.index.identity),
                "request_digest": digest([snapshot, max_pages]),
                "execution_epoch": "original-test-owner",
            },
        )

    def rows(self):
        return [
            dict(row)
            for row in self.metadata.store.conn.execute(
                "SELECT * FROM memory_facts ORDER BY namespace,key"
            )
        ]

    async def close(self):
        assert await self.owner.wait(wait_timeout=2)
        await self.owner.aclose(wait_timeout=2)
        assert self.owner._execution.active_count == 0
        for port in (self.vector, self.metadata, self.source):
            port.close()
            with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                port.store.conn.execute("SELECT 1")


def test_partial_generation_never_publishes_then_reopens_original_ready_receipt(tmp_path):
    async def run():
        ports = NativePorts(tmp_path)
        try:
            for n in range(5):
                ports.source.put_fact(
                    SCOPE, NAMESPACE, str(n), "marker " + str(n), expected_version=0
                )
            snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            partial = await ports.rebuild(snapshot)
            assert partial["status"] == "building" and partial["scanned"] == 2
            rows = ports.rows()
            assert len(rows) == 1
            assert rows[0]["key"].startswith("build:")
            assert json.loads(rows[0]["value"])["build_id"] == partial["build_id"]
            with pytest.raises(ValidationError):
                await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="marker 4"))
            ready = await ports.rebuild(snapshot, max_pages=2)
            assert ready["status"] == "ready" and ready["scanned"] == 5
            assert ready["build_id"] == partial["build_id"]
            page = await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="marker 4"))
            assert len(page.items) == 5
            assert all(item["_fact_index"]["build_id"] == ready["build_id"] for item in page.items)
            identity, rows = ports.index.identity, ports.rows()
            assert ports.index.original_catalog is ports.catalog
        finally:
            await ports.close()
        reopened = NativePorts(tmp_path, "reopened")
        try:
            assert reopened.index.identity == identity
            result = await reopened.rebuild(snapshot)
            assert result == ready and reopened.rows() == rows
            assert reopened.source.inspect_fact(SCOPE, NAMESPACE, "4")["value"] == "marker 4"
        finally:
            await reopened.close()

    asyncio.run(run())


def test_source_update_requires_new_generation_and_invalidates_prepared_facts(tmp_path):
    async def run():
        ports = NativePorts(tmp_path)
        try:
            ports.source.put_fact(SCOPE, NAMESPACE, "one", "violet", expected_version=0)
            old_snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            old = await ports.rebuild(old_snapshot)
            page = await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="violet"))
            assert page.items[0]["value"] == "violet" and page.items[0]["version"] == 1
            assert ports.index.put_fact(SCOPE, NAMESPACE, "one", "amber", expected_version=1) == 2
            with pytest.raises(ValidationError):
                await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="amber"))
            with pytest.raises(api().GenerationSourceChanged):
                await ports.rebuild(old_snapshot)
            snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            ready = await ports.rebuild(snapshot)
            assert ready["build_id"] != old["build_id"]
            current = await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="amber"))
            assert current.items[0]["value"] == "amber" and current.items[0]["version"] == 2
            await ports.index.validate_facts(SCOPE, NAMESPACE, current.items)
            with pytest.raises(ValidationError):
                await ports.index.validate_facts(SCOPE, NAMESPACE, page.items)
            active = [
                json.loads(r["value"]) for r in ports.rows() if r["key"].startswith("active:")
            ]
            assert {r["source_snapshot"] for r in active} == {snapshot, old_snapshot}
        finally:
            await ports.close()

    asyncio.run(run())


def test_expected_snapshot_mismatch_refuses_before_catalog_or_vector_effect(tmp_path):
    async def run():
        ports = NativePorts(tmp_path)
        try:
            ports.source.put_fact(SCOPE, NAMESPACE, "one", "old", expected_version=0)
            snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            ports.source.put_fact(SCOPE, NAMESPACE, "one", "new", expected_version=1)
            with pytest.raises(api().GenerationSourceChanged):
                await ports.rebuild(snapshot)
            assert ports.rows() == []
            assert list(ports.vector.store.conn.execute("SELECT * FROM vector_entries")) == []
            assert ports.source.inspect_fact(SCOPE, NAMESPACE, "one")["value"] == "new"
        finally:
            await ports.close()

    asyncio.run(run())


def test_expired_fact_is_not_recalled_under_unchanged_source_snapshot(tmp_path):
    async def run():
        ports = NativePorts(tmp_path)
        try:
            expires = time.time() + 2
            ports.source.put_fact(
                SCOPE, NAMESPACE, "one", "temporary", expected_version=0, expires_at=expires
            )
            snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            await ports.rebuild(snapshot)
            original = await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="temporary"))
            assert original.items[0]["value"] == "temporary"
            await asyncio.sleep(max(0, expires - time.time()) + 0.02)
            assert await ports.index.source_snapshot(SCOPE, NAMESPACE) == snapshot
            expired = await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="temporary"))
            assert expired.items == [] and expired.skipped == 1
            with pytest.raises(ValidationError):
                await ports.index.validate_facts(SCOPE, NAMESPACE, original.items)
        finally:
            await ports.close()

    asyncio.run(run())


def test_deleted_source_invalidates_old_publication_then_current_empty_build_recalls_none(tmp_path):
    async def run():
        ports = NativePorts(tmp_path)
        try:
            ports.source.put_fact(SCOPE, NAMESPACE, "one", "removed", expected_version=0)
            old_snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            await ports.rebuild(old_snapshot)
            original = await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="removed"))
            with ports.source.store.transaction():
                ports.source.store.conn.execute(
                    "DELETE FROM memory_facts WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                    (SCOPE.workspace, SCOPE.principal, NAMESPACE, "one"),
                )
            with pytest.raises(ValidationError):
                await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="removed"))
            with pytest.raises(ValidationError):
                await ports.index.validate_facts(SCOPE, NAMESPACE, original.items)
            snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            assert snapshot != old_snapshot
            ready = await ports.rebuild(snapshot)
            assert ready["status"] == "ready" and ready["scanned"] == ready["indexed"] == 0
            assert (
                await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="removed"))
            ).items == []
            assert ports.source.inspect_fact(SCOPE, NAMESPACE, "one") is None
        finally:
            await ports.close()

    asyncio.run(run())


def test_sync_cas_catalog_protocol_preserves_original_completed_generation():
    class SyncCAS:
        identity = {"kind": "test-sync-generation-cas", "version": "1"}

        def __init__(self):
            self.records = {}

        def load(self, scope, address, key):
            return copy.deepcopy(self.records.get((scope, address, key), (0, None)))

        def save(self, scope, address, key, value, *, expected_version):
            version, _ = self.load(scope, address, key)
            if version != expected_version:
                raise ValidationError("CAS revision conflict")
            self.records[(scope, address, key)] = (version + 1, copy.deepcopy(value))
            return version + 1

    async def run():
        source, vector, catalog = InMemoryMemory(), InMemoryVectorIndex(dimensions=16), SyncCAS()
        index = api().GenerationIndexedMemoryStore(
            source,
            HashEmbeddingProvider(dimensions=16),
            vector,
            catalog,
            scope=SCOPE,
            namespace=NAMESPACE,
        )
        try:
            source.put_fact(SCOPE, NAMESPACE, "one", "sync CAS", expected_version=0)
            snapshot = await index.source_snapshot(SCOPE, NAMESPACE)
            ready = await index.rebuild_for_snapshot(SCOPE, NAMESPACE, snapshot)
            page = await index.recall(SCOPE, NAMESPACE, RecallQuery(text="sync CAS"))
            assert page.items[0]["value"] == "sync CAS"
            before = copy.deepcopy(catalog.records)
            assert await index.rebuild_for_snapshot(SCOPE, NAMESPACE, snapshot) == ready
            assert catalog.records == before
            with pytest.raises(ValidationError, match="CAS revision conflict"):
                await index.catalog.save(
                    SCOPE, ready["definition"], "build", ready, expected_version=0
                )
            assert catalog.records == before
        finally:
            source.close()
            vector.close()

    asyncio.run(run())


@pytest.mark.parametrize("target", ["source_snapshot", "fact_snapshot", "recall", "rebuild"])
def test_foreign_equal_method_receiver_is_refused_without_calling_equality_or_source(
    tmp_path, target
):
    class EqualReceiver:
        equal_calls = 0

        def __eq__(self, other):
            self.equal_calls += 1
            return True

    async def run():
        ports = NativePorts(tmp_path)
        try:
            snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            source_sql = []
            ports.source.store.conn.set_trace_callback(source_sql.append)
            receiver = EqualReceiver()
            original_target = ports.source if target == "fact_snapshot" else ports.index
            method = target
            original = getattr(original_target, method)
            setattr(original_target, method, types.MethodType(original.__func__, receiver))
            try:
                with pytest.raises(DefinitionMismatch):
                    await ports.index.rebuild_for_snapshot(SCOPE, NAMESPACE, snapshot)
                assert receiver.equal_calls == 0 and source_sql == []
                assert ports.rows() == []
            finally:
                setattr(original_target, method, original)
                ports.source.store.conn.set_trace_callback(None)
        finally:
            await ports.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "change", ["namespace", "context", "catalog", "cloned-store", "source-ports"]
)
def test_selected_config_and_actual_resource_drift_refuses_before_source_sql(tmp_path, change):
    async def run():
        ports = NativePorts(tmp_path)
        extra = SQLiteMemory(tmp_path / "extra.sqlite")
        try:
            snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            source_sql = []
            ports.source.store.conn.set_trace_callback(source_sql.append)
            if change == "namespace":
                original = ports.index._namespace
                ports.index._namespace = "foreign"
            elif change == "context":
                original = ports.index._expected
                ports.index._expected = contextvars.ContextVar("forged", default=None)
            elif change == "catalog":
                original = ports.index.original_catalog
                ports.index.original_catalog = FactIndexCatalog(extra)
            elif change == "source-ports":
                original = ports.index._fixed
                ports.index._fixed = ports.index._source_ports = original._original
            else:
                original = ports.source.store
                original.conn.backup(extra.store.conn)
                ports.source.store = extra.store
            try:
                with pytest.raises(DefinitionMismatch):
                    await ports.index.rebuild_for_snapshot(SCOPE, NAMESPACE, snapshot)
                assert source_sql == []
            finally:
                if change == "namespace":
                    ports.index._namespace = original
                elif change == "context":
                    ports.index._expected = original
                elif change == "catalog":
                    ports.index.original_catalog = original
                elif change == "source-ports":
                    ports.index._fixed = ports.index._source_ports = original
                else:
                    ports.source.store = original
                ports.source.store.conn.set_trace_callback(None)
        finally:
            await ports.close()
            extra.close()
            with pytest.raises(sqlite3.ProgrammingError):
                extra.store.conn.execute("SELECT 1")

    asyncio.run(run())


def test_foreign_selection_refuses_before_source_io(tmp_path):
    async def run():
        ports = NativePorts(tmp_path)
        try:
            sql = []
            ports.source.store.conn.set_trace_callback(sql.append)
            with pytest.raises(AuthorizationDenied):
                await ports.index.source_snapshot(Scope("other", "author"), NAMESPACE)
            with pytest.raises(AuthorizationDenied):
                await ports.index.recall(SCOPE, "other", RecallQuery(text="foreign"))
            assert sql == [] and ports.rows() == []
        finally:
            ports.source.store.conn.set_trace_callback(None)
            await ports.close()

    asyncio.run(run())


def test_late_old_native_publisher_cannot_replace_current_generation(tmp_path):
    module = api()
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()
    failures = []

    def old_worker():
        async def run():
            ports = NativePorts(tmp_path, "older")
            paused = False

            def trace(frame, event, _arg):
                nonlocal paused
                if (
                    not paused
                    and event == "call"
                    and frame.f_code is module._GenerationCatalog.load.__code__
                    and frame.f_locals.get("key") == "active"
                ):
                    paused = True
                    entered.set()
                    assert release.wait(timeout=5), "Actual old publication was not released"
                return trace

            try:
                ports.source.put_fact(SCOPE, NAMESPACE, "one", "older", expected_version=0)
                snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
                sys.settrace(trace)
                try:
                    with pytest.raises(module.GenerationSourceChanged):
                        await ports.rebuild(snapshot)
                finally:
                    sys.settrace(None)
            finally:
                await ports.close()

        try:
            asyncio.run(run())
        except BaseException as exc:
            failures.append(exc)
        finally:
            ended.set()

    async def run():
        thread = threading.Thread(target=old_worker, name="generation-late-original")
        thread.start()
        current = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            current = NativePorts(tmp_path, "newer")
            current.source.put_fact(SCOPE, NAMESPACE, "one", "newer", expected_version=1)
            snapshot = await current.index.source_snapshot(SCOPE, NAMESPACE)
            ready = await current.rebuild(snapshot)
            release.set()
            assert await asyncio.to_thread(ended.wait, 5)
            await asyncio.to_thread(thread.join, 5)
            assert not thread.is_alive() and not failures, failures
            page = await current.index.recall(SCOPE, NAMESPACE, RecallQuery(text="newer"))
            assert page.items[0]["value"] == "newer" and page.items[0]["version"] == 2
            assert page.items[0]["_fact_index"]["build_id"] == ready["build_id"]
            active = [
                json.loads(r["value"]) for r in current.rows() if r["key"].startswith("active:")
            ]
            assert len(active) == 2
            assert {item["source_snapshot"] for item in active} != {snapshot}
        finally:
            release.set()
            await asyncio.to_thread(thread.join, 5)
            assert not thread.is_alive()
            if current is not None:
                await current.close()

    asyncio.run(run())


def test_competing_native_same_generation_cas_refuses_loser_preserving_ready_reader(tmp_path):
    api()
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    ended = [threading.Event(), threading.Event()]
    failures = []

    async def seed():
        ports = NativePorts(tmp_path, "seed")
        try:
            ports.source.put_fact(SCOPE, NAMESPACE, "one", "shared", expected_version=0)
            return await ports.index.source_snapshot(SCOPE, NAMESPACE)
        finally:
            await ports.close()

    snapshot = asyncio.run(seed())

    def worker(number):
        async def run():
            ports = NativePorts(tmp_path, f"writer-{number}")
            paused = False

            def trace(frame, event, _arg):
                nonlocal paused
                if (
                    not paused
                    and event == "return"
                    and frame.f_code is HashEmbeddingProvider.embed.__code__
                ):
                    paused = True
                    entered[number].set()
                    assert release[number].wait(timeout=5), "Actual Hash response was not released"
                return trace

            try:
                sys.settrace(trace)
                try:
                    if number == 0:
                        assert (await ports.rebuild(snapshot))["status"] == "ready"
                    else:
                        with pytest.raises(ValidationError, match="Fact version conflict"):
                            await ports.rebuild(snapshot)
                finally:
                    sys.settrace(None)
            finally:
                await ports.close()

        try:
            asyncio.run(run())
        except BaseException as exc:
            failures.append(exc)
        finally:
            ended[number].set()

    async def run():
        threads = [
            threading.Thread(target=worker, args=(n,), name=f"generation-native-{n}")
            for n in (0, 1)
        ]
        threads[0].start()
        try:
            assert await asyncio.to_thread(entered[0].wait, 5)
            threads[1].start()
            assert await asyncio.to_thread(entered[1].wait, 5)
            release[0].set()
            assert await asyncio.to_thread(ended[0].wait, 5)
            release[1].set()
            assert await asyncio.to_thread(ended[1].wait, 5)
        finally:
            for signal in release:
                signal.set()
            for thread in threads:
                if thread.ident is not None:
                    await asyncio.to_thread(thread.join, 5)
            assert all(not thread.is_alive() for thread in threads)
        assert not failures, failures
        current = NativePorts(tmp_path, "reader")
        try:
            page = await current.index.recall(SCOPE, NAMESPACE, RecallQuery(text="shared"))
            assert page.items[0]["value"] == "shared" and page.items[0]["version"] == 1
            active = [
                json.loads(r["value"]) for r in current.rows() if r["key"].startswith("active:")
            ]
            assert len(active) == 1
            assert page.items[0]["_fact_index"]["build_id"] == active[0]["build_id"]
        finally:
            await current.close()

    asyncio.run(run())


@pytest.mark.parametrize("method", ["inspect_fact", "put_fact"])
def test_original_catalog_refuses_equal_foreign_native_receiver_before_sql(
    tmp_path, monkeypatch, method
):
    equality_calls = []

    def equal(receiver, other):
        equality_calls.append((id(receiver), id(other)))
        return True

    async def run():
        ports = NativePorts(tmp_path)
        foreign = SQLiteMemory(tmp_path / "foreign.sqlite")
        original = getattr(ports.metadata, method)
        traces = [[], [], []]
        try:
            monkeypatch.setattr(SQLiteMemory, "__eq__", equal, raising=False)
            setattr(ports.metadata, method, getattr(foreign, method))
            for port, trace in zip((ports.source, ports.metadata, foreign), traces, strict=True):
                port.store.conn.set_trace_callback(trace.append)
            with pytest.raises(DefinitionMismatch):
                if method == "inspect_fact":
                    await ports.catalog.load(SCOPE, "original-address", "build")
                else:
                    await ports.catalog.save(
                        SCOPE, "original-address", "build", {"state": "foreign"}, expected_version=0
                    )
            assert equality_calls == [] and traces == [[], [], []]
        finally:
            setattr(ports.metadata, method, original)
            for port in (ports.source, ports.metadata, foreign):
                port.store.conn.set_trace_callback(None)
            selected_rows = ports.rows()
            foreign_rows = list(foreign.store.conn.execute("SELECT * FROM memory_facts"))
            try:
                await ports.close()
            finally:
                foreign.close()
            with pytest.raises(sqlite3.ProgrammingError):
                foreign.store.conn.execute("SELECT 1")
        assert selected_rows == foreign_rows == []

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["scan_facts", "validate_facts", "inspect_fact"])
def test_native_source_read_race_completes_exact_source_changed_and_blocks_graph_reader(
    tmp_path, boundary
):
    from relf_agent import (
        GraphNode,
        GraphWorkflowSpec,
        Literal,
        LocalEngine,
        SQLiteStore,
        ToolPolicy,
        ToolRegistry,
        ToolSpec,
        ValueRef,
        register_tool_source,
    )
    from relf_agent.fact_index_maintenance_tools import (
        NAME,
        READY_ONLY_SCHEMA,
        FactIndexMaintenanceToolSource,
    )

    entered, release = threading.Event(), threading.Event()
    writer_evidence = {}

    def writer():
        native = None
        try:
            assert entered.wait(5), "Original native source read was not entered"
            native = SQLiteMemory(tmp_path / "source.sqlite")
            writer_evidence["version"] = native.put_fact(
                SCOPE, NAMESPACE, "one", "new", expected_version=1
            )
        except BaseException as exc:
            writer_evidence["error"] = repr(exc)
        finally:
            if native is not None:
                native.close()
                with pytest.raises(sqlite3.ProgrammingError):
                    native.store.conn.execute("SELECT 1")
                writer_evidence["connection_closed"] = True
            release.set()

    async def run():
        ports = NativePorts(tmp_path)
        source = FactIndexMaintenanceToolSource(
            ports.index, version="native-boundary", scope=SCOPE, namespace=NAMESPACE, max_pages=1
        )
        thread = threading.Thread(target=writer, name="generation-native-source-writer")
        paused = False
        reads = []

        def trace(frame, event, _arg):
            nonlocal paused
            if (
                not paused
                and event == "call"
                and frame.f_code is getattr(SQLiteMemory, boundary).__code__
                and frame.f_locals.get("self") is ports.source
            ):
                paused = True
                entered.set()
                assert release.wait(5), "Concurrent native source writer was not released"
            return trace

        async def read(arguments, context):
            reads.append(context.action_id)
            return asdict(await ports.index.recall(SCOPE, NAMESPACE, RecallQuery(text="new")))

        try:
            ports.source.put_fact(SCOPE, NAMESPACE, "one", "old", expected_version=0)
            original_snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            registry = ToolRegistry()
            await register_tool_source(
                registry,
                source,
                policies={
                    NAME: ToolPolicy(
                        "native-boundary",
                        effect="idempotent_write",
                        requires_approval=False,
                        effect_key_argument="effect_key",
                        reconciler=source.reconcile,
                    )
                },
            )
            registry.register(
                ToolSpec(
                    "native_reader",
                    "Read Facts",
                    {"type": "object"},
                    effect="read_only",
                    requires_approval=False,
                ),
                read,
            )
            spec = GraphWorkflowSpec(
                "native-source-boundary",
                [
                    GraphNode(
                        "ensure", tool=NAME, input=Literal({}), output_schema=READY_ONLY_SCHEMA
                    ),
                    GraphNode(
                        "reader", tool="native_reader", depends_on=("ensure",), input=Literal({})
                    ),
                ],
                output=ValueRef("reader"),
                max_concurrency=1,
            )
            with LocalEngine(
                SQLiteStore(tmp_path / "run.sqlite"), providers={}, tools=registry, scope=SCOPE
            ) as engine:
                handle = engine.submit(spec, "read", command_id="original", budget=4)
                thread.start()
                sys.settrace(trace)
                try:
                    result = await engine.drive(handle.run_id)
                finally:
                    sys.settrace(None)
                    release.set()
                    await asyncio.to_thread(thread.join, 5)
                assert paused and not thread.is_alive() and "error" not in writer_evidence
                assert writer_evidence == {"version": 2, "connection_closed": True}
                actions = engine.store.run(handle.run_id)["actions"]
                assert result.state == "failed" and len(actions) == 1 and reads == []
                action = actions[0]
                assert action["status"] == "completed"
                receipt = action["result"]
                assert receipt["status"] == "source_changed"
                assert receipt["source_snapshot"] == original_snapshot
                assert receipt["run_id"] == handle.run_id and receipt["action_id"] == action["id"]
                assert await source.query_refresh(SCOPE, receipt["effect_key"]) == receipt
                assert await engine.drive(handle.run_id) == result and reads == []
                assert engine.store.budget(handle.run_id) == {"limit": 4, "held": 0, "spent": 1}
                current = await ports.index.source_snapshot(SCOPE, NAMESPACE)
                assert current != original_snapshot and ports.index._expected.get() is None
                assert not list(ports.vector.store.conn.execute("SELECT * FROM vector_entries"))
                assert not any(row["key"].startswith("active:") for row in ports.rows())
                (tmp_path / "source-boundary-evidence.json").write_text(
                    json.dumps(
                        {
                            "boundary": boundary,
                            "writer": writer_evidence,
                            "original_snapshot": original_snapshot,
                            "current_snapshot": current,
                            "receipt": receipt,
                            "action": action,
                            "reader_calls": reads,
                            "catalog_rows": ports.rows(),
                        },
                        indent=2,
                    )
                )
        finally:
            sys.settrace(None)
            release.set()
            if thread.ident is not None:
                await asyncio.to_thread(thread.join, 5)
                assert not thread.is_alive()
            await source.aclose(wait_timeout=2)
            assert source._owner._execution.active_count == 0
            await ports.close()

    asyncio.run(run())


@pytest.mark.parametrize("method", ["check", "call", "_source_current"])
def test_generation_source_boundary_equal_receiver_drift_refuses_before_sql(tmp_path, method):
    class EqualReceiver:
        def __eq__(self, other):
            raise AssertionError("Source boundary must not call supplier equality")

    async def run():
        ports = NativePorts(tmp_path)
        boundary = ports.index._source_ports
        original = getattr(boundary, method)
        sql = []
        try:
            snapshot = await ports.index.source_snapshot(SCOPE, NAMESPACE)
            setattr(boundary, method, types.MethodType(original.__func__, EqualReceiver()))
            ports.source.store.conn.set_trace_callback(sql.append)
            with pytest.raises(DefinitionMismatch):
                await ports.index.rebuild_for_snapshot(SCOPE, NAMESPACE, snapshot)
            assert sql == [] and ports.rows() == []
        finally:
            setattr(boundary, method, original)
            ports.source.store.conn.set_trace_callback(None)
            await ports.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", ["scan-page", "scan-error", "validation-error", "inspect-error"]
)
def test_unchanged_source_read_schema_or_validation_refusal_keeps_effect_pending(failure):
    from relf_agent.fact_index_maintenance_tools import FactIndexMaintenanceToolSource
    from relf_agent.fact_scan import FactScanPage
    from relf_agent.types import InvocationContext

    class InvalidSource(InMemoryMemory):
        def scan_facts(self, scope, namespace, query):
            if failure == "scan-error":
                raise ValidationError("Selected scan schema invalid")
            if failure == "scan-page":
                return FactScanPage([], None, 2, 0, self.fact_snapshot(scope, namespace), False)
            return super().scan_facts(scope, namespace, query)

        def validate_facts(self, scope, namespace, items):
            if failure == "validation-error":
                raise ValidationError("Selected Facts schema invalid")
            return super().validate_facts(scope, namespace, items)

        def inspect_fact(self, scope, namespace, key):
            if failure == "inspect-error":
                raise ValidationError("Selected inspection schema invalid")
            return super().inspect_fact(scope, namespace, key)

    async def run():
        backend, vector, metadata = (
            InvalidSource(),
            InMemoryVectorIndex(dimensions=16),
            InMemoryMemory(),
        )
        catalog = FactIndexCatalog(metadata)
        index = api().GenerationIndexedMemoryStore(
            backend,
            HashEmbeddingProvider(dimensions=16),
            vector,
            catalog,
            scope=SCOPE,
            namespace=NAMESPACE,
        )
        source = FactIndexMaintenanceToolSource(
            index, version="invalid-source", scope=SCOPE, namespace=NAMESPACE, max_pages=1
        )
        context = InvocationContext(SCOPE, "run", "action", "attempt", "effect", "epoch")
        try:
            backend.put_fact(SCOPE, NAMESPACE, "one", "valid", expected_version=0)
            snapshot = await index.source_snapshot(SCOPE, NAMESPACE)
            with pytest.raises(ValidationError) as caught:
                await source.call_tool(
                    (await source.list_tools())[0], {"effect_key": "effect"}, context
                )
            assert type(caught.value) is ValidationError
            assert await index.source_snapshot(SCOPE, NAMESPACE) == snapshot
            assert await source.query_refresh(SCOPE, "effect") is None
            revision, record = await catalog.load(
                SCOPE, source._address, "effect:" + digest("effect")
            )
            assert (
                revision == 1
                and record["receipt"] is None
                and record["source_snapshot"] == snapshot
            )
            assert index._expected.get() is None
        finally:
            await source.aclose(wait_timeout=2)
            assert source._owner._execution.active_count == 0
            for port in (vector, metadata, backend):
                port.close()

    asyncio.run(run())


def test_native_async_custom_source_scan_still_uses_original_bounded_protocol():
    class AsyncScan(InMemoryMemory):
        async def scan_facts(self, scope, namespace, query):
            await asyncio.sleep(0)
            return super().scan_facts(scope, namespace, query)

    async def run():
        backend, vector, metadata = (
            AsyncScan(),
            InMemoryVectorIndex(dimensions=16),
            InMemoryMemory(),
        )
        index = api().GenerationIndexedMemoryStore(
            backend,
            HashEmbeddingProvider(dimensions=16),
            vector,
            FactIndexCatalog(metadata),
            scope=SCOPE,
            namespace=NAMESPACE,
            batch_size=1,
        )
        try:
            backend.put_fact(SCOPE, NAMESPACE, "one", "native async", expected_version=0)
            snapshot = await index.source_snapshot(SCOPE, NAMESPACE)
            ready = await index.rebuild_for_snapshot(SCOPE, NAMESPACE, snapshot, max_pages=1)
            assert ready["status"] == "ready" and ready["scanned"] == 1
            assert (await index.recall(SCOPE, NAMESPACE, RecallQuery(text="native async"))).items[
                0
            ]["value"] == "native async"
        finally:
            for port in (vector, metadata, backend):
                port.close()

    asyncio.run(run())
