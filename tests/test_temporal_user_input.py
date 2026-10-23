"""Original Temporal state owns human questions and exact tool replies."""

import asyncio
import copy
import inspect
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, DynamicWorkflowSpec, ModelResponse, Scope, ToolCall, ToolRegistry
from relf_agent.errors import AuthorizationDenied, IdempotencyConflict, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_parent_state import TemporalParentState
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request
from tests.test_temporal_memory_bindings import grant


class QuestionProvider:
    identity = {"kind": "temporal-human-question-fixture", "version": "1"}

    async def complete(self, messages, tools):
        if not any(message.get("role") == "tool" for message in messages):
            return ModelResponse(
                tool_calls=(ToolCall("request_input", {"prompt": "Which item?"}, "question-call"),)
            )
        assert messages[-1] == {
            "role": "tool",
            "tool_call_id": "question-call",
            "content": '"wire"',
        }
        return ModelResponse(output="Selected wire")


def parts(*, policy=None, native=False):
    assert "user_input_policies" in inspect.signature(TemporalRuntime).parameters, (
        "Missing explicit Temporal input-policy registration"
    )
    from relf_agent.user_input import UserInputPolicy, register_user_input

    tools = ToolRegistry()
    register_user_input(tools, policy=policy or UserInputPolicy())
    options = {}
    if native:
        from relf_agent import CompleteModelHistory

        options.update(
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session"),
            enable_sessions=True,
        )
    runtime = TemporalRuntime(providers={"default": QuestionProvider()}, tools=tools, **options)
    request = submission_request(
        AgentSpec("answer", "Ask then answer", ("request_input",), max_decisions=3),
        "Choose an item",
        budget=4,
    )
    if native:
        request["session_history"] = []
    state = TemporalRunState("input-run", asdict(Scope()), "submit", request, runtime.manifest)
    return runtime, state


async def question(runtime, state):
    for _ in range(12):
        operation = state.next_operation()
        if operation is None:
            break
        action, request = operation
        assert action["kind"] != "tool", "Intrinsic must not dispatch a Tool Activity"
        if action["kind"] == "model":
            state.accept_model(
                action["id"],
                await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
            )
        elif action["kind"] == "model_adoption":
            state.accept_model_adoption(action["id"], await runtime.adopt_model(request))
        else:
            assert action["kind"] == "context"
            state.accept_context(
                action["id"],
                await runtime.prepare_context(request, dispatch_guard=lambda r: grant(state, r)),
            )
    assert state.state == "waiting_input", state.diagnostics()
    return state.snapshot()["pending"][0]


def reply(state, item, *, command="answer", value="wire", **options):
    return state.command(
        command,
        {
            "kind": "send_input",
            "scope": state.scope,
            "run_id": state.run_id,
            "pending_id": item["pending_id"],
            "digest": item["target_digest"],
            "value": value,
            **options,
        },
    )


