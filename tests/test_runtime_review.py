"""Narrow reproductions from the fresh runtime assembly review."""

import asyncio
import sqlite3
import sys
import types

import pytest

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    LocalEngine,
    ModelResponse,
    ProfiledEngine,
    RuntimeBuilder,
    RuntimeCatalog,
    RuntimeProfile,
    Scope,
    SQLiteRunReader,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import AuthorizationDenied, IdempotencyConflict, ValidationError
from relf_agent.runtime_builder import EchoProvider


def catalog():
    selected = RuntimeCatalog()
    selected.register(
        RuntimeProfile("app", "1", {"default": {"adapter": "offline-echo"}}), default=True
    )
    return selected


def test_rejected_engine_without_close_still_cleans_builder_owned_resources(tmp_path):
    stores, closed = [], []

    def store_factory(path):
        store = SQLiteStore(path)
        stores.append(store)
        return store

    class Client:
        def close(self):
            closed.append("client")

    def provider_factory(config, context):
        context.own(Client())
        return EchoProvider("fixture")

    registry = ComponentRegistry()
    registry.register("provider", "owned", provider_factory)
    profile = RuntimeProfile("app", "1", {"default": {"adapter": "owned"}})
    try:
        with pytest.raises(ValidationError):
            RuntimeBuilder(
                registry,
                store_factory=store_factory,
                engine_factory=lambda store, **options: object(),
            ).build(profile, tmp_path / "invalid-engine.sqlite")
        assert closed == ["client"]
        with pytest.raises(sqlite3.ProgrammingError):
            stores[0].conn.execute("SELECT 1")
    finally:
        for store in stores:
            store.close()


def test_invalid_legacy_engine_cleanup_can_be_retried_through_router(tmp_path):
    path, instances = tmp_path / "legacy-cleanup.sqlite", []

    def legacy_factory(database):
        store = SQLiteStore(database)
        try:
            return LocalEngine(
                store, providers={"default": EchoProvider("legacy")}, tools=ToolRegistry()
            )
        except Exception:
            store.close()
            raise

    with legacy_factory(path) as original:
        handle = original.submit(AgentSpec("a", "Answer"), "q", command_id="s")

    class InvalidProxy:
        def __init__(self, engine):
            self.engine, self.tries = engine, 0

        def __getattr__(self, name):
            if name == "drive":
                raise AttributeError(name)
            return getattr(self.engine, name)

        def close(self):
            self.tries += 1
            if self.tries == 1:
                raise RuntimeError("temporary close failure")
            self.engine.close()

    def invalid_factory(database):
        runtime = InvalidProxy(legacy_factory(database))
        instances.append(runtime)
        return runtime

    router = ProfiledEngine(catalog(), path, legacy_factory=invalid_factory)
    try:
        with pytest.raises((RuntimeError, ValidationError)):
            asyncio.run(router.drive(handle.run_id))
        with pytest.raises(ValidationError):
            router.status(handle.run_id)
        router.close()
        with legacy_factory(path):
            pass
    finally:
        for instance in instances:
            instance.close()
        router.close()


def test_cancel_receipt_replay_does_not_switch_a_running_new_profile(tmp_path):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class SlowProvider:
            identity = {"kind": "review-slow", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                return ModelResponse(output="done")

        registry = ComponentRegistry()
        registry.register("provider", "slow", lambda config, context: SlowProvider())
        selected = catalog()
        selected.register(RuntimeProfile("app", "2", {"default": {"adapter": "slow"}}))
        runtime = ProfiledEngine(
            selected, tmp_path / "receipts.sqlite", builder=RuntimeBuilder(registry)
        )
        running = None
        try:
            first = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="old")
            receipt = runtime.cancel(first.run_id, command_id="cancel-old")
            selected.set_default("app", "2")
            second = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="new")
            running = asyncio.create_task(runtime.drive(second.run_id))
            await asyncio.wait_for(started.wait(), 2)
            assert runtime.cancel(first.run_id, command_id="cancel-old") == receipt
        finally:
            release.set()
            if running is not None:
                await running
            runtime.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("output_format", ["json", "text"])
def test_optional_router_reader_diagnostics_do_not_prevent_cli_output(
    tmp_path, monkeypatch, capsys, output_format
):
    from relf_agent.cli import main

    path = tmp_path / "reader.sqlite"

    class Reader:
        def __init__(self):
            self.backend = SQLiteRunReader(path)

        def __getattr__(self, name):
            if name not in {"status", "events", "profile_identity", "submit_receipt"}:
                raise AttributeError(name)
            return getattr(self.backend, name)

    runtime = ProfiledEngine(catalog(), path, reader=Reader())
    handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
    module = types.ModuleType("runtime_review_factory")
    module.create_engine = lambda database: runtime
    monkeypatch.setitem(sys.modules, module.__name__, module)
    try:
        code = main(
            [
                "--db",
                str(path),
                "--factory",
                "runtime_review_factory:create_engine",
                "--format",
                output_format,
                "resume",
                handle.run_id,
            ]
        )
        printed = capsys.readouterr()
        assert code == 0, printed.err
        assert "succeeded" in printed.out
    finally:
        runtime.close()


