import asyncio
import copy
import gc
import sqlite3
import weakref

import pytest

import relf_agent as r
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.runtime_lifecycle import BuildContext


def factories():
    from relf_agent import fact_index_maintenance_factories

    return fact_index_maintenance_factories


def config():
    return {
        "resource_id": "preferences-index",
        "namespace": "preferences",
        "scope": {"workspace": "default", "principal": "local-owner"},
        "backend": {"adapter": "sqlite", "config": {"path": "facts.sqlite"}},
        "embedding": {"adapter": "hash", "config": {"dimensions": 8}},
        "index": {"adapter": "sqlite", "config": {"path": "vectors.sqlite", "dimensions": 8}},
        "catalog": {
            "adapter": "memory-cas",
            "config": {"backend": {"adapter": "sqlite", "config": {"path": "catalog.sqlite"}}},
        },
    }


def profile(components):
    return r.RuntimeProfile(
        "maintenance", "1", {"default": {"adapter": "offline-echo"}}, components
    )


def test_native_paired_factories_share_one_index_and_original_owned_resources(tmp_path):
    async def run():
        f = factories()
        registry = r.ComponentRegistry()
        old = dict(registry._factories)
        f.register_fact_index_maintenance(registry)
        f.register_fact_index_maintenance(registry)
        assert all(registry._factories[key] is entry for key, entry in old.items())
        components = f.fact_index_maintenance_components(config())
        built = await r.RuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile(components), tmp_path / "runs.sqlite"
        )
        context = built._context
        resources = [entry.resource for entry in context._resources]
        index = built.memory
        source = resources[-1]
        assert source._index is index
        assert resources[:-1] == [index.backend, index.index, index.original_catalog.backend]
        assert built.tools.get("facts_index_ensure_current").spec.effect == "idempotent_write"
        assert built.tools.get("facts_index_ensure_current").spec.requires_approval is False
        index.put_fact(r.Scope(), "preferences", "tea", "green tea", expected_version=0)
        ref_factory, ref_config = registry.prepare("memory_store", components["memory_store"])
        assert await ref_factory(ref_config, context) is index
        assert len(context._resources) == 4
        # Actual original context does not survive registry closure after drain.
        context_ref = weakref.ref(context)
        await built.aclose()
        assert context._resources == []
        for native in resources[:-1]:
            with pytest.raises(sqlite3.ProgrammingError):
                native.store.conn.execute("SELECT 1")
        del built, context
        gc.collect()
        assert context_ref() is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "drift_window", ["before-close", "during-close-then-retry", "during-successful-drain"]
)
def test_sdk_owner_close_binding_drift_retains_original_source_and_native_ports(
    tmp_path, monkeypatch, drift_window
):
    import json
    import os

    from relf_agent.embeddings import HashEmbeddingProvider
    from relf_agent.errors import CloseIncomplete
    from relf_agent.types import InvocationContext

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        original_embed = HashEmbeddingProvider.embed

        async def suspended_embed(self, texts):
            vectors = await original_embed(self, texts)
            entered.set()
            await release.wait()
            return vectors

        monkeypatch.setattr(HashEmbeddingProvider, "embed", suspended_embed)
        owner = await factories().create_fact_index_maintenance_owner(
            config(), base_dir=tmp_path, scope=r.Scope()
        )
        source, original_close, native = owner.source, owner.source.aclose, owner.native
        owner.index.put_fact(r.Scope(), "preferences", "tea", "green tea", expected_version=0)
        descriptor = (await source.list_tools())[0]
        context = InvocationContext(r.Scope(), "run", "action", "attempt", "effect", "epoch")
        consumer = asyncio.create_task(
            source.call_tool(descriptor, {"effect_key": "effect"}, context)
        )
        close_task = None
        replacement_calls = []

        async def replacement_close(*, wait_timeout=30):
            replacement_calls.append(wait_timeout)

        evidence = {"pid": os.getpid(), "drift_window": drift_window}
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if drift_window != "before-close":
                timeout = 2 if drift_window == "during-successful-drain" else 0.01
                close_task = asyncio.create_task(owner.aclose(wait_timeout=timeout))
                for _ in range(100):
                    if source._closing:
                        break
                    await asyncio.sleep(0)
                assert source._closing and not close_task.done()
            source.aclose = replacement_close
            refusal = None
            if drift_window == "during-successful-drain":
                release.set()
                try:
                    await close_task
                except DefinitionMismatch as error:
                    refusal = error
            else:
                if close_task is not None:
                    with pytest.raises(CloseIncomplete):
                        await close_task
                try:
                    await owner.aclose(wait_timeout=0.01)
                except DefinitionMismatch as error:
                    refusal = error
            states = []
            for port in native:
                try:
                    port.store.conn.execute("SELECT 1")
                    states.append("open")
                except sqlite3.ProgrammingError:
                    states.append("closed")
            evidence.update(
                refusal=type(refusal).__name__ if refusal is not None else None,
                owner_closed=owner.closed,
                source_closed=source._closed,
                original_active=source._owner_ref._execution.active_count,
                databases=states,
                replacement_calls=replacement_calls,
            )
            (tmp_path / "close-binding-evidence.json").write_text(json.dumps(evidence, indent=2))
            assert states == ["open"] * 3 and not owner.closed
            assert isinstance(refusal, DefinitionMismatch) and refusal.maintenance_owner is owner
            assert not replacement_calls
            if drift_window != "during-successful-drain":
                assert not source._closed and source._owner_ref._execution.active_count == 1
        finally:
            source.aclose = original_close
            release.set()
            outcome = await asyncio.gather(consumer, return_exceptions=True)
            if close_task is not None:
                await asyncio.gather(close_task, return_exceptions=True)
            await owner.aclose(wait_timeout=2)
            fallback_drain = not source._closed
            if fallback_drain:
                # RED still reaps the handler when the broken owner falsely reports closed.
                await original_close(wait_timeout=2)
            # Safe restoration retries the same owner; it closes only after original drain.
            assert owner.closed and source._closed and owner.native == ()
            for port in native:
                with pytest.raises(sqlite3.ProgrammingError):
                    port.store.conn.execute("SELECT 1")
            assert source._owner_ref._execution.active_count == 0
            assert len(asyncio.all_tasks()) == 1
            evidence["cleanup"] = {
                "active_handlers": 0,
                "active_tasks": 0,
                "connections_closed": 3,
                "consumer_outcome": type(outcome[0]).__name__,
                "fallback_drain": fallback_drain,
            }
            (tmp_path / "close-binding-evidence.json").write_text(json.dumps(evidence, indent=2))

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(resource_id=""),
        lambda c: c.update(namespace=""),
        lambda c: c.update(scope={"workspace": "", "principal": "local-owner"}),
        lambda c: c["backend"].update(adapter="postgres"),
        lambda c: c["embedding"].update(adapter="http"),
        lambda c: c["index"].update(adapter="qdrant"),
        lambda c: c["catalog"]["config"]["backend"].update(adapter="redis"),
        lambda c: c["backend"]["config"].update(path="https://invalid.test/facts"),
        lambda c: c["index"]["config"].update(path="facts.sqlite"),
        lambda c: c["embedding"]["config"].update(dimensions=True),
        lambda c: c["index"]["config"].update(dimensions=9),
        lambda c: c.update(batch_size=0),
        lambda c: c.update(max_page_bytes=64001),
        lambda c: c.update(max_records=100001),
        lambda c: c.update(max_pages=257),
        lambda c: c.update(min_score=float("nan")),
    ],
)
def test_invalid_native_declarations_refuse_before_execution_or_data_allocation(tmp_path, mutate):
    f = factories()
    registry = r.ComponentRegistry()
    f.register_fact_index_maintenance(registry)
    c = config()
    mutate(c)
    # Raw declarations demonstrate validator preflight independently of helper.
    with pytest.raises(ValidationError):
        selected = profile(
            {
                "tools": {"adapter": "facts-index-maintenance", "config": c},
                "memory_store": {"adapter": "maintained-index-reference", "config": c},
            }
        )
        asyncio.run(
            r.RuntimeBuilder(registry, base_dir=tmp_path).abuild(selected, tmp_path / "runs.sqlite")
        )
    assert list(tmp_path.iterdir()) == []


