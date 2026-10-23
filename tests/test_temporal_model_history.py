"""Complete accepted native history remains owned by original Temporal History."""

import asyncio
import copy
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentSpec,
    CompletionVerdict,
    ModelResponse,
    NativeHarness,
    Scope,
    ToolRegistry,
)
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState, validate_manifest
from relf_agent.types import digest, submission_request
from tests.test_temporal_memory_bindings import grant


class SignedFinal:
    identity = {"kind": "signed-final-history", "version": "1"}

    def __init__(self):
        self.calls = []

    @property
    def continuation_identity(self):
        return {"protocol": "signed-final-v1", "owner_digest": digest(self.identity)}

    async def complete(self, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        output = ' { "answer" : 42 } '
        return ContinuedModelResponse(
            output=output,
            continuation=ModelContinuation(
                "signed-final-v1",
                digest(self.identity),
                digest({"output": output, "tool_calls": []}),
                {"reasoning": "opaque-original-final", "turn": len(self.calls)},
            ),
        )


class AlwaysRetry:
    identity = {"kind": "retry-history", "version": "1"}

    def verify(self, request):
        return CompletionVerdict("retry", "Evidence needed")


def setup(*, history=True, provider=None, **kwargs):
    from relf_agent.model_history import CompleteModelHistory

    provider = provider or SignedFinal()
    runtime = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        model_continuation=True,
        model_history=CompleteModelHistory() if history is True else history,
        **kwargs,
    )
    definition = AgentSpec(
        "answer",
        "Answer",
        max_decisions=4,
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "integer"}},
            "required": ["answer"],
        },
    )
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "submit",
        submission_request(definition, "Question", budget=10),
        runtime.manifest,
    )
    return runtime, state, provider


async def model(runtime, state, *, adopt=True):
    action, request = state.next_operation()
    assert action["kind"] == "model"
    receipt = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
    state.accept_model(action["id"], receipt)
    if adopt and state.state != "failed":
        adoption, request = state.next_operation()
        assert adoption["kind"] == "model_adoption"
        state.accept_model_adoption(adoption["id"], await runtime.adopt_model(request))
    return action


def test_joint_seven_is_explicit_and_continuation_six_is_unchanged():
    runtime, _, _ = setup()
    assert runtime.manifest["binding_protocol"] == 7
    assert runtime.manifest["model_history_protocol"] == 1
    assert runtime.manifest["model_history"]["identity"]["allow_tool_result_projection"] is False
    validate_manifest(runtime.manifest)
    old = TemporalRuntime(
        providers={"default": SignedFinal()}, tools=ToolRegistry(), model_continuation=True
    )
    assert old.manifest["binding_protocol"] == 6
    assert "model_history" not in old.manifest


def test_final_raw_json_and_signature_saved_once_across_receipt_and_verification_restore():
    async def run():
        runtime, state, provider = setup(verifier=AlwaysRetry())
        await model(runtime, state, adopt=False)
        restored = copy.deepcopy(state)
        assert len(provider.calls) == 1 and len(restored.messages) == 2
        adoption, request = restored.next_operation()
        restored.accept_model_adoption(adoption["id"], await runtime.adopt_model(request))
        assert restored.messages[-1]["content"] == ' { "answer" : 42 } '
        assert (
            restored.messages[-1]["model_continuation"]["data"]["reasoning"]
            == "opaque-original-final"
        )
        recovered = copy.deepcopy(restored)
        verification, request = recovered.next_operation()
        assert verification["kind"] == "agent_completion"
        recovered.accept_completion(verification["id"], await runtime.verify_completion(request))
        assert [m["role"] for m in recovered.messages] == ["system", "user", "assistant", "user"]
        assert len(provider.calls) == 1
        await model(runtime, recovered)
        assert provider.calls[-1] == recovered.messages[:-1]
        assert len([m for m in recovered.messages if m["role"] == "assistant"]) == 2
        assert recovered.budget["spent"] == 2

    asyncio.run(run())


def test_signed_final_is_saved_for_success_without_verifier():
    async def run():
        runtime, state, _ = setup()
        await model(runtime, state)
        assert state.state == "succeeded" and state.result == {"answer": 42}
        assert state.messages[-1]["content"] == ' { "answer" : 42 } '
        assert copy.deepcopy(state).next_operation() is None

    asyncio.run(run())