@pytest.mark.parametrize("native", [False, True])
def test_intrinsic_wait_and_reply_preserve_original_action_without_effect_dispatch(native):
    async def run():
        runtime, state = parts(native=native)
        item = await question(runtime, state)
        before = copy.deepcopy(state.request)
        action = next(a for a in state.actions if a["kind"] == "tool")
        assert action["attempts"] == [] and state.budget["spent"] == 1
        assert state.pending_acks == [] and state.quiescent
        assert state.next_operation() is None
        restored = copy.deepcopy(state)
        receipt = reply(restored, item)
        assert receipt["apply_state"] == "applied" and restored.state == "running"
        assert reply(restored, item) == receipt
        assert restored.request == before
        action = next(a for a in restored.actions if a["kind"] == "tool")
        assert action["status"] == "completed" and action["result"] == "wire"
        assert action["receipt"]["source"] == "user-input" and action["attempts"] == []
        assert restored.pending_acks == [] and restored.budget["spent"] == 1
        assert restored.messages[-1] == {
            "role": "tool",
            "tool_call_id": "question-call",
            "content": '"wire"',
        }
        for _ in range(12):
            operation = restored.next_operation()
            if operation is None:
                break
            action, request = operation
            if action["kind"] == "model":
                restored.accept_model(
                    action["id"],
                    await runtime.complete_model(
                        request, dispatch_guard=lambda r: grant(restored, r)
                    ),
                )
            elif action["kind"] == "model_adoption":
                restored.accept_model_adoption(action["id"], await runtime.adopt_model(request))
            else:
                restored.accept_context(
                    action["id"],
                    await runtime.prepare_context(
                        request, dispatch_guard=lambda r: grant(restored, r)
                    ),
                )
        assert restored.state == "succeeded" and restored.result == "Selected wire"
        assert reply(restored, item) == receipt
        assert restored.budget["spent"] == 2
        if native:
            assert restored.native_history_episodes[0]["history"][3] == restored.messages[3]

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("schema", "invalid_input"),
        ("digest", "stale_pending_target"),
        ("revision", "version_conflict"),
        ("consumed", "stale_pending_target"),
        ("cancelled", "target_closed"),
    ],
)
def test_rejected_reply_is_stable_and_never_appends_or_dispatches(fault, reason):
    async def run():
        runtime, state = parts()
        item = await question(runtime, state)
        options, value = {}, "wire"
        if fault == "schema":
            value = 7
        elif fault == "digest":
            item = {**item, "target_digest": "0" * 64}
        elif fault == "revision":
            options["expected_state_revision"] = state.revision + 1
        elif fault == "consumed":
            reply(state, item)
        else:
            state.command("cancel", {"kind": "cancel", "scope": state.scope})
        before = copy.deepcopy((state.messages, state.input_requests, state.budget))
        receipt = reply(state, item, command="rejected", value=value, **options)
        assert receipt["apply_state"] == "rejected" and receipt["outcome"]["reason"] == reason
        assert reply(state, item, command="rejected", value=value, **options) == receipt
        assert (state.messages, state.input_requests, state.budget) == before
        with pytest.raises(IdempotencyConflict):
            reply(state, item, command="rejected", value="different", **options)

    asyncio.run(run())


def test_foreign_reply_fails_before_command_acceptance():
    async def run():
        runtime, state = parts()
        item = await question(runtime, state)
        before = copy.deepcopy(state.event_log)
        with pytest.raises(AuthorizationDenied):
            state.command(
                "foreign",
                {
                    "kind": "send_input",
                    "scope": {"workspace": "other", "principal": "owner"},
                    "run_id": state.run_id,
                    "pending_id": item["pending_id"],
                    "digest": item["target_digest"],
                    "value": "wire",
                },
            )
        assert state.event_log == before

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["flat", "dag"])
def test_selected_planner_question_resumes_new_revision_with_supplemental_lineage(mode):
    assert "user_input_policies" in inspect.signature(TemporalRuntime).parameters
    from relf_agent.user_input import UserInputPolicy

    runtime = TemporalRuntime(
        providers={"default": QuestionProvider()},
        tools=ToolRegistry(),
        user_input_policies={"ask": UserInputPolicy()},
    )
    spec = DynamicWorkflowSpec(
        "plan",
        {"worker": AgentSpec("worker", "Answer")},
        plan_mode=mode,
        max_revisions=2,
        input_policy="ask",
    )
    parent = TemporalParentState(
        "parent",
        asdict(Scope()),
        "submit",
        submission_request(spec, {"missing": True}, budget=16),
        runtime.orchestration_release,
    )
    parent.accept_selection({"status": "needs_input", "reason": "Which item?"})
    assert parent.state == "waiting_input" and parent.next_calls() == []
    item = parent.snapshot()["pending"][0]
    assert parent.result is None
    receipt = reply(parent, item)
    assert receipt["apply_state"] == "applied" and parent.planning_revision == 1
    assert parent.stage == "plan" and parent.request["input"] == {"missing": True}
    request = parent.planning_request()
    assert request["task"] == {"missing": True}
    assert request["clarifications"][0]["value"] == "wire"
    assert parent.input_requests[item["pending_id"]]["state"] == "answered"