def accepted_control_receipts(path):
    """Obtain real approval, manual effect confirmation, and cancel receipts."""
    selected = RuntimeCatalog()
    selected.register(
        RuntimeProfile(
            "control",
            "1",
            {"default": {"adapter": "review-control"}},
            {"tools": {"adapter": "review-uncertain"}},
        ),
        default=True,
    )
    selected.register(RuntimeProfile("control", "2", {"default": {"adapter": "offline-echo"}}))
    scope = Scope("review-workspace", "alice")
    registry = ComponentRegistry()

    class Provider:
        identity = {"kind": "review-control", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(tool_calls=(ToolCall("change", {}),))

    def tools_factory(config, context):
        def uncertain(arguments, invocation):
            raise TimeoutError("fixture effect outcome unknown")

        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "change",
                "Change a fixture value",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            uncertain,
        )
        return tools

    registry.register("provider", "review-control", lambda config, context: Provider())
    registry.register("tools", "review-uncertain", tools_factory)
    with ProfiledEngine(selected, path, scope=scope, builder=RuntimeBuilder(registry)) as runtime:
        handle = runtime.submit(AgentSpec("a", "Run", ("change",)), "q", command_id="submit")
        waiting = asyncio.run(runtime.drive(handle.run_id))
        assert waiting.state == "waiting_approval"
        pending = waiting.pending[0]
        approval = runtime.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="approve-old"
        )
        unknown = asyncio.run(runtime.drive(handle.run_id))
        assert unknown.state == "waiting_reconciliation"
        result = {"confirmed": {"value": 1}}
        confirmation = runtime.reconcile(
            handle.run_id, pending["action_id"], result, command_id="reconcile-old"
        )
        cancellation = runtime.cancel(handle.run_id, command_id="cancel-old")
        other = runtime.submit(AgentSpec("a", "Run", ("change",)), "other", command_id="other")
    return {
        "catalog": selected,
        "scope": scope,
        "run_id": handle.run_id,
        "other_run_id": other.run_id,
        "action_id": pending["action_id"],
        "target_digest": pending["digest"],
        "result": result,
        "receipts": {"approve": approval, "reconcile": confirmation, "cancel": cancellation},
    }


def retained_catalog(source, keep_original):
    source["catalog"].set_default("control", "2")
    if keep_original:
        return source["catalog"]
    replacement = RuntimeCatalog()
    replacement.register(source["catalog"].default, default=True)
    return replacement


def replay_control(runtime, source, kind, **changes):
    parameters = {
        "run_id": source["run_id"],
        "command_id": f"{kind}-old",
    }
    if kind != "cancel":
        parameters["action_id"] = source["action_id"]
    if kind == "approve":
        parameters["target_digest"] = source["target_digest"]
    elif kind == "reconcile":
        parameters["result"] = source["result"]
    return getattr(runtime, kind)(**{**parameters, **changes})


@pytest.mark.parametrize("kind", ["approve", "reconcile", "cancel"])
@pytest.mark.parametrize("keep_original", [True, False])
def test_control_receipts_replay_after_default_change_or_original_profile_removal(
    tmp_path, kind, keep_original
):
    path = tmp_path / "control-replay.sqlite"
    source = accepted_control_receipts(path)
    reader = SQLiteRunReader(path, scope=source["scope"])
    before = reader.diagnostics(source["run_id"])
    events = reader.events(source["run_id"])
    with ProfiledEngine(
        retained_catalog(source, keep_original), path, scope=source["scope"]
    ) as runtime:
        fresh = runtime.submit(AgentSpec("a", "Answer"), "new", command_id="new")
        assert asyncio.run(runtime.drive(fresh.run_id)).state == "succeeded"
        assert replay_control(runtime, source, kind) == source["receipts"][kind]
    assert reader.diagnostics(source["run_id"]) == before
    assert reader.events(source["run_id"]) == events


@pytest.mark.parametrize(
    "kind,change",
    [
        ("approve", {"approved": False}),
        ("approve", {"target_digest": "0" * 64}),
        ("approve", {"action_id": "different-action"}),
        ("approve", {"run_id": "other_run_id"}),
        ("reconcile", {"result": {"confirmed": {"value": 2}}}),
        ("reconcile", {"action_id": "different-action"}),
        ("reconcile", {"run_id": "other_run_id"}),
        ("cancel", {"run_id": "other_run_id"}),
    ],
)
def test_changed_control_request_conflicts_before_missing_profile_resolution(
    tmp_path, kind, change
):
    path = tmp_path / "control-conflict.sqlite"
    source = accepted_control_receipts(path)
    if "run_id" in change:
        change = {**change, "run_id": source["other_run_id"]}
    with ProfiledEngine(retained_catalog(source, False), path, scope=source["scope"]) as runtime:
        with pytest.raises(IdempotencyConflict):
            replay_control(runtime, source, kind, **change)


@pytest.mark.parametrize("kind", ["approve", "reconcile", "cancel"])
@pytest.mark.parametrize(
    "scope", [Scope("other-workspace", "alice"), Scope("review-workspace", "bob")]
)
def test_control_receipts_cannot_be_replayed_by_another_workspace_or_principal(
    tmp_path, kind, scope
):
    path = tmp_path / "control-scope.sqlite"
    source = accepted_control_receipts(path)
    with ProfiledEngine(retained_catalog(source, False), path, scope=scope) as runtime:
        with pytest.raises(AuthorizationDenied):
            replay_control(runtime, source, kind)
