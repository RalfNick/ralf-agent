import asyncio
import importlib.util
import inspect
from dataclasses import asdict

import pytest

from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.tools import ToolRegistry, ToolSpec
from relf_agent.types import AgentSpec, ModelResponse, Scope, WorkflowSpec


def test_temporal_backend_exposes_explicit_async_network_controls():
    assert importlib.util.find_spec("relf_agent.temporal"), "Missing independent Temporal backend"
    from relf_agent.temporal import TemporalEngine

    for name in (
        "submit",
        "status",
        "events",
        "approve",
        "cancel",
        "reconcile",
        "drive",
        "diagnostics",
    ):
        assert inspect.iscoroutinefunction(getattr(TemporalEngine, name)), name


class Provider:
    identity = {"kind": "temporal-test-provider", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output={"answer": 42})


async def read(arguments, context):
    return arguments


def registry():
    tools = ToolRegistry()
    tools.register(ToolSpec("read", "read", {"type": "object"}), read)
    return tools


def test_history_controls_are_initialized_before_workflow_run(monkeypatch):
    if importlib.util.find_spec("temporalio") is None:
        pytest.skip("Requires the optional Temporal SDK")
    pytest.importorskip("temporalio")
    from types import SimpleNamespace

    from relf_agent import TemporalRuntime
    from relf_agent.temporal_workflow import (
        TemporalCommandRegistryWorkflow,
        TemporalRunWorkflow,
        workflow,
    )
    from relf_agent.types import submission_request

    scope = asdict(Scope())
    request = submission_request(AgentSpec("a", "Answer"), "task", budget=8, session_id=None)
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    monkeypatch.setattr(
        workflow, "info", lambda: SimpleNamespace(workflow_id="run", run_id="epoch")
    )
    # Temporal can deliver a Query/Update before scheduling the run coroutine.
    run = TemporalRunWorkflow(
        {
            "scope": scope,
            "command_id": "first",
            "request": request,
            "manifest": runtime.manifest,
            "activity_timeout": 3,
        }
    )
    assert run.view({"scope": scope, "kind": "status"})["state"] == "queued"
    receipt = run.view(
        {"scope": scope, "kind": "submission", "request": request, "command_id": "first"}
    )
    assert receipt["run_id"] == "run" and receipt["apply_state"] == "applied"
    commands = TemporalCommandRegistryWorkflow({"scope": scope})
    identity = {
        "scope": scope,
        "command_id": "first",
        "kind": "submit",
        "target": "run",
        "payload_digest": "digest",
    }
    first = asyncio.run(commands.reserve(identity))
    assert asyncio.run(commands.reserve(identity)) == first
    assert commands.view({"scope": scope})["accepted_commands"] == 1


def test_runtime_release_is_detached_and_configuration_drift_is_refused():
    from relf_agent.temporal_activities import TemporalRuntime

    provider = Provider()
    runtime = TemporalRuntime(providers={"default": provider}, tools=registry())
    manifest = runtime.manifest
    manifest["providers"]["default"]["version"] = "mutated"
    assert runtime.manifest["providers"]["default"]["version"] == "1"
    provider.identity = {**provider.identity, "version": "2"}
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_temporal_refuses_unsupported_definition_before_any_network_operation():
    from relf_agent.temporal import TemporalEngine
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.workflow import GraphNode, GraphWorkflowSpec

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    engine = TemporalEngine(object(), task_queue="test", release=runtime.manifest)
    graph = GraphWorkflowSpec("graph", [GraphNode("a", agent=AgentSpec("a", "answer"))])
    with pytest.raises(ValidationError, match="native AgentSpec or sequential WorkflowSpec"):
        asyncio.run(engine.submit(graph, "hi", command_id="g"))


@pytest.mark.parametrize("policy", [lambda *_: True, lambda *_: iter(())])
def test_tool_policy_requires_synchronously_completed_none_before_dispatch(policy):
    from relf_agent.temporal_activities import TemporalRuntime

    calls = []
    tools = ToolRegistry()

    async def handler(arguments, context):
        calls.append(context.effect_key)
        return "written"

    tools.register(ToolSpec("write", "write", {"type": "object"}), handler)
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=tools,
        policy=policy,
        policy_identity={"kind": "test-policy", "version": "1"},
    )
    request = {
        "runtime_manifest": runtime.manifest,
        "scope": asdict(Scope()),
        "run_id": "run",
        "action_id": "a",
        "attempt_id": "a:1",
        "effect_key": "original-key",
        "execution_epoch": "epoch",
        "tool": "write",
        "tool_manifest": tools.get("write").manifest,
        "arguments": {},
        "operation_digest": "op",
    }
    result = asyncio.run(runtime.execute_tool(request))
    assert result == {"ok": False, "code": "validation_error", "dispatched": False}
    assert calls == []


