"""History Session admission and real Run evidence, independently of SDK I/O."""

import copy
import importlib
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, ModelResponse, Scope, ToolRegistry
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request


class Provider:
    identity = {"kind": "session-test-provider", "version": "1"}

    def __init__(self):
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(messages)
        return ModelResponse(output="answer")


def session(**components):
    runtime = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), enable_sessions=True, **components
    )
    module = importlib.import_module("relf_agent.temporal_session_state")
    accepted = {
        "scope": asdict(Scope()),
        "namespace_id": "namespace-uuid",
        "session_namespace": "chat",
        "session_id": "same",
        "command_id": "open",
        "request": submission_request(AgentSpec("answer", "Answer"), None),
        "manifest": runtime.manifest,
        "task_queue": "queue",
        "activity_timeout": 10,
    }
    state = module.TemporalSessionState(accepted)
    return state, runtime


def submit(state, command="turn", value="question", ref=None):
    return state.command(
        {
            "kind": "submit",
            "scope": state.scope,
            "command_id": command,
            "session_ref": ref or state.ref.to_dict(),
            "input": value,
            "budget": 8,
        }
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_queue", ""),
        ("task_queue", 1),
        ("activity_timeout", 0),
        ("activity_timeout", float("inf")),
    ],
)
def test_rebind_rejects_invalid_execution_binding_without_changing_revision(field, value):
    from relf_agent.errors import ValidationError

    state, _ = session()
    binding = copy.deepcopy(state.binding)
    binding[field] = value
    with pytest.raises(ValidationError):
        state.command(
            {
                "kind": "rebind",
                "scope": state.scope,
                "command_id": "bad",
                "session_ref": state.ref.to_dict(),
                "binding": binding,
                "expected_binding_revision": 1,
            }
        )
    assert state.binding_revision == 1
    assert state.active is None


def test_turn_receipt_and_busy_rejection_survive_restore():
    state, _ = session()
    first = submit(state)
    assert first["apply_state"] == "applied"
    assert first["outcome"]["turn"]["turn_seq"] == 1
    refused = submit(state, "busy", "new question")
    assert refused["apply_state"] == "rejected" and refused["outcome"]["error"] == "session_busy"
    restored = copy.deepcopy(state)
    assert submit(restored) == first
    assert submit(restored, "busy", "new question") == refused
    assert restored.snapshot()["busy"] is True
    assert len(restored.turns(after=0, limit=10)) == 1


def nested_proof():
    from relf_agent import TeamSpec
    from relf_agent.temporal_parent_state import TemporalParentState
    from relf_agent.temporal_session_state import TemporalSessionState

    host = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), enable_sessions=True
    )
    manifest = host.orchestration_release
    inner = TeamSpec("inner", {"leaf": AgentSpec("leaf", "Answer")}, child_budget=2)
    outer = TeamSpec("outer", {"inner": inner}, child_budget=4)
    state = TemporalSessionState(
        {
            "scope": asdict(Scope()),
            "namespace_id": "namespace-uuid",
            "session_namespace": "chat",
            "session_id": "nested",
            "command_id": "open",
            "request": submission_request(outer, None),
            "manifest": manifest,
            "task_queue": "queue",
            "activity_timeout": 10,
        }
    )
    submit(state)
    intent = state.start_intent()
    root = TemporalParentState(
        intent["run_id"], state.scope, intent["command_id"], intent["request"], manifest
    )

    def dispatch(parent, member, ident):
        parent.accept_selection(
            {
                "calls": [{"id": ident, "member": member, "input": "question"}],
                "done": False,
                "result": None,
            }
        )
        call = parent.next_calls()[0]
        parent.children[0]["dispatch_started"] = True
        parent.mark_started(call["run_id"])
        return call

    a = dispatch(root, "inner", "one")
    mid = TemporalParentState(
        a["run_id"], state.scope, a["command_id"], a["request"], manifest, depth=1
    )
    b = dispatch(mid, "leaf", "two")
    leaf = TemporalRunState(b["run_id"], state.scope, b["command_id"], b["request"], manifest)
    action, _ = leaf.next_operation()
    leaf.accept_model(action["id"], {"ok": True, "output": "answer", "tool_calls": [], "usage": {}})

    def proof(run):
        return {"scope": state.scope, "request": run.request, **run.diagnostics()}

    leaf_proof = proof(leaf)
    mid.observe(b["run_id"], leaf_proof)
    mid.next_calls()
    mid.accept_selection({"calls": [], "done": True, "result": "middle answer"})
    mid_proof = proof(mid)
    root.observe(a["run_id"], mid_proof)
    root.next_calls()
    root.accept_selection({"calls": [], "done": True, "result": "outer answer"})
    return state, {**proof(root), "descendants": [mid_proof, leaf_proof]}


