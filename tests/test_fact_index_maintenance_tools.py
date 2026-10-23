"""Actual native Facts maintenance journal and original Graph authority checks."""

import asyncio
import importlib
import json
import sqlite3
from dataclasses import asdict, replace

import pytest

from relf_agent import (
    FactIndexCatalog,
    GraphNode,
    GraphWorkflowSpec,
    Literal,
    LocalEngine,
    RecallQuery,
    Scope,
    SQLiteStore,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
    ValueRef,
    register_tool_source,
)
from relf_agent.embeddings import HashEmbeddingProvider
from relf_agent.errors import (
    AuthorizationDenied,
    BudgetExceeded,
    CloseIncomplete,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from relf_agent.fact_index_generation import GenerationIndexedMemoryStore
from relf_agent.memory import SQLiteMemory
from relf_agent.temporal_context_execution import ContextExecutionOwner
from relf_agent.tool_execution import ToolExecutionOwner
from relf_agent.types import InvocationContext, digest
from relf_agent.vector import SQLiteVectorIndex

SCOPE = Scope("private-index-tools", "author")
NS = "facts"
NAME = "facts_index_ensure_current"


class GateHash(HashEmbeddingProvider):
    def __init__(self):
        super().__init__(dimensions=16)
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.pause = False

    async def embed(self, texts):
        self.calls += 1
        value = await super().embed(texts)
        if self.pause:
            self.entered.set()
            await self.release.wait()
        return value


class Ports:
    def __init__(self, root, *, pages=1, max_records=100000):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.backend = SQLiteMemory(root / "source.sqlite")
        self.vector = SQLiteVectorIndex(root / "vector.sqlite", dimensions=16)
        self.metadata = SQLiteMemory(root / "catalog.sqlite")
        self.embedding = GateHash()
        self.catalog = FactIndexCatalog(self.metadata)
        self.index = GenerationIndexedMemoryStore(
            self.backend,
            self.embedding,
            self.vector,
            self.catalog,
            scope=SCOPE,
            namespace=NS,
            batch_size=2,
            max_records=max_records,
        )
        self.source = None
        self.pages = pages

    def prepare(self):
        module = importlib.import_module("relf_agent.fact_index_maintenance_tools")
        self.source = module.FactIndexMaintenanceToolSource(
            self.index,
            version="private-1",
            scope=SCOPE,
            namespace=NS,
            max_pages=self.pages,
        )
        return self.source

    def seed(self, n=5):
        for i in range(n):
            self.backend.put_fact(SCOPE, NS, str(i), "violet target " + str(i), expected_version=0)

    async def registry(self):
        source = self.prepare()
        registry = ToolRegistry()
        await register_tool_source(
            registry,
            source,
            policies={
                NAME: ToolPolicy(
                    "private-1",
                    effect="idempotent_write",
                    requires_approval=False,
                    effect_key_argument="effect_key",
                    reconciler=source.reconcile,
                )
            },
        )
        return registry

    async def capture(self, label, **extra):
        value = {
            "label": label,
            "source_snapshot": await self.index.source_snapshot(SCOPE, NS),
            "embedding_calls": self.embedding.calls,
            "source_rows": [
                dict(row)
                for row in self.backend.store.conn.execute(
                    "SELECT * FROM memory_facts ORDER BY namespace,key"
                )
            ],
            "catalog_rows": [
                dict(row)
                for row in self.metadata.store.conn.execute(
                    "SELECT * FROM memory_facts ORDER BY namespace,key"
                )
            ],
            "vector_rows": [
                dict(row)
                for row in self.vector.store.conn.execute(
                    "SELECT * FROM vector_entries ORDER BY namespace,document_id,chunk_id"
                )
            ],
            **extra,
        }
        (self.root / (label + ".json")).write_text(json.dumps(value, indent=2), encoding="utf-8")

    async def close(self):
        if self.source is not None:
            self.embedding.release.set()
            await self.source.aclose(wait_timeout=2)
            assert self.source._owner._execution.active_count == 0
        closed = []
        for name, port in (
            ("source", self.backend),
            ("vector", self.vector),
            ("catalog", self.metadata),
        ):
            port.close()
            with pytest.raises(sqlite3.ProgrammingError):
                port.store.conn.execute("SELECT 1")
            closed.append(name)
        (self.root / "closed.json").write_text(
            json.dumps(
                {
                    "connections_closed": closed,
                    "active_owner": 0,
                    "other_live_tasks": len(asyncio.all_tasks()) - 1,
                }
            ),
            encoding="utf-8",
        )


def ctx(key="effect-1", action="action-1"):
    return InvocationContext(SCOPE, "original-run", action, "attempt-1", key, "epoch-1")


def run_ports(tmp_path, operation, **options):
    async def run():
        ports = Ports(tmp_path, **options)
        try:
            await operation(ports)
        finally:
            await ports.close()

    asyncio.run(run())


def test_actual_partial_new_action_then_ready_and_historical_replay(tmp_path):
    async def run(p):
        p.seed()
        registry = await p.registry()
        tool = registry.get(NAME)
        first = await tool.handler({}, ctx())
        assert first["status"] == "partial" and first["coverage"]["scanned"] == 2
        assert await p.source.query_refresh(SCOPE, "effect-1") == first
        calls = p.embedding.calls
        replay = await tool.handler(
            {}, replace(ctx(), attempt_id="attempt-2", execution_epoch="epoch-2")
        )
        assert replay == first and p.embedding.calls == calls
        with pytest.raises(ValidationError):
            await p.index.recall(SCOPE, NS, RecallQuery(text="violet target"))
        second = await tool.handler({}, ctx("effect-2", "action-2"))
        assert second["status"] == "partial" and second["coverage"]["scanned"] == 4
        third = await tool.handler({}, ctx("effect-3", "action-3"))
        assert third["status"] == "ready" and third["coverage"]["indexed"] == 5
        assert third["build_id"] == first["build_id"]
        old = await p.index.recall(SCOPE, NS, RecallQuery(text="violet target", max_items=1))
        assert old.items
        p.index.put_fact(SCOPE, NS, "0", "amber repaired", expected_version=1)
        calls = p.embedding.calls
        assert await tool.handler({}, ctx("effect-3", "action-3")) == third
        assert await tool.reconciler({}, ctx("effect-3", "action-3")) == third
        assert p.embedding.calls == calls
        with pytest.raises(ValidationError):
            await p.index.validate_facts(SCOPE, NS, old.items)
        repaired = await tool.handler({}, ctx("effect-4", "action-4"))
        assert repaired["status"] == "partial" and repaired["build_id"] != third["build_id"]
        assert await p.source.query_refresh(SCOPE, "effect-3") == third
        await p.capture("partial-ready-update", first=first, ready=third, repaired=repaired)
        assert tool.spec.effect == "idempotent_write" and tool.reconciler is not None
        assert set(tool.spec.input_schema["properties"]) == set()
        with pytest.raises(ValidationError):
            await tool.handler({"effect_key": "forged"}, ctx())

    run_ports(tmp_path, run)


def test_original_key_cannot_substitute_run_action_or_trusted_scope(tmp_path):
    async def run(p):
        p.seed(1)
        tool = (await p.registry()).get(NAME)
        receipt = await tool.handler({}, ctx())
        for changed in (
            replace(ctx(), run_id="another-run"),
            replace(ctx(), action_id="another-action"),
        ):
            with pytest.raises(IdempotencyConflict):
                await tool.handler({}, changed)
            with pytest.raises(IdempotencyConflict):
                await tool.reconciler({}, changed)
        with pytest.raises(AuthorizationDenied):
            await tool.handler({}, replace(ctx(), scope=Scope("foreign", "author")))
        with pytest.raises(AuthorizationDenied):
            await p.source.query_refresh(Scope("foreign", "author"), "effect-1")
        assert await p.source.query_refresh(SCOPE, "effect-1") == receipt
        assert p.embedding.calls == 1

    run_ports(tmp_path, run)


@pytest.mark.parametrize(
    "policy",
    [
        {"effect": "read_only"},
        {"effect": "idempotent_write", "effect_key_argument": "wrong"},
        {"effect": "idempotent_write", "effect_key_argument": "effect_key"},
    ],
)
def test_registration_requires_exact_original_idempotent_reconciler(tmp_path, policy):
    async def run(p):
        source = p.prepare()
        with pytest.raises(ValidationError):
            await register_tool_source(
                ToolRegistry(), source, policies={NAME: ToolPolicy("1", **policy)}
            )

    run_ports(tmp_path, run)


def test_cancelled_consumer_close_incomplete_retains_actual_handler_and_backends(tmp_path):
    async def run(p):
        p.seed(1)
        tool = (await p.registry()).get(NAME)
        p.embedding.pause = True
        task = asyncio.create_task(tool.handler({}, ctx()))
        await asyncio.wait_for(p.embedding.entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert p.source._owner._execution.active_count == 1
        assert await p.source.query_refresh(SCOPE, "effect-1") is None
        with pytest.raises(CloseIncomplete):
            await p.source.aclose(wait_timeout=0)
        for port in (p.backend, p.vector, p.metadata):
            assert port.store.conn.execute("SELECT 1").fetchone()[0] == 1
        assert p.source._owner._execution.active_count == 1
        p.embedding.release.set()
        assert await p.source._owner.wait(wait_timeout=2)
        receipt = await p.source.query_refresh(SCOPE, "effect-1")
        assert receipt["status"] == "ready"
        await p.capture("cancelled-owner-finished", receipt=receipt, owner_count=0)
        await p.source.aclose(wait_timeout=2)

    run_ports(tmp_path, run)


@pytest.mark.parametrize("during_close", [False, True])
@pytest.mark.parametrize("selected", ["owner", "execution", "guard"])
def test_close_owner_reference_drift_keeps_original_handler_owned(tmp_path, during_close, selected):
    async def run(p):
        p.seed(1)
        tool = (await p.registry()).get(NAME)
        source = p.source
        original_owner = source._owner
        original_execution = original_owner._execution
        original_guard = source._check_execution_owner
        source_identity = source.identity
        replacement = (
            ToolExecutionOwner(version="private-1", max_calls=1)
            if selected == "owner"
            else ContextExecutionOwner(max_calls=1)
        )
        if selected == "owner":
            assert replacement.identity == original_owner.identity
        p.embedding.pause = True
        consumer = asyncio.create_task(tool.handler({}, ctx()))
        first_close = None
        await asyncio.wait_for(p.embedding.entered.wait(), 2)
        try:
            if during_close:
                first_close = asyncio.create_task(source.aclose(wait_timeout=2))
                await asyncio.sleep(0)
                assert source._closing and not first_close.done()
            if selected == "owner":
                source._owner = replacement
            else:
                original_owner._execution = replacement
                if selected == "guard":
                    source._check_execution_owner = lambda: None
            try:
                identity_equal = source.identity == source_identity
            except DefinitionMismatch:
                identity_equal = False
            refusal = None
            try:
                await source.aclose(wait_timeout=0)
            except (CloseIncomplete, DefinitionMismatch) as exc:
                refusal = type(exc).__name__
            observed = {
                "during_original_close": during_close,
                "selected_reference": selected,
                "source_identity_equal": identity_equal,
                "refusal": refusal,
                "source_closed": source._closed,
                "original_active": original_execution.active_count,
                "replacement_active": (
                    replacement._execution.active_count
                    if selected == "owner"
                    else replacement.active_count
                ),
                "consumer_done": consumer.done(),
                "first_close_done": None if first_close is None else first_close.done(),
                "native_connections_open": [
                    port.store.conn.execute("SELECT 1").fetchone()[0] == 1
                    for port in (p.backend, p.vector, p.metadata)
                ],
            }
            await p.capture("owner-reference-drift-before-handler-end", observed=observed)
            assert refusal is not None, "Close returned through the empty substitute owner"
            assert not source._closed and original_execution.active_count == 1
            assert not consumer.done() and all(observed["native_connections_open"])
            if first_close is not None:
                assert not first_close.done()
        finally:
            # Host retains the original owner/backends even when the product's
            # close result is wrong. End the real handler before any connection.
            source._owner = original_owner
            original_owner._execution = original_execution
            source._check_execution_owner = original_guard
            p.embedding.release.set()
            receipt = await consumer
            assert receipt["status"] == "ready" and receipt["effect_key"] == ctx().effect_key
            assert await original_owner.wait(wait_timeout=2)
            if first_close is not None:
                try:
                    await first_close
                except (CloseIncomplete, DefinitionMismatch):
                    pass
            await original_owner.aclose(wait_timeout=2)
            await replacement.aclose(wait_timeout=2)
            assert original_execution.active_count == 0
            assert await source.query_refresh(SCOPE, ctx().effect_key) == receipt
            await p.capture(
                "owner-reference-drift-actual-handler-ended",
                receipt=receipt,
                original_active=0,
                consumer_done=consumer.done(),
                replacement_active=0,
            )

    run_ports(tmp_path, run)


def test_actual_source_change_during_embed_terminal_receipt_stays_historical(tmp_path):
    async def run(p):
        p.seed(1)
        tool = (await p.registry()).get(NAME)
        p.embedding.pause = True
        task = asyncio.create_task(tool.handler({}, ctx()))
        await asyncio.wait_for(p.embedding.entered.wait(), 2)
        p.backend.put_fact(SCOPE, NS, "0", "amber changed", expected_version=1)
        p.embedding.release.set()
        receipt = await task
        assert receipt["status"] == "source_changed"
        assert await tool.reconciler({}, ctx()) == receipt
        assert await tool.handler({}, ctx()) == receipt
        with pytest.raises(ValidationError):
            await p.index.recall(SCOPE, NS, RecallQuery(text="amber changed"))
        repair = await tool.handler({}, ctx("effect-2", "action-2"))
        assert repair["status"] == "ready" and repair["build_id"] != receipt["build_id"]
        await p.capture("source-change-historical", receipt=receipt, repaired=repair)

    run_ports(tmp_path, run)


@pytest.mark.parametrize(
    "target,method",
    [("index", "rebuild_for_snapshot"), ("catalog", "save"), ("backend", "fact_snapshot")],
)
def test_method_or_source_drift_rejected_before_effects(tmp_path, target, method):
    async def run(p):
        p.seed(1)
        tool = (await p.registry()).get(NAME)
        obj = getattr(p, target)
        original = getattr(obj, method)
        if asyncio.iscoroutinefunction(original):

            async def changed(*args, **kwargs):
                return await original(*args, **kwargs)
        else:

            def changed(*args, **kwargs):
                return original(*args, **kwargs)

        setattr(obj, method, changed)
        try:
            with pytest.raises(DefinitionMismatch):
                await tool.handler({}, ctx())
            assert p.embedding.calls == 0
            assert not p.vector.store.conn.execute("SELECT * FROM vector_entries").fetchall()
            assert not p.metadata.store.conn.execute("SELECT * FROM memory_facts").fetchall()
        finally:
            setattr(obj, method, original)

    run_ports(tmp_path, run)


def test_equal_substitute_reconciler_receiver_is_not_original(tmp_path):
    async def run(p):
        source = p.prepare()

        class Equal:
            __hash__ = None

            def __eq__(self, other):
                raise AssertionError("supplier receiver equality is not binding identity")

        substitute = Equal()
        method = source.reconcile.__func__.__get__(substitute, Equal)
        with pytest.raises(ValidationError):
            await register_tool_source(
                ToolRegistry(),
                source,
                policies={
                    NAME: ToolPolicy(
                        "1",
                        effect="idempotent_write",
                        effect_key_argument="effect_key",
                        reconciler=method,
                    )
                },
            )

    run_ports(tmp_path, run)


def test_actual_same_generation_cas_competitor_does_not_complete_original_effect(tmp_path):
    async def run(p):
        p.seed(1)
        first = (await p.registry()).get(NAME)
        module = importlib.import_module("relf_agent.fact_index_maintenance_tools")
        other_source = module.FactIndexMaintenanceToolSource(
            p.index,
            version="private-1",
            scope=SCOPE,
            namespace=NS,
            max_pages=1,
        )
        other_registry = ToolRegistry()
        await register_tool_source(
            other_registry,
            other_source,
            policies={
                NAME: ToolPolicy(
                    "private-1",
                    effect="idempotent_write",
                    requires_approval=False,
                    effect_key_argument="effect_key",
                    reconciler=other_source.reconcile,
                )
            },
        )
        p.embedding.pause = True
        task = asyncio.create_task(first.handler({}, ctx()))
        try:
            await asyncio.wait_for(p.embedding.entered.wait(), 2)
            p.embedding.pause = False
            competitor = await other_registry.get(NAME).handler({}, ctx("effect-2", "action-2"))
            assert competitor["status"] == "ready"
            p.embedding.release.set()
            with pytest.raises(ValidationError):
                await task
            assert await p.source.query_refresh(SCOPE, "effect-1") is None
            assert await first.reconciler({}, ctx()) is None
            assert await other_source.query_refresh(SCOPE, "effect-2") == competitor
            revision, original_intent = await p.catalog.load(
                SCOPE,
                p.source.identity["index_address"],
                "effect:" + digest("effect-1"),
            )
            assert revision == 1 and original_intent["receipt"] is None
            assert original_intent["request"]["action_id"] == "action-1"
            # Metadata is actually ready through the competing original effect,
            # but it cannot be attributed to this refused original effect.
            page = await p.index.recall(SCOPE, NS, RecallQuery(text="violet target"))
            assert page.items
            await p.capture(
                "same-generation-cas-refusal",
                competitor=competitor,
                original_intent=original_intent,
                refused_effect_query=None,
            )
        finally:
            p.embedding.release.set()
            await other_source.aclose(wait_timeout=2)
            if not task.done():
                await task

    run_ports(tmp_path, run)


def test_original_record_budget_refusal_retains_pending_without_partial_receipt(tmp_path):
    async def run(p):
        p.seed()
        tool = (await p.registry()).get(NAME)
        with pytest.raises(BudgetExceeded):
            await tool.handler({}, ctx())
        assert await tool.reconciler({}, ctx()) is None
        assert await p.source.query_refresh(SCOPE, "effect-1") is None
        with pytest.raises(ValidationError):
            await p.index.recall(SCOPE, NS, RecallQuery(text="violet target"))
        await p.capture("record-budget-refusal", query=None)

    run_ports(tmp_path, run, pages=3, max_records=3)


def test_source_method_drift_during_owned_call_refuses_completion_attribution(tmp_path):
    async def run(p):
        p.seed(1)
        tool = (await p.registry()).get(NAME)
        p.embedding.pause = True
        task = asyncio.create_task(tool.handler({}, ctx()))
        await asyncio.wait_for(p.embedding.entered.wait(), 2)
        original = p.catalog.save

        async def changed(*args, **kwargs):
            return await original(*args, **kwargs)

        p.catalog.save = changed
        try:
            p.embedding.release.set()
            with pytest.raises(DefinitionMismatch):
                await task
        finally:
            p.catalog.save = original
        assert await p.source.query_refresh(SCOPE, "effect-1") is None
        assert not p.vector.store.conn.execute("SELECT * FROM vector_entries").fetchall()
        await p.capture("inflight-method-drift", query=None)

    run_ports(tmp_path, run)


@pytest.mark.parametrize("pages", [0, 257, True])
def test_per_dispatch_page_bounds_refused_before_original_journal(tmp_path, pages):
    async def run(p):
        module = importlib.import_module("relf_agent.fact_index_maintenance_tools")
        with pytest.raises(ValidationError):
            module.FactIndexMaintenanceToolSource(
                p.index,
                version="private-1",
                scope=SCOPE,
                namespace=NS,
                max_pages=pages,
            )
        assert not p.metadata.store.conn.execute("SELECT * FROM memory_facts").fetchall()

    run_ports(tmp_path, run)


@pytest.mark.parametrize("records,expected", [(1, "succeeded"), (5, "failed")])
def test_original_graph_action_receipt_budget_and_ready_gate(tmp_path, records, expected):
    async def run(p):
        p.seed(records)
        registry = await p.registry()
        reads = []

        async def read(arguments, context):
            reads.append(context.action_id)
            return asdict(await p.index.recall(SCOPE, NS, RecallQuery(text="violet target")))

        registry.register(
            ToolSpec(
                "private_reader",
                "Read actual current native Facts index",
                {"type": "object"},
                effect="read_only",
                requires_approval=False,
            ),
            read,
        )
        module = importlib.import_module("relf_agent.fact_index_maintenance_tools")
        spec = GraphWorkflowSpec(
            "private-maintenance",
            [
                GraphNode(
                    "ensure", tool=NAME, input=Literal({}), output_schema=module.READY_ONLY_SCHEMA
                ),
                GraphNode(
                    "reader", tool="private_reader", depends_on=("ensure",), input=Literal({})
                ),
            ],
            output=ValueRef("reader"),
            max_concurrency=1,
        )
        with LocalEngine(
            SQLiteStore(p.root / "run.sqlite"), providers={}, tools=registry, scope=SCOPE
        ) as engine:
            handle = engine.submit(spec, "violet target", command_id="original-submit", budget=10)
            result = await engine.drive(handle.run_id)
            assert result.state == expected
            run = engine.store.run(handle.run_id)
            action = run["actions"][0]
            assert action["kind"] == "tool" and action["status"] == "completed"
            receipt = action["result"]
            assert receipt["run_id"] == handle.run_id and receipt["action_id"] == action["id"]
            assert await p.source.query_refresh(SCOPE, receipt["effect_key"]) == receipt
            assert receipt["status"] == ("ready" if records == 1 else "partial")
            assert len(reads) == (1 if records == 1 else 0)
            budget = engine.store.budget(handle.run_id)
            assert budget["held"] == 0 and budget["spent"] == (2 if records == 1 else 1)
            if records > 1:
                assert result.error["code"] == "validation_error" and len(run["actions"]) == 1
            before = p.embedding.calls
            assert await engine.drive(handle.run_id) == result
            assert p.embedding.calls == before
            await p.capture(
                "original-graph-authority",
                run=run,
                budget=budget,
                reader_calls=reads,
                events=[asdict(event) for event in engine.events(handle.run_id)],
            )

    run_ports(tmp_path, run)