def test_model_activity_validates_output_schema_and_provider_usage():
    from relf_agent.temporal_activities import TemporalRuntime

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    step = asdict(AgentSpec("a", "answer", output_schema={"type": "integer"}))
    result = asyncio.run(
        runtime.complete_model(
            {
                "runtime_manifest": runtime.manifest,
                "step": step,
                "messages": [{"role": "user", "content": "hi"}],
            }
        )
    )
    assert result["ok"] is False and result["code"] == "validation_error"
    assert result["dispatched"] is True and result["model_evidence_version"] == 2
    assert result["received_response"] == {
        "output": {"answer": 42},
        "tool_calls": [],
        "usage": None,
    }


def test_workflow_state_owns_budget_receipts_and_preserves_original_action_on_unknown():
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_state import TemporalRunState
    from relf_agent.types import submission_request

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    request = submission_request(AgentSpec("a", "answer", tools=("read",)), "hi", budget=3)
    state = TemporalRunState("run", asdict(Scope()), "submit", request, runtime.manifest)
    model, dispatch = state.next_operation()
    assert model["kind"] == "model"
    assert state.budget["reserved"] == 1
    state.accept_model(
        model["id"],
        {
            "ok": True,
            "output": None,
            "tool_calls": [{"name": "read", "arguments": {}, "call_id": "c"}],
            "usage": None,
        },
    )
    action, tool_dispatch = state.next_operation()
    original = action["id"], action["effect_key"], tool_dispatch["attempt_id"]
    state.operation_unknown(action["id"], "activity_timeout")
    assert state.budget["unknown"] == 1
    assert state.next_operation() is None
    receipt = state.command(
        "reconcile",
        {
            "kind": "reconcile",
            "scope": asdict(Scope()),
            "action_id": action["id"],
            "result": "seen",
        },
    )
    assert receipt["apply_state"] == "applied"
    assert (action["id"], action["effect_key"], action["attempts"][0]["id"]) == original
    assert state.budget["spent"] == 2 and state.budget["unknown"] == 0
    assert (
        state.command(
            "reconcile",
            {
                "kind": "reconcile",
                "scope": asdict(Scope()),
                "action_id": action["id"],
                "result": "seen",
            },
        )
        == receipt
    )


def test_sequential_state_passes_validated_output_to_next_agent():
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_state import TemporalRunState
    from relf_agent.types import submission_request

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    request = submission_request(
        WorkflowSpec("seq", (AgentSpec("a", "one"), AgentSpec("b", "two"))), "input"
    )
    state = TemporalRunState("run", asdict(Scope()), "s", request, runtime.manifest)
    action, _ = state.next_operation()
    state.accept_model(
        action["id"], {"ok": True, "output": {"first": 1}, "tool_calls": [], "usage": None}
    )
    action, operation = state.next_operation()
    assert action["node"] == 1
    assert operation["messages"][1]["content"] == '{"first":1}'
    state.accept_model(
        action["id"], {"ok": True, "output": "done", "tool_calls": [], "usage": None}
    )
    assert state.snapshot()["state"] == "succeeded"


def state_with_tool():
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_state import TemporalRunState
    from relf_agent.types import submission_request

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    value = TemporalRunState(
        "run",
        asdict(Scope()),
        "s",
        submission_request(AgentSpec("a", "answer", tools=("read",)), "hi", budget=4),
        runtime.manifest,
    )
    model, _ = value.next_operation()
    value.accept_model(
        model["id"],
        {
            "ok": True,
            "output": None,
            "tool_calls": [{"name": "read", "arguments": {}, "call_id": "c"}],
            "usage": None,
        },
    )
    action, _ = value.next_operation()
    return value, action


