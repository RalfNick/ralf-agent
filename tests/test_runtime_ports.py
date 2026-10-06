import asyncio
import copy
import importlib
import sys
import types

import pytest

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    MemoryRecallPolicy,
    ModelResponse,
    RecallQuery,
    Scope,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.memory import InMemoryMemory


class Provider:
    identity = {"kind": "port-fixture", "version": "1"}

    def __init__(self, fail_once=False):
        self.requests = []
        self.fail_once = fail_once

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        if self.fail_once and len(self.requests) == 1:
            raise TimeoutError("Unknown response")
        return ModelResponse(output="done")


def engine(path, provider=None, **options):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": provider or Provider()},
        tools=ToolRegistry(),
        **options,
    )


def test_knowledge_context_can_implement_the_port_without_inheritance(tmp_path):
    class Knowledge:
        identity = {"kind": "external-context", "version": "1", "limit": 2, "max_chars": 1000}
        limit = 2
        max_chars = 1000
        validations = 0

        async def references(self, scope, text):
            return [{"key": "external", "version": 1, "value": "CUSTOM_EVIDENCE"}]

        async def validate(self, scope, references):
            self.validations += 1
            assert references[0]["value"] == "CUSTOM_EVIDENCE"

    provider, knowledge = Provider(), Knowledge()
    with engine(tmp_path / "knowledge.sqlite", provider, knowledge=knowledge) as runtime:
        run = runtime.submit(AgentSpec("a", "Answer"), "question", command_id="s")
        result = asyncio.run(runtime.drive(run.run_id))
        assert result.state == "succeeded" and knowledge.validations >= 1
        assert "CUSTOM_EVIDENCE" in str(provider.requests[0])


@pytest.mark.parametrize("field,value", [("limit", True), ("limit", 0), ("max_chars", 1)])
def test_invalid_knowledge_port_limits_are_rejected_before_acquiring_lease(tmp_path, field, value):
    class Knowledge:
        identity = {"kind": "invalid-port", "version": "1"}
        limit, max_chars = 1, 1000

        async def references(self, scope, text):
            return []

        async def validate(self, scope, references):
            pass

    knowledge = Knowledge()
    setattr(knowledge, field, value)
    path = tmp_path / "invalid.sqlite"
    store = SQLiteStore(path)
    try:
        with pytest.raises(ValidationError):
            LocalEngine(store, providers={}, tools=ToolRegistry(), knowledge=knowledge)
        with engine(path):
            pass
    finally:
        store.close()


def test_dynamic_recall_planner_is_used_once_and_retry_keeps_original_query(tmp_path):
    class Planner:
        identity = {"kind": "query-planner", "version": "1"}
        calls = 0

        def plan(self, scope, namespace, session_id, text):
            self.calls += 1
            assert scope == Scope() and namespace == "a" and text == "ticket"
            return MemoryRecallPolicy(facts=RecallQuery(text="incident"))

    memory = InMemoryMemory(backend_id="facts-fixture")
    memory.put_fact(Scope(), "a", "incident", "SELECTED", expected_version=0)
    memory.put_fact(Scope(), "a", "other", "EXCLUDED", expected_version=0)
    provider, planner = Provider(fail_once=True), Planner()
    with engine(
        tmp_path / "planner.sqlite", provider, memory_store=memory, recall_planner=planner
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "Answer"), "ticket", command_id="s")
        first = asyncio.run(runtime.drive(run.run_id))
        assert first.state == "waiting_reconciliation"
        original = copy.deepcopy(first.actions[0]["snapshot"])
        done = asyncio.run(runtime.drive(run.run_id))
        assert done.state == "succeeded" and planner.calls == 1
        assert provider.requests == [original, original]
        assert "SELECTED" in str(original) and "EXCLUDED" not in str(original)
        assert (
            done.actions[0]["context_manifest"]["memory_recall_policy"]["facts"]["text"]
            == "incident"
        )


def test_recall_policy_and_planner_are_mutually_exclusive(tmp_path):
    class Planner:
        identity = {"kind": "planner", "version": "1"}

        def plan(self, *args):
            return MemoryRecallPolicy()

    store = SQLiteStore(tmp_path / "mutual.sqlite")
    try:
        with pytest.raises(ValidationError):
            LocalEngine(
                store,
                providers={},
                tools=ToolRegistry(),
                recall_policy=MemoryRecallPolicy(),
                recall_planner=Planner(),
            )
    finally:
        store.close()