@pytest.mark.parametrize("damage", ["missing", "foreign", "deferred-ack", "not-quiet"])
def test_nested_leaf_evidence_is_required_even_after_parent_is_terminal(damage):
    from relf_agent.errors import DefinitionMismatch

    state, proof = nested_proof()
    damaged = copy.deepcopy(proof)
    if damage == "missing":
        damaged["descendants"].pop()
    elif damage == "foreign":
        damaged["descendants"][-1]["request"]["input"] = "foreign"
    elif damage == "deferred-ack":
        damaged["descendants"][-1]["workflow"]["deferred_evidence_acks"] = 1
    else:
        damaged["descendants"][-1]["workflow"]["quiescent"] = False
    if damage in {"missing", "foreign"}:
        with pytest.raises(DefinitionMismatch):
            state.adopt_observation(damaged)
    else:
        assert state.adopt_observation(damaged) is False
    assert state.snapshot()["busy"]
    assert state.adopt_observation(proof)
    assert not state.snapshot()["busy"]


def test_original_run_quiescence_and_ack_are_required_before_next_turn():
    state, runtime = session()
    submit(state)
    intent = state.start_intent()
    run = TemporalRunState(
        intent["run_id"], state.scope, intent["command_id"], intent["request"], runtime.manifest
    )
    action, _ = run.next_operation()
    assert action["kind"] == "model"
    run.accept_model(action["id"], {"ok": True, "output": "answer", "tool_calls": [], "usage": {}})
    proof = {"scope": state.scope, "request": run.request, **run.diagnostics()}
    blocked = copy.deepcopy(proof)
    blocked["workflow"]["deferred_evidence_acks"] = 1
    assert state.adopt_observation(blocked) is False
    assert state.snapshot()["busy"] is True
    assert state.adopt_observation(proof) is True
    second = submit(state, "second", "follow up")
    assert second["outcome"]["turn"]["turn_seq"] == 2
    assert state.start_intent()["request"]["session_history"] == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


@pytest.mark.parametrize(
    "damage",
    [
        "wrong-scope",
        "wrong-request",
        "wrong-run",
        "wrong-release",
        "false-quiescence",
        "unknown-credit",
        "reserved-credit",
        "pending-ack",
        "truthy-quiescence",
    ],
)
def test_unconfirmed_or_foreign_run_cannot_release_lane(damage):
    from relf_agent.errors import RalfError

    state, runtime = session()
    submit(state)
    intent = state.start_intent()
    run = TemporalRunState(
        intent["run_id"], state.scope, intent["command_id"], intent["request"], runtime.manifest
    )
    action, _ = run.next_operation()
    run.accept_model(action["id"], {"ok": True, "output": "answer", "tool_calls": [], "usage": {}})
    proof = {"scope": state.scope, "request": run.request, **run.diagnostics()}
    if damage == "wrong-scope":
        proof["scope"] = {"workspace": "other", "principal": "other"}
    elif damage == "wrong-request":
        proof["request"]["input"] = "forged"
    elif damage == "wrong-run":
        proof["snapshot"]["run_id"] = "different"
    elif damage == "wrong-release":
        proof["release_digest"] = "0" * 64
    elif damage == "false-quiescence":
        proof["workflow"]["quiescent"] = False
    elif damage == "truthy-quiescence":
        proof["workflow"]["quiescent"] = "false"
    elif damage == "unknown-credit":
        proof["budget"]["unknown"] = 1
    elif damage == "reserved-credit":
        proof["budget"]["reserved"] = 1
    else:
        proof["workflow"]["evidence_ack_pending"] = True
    try:
        assert state.adopt_observation(proof) is False
    except RalfError:
        pass
    assert state.snapshot()["busy"] is True