def test_cancel_keeps_pending_late_tool_evidence_and_immutable_terminal():
    value, action = state_with_tool()
    cancel = value.command("cancel", {"kind": "cancel", "scope": asdict(Scope())})
    assert cancel["outcome"]["remote_stop_confirmed"] is False
    value.accept_tool(action["id"], {"ok": True, "result": "completed-after-cancel"})
    assert value.snapshot()["state"] == "cancelled"
    assert value.result is None and value.next_operation() is None
    assert action["result"] == "completed-after-cancel"
    assert value.budget["spent"] == 2 and value.quiescent
    value.accept_tool(action["id"], {"ok": True, "result": "contradiction"}, reconciled=True)
    assert action["result"] == "completed-after-cancel"
    assert value.event_log[-1]["data"]["matches_committed_result"] is False


def test_duplicate_rejected_command_preserves_original_receipt_and_conflicts():
    from relf_agent.errors import IdempotencyConflict

    value, action = state_with_tool()
    payload = {
        "kind": "approve",
        "scope": asdict(Scope()),
        "action_id": "no-action",
        "digest": "wrong",
        "approved": True,
    }
    receipt = value.command("bad", payload)
    assert receipt["apply_state"] == "rejected"
    assert value.command("bad", payload) == receipt
    with pytest.raises(IdempotencyConflict):
        value.command("bad", {**payload, "digest": "changed"})


def test_no_write_registration_without_explicit_durable_journal():
    from relf_agent.temporal_activities import TemporalRuntime

    tools = ToolRegistry()
    tools.register(ToolSpec("write", "write", {"type": "object"}, effect="queryable_write"), read)
    with pytest.raises(ValidationError, match="durable EffectJournal"):
        TemporalRuntime(providers={"default": Provider()}, tools=tools)


def test_query_reconciliation_drive_waits_for_evidence_in_history():

    value, action = state_with_tool()
    value.operation_unknown(action["id"], "timeout")
    value.command(
        "query",
        {"kind": "reconcile", "scope": asdict(Scope()), "action_id": action["id"], "query": True},
    )
    assert value.diagnostics()["workflow"]["reconciliation_pending"]


def test_worker_identity_cannot_override_pinned_release_build_id():
    from relf_agent.temporal import build_temporal_worker
    from relf_agent.temporal_activities import TemporalRuntime

    if not importlib.util.find_spec("temporalio"):
        pytest.skip("optional Temporal SDK not installed")
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    with pytest.raises(DefinitionMismatch, match="build identity"):
        build_temporal_worker(object(), task_queue="test", runtime=runtime, build_id="unrelated")


def test_scoped_registry_refuses_cross_run_and_cross_kind_command_reuse():
    from relf_agent.errors import AuthorizationDenied, IdempotencyConflict
    from relf_agent.temporal_state import TemporalCommandRegistryState

    commands = TemporalCommandRegistryState(asdict(Scope()), capacity=2)
    request = {
        "scope": asdict(Scope()),
        "command_id": "same",
        "kind": "cancel",
        "target": "run-one",
        "payload_digest": "first",
    }
    original = commands.reserve(request)
    assert original["apply_state"] == "not_applied"
    assert commands.reserve(request) == original
    with pytest.raises(IdempotencyConflict):
        commands.reserve({**request, "target": "run-two"})
    with pytest.raises(IdempotencyConflict):
        commands.reserve({**request, "kind": "submit"})
    with pytest.raises(AuthorizationDenied):
        commands.reserve({**request, "scope": asdict(Scope("other", "other"))})
    commands.reserve({**request, "command_id": "second"})
    with pytest.raises(ValidationError, match="capacity"):
        commands.reserve({**request, "command_id": "third"})