def test_planner_cannot_create_wait_without_resume_revision():
    assert "user_input_policies" in inspect.signature(TemporalRuntime).parameters
    from relf_agent.user_input import UserInputPolicy

    runtime = TemporalRuntime(
        providers={"default": QuestionProvider()},
        tools=ToolRegistry(),
        user_input_policies={"ask": UserInputPolicy()},
    )
    spec = DynamicWorkflowSpec(
        "plan", {"worker": AgentSpec("worker", "Answer")}, max_revisions=1, input_policy="ask"
    )
    parent = TemporalParentState(
        "parent",
        asdict(Scope()),
        "submit",
        submission_request(spec, "task", budget=16),
        runtime.orchestration_release,
    )
    with pytest.raises(ValidationError):
        parent.accept_selection({"status": "needs_input", "reason": "Which item?"})
    assert not parent.input_requests and parent.state != "waiting_input"


def test_intrinsic_obeys_original_authorization_before_question_adoption():
    async def run():
        runtime, state = parts()

        def denied(scope, tool, arguments):
            raise AuthorizationDenied("Question denied")

        runtime.policy = denied
        runtime.policy_identity = {"kind": "denied-input", "version": "1"}
        runtime._manifest = runtime._current_manifest()
        state = TemporalRunState("denied", state.scope, "submit", state.request, runtime.manifest)
        action, request = state.next_operation()
        state.accept_model(
            action["id"],
            await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
        )
        assert state.state == "failed" and state.error["code"] == "authorization_denied"
        assert not state.input_requests and not any(a["kind"] == "tool" for a in state.actions)

    asyncio.run(run())


@pytest.mark.parametrize("native", [False, True])
def test_input_authorization_receives_detached_original_question_and_descriptor(native):
    async def run():
        runtime, initial = parts(native=native)
        original_spec = copy.deepcopy(runtime.tools.get("request_input").spec)
        authorized = []

        def policy(scope, tool, arguments):
            authorized.append(copy.deepcopy((scope, tool, arguments)))
            arguments["prompt"] = "Changed by authorization callback"
            tool.config["user_input"]["max_requests"] = 999
            tool.input_schema["properties"]["prompt"]["maxLength"] = 1

        runtime.policy = policy
        runtime.policy_identity = {"kind": "mutating-input-authorization", "version": "1"}
        runtime._manifest = runtime._current_manifest()
        state = TemporalRunState(
            "detached-authorization", initial.scope, "submit", initial.request, runtime.manifest
        )
        item = await question(runtime, state)
        assert len(authorized) == 1 and authorized[0][2] == {"prompt": "Which item?"}
        assert runtime.tools.get("request_input").spec == original_spec
        assert item["prompt"] == "Which item?"
        action = next(a for a in state.actions if a["kind"] == "tool")
        assert action["arguments"] == {"prompt": "Which item?"}
        assert action["call_id"] == "question-call"
        assert reply(state, item)["apply_state"] == "applied"
        for _ in range(12):
            operation = state.next_operation()
            if operation is None:
                break
            action, request = operation
            if action["kind"] == "model":
                state.accept_model(
                    action["id"],
                    await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
                )
            elif action["kind"] == "model_adoption":
                state.accept_model_adoption(action["id"], await runtime.adopt_model(request))
            else:
                state.accept_context(
                    action["id"],
                    await runtime.prepare_context(
                        request, dispatch_guard=lambda r: grant(state, r)
                    ),
                )
        assert state.state == "succeeded" and state.result == "Selected wire"

    asyncio.run(run())