def test_history_requires_opt_in_before_any_model_io():
    from relf_agent.model_history import CompleteModelHistory

    with pytest.raises(ValidationError):
        TemporalRuntime(
            providers={"default": SignedFinal()},
            tools=ToolRegistry(),
            model_history=CompleteModelHistory(),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_history_protocol", True),
        ("model_history_protocol", 2),
        ("model_history", {}),
        ("model_continuation_protocol", 2),
        ("binding_protocol", 6),
    ],
)
def test_history_manifest_rejects_missing_or_malformed_original_gates(field, value):
    runtime, _, _ = setup()
    manifest = runtime.manifest
    manifest[field] = value
    with pytest.raises((DefinitionMismatch, ValidationError)):
        validate_manifest(manifest)


class TruncatingHarness(NativeHarness):
    identity = {"kind": "truncating-history", "version": "1"}

    def prepare(self, spec, messages, tools):
        return super().prepare(spec, messages[:2], tools)


def test_actual_harness_request_cannot_truncate_accepted_final():
    async def run():
        runtime, state, provider = setup(verifier=AlwaysRetry(), harness=TruncatingHarness())
        await model(runtime, state)
        verification, request = state.next_operation()
        state.accept_completion(verification["id"], await runtime.verify_completion(request))
        await model(runtime, state)
        assert state.state == "failed" and len(provider.calls) == 1
        assert state.budget["spent"] == 1 and state.budget["unknown"] == 0

    asyncio.run(run())


def test_policy_registration_and_method_replacement_are_pinned():
    runtime, _, _ = setup()
    runtime.model_history.validate = lambda history, messages: None
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


async def advance(runtime, state):
    action, request = state.next_operation()
    if action["kind"] == "managed_context":
        response = await runtime.manage_context(request, dispatch_guard=lambda r: grant(state, r))
        state.accept_managed_context(action["id"], response)
    elif action["kind"] == "context":
        state.accept_context(action["id"], await runtime.prepare_context(request))
    elif action["kind"] == "model":
        state.accept_model(
            action["id"],
            await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
        )
    elif action["kind"] == "model_adoption":
        state.accept_model_adoption(action["id"], await runtime.adopt_model(request))
    elif action["kind"] == "agent_completion":
        state.accept_completion(action["id"], await runtime.verify_completion(request))
    else:
        state.accept_tool(action["id"], await runtime.execute_tool(request))
    return action


@pytest.mark.parametrize("allow_projection", [False, True])
def test_managed_artifact_projection_is_explicit_and_never_summarizes_native_chain(
    allow_projection,
):
    from relf_agent import InMemoryArtifactStore, ToolCall, ToolSpec
    from relf_agent.data_context import ManagedDataContext
    from relf_agent.model_history import CompleteModelHistory

    class Provider:
        identity = {"kind": "complete-artifact-provider", "version": "1"}

        def __init__(self):
            self.calls = []

        async def complete(self, messages, tools):
            self.calls.append(copy.deepcopy(messages))
            if len(self.calls) == 1:
                return ModelResponse(tool_calls=[ToolCall("read", {}, "original-call")])
            return ModelResponse(output="finished")

    async def run():
        store = InMemoryArtifactStore(backend_id="history-artifacts")
        provider, tools = Provider(), ToolRegistry()
        tools.register(
            ToolSpec("read", "Read", {"type": "object"}, cost=0), lambda args, ctx: "LARGE" * 2000
        )
        context = ManagedDataContext(store, mode="model", tool_result_chars=1024, preview_chars=32)
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=tools,
            context_builder=context,
            model_continuation=True,
            model_history=CompleteModelHistory(allow_tool_result_projection=allow_projection),
        )
        spec = AgentSpec("a", "Answer", tools=("read",), max_context_chars=2500)
        state = TemporalRunState(
            "run", asdict(Scope()), "s", submission_request(spec, "q", budget=10), runtime.manifest
        )
        for _ in range(35):
            if state.state in {"succeeded", "failed"}:
                break
            await advance(runtime, state)
            state = copy.deepcopy(state)
        assert not any(a.get("phase") == "summary" for a in state.actions)
        assert "LARGE" * 2000 in str(state.messages)
        if allow_projection:
            assert state.state == "succeeded", state.snapshot()
            assert len(provider.calls) == 2 and state.budget["spent"] == 2
            assert provider.calls[-1][-2]["tool_calls"][0]["id"] == "original-call"
            assert "Untrusted tool result" in provider.calls[-1][-1]["content"]
            assert len(store._records) == 1
            assert {a.get("phase") for a in state.actions} >= {"read", "write", "verify"}
        else:
            assert state.state == "failed" and state.error["code"] == "validation_error"
            assert len(provider.calls) == 1 and state.budget["spent"] == 1
            assert not store._records

    asyncio.run(run())