def test_sync_builder_refuses_async_factory_before_any_allocation(tmp_path):
    f = factories()
    registry = r.ComponentRegistry()
    f.register_fact_index_maintenance(registry)
    builder = r.RuntimeBuilder(registry, base_dir=tmp_path)
    with pytest.raises(ValidationError, match="abuild"):
        builder.build(
            profile(f.fact_index_maintenance_components(config())), tmp_path / "runs.sqlite"
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("allow_async,store_none", [(False, False), (True, True)])
def test_factory_refuses_nonlocal_or_sync_context_before_data_io(tmp_path, allow_async, store_none):
    async def run():
        f = factories()
        registry = r.ComponentRegistry()
        f.register_fact_index_maintenance(registry)
        declaration = f.fact_index_maintenance_components(config())["tools"]
        factory, options = registry.prepare("tools", declaration)
        authority = None if store_none else r.SQLiteStore(tmp_path / "runs.sqlite")
        context = BuildContext(
            authority, tmp_path / "runs.sqlite", r.Scope(), tmp_path, allow_async=allow_async
        )
        try:
            with pytest.raises(ValidationError):
                await factory(options, context)
            assert context._resources == []
            assert not (tmp_path / "facts.sqlite").exists()
        finally:
            if authority is not None:
                authority.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value", [("resource_id", "other"), ("namespace", "other"), ("batch_size", 1)]
)
def test_reference_refuses_different_selection_without_allocating_another_index(
    tmp_path, field, value
):
    async def run():
        f = factories()
        registry = r.ComponentRegistry()
        f.register_fact_index_maintenance(registry)
        pairs = f.fact_index_maintenance_components(config())
        built = await r.RuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile(pairs), tmp_path / "runs.sqlite"
        )
        try:
            c = copy.deepcopy(pairs["memory_store"]["config"])
            c[field] = value
            factory, options = registry.prepare(
                "memory_store", {"adapter": "maintained-index-reference", "config": c}
            )
            with pytest.raises((ValidationError, DefinitionMismatch)):
                await factory(options, built._context)
            assert len(built._context._resources) == 4
        finally:
            await built.aclose()

    asyncio.run(run())