@pytest.mark.parametrize("native", [False, True])
def test_input_authorization_rechecks_runtime_release_before_returning_evidence(native):
    async def run():
        runtime, initial = parts(native=native)

        def policy(scope, tool, arguments):
            runtime.tools._tools["request_input"].spec.config["user_input"]["max_requests"] = 999

        runtime.policy = policy
        runtime.policy_identity = {"kind": "changing-input-release", "version": "1"}
        runtime._manifest = runtime._current_manifest()
        state = TemporalRunState(
            "changed-authorization-release",
            initial.scope,
            "submit",
            initial.request,
            runtime.manifest,
        )
        response = None
        for _ in range(12):
            action, request = state.next_operation()
            if action["kind"] == "context":
                state.accept_context(
                    action["id"],
                    await runtime.prepare_context(
                        request, dispatch_guard=lambda r: grant(state, r)
                    ),
                )
            elif action["kind"] == "model":
                response = await runtime.complete_model(
                    request, dispatch_guard=lambda r: grant(state, r)
                )
                if native:
                    state.accept_model(action["id"], response)
                else:
                    break
            else:
                response = await runtime.adopt_model(request)
                break
        assert response["ok"] is False and response["code"] == "definition_mismatch"
        assert "input_authorization" not in response
        assert not state.input_requests

    asyncio.run(run())


def test_copied_intrinsic_configuration_does_not_create_a_wait():
    async def run():
        from relf_agent.tools import ToolSpec
        from relf_agent.user_input import UserInputPolicy, register_user_input

        original = ToolRegistry()
        register_user_input(original, policy=UserInputPolicy())
        tools = ToolRegistry()

        async def ordinary(arguments, context):
            return "ordinary"

        tools.register(ToolSpec(**asdict(original.get("request_input").spec)), ordinary)
        runtime = TemporalRuntime(providers={"default": QuestionProvider()}, tools=tools)
        assert "user_input_protocol" not in runtime.manifest
        state = TemporalRunState(
            "ordinary",
            asdict(Scope()),
            "submit",
            submission_request(AgentSpec("a", "Answer", ("request_input",)), "task", budget=4),
            runtime.manifest,
        )
        action, request = state.next_operation()
        state.accept_model(
            action["id"],
            await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
        )
        operation = state.next_operation()
        assert operation[0]["kind"] == "tool" and state.state == "running"

    asyncio.run(run())


def test_tampered_original_tool_source_cannot_receive_a_reply():
    async def run():
        runtime, state = parts()
        item = await question(runtime, state)
        action = next(a for a in state.actions if a["kind"] == "tool")
        action["arguments"] = {"prompt": "Changed question"}
        before = copy.deepcopy(state.messages)
        receipt = reply(state, item)
        assert receipt["apply_state"] == "rejected"
        assert state.messages == before and state.state == "waiting_input"

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["different_prompt", "prompt_exceeds_policy"])
@pytest.mark.parametrize("surface", ["records", "snapshot", "send_input", "observed_journal"])
def test_restored_input_request_must_match_original_tool_question(fault, surface):
    async def run():
        from relf_agent.errors import DefinitionMismatch
        from relf_agent.temporal_user_input import observed_journal, records
        from relf_agent.types import digest
        from relf_agent.user_input import PendingInput, UserInputPolicy

        policy = (
            UserInputPolicy(max_prompt_chars=len("Which item?"))
            if (fault == "prompt_exceeds_policy")
            else UserInputPolicy()
        )
        runtime, state = parts(policy=policy, native=True)
        item = await question(runtime, state)
        proof = copy.deepcopy({**state.diagnostics(), "scope": state.scope})
        restored = copy.deepcopy(state)
        record = restored.input_requests[item["pending_id"]]
        original = copy.deepcopy(record["request"])
        record["request"]["prompt"] = (
            "x" * (policy.max_prompt_chars + 1)
            if fault == "prompt_exceeds_policy"
            else "Different question from the accepted tool call"
        )
        record["request"]["target_digest"] = digest(
            {key: value for key, value in record["request"].items() if key != "target_digest"}
        )
        assert PendingInput.from_dict(record["request"]).to_dict() == record["request"]
        assert record["request"]["source"] == original["source"]
        assert record["request"]["pending_id"] == original["pending_id"]
        action = next(a for a in restored.actions if a["kind"] == "tool")
        assert action["arguments"] == {"prompt": "Which item?"}
        if surface == "records":
            with pytest.raises(DefinitionMismatch):
                records(restored)
        elif surface == "snapshot":
            with pytest.raises(DefinitionMismatch):
                restored.snapshot()
        elif surface == "observed_journal":
            proof["input_requests"] = copy.deepcopy(restored.input_requests)
            with pytest.raises(DefinitionMismatch):
                observed_journal(proof, restored.request)
        else:
            before = copy.deepcopy((restored.messages, restored.input_requests, restored.budget))
            forged = {**item, "target_digest": record["request"]["target_digest"]}
            receipt = reply(restored, forged)
            assert receipt["apply_state"] == "rejected"
            assert receipt["outcome"] == {"error": "definition_mismatch"}
            assert (restored.messages, restored.input_requests, restored.budget) == before
            assert restored.state == "waiting_input"
            assert reply(restored, forged) == receipt

    asyncio.run(run())