def test_original_history_rejects_forged_prepared_receipt_after_recording_model_evidence():
    async def run():
        runtime, state, provider = setup(verifier=AlwaysRetry())
        await model(runtime, state)
        verification, request = state.next_operation()
        state.accept_completion(verification["id"], await runtime.verify_completion(request))
        action, request = state.next_operation()
        receipt = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
        receipt["prepared_request"]["messages"] = receipt["prepared_request"]["messages"][:2]
        state.accept_model(action["id"], receipt)
        assert state.state == "failed" and len(provider.calls) == 2
        assert (
            action["received_response"]["continuation"]["data"]["reasoning"]
            == "opaque-original-final"
        )
        assert state.budget["spent"] == 2 and state.budget["unknown"] == 0
        assert len([m for m in state.messages if m["role"] == "assistant"]) == 1

    asyncio.run(run())


def test_joint_seven_does_not_implicitly_enable_context_or_tool_owners():
    from relf_agent.tool_execution import ToolExecutionOwner

    async def run():
        runtime, _, _ = setup(
            context_reads=True, tool_execution=ToolExecutionOwner(version="history-1")
        )
        manifest = runtime.manifest
        assert "context_read_protocol" in manifest and "tool_execution_protocol" in manifest
        for field in ("context_read_protocol", "tool_execution_protocol"):
            invalid = copy.deepcopy(manifest)
            invalid[field]["version"] = 2
            with pytest.raises(DefinitionMismatch):
                validate_manifest(invalid)
        await runtime.close_context_execution(wait_timeout=1)

    asyncio.run(run())


def test_joint_seven_artifact_bindings_keep_the_original_template_contract():
    from relf_agent.model_history import CompleteModelHistory
    from relf_agent.temporal_bindings import effective_manifest, selected_runtime
    from tests.test_artifact_binding_temporal import host, request

    old, stores = host()
    runtime = TemporalRuntime(
        providers=old.providers,
        tools=old.tools,
        context_builder=old.context,
        binding_catalog=old.binding_catalog,
        model_continuation=True,
        model_history=CompleteModelHistory(allow_tool_result_projection=True),
    )
    manifest = runtime.manifest
    assert manifest["binding_protocol"] == 7 and manifest["artifacts_binding_protocol"] == 1
    req = request()
    selected = effective_manifest(manifest, req["agent_bindings"]["agent"])
    actual = selected_runtime(
        runtime, {**req, "scope": asdict(Scope()), "step_bindings": req["agent_bindings"]["agent"]}
    )
    assert selected["context_builder"] == actual.context.identity
    assert selected["model_history"] == manifest["model_history"]
    invalid = copy.deepcopy(manifest)
    invalid["artifact_contexts"]["version"] = 2
    with pytest.raises(DefinitionMismatch):
        validate_manifest(invalid)
    assert all(not store._records for store in stores.values())


def test_joint_seven_sandbox_grants_keep_original_tool_owner(registered):
    from relf_agent import AgentBindingDescriptor, BindingCatalog, BindingSelection
    from relf_agent.binding_sandbox import SandboxBindingResource
    from relf_agent.model_history import CompleteModelHistory
    from relf_agent.temporal_bindings import effective_step
    from tests.test_sandbox_binding_execution import Reader

    registry, _ = registered
    catalog = BindingCatalog(scope=Scope())
    catalog.register("sandbox", "a", "1", SandboxBindingResource(registry, names=["a_sandbox_run"]))
    runtime = TemporalRuntime(
        providers={"default": Reader()},
        tools=registry,
        binding_catalog=catalog,
        context_reads=True,
        model_continuation=True,
        model_history=CompleteModelHistory(),
    )
    manifest = runtime.manifest
    assert manifest["binding_protocol"] == 7 and manifest["sandbox_binding_protocol"] == 1
    chosen = effective_step(
        asdict(AgentSpec("a", "Run", tools=("a_sandbox_run", "b_sandbox_run", "business"))),
        manifest,
        AgentBindingDescriptor(sandbox=BindingSelection.ref("a", "1")).to_dict(),
    )
    assert chosen["tools"] == ["a_sandbox_run", "business"]
    invalid = copy.deepcopy(manifest)
    invalid.pop("tool_execution_protocol")
    with pytest.raises(DefinitionMismatch):
        validate_manifest(invalid)
    asyncio.run(runtime.close_context_execution(wait_timeout=1))