def test_graph_helper_fixes_namespace_and_refresh_before_reader():
    f = factories()
    flow = f.maintained_agent_workflow(r.AgentSpec("preferences", "Read current Facts"), config())
    assert flow.max_concurrency == 1
    assert flow.nodes[0].tool == "facts_index_ensure_current"
    assert flow.nodes[0].input == r.Literal({})
    assert flow.nodes[0].output_schema["properties"]["status"] == {"const": "ready"}
    assert flow.nodes[1].depends_on == (flow.nodes[0].id,)
    assert flow.to_dict()["output"]["source"] == "reader"
    with pytest.raises(ValidationError):
        f.maintained_agent_workflow(r.AgentSpec("wrong", "Read"), config())


def test_explicit_borrowed_owner_remains_live_until_caller_closes_it(tmp_path):
    async def run():
        f = factories()
        owner = await f.create_fact_index_maintenance_owner(
            config(), base_dir=tmp_path, scope=r.Scope()
        )
        registry = r.ComponentRegistry()
        f.register_fact_index_maintenance(registry, borrowed=owner)
        built = await r.RuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile(f.fact_index_maintenance_components(config(), borrowed=True)),
            tmp_path / "runs.sqlite",
        )
        assert built.memory is owner.index
        assert built._context._resources == []
        await built.aclose()
        assert owner.index.backend.store.conn.execute("SELECT 1").fetchone()[0] == 1
        await owner.aclose()
        assert owner.closed
        assert owner.source._owner._execution.active_count == 0
        with pytest.raises(sqlite3.ProgrammingError):
            owner.index.backend.store.conn.execute("SELECT 1")

    asyncio.run(run())