def test_optional_temporal_import_does_not_load_sdk_or_driver(tmp_path):
    import subprocess
    import sys

    script = """
import builtins
original = builtins.__import__
def restricted(name, *args, **kwargs):
    if name.split(".")[0] in {"temporalio", "psycopg"}:
        raise ImportError("optional dependency deliberately unavailable")
    return original(name, *args, **kwargs)
builtins.__import__ = restricted
from relf_agent.temporal import TemporalEngine
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_journal import PostgresEffectJournal
assert TemporalEngine and TemporalRuntime and PostgresEffectJournal
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_shared_session_requirement_is_refused_before_any_network_operation():
    from relf_agent.temporal import TemporalEngine
    from relf_agent.temporal_activities import TemporalRuntime

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    engine = TemporalEngine(object(), task_queue="test", release=runtime.manifest)
    with pytest.raises(ValidationError, match="shared sessions"):
        asyncio.run(
            engine.submit(AgentSpec("a", "answer"), "hi", command_id="s", session_id="shared")
        )


def test_temporal_capability_matrix_is_explicit_and_detached():
    from relf_agent.temporal import TemporalEngine
    from relf_agent.temporal_activities import TemporalRuntime

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    engine = TemporalEngine(object(), task_queue="test", release=runtime.manifest)
    for component in (engine, runtime):
        capabilities = component.capabilities
        assert (
            capabilities["native_agent"]
            and capabilities["sequence"]
            and capabilities["history_context"]
        )
        for name in (
            "graph",
            "team",
            "dag",
            "nesting",
            "shared_session",
            "remote_memory",
            "rag",
            "custom_harness",
        ):
            assert capabilities[name] is False
        capabilities["dag"] = True
        assert component.capabilities["dag"] is False


def test_custom_harness_and_context_are_explicitly_refused():
    from relf_agent.temporal_activities import TemporalRuntime

    with pytest.raises(ValidationError, match="native harness"):
        TemporalRuntime(providers={"default": Provider()}, tools=registry(), harness=object())
    with pytest.raises(ValidationError, match="default History context"):
        TemporalRuntime(
            providers={"default": Provider()}, tools=registry(), context_builder=object()
        )


def test_network_schema_references_are_refused_before_history_execution():
    from relf_agent.temporal import TemporalEngine
    from relf_agent.temporal_activities import TemporalRuntime

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    engine = TemporalEngine(object(), task_queue="test", release=runtime.manifest)
    agent = AgentSpec("a", "answer", output_schema={"$ref": "https://example.invalid/schema"})
    with pytest.raises(ValidationError, match="local Schema references"):
        asyncio.run(engine.submit(agent, "hi", command_id="s"))


def test_invalid_published_tool_manifest_is_a_typed_preflight_failure():
    from relf_agent.temporal import TemporalEngine
    from relf_agent.temporal_activities import TemporalRuntime

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    release = runtime.manifest
    del release["tools"]["read"]["input_schema"]
    with pytest.raises(ValidationError, match="tool manifest"):
        TemporalEngine(object(), task_queue="test", release=release)


def test_model_json_string_schema_is_normalized_once_by_history_authority():
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_state import TemporalRunState
    from relf_agent.types import submission_request

    class StringProvider(Provider):
        async def complete(self, messages, tools):
            return ModelResponse(output='"valid string"')

    runtime = TemporalRuntime(providers={"default": StringProvider()}, tools=registry())
    agent = AgentSpec("a", "answer", output_schema={"type": "string"})
    state = TemporalRunState(
        "run", asdict(Scope()), "s", submission_request(agent, "hi"), runtime.manifest
    )
    action, dispatch = state.next_operation()
    evidence = asyncio.run(runtime.complete_model(dispatch))
    state.accept_model(action["id"], evidence)
    assert state.state == "succeeded"
    assert state.result == "valid string"
    assert evidence["output"] == '"valid string"'


@pytest.mark.parametrize("terminal", ["cancelled", "failed", "succeeded"])
def test_drive_never_reopens_terminal_run_with_an_undispatched_blocked_write(terminal):
    value, action = state_with_tool()
    value.accept_failure(
        action["id"],
        {
            "ok": False,
            "dispatched": False,
            "blocked": True,
            "prior": {},
            "code": "prior_effect_unknown",
        },
    )
    if terminal == "cancelled":
        value.command("cancel", {"kind": "cancel", "scope": asdict(Scope())})
    else:
        value.state = terminal
    value.command("drive", {"kind": "drive", "scope": asdict(Scope())})
    value.retry_blocked()
    assert value.state == terminal
    assert action["status"] == "blocked"
    assert value.next_operation() is None
    assert value.budget["spent"] == 1


class JournalContractFixture:
    identity = {"kind": "test-effect-journal", "version": "1"}

    def __init__(self, *, begin=None, received=None, observation=None, acknowledge=None):
        self.begin_result = {"execute": True} if begin is None else begin
        self.received_result, self.observation_result, self.acknowledge_result = (
            received,
            observation,
            acknowledge,
        )
        self.intent = False
        self.acknowledged = False

    async def begin(self, envelope):
        self.intent = True
        return self.begin_result

    async def received(self, envelope, observation):
        return self.received_result

    async def observation(self, envelope):
        return self.observation_result

    async def acknowledge(self, envelope, observation):
        return self.acknowledge_result


def journal_runtime(journal, calls):
    from relf_agent.temporal_activities import TemporalRuntime

    async def handler(arguments, context):
        calls.append(context.effect_key)
        return "written"

    tools = ToolRegistry()
    tools.register(
        ToolSpec("write", "write", {"type": "object"}, effect="queryable_write"), handler
    )
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=tools, journal=journal)
    request = {
        "runtime_manifest": runtime.manifest,
        "scope": asdict(Scope()),
        "run_id": "run",
        "action_id": "a",
        "attempt_id": "a:1",
        "effect_key": "original-key",
        "execution_epoch": "epoch",
        "tool": "write",
        "tool_manifest": tools.get("write").manifest,
        "arguments": {},
        "operation_digest": "op",
    }
    return runtime, request


def test_journal_received_requires_completed_none_and_closes_nested_coroutine():
    calls, entered = [], []

    async def delayed_receipt():
        entered.append("entered")

    lazy = delayed_receipt()
    journal = JournalContractFixture(received=lazy)
    runtime, _ = journal_runtime(journal, calls)
    from relf_agent.temporal_state import TemporalRunState
    from relf_agent.types import submission_request

    agent = AgentSpec("a", "write", tools=("write",))
    state = TemporalRunState(
        "run", asdict(Scope()), "s", submission_request(agent, "hi", budget=3), runtime.manifest
    )
    model, _ = state.next_operation()
    state.accept_model(
        model["id"],
        {
            "ok": True,
            "output": None,
            "tool_calls": [{"name": "write", "arguments": {}, "call_id": "c"}],
            "usage": None,
        },
    )
    action, request = state.next_operation()
    result = asyncio.run(runtime.execute_tool(request))
    state.accept_tool(action["id"], result)
    assert result == {"ok": False, "code": "validation_error", "dispatched": True}
    assert calls == [action["effect_key"]] and entered == []
    assert lazy.cr_frame is None
    assert journal.intent and not journal.acknowledged
    assert state.state == "waiting_reconciliation" and action["status"] == "outcome_unknown"
    assert state.budget["unknown"] == 1 and state.pending_acks == []


@pytest.mark.parametrize("invalid", [True, 0, {}, iter(())])
def test_journal_acknowledgement_requires_exact_none(invalid):
    journal = JournalContractFixture(acknowledge=invalid)
    runtime, request = journal_runtime(journal, [])
    result = asyncio.run(
        runtime.acknowledge_evidence({**request, "result": "seen", "source": "operator"})
    )
    assert result == {"ok": False, "code": "validation_error"}
    assert not journal.acknowledged


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"execute": 1},
        {"execute": "yes"},
        {
            "execute": True,
            "blocked": True,
            "prior": {"run_id": "r", "action_id": "a", "effect_key": "k"},
        },
        {"execute": True, "observation": "receipt"},
        {"execute": False, "blocked": True, "prior": {"unexpected": "shape"}},
        {"execute": False, "unknown": float("nan")},
    ],
)
def test_journal_begin_has_a_finite_typed_mutually_exclusive_contract(invalid):
    journal = JournalContractFixture(begin=invalid)
    calls = []
    runtime, request = journal_runtime(journal, calls)
    result = asyncio.run(runtime.execute_tool(request))
    assert result == {"ok": False, "code": "validation_error", "dispatched": False}
    assert calls == [] and journal.intent and not journal.acknowledged


def test_journal_observation_cannot_return_an_unexecuted_coroutine():
    entered = []

    async def delayed_observation():
        entered.append("entered")

    lazy = delayed_observation()
    journal = JournalContractFixture(observation=lazy)
    runtime, request = journal_runtime(journal, [])
    result = asyncio.run(runtime.reconcile_tool(request))
    assert result == {"ok": False, "code": "validation_error", "dispatched": False}
    assert lazy.cr_frame is None and entered == []
