"""Original Local authority persists signed evidence before tool adoption."""

import asyncio
import copy
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

import ralf_agent
from ralf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolCall
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.harness import DecisionProposal, NativeHarness
from ralf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from ralf_agent.tools import ToolRegistry
from ralf_agent.types import digest


class Provider:
    identity = {"kind": "signed-model-fixture", "version": "1"}
    continuation_identity = {"protocol": "fixture-functions-1", "owner_digest": "a" * 64}

    def __init__(self, audit=None, drift=False, declared=True, corrupt=False):
        self.audit, self.drift, self.corrupt = audit, drift, corrupt
        self.calls = 0
        if not declared:
            self.continuation_identity = None

    async def complete(self, messages, tools):
        self.calls += 1
        if self.audit:
            with sqlite3.connect(self.audit) as db:
                db.execute("INSERT INTO model_calls VALUES (1)")
        if any(m.get("role") == "tool" for m in messages):
            assistant = next(m for m in messages if m.get("model_continuation"))
            assert assistant["model_continuation"]["data"] == {"signature": "原始签名"}
            assert assistant["tool_calls"][0]["function"]["arguments"] == '{"value":7}'
            return ModelResponse(output="done")
        calls = [{"name": "write", "arguments": {"value": 7}, "call_id": "first"}]
        continuation = ModelContinuation(
            "fixture-functions-1",
            "a" * 64,
            digest({"output": None, "tool_calls": calls}) if not self.corrupt else "b" * 64,
            {"signature": "原始签名"},
        )
        if self.drift:
            self.continuation_identity = {**self.continuation_identity, "owner_digest": "b" * 64}
        return ContinuedModelResponse(
            tool_calls=tuple(ToolCall(**c) for c in calls), continuation=continuation
        )


def registry(effects, *, approval=False):
    def write(value: int, flag: bool = True):
        effects.append({"value": value, "flag": flag})
        return {"value": value, "flag": flag}

    tools = ToolRegistry()
    tools.register_function(write, effect="unqueryable_write", requires_approval=approval)
    return tools


def spec():
    return AgentSpec("a", "Act", tools=("write",))


def test_opt_in_preserves_signed_raw_arguments_and_resolves_real_tool_defaults(tmp_path):
    async def run():
        effects, provider = [], Provider()
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": provider},
            tools=registry(effects),
            model_continuation=True,
        ) as engine:
            handle = engine.submit(spec(), "task", command_id="s")
            result = await engine.drive(handle.run_id)
            assert result.state == "succeeded" and result.result == "done"
            record = engine.store.run(handle.run_id)
            model, tool = record["actions"][:2]
            assert model["received_response"]["continuation"]["data"] == {"signature": "原始签名"}
            assert model["response"]["continuation"] == model["received_response"]["continuation"]
            assert tool["arguments"] == {"value": 7, "flag": True}
            assert effects == [{"value": 7, "flag": True}]
            assert provider.calls == 2
            assert record["manifest"]["model_continuation_protocol"] == 1
            assert record["manifest"]["provider_continuations"] == {
                "default": Provider.continuation_identity
            }

    asyncio.run(run())


def test_declared_provider_requires_explicit_enablement_before_acceptance(tmp_path):
    effects, provider = [], Provider()
    store = SQLiteStore(tmp_path / "runs.sqlite")
    try:
        with pytest.raises(ValidationError):
            with LocalEngine(
                store, providers={"default": provider}, tools=registry(effects)
            ) as engine:
                engine.submit(spec(), "task", command_id="s")
        assert effects == [] and provider.calls == 0
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["undeclared", "digest", "harness", "drift"])
def test_rejected_continuation_keeps_completed_evidence_without_any_tool_action(tmp_path, failure):
    class ChangedHarness(NativeHarness):
        identity = {"kind": "changed-harness", "version": "1"}

        def propose(self, spec, response):
            return DecisionProposal(tool_calls=[ToolCall("write", {"value": 8}, "first")])

    effects = []
    provider = Provider(
        declared=failure != "undeclared", corrupt=failure == "digest", drift=failure == "drift"
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": provider},
        tools=registry(effects),
        model_continuation=True,
        harness=ChangedHarness() if failure == "harness" else None,
    ) as engine:
        h = engine.submit(spec(), "task", command_id="s")
        outcome = asyncio.run(engine.drive(h.run_id))
        assert outcome.state == "failed"
        record = engine.store.run(h.run_id)
        assert (
            len(record["actions"]) == 1
            and record["actions"][0]["received_response"]["continuation"]
        )
        assert record["actions"][0]["attempts"][-1]["status"] == "completed"
        assert engine.store.budget(h.run_id)["spent"] == 1
        assert effects == []
        assert provider.calls == 1
        assert asyncio.run(engine.drive(h.run_id)).state == "failed"
        assert provider.calls == 1