def test_idle_rebind_cas_preserves_old_open_receipt_and_ref_replay():
    state, _ = session()
    old = state.ref.to_dict()
    changed = copy.deepcopy(state.binding)
    changed["request"]["definition"]["steps"][0]["instructions"] = "New instruction"
    receipt = state.command(
        {
            "kind": "rebind",
            "scope": state.scope,
            "command_id": "rebind",
            "session_ref": old,
            "expected_binding_revision": 1,
            "binding": changed,
        }
    )
    assert receipt["outcome"]["session_ref"]["binding_revision"] == 2
    refused = submit(state, "stale", ref=old)
    assert refused["outcome"]["error"] == "session_binding_mismatch"
    assert submit(state, "current")["outcome"]["turn"]["session"]["binding_revision"] == 2
    assert state.receipts["open"]["outcome"]["session_ref"] == old


@pytest.mark.parametrize("managed", [False, True])
def test_session_history_does_not_replace_current_knowledge_query(managed):
    import asyncio

    from relf_agent import (
        Document,
        InMemoryKnowledgeStore,
        KnowledgeContext,
        LexicalRetriever,
        ManagedContextPipeline,
    )
    from tests.test_temporal_binding_isolation import advance

    async def run():
        store = InMemoryKnowledgeStore()
        store.put(Scope(), "docs", Document("old", "old evidence"), expected_version=0)
        store.put(Scope(), "docs", Document("current", "current evidence"), expected_version=0)
        state, runtime = session(
            knowledge=KnowledgeContext(LexicalRetriever(store), namespace="docs"),
            context_builder=ManagedContextPipeline() if managed else None,
        )
        state.history = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
        ]
        submit(state, value="current")
        intent = state.start_intent()
        run = TemporalRunState(
            intent["run_id"], state.scope, intent["command_id"], intent["request"], runtime.manifest
        )
        for _ in range(12):
            if run.context_snapshot is not None:
                break
            await advance(runtime, run)
        assert run.context_snapshot is not None, run.snapshot()
        assert [r["value"]["document_id"] for r in run.context_snapshot["references"]] == [
            "current"
        ]

    asyncio.run(run())


@pytest.mark.parametrize("cancel_during_source_read", [False, True])
def test_closed_session_run_refuses_model_at_original_history_admission(cancel_during_source_read):
    import asyncio

    from relf_agent.types import digest

    async def check():
        from relf_agent import InMemoryKnowledgeStore, KnowledgeContext, LexicalRetriever

        entered, release = asyncio.Event(), asyncio.Event()

        class GatedKnowledge(KnowledgeContext):
            blocked = False

            async def validate(self, scope, references):
                if self.blocked:
                    entered.set()
                    await release.wait()
                return await super().validate(scope, references)

        knowledge = GatedKnowledge(LexicalRetriever(InMemoryKnowledgeStore()))
        state, runtime = session(**({"knowledge": knowledge} if cancel_during_source_read else {}))
        submit(state)
        intent = state.start_intent()
        run = TemporalRunState(
            intent["run_id"], state.scope, intent["command_id"], intent["request"], runtime.manifest
        )
        action, request = run.next_operation()
        if action["kind"] == "context":
            run.accept_context(action["id"], await runtime.prepare_context(request))
            action, request = run.next_operation()

        async def guard(value):
            return run.admit_context_dispatch(
                {
                    "scope": state.scope,
                    "run_id": run.run_id,
                    "action_id": action["id"],
                    "release_digest": run.release_digest,
                    "phase": "model",
                    "request_digest": digest(value),
                }
            )

        if cancel_during_source_read:
            knowledge.blocked = True
            pending = asyncio.create_task(runtime.complete_model(request, dispatch_guard=guard))
            await entered.wait()
            assert runtime.providers["default"].calls == []
            run.command("cancel", {"kind": "cancel", "scope": state.scope})
            release.set()
            result = await pending
        else:
            run.command("cancel", {"kind": "cancel", "scope": state.scope})
            result = await runtime.complete_model(request, dispatch_guard=guard)
        assert runtime.providers["default"].calls == []
        assert result["ok"] is False and result["dispatched"] is False

    asyncio.run(check())