def test_changed_planner_identity_cannot_continue_a_pinned_run(tmp_path):
    class Planner:
        identity = {"kind": "planner", "version": "1"}

        def plan(self, *args):
            return MemoryRecallPolicy()

    planner = Planner()
    with engine(tmp_path / "pinned.sqlite", recall_planner=planner) as runtime:
        run = runtime.submit(AgentSpec("a", "Answer"), "ticket", command_id="s")
        planner.identity = {"kind": "planner", "version": "2"}
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(run.run_id))


class EngineProxy:
    """A real execution engine behind only the public operations."""

    def __init__(self, runtime):
        self.runtime = runtime

    def __getattr__(self, name):
        if name not in {
            "submit",
            "drive",
            "status",
            "events",
            "approve",
            "cancel",
            "reconcile",
            "wait_for_threads",
            "close",
        }:
            raise AttributeError(name)
        return getattr(self.runtime, name)


@pytest.mark.parametrize("output_format", ["json", "text"])
def test_cli_factory_accepts_a_public_engine_without_local_inheritance_or_store(
    tmp_path, monkeypatch, capsys, output_format
):
    from ralf_agent.cli import main

    runtime = engine(tmp_path / "proxy.sqlite")
    handle = runtime.submit(AgentSpec("a", "Answer"), "question", command_id="s")
    module = types.ModuleType("explicit_port_factory")
    module.create_engine = lambda db: EngineProxy(runtime)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    try:
        assert (
            main(
                [
                    "--factory",
                    "explicit_port_factory:create_engine",
                    "--format",
                    output_format,
                    "resume",
                    handle.run_id,
                ]
            )
            == 0
        )
        printed = capsys.readouterr().out
        assert "succeeded" in printed and "done" in printed
    finally:
        runtime.close()
    with engine(tmp_path / "proxy.sqlite"):
        pass


def test_public_execution_port_and_detached_diagnostics_are_available(tmp_path):
    ports = importlib.import_module("ralf_agent.ports")
    with engine(tmp_path / "diagnostics.sqlite") as runtime:
        assert isinstance(runtime, ports.ExecutionEngine)
        run = runtime.submit(AgentSpec("a", "Answer"), "question", command_id="s")
        details = runtime.diagnostics(run.run_id)
        details.manifest["kernel"] = "changed"
        details.budget["limit"] = 0
        current = runtime.diagnostics(run.run_id)
        assert current.manifest["kernel"] == "local-4" and current.budget["limit"] == 32
        assert "runtime_profile" not in current.manifest
        assert "recall_planner" not in current.manifest


def test_runtime_profile_identity_is_saved_only_when_explicitly_enabled(tmp_path):
    identity = {"kind": "runtime-profile", "name": "app", "version": "1", "digest": "a" * 64}
    with engine(tmp_path / "profile.sqlite", runtime_profile=identity) as runtime:
        identity["version"] = "changed"
        run = runtime.submit(AgentSpec("a", "Answer"), "question", command_id="s")
        assert runtime.store.run(run.run_id)["manifest"]["runtime_profile"]["version"] == "1"


def test_cli_rejects_async_callable_factory_without_creating_an_unawaited_coroutine(
    tmp_path, monkeypatch
):
    from ralf_agent.cli import load_engine

    class AsyncFactory:
        async def __call__(self, path):
            pytest.fail("Unsupported factory must not execute")

    module = types.ModuleType("async_callable_factory")
    module.create_engine = AsyncFactory()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(ValidationError):
        load_engine(tmp_path / "unused.sqlite", "async_callable_factory:create_engine")


def test_cli_invalid_engine_cleanup_does_not_leak_an_owned_coordinator(tmp_path, monkeypatch):
    from ralf_agent.cli import load_engine

    runtime = engine(tmp_path / "invalid-engine.sqlite")

    class Invalid(EngineProxy):
        def __getattr__(self, name):
            if name == "drive":
                raise AttributeError(name)
            return super().__getattr__(name)

    module = types.ModuleType("invalid_engine_factory")
    module.create_engine = lambda path: Invalid(runtime)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    try:
        with pytest.raises(ValidationError):
            load_engine(tmp_path / "invalid-engine.sqlite", "invalid_engine_factory:create_engine")
        with engine(tmp_path / "invalid-engine.sqlite"):
            pass
    finally:
        runtime.close()