def test_deferred_policy_registry_is_rejected_without_iteration():
    observed = []

    def policies():
        observed.append("iterated")
        yield "ask", object()

    value = policies()
    try:
        with pytest.raises(ValidationError):
            TemporalRuntime(
                providers={"default": QuestionProvider()},
                tools=ToolRegistry(),
                user_input_policies=value,
            )
        assert observed == []
    finally:
        value.close()


def test_malformed_null_revision_is_not_an_accepted_command():
    async def run():
        runtime, state = parts()
        item = await question(runtime, state)
        before = copy.deepcopy(state.event_log)
        with pytest.raises(ValidationError):
            reply(state, item, expected_state_revision=None)
        assert state.event_log == before
        assert "answer" not in state.receipts

    asyncio.run(run())


def test_parent_completion_preserves_child_reply_lineage_without_business_receipt():
    async def run():
        from relf_agent import CompleteModelHistory, ParentCompletionPolicy, TeamSpec
        from relf_agent.temporal_parent_completion_state import source
        from relf_agent.user_input import register_user_input
        from tests.test_temporal_parent_completion import Gate

        tools = ToolRegistry()
        register_user_input(tools)
        runtime = TemporalRuntime(
            providers={"default": QuestionProvider()},
            tools=tools,
            model_continuation=True,
            model_history=CompleteModelHistory(),
            parent_completion_policies={"checked": ParentCompletionPolicy(Gate())},
        )
        spec = TeamSpec(
            "team",
            {"worker": AgentSpec("ask", "Ask then answer", ("request_input",))},
            child_budget=4,
            completion_policy="checked",
        )
        parent = TemporalParentState(
            "parent",
            asdict(Scope()),
            "submit",
            submission_request(spec, "Choose an item", budget=8),
            runtime.orchestration_release,
        )
        parent.accept_selection(
            {"calls": [{"id": "one", "member": "worker", "input": "Choose an item"}], "done": False}
        )
        call = parent.next_calls()[0]
        child = TemporalRunState(
            call["run_id"], parent.scope, call["command_id"], call["request"], parent.manifest
        )
        item = await question(runtime, child)
        parent.observe(child.run_id, {**child.diagnostics(), "scope": child.scope})
        assert parent.state == "waiting_input" and parent.budget["reserved"] == 4
        reply(child, item)
        for _ in range(10):
            operation = child.next_operation()
            if operation is None:
                break
            action, request = operation
            if action["kind"] == "model":
                child.accept_model(
                    action["id"],
                    await runtime.complete_model(request, dispatch_guard=lambda r: grant(child, r)),
                )
            else:
                child.accept_model_adoption(action["id"], await runtime.adopt_model(request))
        assert child.state == "succeeded"
        parent.observe(child.run_id, {**child.diagnostics(), "scope": child.scope})
        data = source(parent, child.result)
        assert data["receipts"] == []
        assert data["clarifications"][0]["request"]["owner"]["run_id"] == child.run_id
        assert data["clarifications"][0]["value"] == "wire"
        assert data["task"] == "Choose an item"

    asyncio.run(run())