def test_signed_approval_and_duplicate_command_survive_restart(tmp_path):
    path, effects = tmp_path / "runs.sqlite", []
    provider = Provider()
    tools = registry(effects, approval=True)
    with LocalEngine(
        SQLiteStore(path), providers={"default": provider}, tools=tools, model_continuation=True
    ) as engine:
        h = engine.submit(spec(), "task", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).state == "waiting_approval"
        original = copy.deepcopy(engine.store.run(h.run_id))
        pending = original["actions"][-1]
    fresh = Provider()
    with LocalEngine(
        SQLiteStore(path), providers={"default": fresh}, tools=tools, model_continuation=True
    ) as engine:
        assert engine.submit(spec(), "task", command_id="s") == h
        receipt = engine.approve(h.run_id, pending["id"], pending["digest"], command_id="approve")
        assert (
            engine.approve(h.run_id, pending["id"], pending["digest"], command_id="approve")
            == receipt
        )
        assert asyncio.run(engine.drive(h.run_id)).result == "done"
        assert effects == [{"value": 7, "flag": True}] and fresh.calls == 1
        assert (
            engine.store.run(h.run_id)["actions"][0]["received_response"]
            == original["actions"][0]["received_response"]
        )


def test_recovery_refuses_opt_in_release_under_legacy_engine_before_business_io(tmp_path):
    path, effects = tmp_path / "runs.sqlite", []
    with LocalEngine(
        SQLiteStore(path),
        providers={"default": Provider()},
        tools=registry(effects),
        model_continuation=True,
    ) as engine:
        h = engine.submit(spec(), "task", command_id="s")
    provider = Provider(declared=False)
    with LocalEngine(
        SQLiteStore(path), providers={"default": provider}, tools=registry(effects)
    ) as old:
        with pytest.raises(DefinitionMismatch):
            asyncio.run(old.drive(h.run_id))
    assert effects == [] and provider.calls == 0


@pytest.mark.parametrize("window", ["model_response_recorded", "decision_adopted"])
def test_true_process_exit_recovery_does_not_redispatch_received_model(tmp_path, window):
    for mode, expected in (("crash", 77), ("resume", 0)):
        process = subprocess.run(
            [sys.executable, str(Path(__file__)), str(tmp_path), window, mode],
            env={"PATH": os.defpath, "PYTHONPATH": str(Path(ralf_agent.__file__).parent.parent)},
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert process.returncode == expected, process.stderr
        if mode == "resume":
            result = json.loads(process.stdout)
            assert result == {
                "state": "succeeded",
                "models": 2,
                "effects": 1,
                "raw": '{"value":7}',
                "continuation": {"signature": "原始签名"},
            }


def process_worker(root, window, mode):
    audit = root / "audit.sqlite"
    with sqlite3.connect(audit) as db:
        db.execute("CREATE TABLE IF NOT EXISTS model_calls(n INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS effects(value INTEGER, flag INTEGER)")

    class CrashStore(SQLiteStore):
        depth, trigger = 0, False

        @contextmanager
        def transaction(self):
            self.depth += 1
            try:
                with super().transaction():
                    yield
            finally:
                self.depth -= 1
            if not self.depth and self.trigger:
                os._exit(77)

        def emit(self, run_id, event, data=None):
            super().emit(run_id, event, data)
            if mode == "crash" and event == window:
                self.trigger = True

    def write(value: int, flag: bool = True):
        with sqlite3.connect(audit) as db:
            db.execute("INSERT INTO effects VALUES (?,?)", (value, flag))
        return {"value": value, "flag": flag}

    tools = ToolRegistry()
    tools.register_function(write, effect="unqueryable_write")
    with LocalEngine(
        CrashStore(root / "runs.sqlite"),
        providers={"default": Provider(audit)},
        tools=tools,
        model_continuation=True,
    ) as engine:
        h = engine.submit(spec(), "task", command_id="s")
        result = asyncio.run(engine.drive(h.run_id))
        if mode == "crash":
            raise AssertionError("Crash checkpoint not reached")
        assert asyncio.run(engine.drive(h.run_id)) == result
        with sqlite3.connect(audit) as db:
            models = db.execute("SELECT count(*) FROM model_calls").fetchone()[0]
            effects = db.execute("SELECT count(*) FROM effects").fetchone()[0]
        model = engine.store.run(h.run_id)["actions"][0]
        next_model = engine.store.run(h.run_id)["actions"][-1]
        assistant = next(m for m in next_model["snapshot"] if m.get("model_continuation"))
        print(
            json.dumps(
                {
                    "state": result.state,
                    "models": models,
                    "effects": effects,
                    "raw": assistant["tool_calls"][0]["function"]["arguments"],
                    "continuation": model["received_response"]["continuation"]["data"],
                }
            )
        )


if __name__ == "__main__":
    process_worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3])


