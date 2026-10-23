import asyncio
import copy
from dataclasses import asdict

from relf_agent import InMemoryArtifactStore, Scope
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import digest, submission_request
from tests.test_composite_data_context import Provider, agent, registry
from tests.test_managed_data_context import context


def setup(store=None, provider=None, *, budget=32, **options):
    store = InMemoryArtifactStore(backend_id="artifacts") if store is None else store
    provider = Provider() if provider is None else provider
    writes = []
    runtime = TemporalRuntime(
        providers={"default": provider},
        tools=registry(writes),
        context_builder=context(store, mode="model", summary_max_chars=256, **options),
    )
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "s",
        submission_request(agent(), "task", budget=budget),
        runtime.manifest,
    )
    return runtime, state, provider, writes


async def grant(state, request):
    return state.admit_context_dispatch(
        {
            "scope": request["scope"],
            "action_id": request["action_id"],
            "release_digest": request["release_digest"],
            "phase": request.get("phase", "model"),
            "request_digest": digest(request),
        }
    )


async def managed(runtime, state, request):
    return await runtime.manage_context(request, dispatch_guard=lambda value: grant(state, value))


async def completed(runtime, state, request):
    return await runtime.complete_model(request, dispatch_guard=lambda value: grant(state, value))


async def step(runtime, state):
    action, request = state.next_operation()
    if action["kind"] == "managed_context":
        response = await managed(runtime, state, request)
        state.accept_managed_context(action["id"], response)
    elif action["kind"] == "model":
        state.accept_model(action["id"], await completed(runtime, state, request))
    else:
        state.accept_tool(action["id"], await runtime.execute_tool(request))
    return action, request


async def finish(runtime, state):
    for _ in range(100):
        if state.state in {"succeeded", "failed", "cancelled"}:
            break
        await step(runtime, state)
    assert state.state == "succeeded", state.snapshot()


def test_history_stages_use_original_effects_and_summary_budget():
    async def run():
        runtime, state, provider, writes = setup()
        await finish(runtime, state)
        assert len(writes) == 4 and provider.summaries >= 1
        assert state.budget["spent"] == 5 + provider.summaries
        assert state.budget["unknown"] == 0
        phases = [a["phase"] for a in state.actions if a["kind"] == "managed_context"]
        assert {"plan", "read", "write", "verify", "summary", "finalize"} <= set(phases)
        assert all(s["status"] == "completed" for s in state.managed_context_stages.values())
        assert "BIG" * 4000 in str(state.messages)
        assert runtime.manifest["kernel"] == "temporal-2"

    asyncio.run(run())


class LostAckStore(InMemoryArtifactStore):
    def __init__(self):
        super().__init__(backend_id="artifacts")
        self.puts = 0

    def put(self, *args, **kwargs):
        self.puts += 1
        super().put(*args, **kwargs)
        raise RuntimeError("acknowledgement lost")


def test_artifact_write_lost_acknowledgement_is_read_verified_without_repeated_put():
    async def run():
        store = LostAckStore()
        runtime, state, _, writes = setup(store)
        await finish(runtime, state)
        assert store.puts == 1 and len(writes) == 4
        assert any(e["kind"] == "context_artifact_verified" for e in state.event_log)

    asyncio.run(run())


def test_summary_response_survives_state_restore_without_second_model_call():
    async def run():
        runtime, state, provider, writes = setup()
        while True:
            action, _ = await step(runtime, state)
            if action.get("phase") == "summary":
                break
        before = provider.summaries
        restored = copy.deepcopy(state)
        assert any(e["kind"] == "context_summary_response_recorded" for e in restored.event_log)
        action, _ = await step(runtime, restored)
        assert action["phase"] == "finalize" and provider.summaries == before
        await finish(runtime, restored)
        original_key = action["stage_key"]
        assert (
            len(
                [
                    a
                    for a in restored.actions
                    if a.get("phase") == "summary" and a["stage_key"] == original_key
                ]
            )
            == 1
        )
        assert len(writes) == 4

    asyncio.run(run())