@pytest.mark.parametrize("borrowed", [False, True])
def test_actual_cancelled_handler_keeps_native_connections_until_original_owner_retry(
    tmp_path, monkeypatch, borrowed
):
    import json

    import relf_agent.fact_index_maintenance_tools as tool_module
    from relf_agent.embeddings import HashEmbeddingProvider
    from relf_agent.errors import CloseIncomplete
    from relf_agent.types import InvocationContext

    async def run():
        f = factories()
        entered, release = asyncio.Event(), asyncio.Event()
        original_embed = HashEmbeddingProvider.embed
        original_close = tool_module.FactIndexMaintenanceToolSource.aclose

        async def suspended_embed(self, texts):
            vectors = await original_embed(self, texts)
            entered.set()
            await release.wait()
            return vectors

        async def bounded_close(self, *, wait_timeout=0.01):
            return await original_close(self, wait_timeout=wait_timeout)

        monkeypatch.setattr(HashEmbeddingProvider, "embed", suspended_embed)
        monkeypatch.setattr(tool_module.FactIndexMaintenanceToolSource, "aclose", bounded_close)
        owner = (
            await f.create_fact_index_maintenance_owner(
                config(), base_dir=tmp_path, scope=r.Scope()
            )
            if borrowed
            else None
        )
        registry = r.ComponentRegistry()
        f.register_fact_index_maintenance(registry, borrowed=owner)
        built = await r.RuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile(f.fact_index_maintenance_components(config(), borrowed=borrowed)),
            tmp_path / "runs.sqlite",
        )
        index = built.memory
        source = owner.source if borrowed else built._context._resources[-1].resource
        native = [index.backend, index.index, index.original_catalog.backend]
        index.put_fact(r.Scope(), "preferences", "tea", "green tea", expected_version=0)
        context = InvocationContext(
            r.Scope(), "actual-run", "actual-action", "attempt-1", "actual-key", "epoch-1"
        )
        consumer = asyncio.create_task(
            built.tools.get("facts_index_ensure_current").handler({}, context)
        )
        await asyncio.wait_for(entered.wait(), 2)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        assert source._owner._execution.active_count == 1
        if borrowed:
            await built.aclose()
            with pytest.raises(CloseIncomplete):
                await owner.aclose(wait_timeout=0.01)
        else:
            with pytest.raises(CloseIncomplete):
                await built.aclose()
            assert built._context._resources[-1].resource is source
        for port in native:
            assert port.store.conn.execute("SELECT 1").fetchone()[0] == 1
        assert not source._closed
        release.set()
        assert await source._owner.wait(wait_timeout=2)
        original_receipt = await source.query_refresh(r.Scope(), "actual-key")
        assert original_receipt["status"] == "ready"
        if borrowed:
            await owner.aclose(wait_timeout=2)
        else:
            await built.aclose()
        assert source._closed and source._owner._execution.active_count == 0
        assert built._context._resources == []
        for port in native:
            with pytest.raises(sqlite3.ProgrammingError):
                port.store.conn.execute("SELECT 1")
        assert len(asyncio.all_tasks()) == 1
        (tmp_path / "owner-closure.json").write_text(
            json.dumps(
                {
                    "borrowed": borrowed,
                    "original_receipt": original_receipt,
                    "source_closed": source._closed,
                    "active_handlers": 0,
                    "active_tasks": 0,
                    "runtime_resources": 0,
                    "connections_closed": 3,
                }
            )
        )

    asyncio.run(run())


def test_borrowed_construction_close_error_retains_original_owner_for_retry(tmp_path, monkeypatch):
    from relf_agent.memory import SQLiteMemory
    from relf_agent.vector import SQLiteVectorIndex

    f = factories()
    vector = SQLiteVectorIndex(tmp_path / "vectors.sqlite", dimensions=9)
    vector.close()
    original_close = SQLiteMemory.close
    failures = []

    def fail_once(self):
        if not failures:
            failures.append(self)
            raise OSError("actual native source close failed")
        return original_close(self)

    monkeypatch.setattr(SQLiteMemory, "close", fail_once)

    async def run():
        with pytest.raises(OSError) as caught:
            await f.create_fact_index_maintenance_owner(
                config(), base_dir=tmp_path, scope=r.Scope()
            )
        assert isinstance(caught.value.__cause__, ValidationError)
        owner = caught.value.maintenance_owner
        assert owner.native == tuple(failures)
        assert owner.native[0].store.conn.execute("SELECT 1").fetchone()[0] == 1
        await owner.aclose()
        assert owner.closed and owner.native == ()

    asyncio.run(run())