def test_mutated_invalid_continuation_is_received_then_rejected_not_unknown(tmp_path):
    class InvalidProvider(Provider):
        async def complete(self, messages, tools):
            response = await super().complete(messages, tools)
            response.continuation.data["invalid"] = float("nan")
            return response

    effects = []
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": InvalidProvider()},
        tools=registry(effects),
        model_continuation=True,
    ) as engine:
        h = engine.submit(spec(), "task", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).state == "failed"
        action = engine.store.run(h.run_id)["actions"][0]
        assert action["status"] == "rejected"
        assert action["attempts"][-1]["status"] == "completed"
        assert action["received_response"]["invalid_fields"] == ["continuation"]
        assert engine.store.budget(h.run_id)["held"] == 0
        assert engine.store.budget(h.run_id)["spent"] == 1
        assert effects == []


def test_bound_selected_provider_pins_continuation_and_restarts_without_host_fallback(tmp_path):
    from ralf_agent.binding_catalog import BindingCatalog
    from ralf_agent.binding_definitions import AgentDefinition
    from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
    from ralf_agent.types import Scope

    class Host:
        identity = {"kind": "must-not-run", "version": "1"}

        async def complete(self, messages, tools):
            raise AssertionError("Selected Provider must not fall back")

    catalog = BindingCatalog(scope=Scope())
    catalog.register("provider", "signed", "1", Provider())
    definition = AgentDefinition(
        spec(), AgentBindingDescriptor(provider=BindingSelection.ref("signed", "1"))
    )
    effects, path = [], tmp_path / "runs.sqlite"
    tools = registry(effects, approval=True)
    with LocalEngine(
        SQLiteStore(path),
        providers={"default": Host()},
        tools=tools,
        binding_catalog=catalog,
        model_continuation=True,
    ) as engine:
        h = engine.submit(definition, "task", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).state == "waiting_approval"
        manifest = engine.diagnostics(h.run_id).manifest
        assert manifest["model_continuation_protocol"] == 1
        assert manifest["agent_bindings"]["steps"]["agent"]["manifest"][
            "provider_continuations"
        ] == {"default": Provider.continuation_identity}
        pending = engine.store.run(h.run_id)["actions"][-1]
    with LocalEngine(
        SQLiteStore(path),
        providers={"default": Host()},
        tools=tools,
        binding_catalog=catalog,
        model_continuation=True,
    ) as engine:
        engine.approve(h.run_id, pending["id"], pending["digest"], command_id="a")
        assert asyncio.run(engine.drive(h.run_id)).result == "done"
        assert effects == [{"value": 7, "flag": True}]
        assert engine.diagnostics(h.run_id).manifest == manifest


@pytest.mark.parametrize("context_kind", ["default", "managed", "managed-data"])
def test_context_budget_preserves_latest_signed_tool_group_without_truncation(context_kind):
    from ralf_agent.artifacts import InMemoryArtifactStore
    from ralf_agent.context import ContextAssembler
    from ralf_agent.data_context import ManagedDataContext
    from ralf_agent.managed_context import ManagedContextPipeline
    from ralf_agent.model_continuation import assistant_message
    from ralf_agent.model_evidence import snapshot_model_response
    from ralf_agent.types import canonical

    response = asyncio.run(Provider().complete([], []))
    raw = snapshot_model_response(response)
    group = [
        assistant_message(
            None,
            [{"tool": "write", "arguments": {"value": 7, "flag": True}, "call_id": "first"}],
            received=raw,
            continuation=raw["continuation"],
        ),
        {"role": "tool", "tool_call_id": "first", "content": '{"value":7,"flag":true}'},
    ]
    history = [
        {"role": "system", "content": "Policy"},
        {"role": "user", "content": "Task"},
        {"role": "assistant", "content": "Old evidence" * 1000},
        *group,
    ]
    context = (
        ContextAssembler()
        if context_kind == "default"
        else ManagedContextPipeline()
        if context_kind == "managed"
        else ManagedDataContext(InMemoryArtifactStore())
    )
    before = copy.deepcopy(history)
    bound = len(canonical(history[:2] + group))
    messages, manifest = context.assemble(history, [], bound)
    assert messages[-2:] == group
    assert messages[-2]["model_continuation"]["data"] == {"signature": "原始签名"}
    assert manifest["dropped_groups"] == 1
    assert history == before
    with pytest.raises(ValidationError):
        context.assemble(history, [], bound - 1)