def test_cancel_during_artifact_read_prevents_new_write_and_model():
    async def run():
        runtime, state, provider, writes = setup()
        while True:
            operation = state.next_operation()
            action, request = operation
            if action.get("phase") == "read":
                break
            if action["kind"] == "managed_context":
                state.accept_managed_context(action["id"], await managed(runtime, state, request))
            elif action["kind"] == "model":
                state.accept_model(action["id"], await completed(runtime, state, request))
            else:
                state.accept_tool(action["id"], await runtime.execute_tool(request))
        response = await managed(runtime, state, request)
        state.command("cancel", {"scope": state.scope, "kind": "cancel"})
        state.accept_managed_context(action["id"], response)
        assert state.next_operation() is None
        assert state.quiescent and state.state == "cancelled"
        assert len(writes) == 1 and len(provider.requests) == 1
        assert not runtime.context.artifacts._records

    asyncio.run(run())


def test_summary_unknown_holds_credit_and_falls_back_without_retry():
    class Unknown(Provider):
        async def complete(self, messages, tools):
            if messages[0]["content"].startswith("context-summary:"):
                self.summaries += 1
                raise RuntimeError("summary response lost")
            return await super().complete(messages, tools)

    async def run():
        runtime, state, provider, writes = setup(provider=Unknown())
        await finish(runtime, state)
        assert state.budget["unknown"] >= 1
        assert not state.quiescent
        assert len(writes) == 4 and provider.summaries >= 1
        assert all(
            a["attempts"][0]["status"] == "unknown"
            for a in state.actions
            if a.get("phase") == "summary"
        )

    asyncio.run(run())


def test_previously_verified_artifact_disappearance_never_rewrites():
    async def run():
        runtime, state, provider, writes = setup()
        while len(writes) < 2:
            await step(runtime, state)
        artifact = next(iter(state.context_artifact_receipts))
        runtime.context.artifacts._records.clear()
        while state.state not in {"failed", "succeeded"}:
            await step(runtime, state)
        assert state.state == "failed" and state.error["code"] == "context_artifact_unavailable"
        assert len(state.context_artifact_dispatches) == 1
        assert artifact in state.context_artifact_receipts
        assert len(writes) == 2

    asyncio.run(run())


def test_actual_artifact_target_changed_after_await_refuses_disclosure():
    class Moving(InMemoryArtifactStore):
        async def put(self, *args, **kwargs):
            return super().put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            runtime.context.artifacts = InMemoryArtifactStore(backend_id="artifacts")
            return super().get(*args, **kwargs)

    async def run():
        nonlocal runtime
        runtime, state, provider, writes = setup(store=Moving(backend_id="artifacts"))
        while state.state not in {"failed", "succeeded"}:
            await step(runtime, state)
        assert state.state == "failed" and state.error["code"] == "definition_mismatch"
        assert len(writes) == 1 and len(provider.requests) == 1

    runtime = None
    asyncio.run(run())


def test_late_summary_after_cancel_is_settled_without_business_dispatch():
    class Late(Provider):
        async def complete(self, messages, tools):
            response = await super().complete(messages, tools)
            if messages[0]["content"].startswith("context-summary:"):
                state.command("cancel", {"scope": state.scope, "kind": "cancel"})
            return response

    async def run():
        nonlocal state
        runtime, state, provider, writes = setup(provider=Late())
        while True:
            action, request = state.next_operation()
            if action.get("phase") == "summary":
                break
            if action["kind"] == "managed_context":
                state.accept_managed_context(action["id"], await managed(runtime, state, request))
            elif action["kind"] == "model":
                state.accept_model(action["id"], await completed(runtime, state, request))
            else:
                state.accept_tool(action["id"], await runtime.execute_tool(request))
        response = await managed(runtime, state, request)
        state.accept_managed_context(action["id"], response)
        assert state.next_operation() is None and state.quiescent
        assert state.budget["reserved"] == 0 and state.budget["unknown"] == 0
        assert state.reservations[action["attempts"][0]["id"]]["actual"] == 1
        assert provider.summaries == 1 and len(writes) == 3

    state = None
    asyncio.run(run())