def test_answered_journal_cannot_mask_a_changed_native_tool_reply():
    async def run():
        from relf_agent.errors import DefinitionMismatch

        runtime, state = parts(native=True)
        item = await question(runtime, state)
        reply(state, item)
        action = next(a for a in state.actions if a["kind"] == "tool")
        action["result"] = "forged"
        with pytest.raises(DefinitionMismatch):
            state.snapshot()

    asyncio.run(run())


@pytest.mark.parametrize("limit", ["budget", "decisions"])
def test_reply_preserves_original_exhausted_allowance(limit):
    async def run():
        runtime, original = parts()
        request = copy.deepcopy(original.request)
        if limit == "budget":
            request["budget"] = 1
        else:
            request["definition"]["steps"][0]["max_decisions"] = 1
        state = TemporalRunState("bounded", original.scope, "submit", request, runtime.manifest)
        item = await question(runtime, state)
        receipt = reply(state, item)
        assert receipt["apply_state"] == "applied"
        assert state.next_operation() is None
        assert state.state == "failed" and state.error["code"] == (
            "budget_exceeded" if limit == "budget" else "decision_limit"
        )
        assert state.budget["spent"] == 1 and state.budget["reserved"] == 0
        assert len([a for a in state.actions if a["kind"] == "model" and a["attempts"]]) == 1
        assert reply(state, item) == receipt

    asyncio.run(run())


def test_intrinsic_cannot_share_a_model_decision_with_a_business_tool():
    async def run():
        from relf_agent.tools import ToolSpec
        from relf_agent.user_input import register_user_input

        class Mixed(QuestionProvider):
            identity = {"kind": "mixed-input-fixture", "version": "1"}

            async def complete(self, messages, tools):
                return ModelResponse(
                    tool_calls=(
                        ToolCall("request_input", {"prompt": "Which item?"}, "ask"),
                        ToolCall("business", {}, "write"),
                    )
                )

        tools = ToolRegistry()
        register_user_input(tools)

        def forbidden(arguments, context):
            raise AssertionError("Business tool must never execute")

        tools.register(ToolSpec("business", "Business action", {"type": "object"}), forbidden)
        runtime = TemporalRuntime(providers={"default": Mixed()}, tools=tools)
        state = TemporalRunState(
            "mixed",
            asdict(Scope()),
            "submit",
            submission_request(
                AgentSpec("a", "Ask", ("request_input", "business")), "task", budget=4
            ),
            runtime.manifest,
        )
        action, request = state.next_operation()
        state.accept_model(
            action["id"],
            await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
        )
        assert state.state == "failed" and not state.input_requests
        assert not any(a["kind"] == "tool" for a in state.actions)
        assert state.budget["spent"] == 1

    asyncio.run(run())


def test_planner_question_cannot_replace_its_accepted_original_conclusion():
    from relf_agent.errors import DefinitionMismatch
    from relf_agent.types import digest
    from relf_agent.user_input import UserInputPolicy, make_input_record

    policy = UserInputPolicy()
    runtime = TemporalRuntime(
        providers={"default": QuestionProvider()},
        tools=ToolRegistry(),
        user_input_policies={"ask": policy},
    )
    spec = DynamicWorkflowSpec(
        "plan", {"worker": AgentSpec("worker", "Answer")}, max_revisions=2, input_policy="ask"
    )
    parent = TemporalParentState(
        "parent",
        asdict(Scope()),
        "submit",
        submission_request(spec, "original", budget=16),
        runtime.orchestration_release,
    )
    parent.accept_selection({"status": "needs_input", "reason": "Original question"})
    forged = make_input_record(
        run_id=parent.run_id,
        release_digest=parent.release_digest,
        scope=parent.scope,
        source={
            "kind": "planner",
            "revision": 0,
            "proposal_digest": digest({"status": "needs_input", "reason": "Forged question"}),
        },
        prompt="Forged question",
        policy=policy,
        ordinal=1,
    )
    parent.input_requests = {forged["request"]["pending_id"]: forged}
    with pytest.raises(DefinitionMismatch):
        parent.snapshot()