from tests.test_sandbox_bindings import registered as registered  # noqa: E402,F401


def test_complete_history_budget_failure_does_not_dispatch_summary_or_second_business_model():
    from relf_agent.managed_context import ManagedContextPipeline
    from relf_agent.model_history import CompleteModelHistory

    class LargeFinal:
        identity = {"kind": "large-final", "version": "1"}

        def __init__(self):
            self.calls = []

        async def complete(self, messages, tools):
            self.calls.append(copy.deepcopy(messages))
            return ModelResponse(output="FINAL" * 200)

    async def run():
        provider = LargeFinal()
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            model_continuation=True,
            model_history=CompleteModelHistory(),
            context_builder=ManagedContextPipeline(mode="model"),
            verifier=AlwaysRetry(),
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "s",
            submission_request(AgentSpec("a", "Answer", max_context_chars=512), "q", budget=10),
            runtime.manifest,
        )
        for _ in range(25):
            if state.state in {"succeeded", "failed"}:
                break
            await advance(runtime, state)
        assert state.state == "failed" and state.error["code"] == "validation_error"
        assert len(provider.calls) == 1 and state.budget["spent"] == 1
        assert state.budget["unknown"] == 0
        assert not any(a.get("phase") == "summary" for a in state.actions)
        assert state.messages[-2]["content"] == "FINAL" * 200

    asyncio.run(run())


def test_custom_history_policy_cannot_bypass_framework_source_guard():
    from relf_agent.model_history import CompleteModelHistory

    class UnsafePolicy(CompleteModelHistory):
        @property
        def identity(self):
            return {"kind": "unsafe-history", "version": "1", "allow_tool_result_projection": False}

        def assemble(self, history, references, max_chars, *, context):
            return history[:2], {}

        def validate(self, history, messages):
            return None

    async def run():
        runtime, state, provider = setup(history=UnsafePolicy(), verifier=AlwaysRetry())
        await model(runtime, state)
        verification, request = state.next_operation()
        state.accept_completion(verification["id"], await runtime.verify_completion(request))
        await model(runtime, state)
        assert state.state == "failed" and len(provider.calls) == 1
        assert state.budget["spent"] == 1 and state.budget["unknown"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("value", [None, {"answer": 42}, "unstructured"])
def test_new_final_history_preserves_json_value_and_null_without_normalized_projection(value):
    from relf_agent.model_history import CompleteModelHistory
    from relf_agent.types import canonical

    class Provider:
        identity = {"kind": "raw-final", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output=value)

    async def run():
        runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            model_continuation=True,
            model_history=CompleteModelHistory(),
        )
        spec = AgentSpec("a", "Answer", output_schema={"type": "null"} if value is None else None)
        state = TemporalRunState(
            "run", asdict(Scope()), "s", submission_request(spec, "q"), runtime.manifest
        )
        await model(runtime, state)
        assert state.state == "succeeded", state.snapshot()
        assert state.messages[-1]["content"] == (
            value if value is None or isinstance(value, str) else canonical(value)
        )

    asyncio.run(run())