def test_provider_replacement_during_artifact_validation_prevents_model_disclosure():
    class Store(InMemoryArtifactStore):
        moving = False

        async def put(self, *args, **kwargs):
            return super().put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            if self.moving:
                runtime.providers["default"] = Provider()
            return value

    async def run():
        nonlocal runtime
        store = Store(backend_id="artifacts")
        runtime, state, provider, writes = setup(store=store)
        while True:
            action, request = state.next_operation()
            if action["kind"] == "model" and request.get("context", {}).get(
                "context_identity", {}
            ).get("artifact_projection"):
                break
            if action["kind"] == "managed_context":
                state.accept_managed_context(action["id"], await managed(runtime, state, request))
            elif action["kind"] == "model":
                state.accept_model(action["id"], await completed(runtime, state, request))
            else:
                state.accept_tool(action["id"], await runtime.execute_tool(request))
        store.moving = True
        response = await completed(runtime, state, request)
        assert not response["ok"] and not response["dispatched"]
        assert response["code"] == "definition_mismatch"
        assert len(provider.requests) == 1 and not runtime.providers["default"].requests

    runtime = None
    asyncio.run(run())


def test_completed_malformed_summary_is_charged_once_and_uses_frozen_fallback():
    class Invalid(Provider):
        async def complete(self, messages, tools):
            if messages[0]["content"].startswith("context-summary:"):
                self.summaries += 1
                return {"text": "wrong response type"}
            return await super().complete(messages, tools)

    async def run():
        runtime, state, provider, writes = setup(provider=Invalid())
        await finish(runtime, state)
        assert state.budget["unknown"] == 0
        assert state.budget["spent"] == 5 + provider.summaries
        summaries = [a for a in state.actions if a.get("phase") == "summary"]
        assert all(a["received_response"]["invalid_fields"] == ["response"] for a in summaries)

    asyncio.run(run())


def test_real_knowledge_context_port_integrates_with_managed_temporal_context():
    from relf_agent import InMemoryKnowledgeStore, KnowledgeContext, LexicalRetriever

    async def run():
        runtime, state, provider, writes = setup()
        runtime = TemporalRuntime(
            providers=runtime.providers,
            tools=runtime.tools,
            context_builder=runtime.context,
            knowledge=KnowledgeContext(
                LexicalRetriever(InMemoryKnowledgeStore()), namespace="docs"
            ),
        )
        state = TemporalRunState("run", asdict(Scope()), "s", state.request, runtime.manifest)
        await finish(runtime, state)
        assert len(writes) == 4

    asyncio.run(run())


def test_uncertain_artifact_writer_stays_nonquiescent_after_later_tools():
    async def run():
        runtime, state, provider, writes = setup()
        while True:
            action, request = state.next_operation()
            if action.get("phase") == "write":
                break
            if action["kind"] == "managed_context":
                state.accept_managed_context(action["id"], await managed(runtime, state, request))
            elif action["kind"] == "model":
                state.accept_model(action["id"], await completed(runtime, state, request))
            else:
                state.accept_tool(action["id"], await runtime.execute_tool(request))
        assert (await managed(runtime, state, request))["ok"]  # committed payload, result lost
        state.accept_managed_context(
            action["id"],
            {
                "ok": False,
                "code": "activity_outcome_unknown",
                "dispatched": True,
                "execution_uncertain": True,
            },
        )
        assert state.remote_uncertain
        await finish(runtime, state)
        assert state.remote_uncertain and not state.quiescent
        assert action["status"] == "outcome_unknown"

    asyncio.run(run())