def test_borrowed_owner_refuses_other_loop_before_closing_original_native_resources(tmp_path):
    async def run():
        f = factories()
        owner = await f.create_fact_index_maintenance_owner(
            config(), base_dir=tmp_path, scope=r.Scope()
        )

        def foreign_loop():
            with pytest.raises(ValidationError):
                asyncio.run(owner.aclose())

        await asyncio.to_thread(foreign_loop)
        assert owner.index.backend.store.conn.execute("SELECT 1").fetchone()[0] == 1
        assert not owner.closed
        await owner.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("drift_window", ["before-close", "during-close-then-retry"])
def test_sdk_owner_source_drift_keeps_original_handler_and_databases_until_actual_drain(
    tmp_path, monkeypatch, drift_window
):
    import json
    import os

    from relf_agent.embeddings import HashEmbeddingProvider
    from relf_agent.errors import CloseIncomplete
    from relf_agent.tool_sources import ToolPolicy, register_tool_source
    from relf_agent.tools import ToolRegistry
    from relf_agent.types import InvocationContext

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        original_embed = HashEmbeddingProvider.embed

        async def suspended_embed(self, texts):
            vectors = await original_embed(self, texts)
            entered.set()
            await release.wait()
            return vectors

        monkeypatch.setattr(HashEmbeddingProvider, "embed", suspended_embed)
        owner = await factories().create_fact_index_maintenance_owner(
            config(), base_dir=tmp_path, scope=r.Scope()
        )
        source = owner.source
        original_index = owner.index
        native = [
            original_index.backend,
            original_index.index,
            original_index.original_catalog.backend,
        ]
        original_index.put_fact(r.Scope(), "preferences", "tea", "green tea", expected_version=0)
        registry = ToolRegistry()
        await register_tool_source(
            registry,
            source,
            policies={
                "facts_index_ensure_current": ToolPolicy(
                    "1",
                    effect="idempotent_write",
                    requires_approval=False,
                    effect_key_argument="effect_key",
                    reconciler=source.reconcile,
                )
            },
        )
        context = InvocationContext(
            r.Scope(),
            "original-run",
            "original-action",
            "original-attempt",
            "original-key",
            "epoch-1",
        )
        consumer = asyncio.create_task(
            registry.get("facts_index_ensure_current").handler({}, context)
        )
        close_task = None
        evidence = {
            "pid": os.getpid(),
            "drift_window": drift_window,
            "source_id": id(source),
            "owner_id": id(owner),
        }
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if drift_window == "during-close-then-retry":
                close_task = asyncio.create_task(owner.aclose(wait_timeout=0.01))
                # Actual original close has entered its drain while the handler remains gated.
                for _ in range(100):
                    if source._closing:
                        break
                    await asyncio.sleep(0)
                assert source._closing and not close_task.done()
            owner.source = None
            if close_task is not None:
                with pytest.raises((CloseIncomplete, DefinitionMismatch)):
                    await close_task
            refusal = None
            try:
                await owner.aclose(wait_timeout=0.01)
            except (CloseIncomplete, DefinitionMismatch) as error:
                refusal = type(error).__name__
            states = []
            for port in native:
                try:
                    port.store.conn.execute("SELECT 1")
                    states.append("open")
                except sqlite3.ProgrammingError:
                    states.append("closed")
            evidence.update(
                refusal=refusal,
                source_closed=source._closed,
                sdk_owner_closed=owner.closed,
                original_active=source._owner._execution.active_count,
                consumer_done=consumer.done(),
                databases=states,
            )
            (tmp_path / "source-drift-evidence.json").write_text(json.dumps(evidence, indent=2))
            assert states == ["open", "open", "open"]
            assert source._owner._execution.active_count == 1 and not source._closed
            assert owner.closed is False
        finally:
            # RED reproductions also release/drain the real original handler and close all ports.
            owner.source = source
            release.set()
            await asyncio.gather(consumer, return_exceptions=True)
            if close_task is not None:
                await asyncio.gather(close_task, return_exceptions=True)
            assert await source._owner.wait(wait_timeout=2)
            await source.aclose(wait_timeout=2)
            await owner.aclose(wait_timeout=2)
            for port in native:
                port.close()
            assert source._owner._execution.active_count == 0
            assert len(asyncio.all_tasks()) == 1
            evidence["cleanup"] = {
                "active_handlers": 0,
                "active_tasks": 0,
                "databases": ["closed"] * 3,
            }
            (tmp_path / "source-drift-evidence.json").write_text(json.dumps(evidence, indent=2))

    asyncio.run(run())