@pytest.mark.parametrize("signed", [False, True])
def test_plain_tool_history_preserves_pre_default_model_arguments_and_json_content(signed):
    from relf_agent import ToolCall
    from relf_agent.model_history import CompleteModelHistory
    from relf_agent.types import canonical

    class PlainProvider:
        identity = {"kind": "plain-history-defaults", "version": "1"}

        @property
        def continuation_identity(self):
            return (
                {"protocol": "json-tool-history-v1", "owner_digest": "c" * 64} if signed else None
            )

        async def complete(self, messages, tools):
            output = {"phase": "inspect"}
            calls = [ToolCall("calculate", {"quantity": 3}, "call-1")]
            if signed:
                return ContinuedModelResponse(
                    output=output,
                    tool_calls=calls,
                    continuation=ModelContinuation(
                        "json-tool-history-v1",
                        "c" * 64,
                        digest({"output": output, "tool_calls": [asdict(c) for c in calls]}),
                        {"signature": "json-tool"},
                    ),
                )
            return ModelResponse(output=output, tool_calls=calls)

    def calculate(quantity: int, price: int = 2):
        return quantity * price

    async def run():
        tools = ToolRegistry()
        tools.register_function(calculate, effect="read_only")
        runtime = TemporalRuntime(
            providers={"default": PlainProvider()},
            tools=tools,
            model_continuation=True,
            model_history=CompleteModelHistory(),
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "s",
            submission_request(AgentSpec("a", "Answer", tools=("calculate",)), "q"),
            runtime.manifest,
        )
        await model(runtime, state)
        tool = next(a for a in state.actions if a["kind"] == "tool")
        assert tool["arguments"] == {"quantity": 3, "price": 2}
        assert state.messages[-1]["tool_calls"][0]["function"]["arguments"] == canonical(
            {"quantity": 3}
        )
        assert state.messages[-1]["content"] == canonical({"phase": "inspect"})

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_joint_seven_recreates_only_once_fenced_context_or_plan_without_grant(managed):
    from relf_agent.context_pipeline import BudgetedContextAssembler
    from relf_agent.managed_context import ManagedContextPipeline

    async def run():
        runtime, state, provider = setup(
            context_reads=True,
            context_builder=ManagedContextPipeline(mode="model")
            if managed
            else BudgetedContextAssembler(),
        )
        action, request = state.next_operation()
        assert action["kind"] == ("managed_context" if managed else "context")
        assert request["phase"] == ("plan" if managed else "context")
        unknown = {"ok": False, "code": "activity_outcome_unknown"}
        accept_context = state.accept_managed_context if managed else state.accept_context
        accept_context(action["id"], unknown)
        assert state.state == "running" and state.active_action is None
        assert state.context_read_stages[action["id"]]["fenced"] is True
        replayed = copy.deepcopy(state)
        retry, retry_request = replayed.next_operation()
        assert retry["id"] != action["id"] and retry_request["messages"] == request["messages"]
        accept_context = replayed.accept_managed_context if managed else replayed.accept_context
        accept_context(retry["id"], unknown)
        assert replayed.state == "failed" and replayed.error["code"] == "activity_outcome_unknown"
        assert not provider.calls
        denied = replayed.admit_context_dispatch(
            {
                "scope": request["scope"],
                "action_id": action["id"],
                "release_digest": request["release_digest"],
                "phase": request["phase"],
                "execution_epoch": request["execution_epoch"],
                "request_digest": digest(request),
                "run_id": replayed.run_id,
            }
        )
        assert denied["allowed"] is False
        await runtime.close_context_execution(wait_timeout=1)

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_joint_seven_never_recreates_context_unknown_after_original_grant(managed):
    from relf_agent.context_pipeline import BudgetedContextAssembler
    from relf_agent.managed_context import ManagedContextPipeline

    async def run():
        runtime, state, _ = setup(
            context_reads=True,
            context_builder=ManagedContextPipeline(mode="model")
            if managed
            else BudgetedContextAssembler(),
        )
        action, request = state.next_operation()
        grant_result = state.admit_context_dispatch(
            {
                "scope": request["scope"],
                "action_id": action["id"],
                "release_digest": request["release_digest"],
                "phase": request["phase"],
                "execution_epoch": request["execution_epoch"],
                "request_digest": digest(request),
                "run_id": state.run_id,
            }
        )
        assert grant_result["allowed"] is True
        accept_context = state.accept_managed_context if managed else state.accept_context
        accept_context(action["id"], {"ok": False, "code": "activity_outcome_unknown"})
        assert state.state == "failed" and state.active_action == action["id"]
        assert not state.context_read_stages[action["id"]]["fenced"]
        await runtime.close_context_execution(wait_timeout=1)

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_original_reference_guard_precedes_custom_policy_excerpt_and_model_io(managed):
    from relf_agent import InMemoryArtifactStore
    from relf_agent.data_context import ManagedDataContext
    from relf_agent.model_history import CompleteModelHistory
    from relf_agent.types import canonical

    continuation = {
        "protocol": "opaque-reference-v1",
        "owner_digest": "d" * 64,
        "decision_digest": "e" * 64,
        "data": {"signature": "OPAQUE_SECRET_HISTORY"},
    }

    class Knowledge:
        identity = {"kind": "opaque-reference-source", "version": "1"}
        limit, max_chars = 8, 65536

        async def references(self, scope, query):
            return [{"key": "doc", "value": {"model_continuation": continuation}}]

        async def validate(self, scope, references):
            return None

    class ExcerptPolicy(CompleteModelHistory):
        def __init__(self):
            super().__init__()
            self.calls = 0

        @property
        def identity(self):
            return {
                "kind": "excerpt-before-validation",
                "version": "1",
                "allow_tool_result_projection": False,
            }

        def assemble(self, history, references, max_chars, *, context):
            from relf_agent.data_context import ManagedDataContext

            self.calls += 1
            projected = (
                context.project_references(references)[0]
                if isinstance(context, ManagedDataContext)
                else [{"evidence_excerpt": canonical(references)}]
            )
            return super().assemble(history, projected, max_chars, context=context)

    async def run():
        policy, provider = ExcerptPolicy(), SignedFinal()
        context = (
            ManagedDataContext(InMemoryArtifactStore(), reference_chars=16) if managed else None
        )
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            knowledge=Knowledge(),
            context_builder=context,
            model_continuation=True,
            model_history=policy,
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "s",
            submission_request(AgentSpec("a", "Answer"), "q"),
            runtime.manifest,
        )
        for _ in range(10):
            if state.state in {"succeeded", "failed"}:
                break
            await advance(runtime, state)
        assert state.state == "failed" and state.error["code"] == "validation_error"
        assert policy.calls == 0 and not provider.calls
        assert state.budget["spent"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_legacy_joint_six_does_not_recreate_unadmitted_context_timeout(managed):
    from relf_agent.context_pipeline import BudgetedContextAssembler
    from relf_agent.managed_context import ManagedContextPipeline

    async def run():
        runtime, state, _ = setup(
            history=None,
            context_reads=True,
            context_builder=ManagedContextPipeline(mode="model")
            if managed
            else BudgetedContextAssembler(),
        )
        action, _ = state.next_operation()
        accept_context = state.accept_managed_context if managed else state.accept_context
        accept_context(action["id"], {"ok": False, "code": "activity_outcome_unknown"})
        assert state.manifest["binding_protocol"] == 6 and state.state == "failed"
        assert not hasattr(state, "unadmitted_context_retries")
        await runtime.close_context_execution(wait_timeout=1)

    asyncio.run(run())


@pytest.mark.parametrize("joint", [6, 7])
@pytest.mark.parametrize("error_kind", ["timeout", "application"])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("tool_end_evidence", [False, True])
def test_workflow_plain_context_maps_only_new_joint_seven_sdk_timeout_to_unknown(
    monkeypatch, joint, error_kind, managed, tool_end_evidence
):
    pytest.importorskip("temporalio")
    from temporalio.exceptions import ActivityError, ApplicationError, TimeoutError, TimeoutType

    from relf_agent import temporal_workflow

    class LoopFinished(BaseException):
        pass

    class State:
        manifest = {
            "kernel": "temporal-3",
            "binding_protocol": joint,
            "model_history_protocol": 1,
            "context_read_protocol": {},
        }
        pending_acks, reconcile_requests, event_log = [], [], []

        def __init__(self):
            self.response = None

        def next_operation(self):
            if self.response is not None:
                raise LoopFinished()
            return {
                "id": "original-context",
                "kind": "managed_context" if managed else "context",
                "phase": "plan" if managed else "context",
                "attempts": [],
            }, {}

        def accept_context(self, action_id, response):
            assert action_id == "original-context"
            self.response = response

        accept_managed_context = accept_context

    async def no_session():
        return None

    def patched(change_id):
        assert change_id == "ralf-unowned-tool-end-evidence-v1"
        return tool_end_evidence  # Replay without the marker and new History.

    async def failing_activity(*args, **kwargs):
        cause = (
            TimeoutError(
                "server timeout", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]
            )
            if error_kind == "timeout"
            else ApplicationError("application refused", non_retryable=True)
        )
        error = ActivityError(
            "context activity failed",
            scheduled_event_id=1,
            started_event_id=2,
            identity="worker",
            activity_type="context",
            activity_id="original-context",
            retry_state=None,
        )
        error.__cause__ = cause
        raise error

    async def run():
        instance = temporal_workflow.TemporalRunWorkflow.__new__(
            temporal_workflow.TemporalRunWorkflow
        )
        instance.state, instance.wake_revision = State(), 0
        instance._notify_session = no_session
        monkeypatch.setattr(temporal_workflow.workflow, "patched", patched)
        monkeypatch.setattr(temporal_workflow.workflow, "execute_activity", failing_activity)
        with pytest.raises(LoopFinished):
            await instance.run({"activity_timeout": 1})
        expected = (
            "activity_outcome_unknown"
            if error_kind == "timeout" and (joint == 7 or managed)
            else "context_failed"
        )
        if managed and joint == 6:
            expected = "activity_outcome_unknown"  # Original 1–6 mapping remains unchanged.
        assert instance.state.response["ok"] is False
        assert instance.state.response["code"] == expected

    asyncio.run(run())