def test_cancel_during_final_artifact_read_prevents_new_provider_request():
    class Store(InMemoryArtifactStore):
        cancel = False

        async def put(self, *args, **kwargs):
            return super().put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            if self.cancel:
                state.command("cancel-during-get", {"scope": state.scope, "kind": "cancel"})
            return value

    async def run():
        nonlocal state
        store = Store(backend_id="artifacts")
        runtime, state, provider, writes = setup(store=store)
        while True:
            action, request = state.next_operation()
            if action["kind"] == "model" and request.get("context", {}).get(
                "context_identity", {}
            ).get("artifact_projection"):
                break
            if action["kind"] == "managed_context":
                state.accept_managed_context(action["id"], await managed(runtime, state, request))
            elif action["kind"] == "model":
                state.accept_model(action["id"], await completed(runtime, state, request))
            else:
                state.accept_tool(action["id"], await runtime.execute_tool(request))
        store.cancel = True
        response = await completed(runtime, state, request)
        assert state.state == "cancelled" and len(provider.requests) == 1
        assert not response["ok"] and not response["dispatched"]

    state = None
    asyncio.run(run())


def test_real_knowledge_version_changed_during_artifact_await_blocks_provider():
    from relf_agent import Document, InMemoryKnowledgeStore, KnowledgeContext, LexicalRetriever

    store = InMemoryKnowledgeStore()
    store.put(Scope(), "docs", Document("guide", "task evidence " * 60), expected_version=0)

    class Artifacts(InMemoryArtifactStore):
        moving = False

        async def put(self, *args, **kwargs):
            return super().put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            if self.moving:
                store.put(Scope(), "docs", Document("guide", "replaced"), expected_version=1)
                self.moving = False
            return value

    async def run():
        artifacts = Artifacts(backend_id="artifacts")
        initial, state, provider, writes = setup(store=artifacts)
        runtime = TemporalRuntime(
            providers=initial.providers,
            tools=initial.tools,
            context_builder=initial.context,
            knowledge=KnowledgeContext(LexicalRetriever(store), namespace="docs", max_chars=8000),
        )
        state = TemporalRunState("run", asdict(Scope()), "s", state.request, runtime.manifest)
        while True:
            action, request = state.next_operation()
            if action["kind"] == "model" and request.get("context", {}).get(
                "context_identity", {}
            ).get("artifact_projection"):
                break
            if action["kind"] == "managed_context":
                state.accept_managed_context(action["id"], await managed(runtime, state, request))
            elif action["kind"] == "model":
                state.accept_model(action["id"], await completed(runtime, state, request))
            else:
                state.accept_tool(action["id"], await runtime.execute_tool(request))
        assert request["context"]["references"]
        artifacts.moving = True
        response = await completed(runtime, state, request)
        assert not response["ok"] and not response["dispatched"]
        assert len(provider.requests) == 1

    asyncio.run(run())


def test_unknown_artifact_execution_prevents_parent_allowance_release():
    from relf_agent import TeamSpec
    from relf_agent.temporal_parent_state import TemporalParentState

    async def run():
        runtime, _, _, _ = setup()
        parent = TemporalParentState(
            "parent",
            asdict(Scope()),
            "s",
            submission_request(
                TeamSpec("team", {"a": agent()}, child_budget=12), "task", budget=16
            ),
            runtime.orchestration_release,
        )
        parent.accept_selection(
            {"calls": [{"id": "a", "member": "a", "input": "task"}], "done": False, "result": None}
        )
        call = parent.next_calls()[0]
        child = TemporalRunState(
            call["run_id"], parent.scope, call["command_id"], call["request"], parent.manifest
        )
        while True:
            action, request = child.next_operation()
            if action.get("phase") == "write":
                break
            if action["kind"] == "managed_context":
                child.accept_managed_context(action["id"], await managed(runtime, child, request))
            elif action["kind"] == "model":
                child.accept_model(action["id"], await completed(runtime, child, request))
            else:
                child.accept_tool(action["id"], await runtime.execute_tool(request))
        assert (await managed(runtime, child, request))["ok"]
        child.accept_managed_context(
            action["id"],
            {
                "ok": False,
                "code": "activity_outcome_unknown",
                "dispatched": True,
                "execution_uncertain": True,
            },
        )
        await finish(runtime, child)
        evidence = {**child.diagnostics(), "scope": parent.scope}
        parent.observe(child.run_id, evidence)
        observed = parent.children[0]
        assert not observed["settled"]
        assert parent.budget["reserved"] + parent.budget["unknown"] == 12

    asyncio.run(run())
