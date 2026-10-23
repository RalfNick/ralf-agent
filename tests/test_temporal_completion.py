import asyncio
import copy
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    CompletionVerdict,
    InMemoryMemory,
    ManagedMemoryPolicy,
    ModelResponse,
    Scope,
    ToolRegistry,
)
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import normalize_request
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request
from tests.test_temporal_memory_bindings import grant


class Provider:
    identity = {"kind": "completion-test-provider", "version": "1"}

    def __init__(self):
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        return ModelResponse(output={"status": "resolved", "target": "demo"})


class Verifier:
    identity = {"kind": "completion-test-verifier", "version": "1"}

    def __init__(self, status="accept"):
        self.identity = {**self.identity, "status": status}
        self.calls = []

    def verify(self, request):
        self.calls.append(request.to_dict())
        return CompletionVerdict(
            self.identity["status"],
            None if self.identity["status"] == "accept" else "need evidence",
        )


def setup(*, verifier=None, selected=None, disabled=False, memory=False):
    verifier = verifier or Verifier()
    scope = Scope()
    catalog = None
    if selected is not None:
        catalog = BindingCatalog(scope=scope)
        catalog.register("verifier", "selected", "1", selected)
    provider = Provider()
    runtime = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        verifier=verifier,
        binding_catalog=catalog,
        stage_policy=ManagedMemoryPolicy(InMemoryMemory()) if memory else None,
    )
    choice = (
        BindingSelection.disabled()
        if disabled
        else BindingSelection.ref("selected", "1")
        if selected is not None
        else BindingSelection.inherit()
    )
    definition = AgentDefinition(
        AgentSpec("answer", "Answer", max_decisions=3), AgentBindingDescriptor(verifier=choice)
    )
    state = TemporalRunState(
        "run",
        asdict(scope),
        "submit",
        normalize_request(submission_request(definition, {"target": "demo"})),
        runtime.manifest,
    )
    return runtime, state, provider, verifier


async def model(runtime, state):
    action, request = state.next_operation()
    assert action["kind"] == "model"
    state.accept_model(
        action["id"],
        await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
    )
    return action


async def verify(runtime, state):
    action, request = state.next_operation()
    assert action["kind"] == "agent_completion"
    state.accept_completion(action["id"], await runtime.verify_completion(request))
    return action


@pytest.mark.parametrize("status", ["accept", "reject", "retry"])
def test_original_history_adopts_verdict_before_completion(status):
    async def run():
        runtime, state, _, verifier = setup(verifier=Verifier(status))
        action = await model(runtime, state)
        assert state.state == "running" and state.result is None
        await verify(runtime, state)
        evidence = action["completion_verification"]
        assert evidence["request"]["task"] == {"target": "demo"}
        assert evidence["verdict"]["status"] == status
        assert len(verifier.calls) == 1
        restored = copy.deepcopy(state)
        if status == "accept":
            assert restored.state == "succeeded"
            assert restored.result == {"status": "resolved", "target": "demo"}
        elif status == "reject":
            assert restored.state == "failed"
            assert restored.error["code"] == "completion_rejected"
        else:
            assert restored.state == "running"
            assert restored.messages[-1]["content"] == "Completion verification: need evidence"
            assert restored.next_operation()[0]["kind"] == "model"
            assert len(verifier.calls) == 1

    asyncio.run(run())


def test_binding_ref_replaces_host_and_disabled_only_skips_extra_rules():
    async def run():
        selected = Verifier("accept")
        runtime, state, _, host = setup(verifier=Verifier("reject"), selected=selected)
        await model(runtime, state)
        await verify(runtime, state)
        assert state.state == "succeeded" and len(selected.calls) == 1 and not host.calls
        runtime, state, _, host = setup(verifier=Verifier("reject"), disabled=True)
        await model(runtime, state)
        assert state.state == "succeeded" and not host.calls

    asyncio.run(run())


def test_rejected_or_retry_completion_never_prepares_automatic_memory():
    async def run():
        for status in ("reject", "retry"):
            runtime, state, _, _ = setup(verifier=Verifier(status), memory=True)
            await model(runtime, state)
            assert not state.memory_stages
            await verify(runtime, state)
            assert not state.memory_stages and state.pending_completion is None
        runtime, state, _, _ = setup(memory=True)
        await model(runtime, state)
        await verify(runtime, state)
        assert state.pending_completion == "0" and state.memory_stages

    asyncio.run(run())


def test_retry_consumes_original_decision_limit():
    async def run():
        runtime, state, provider, verifier = setup(verifier=Verifier("retry"))
        for _ in range(3):
            await model(runtime, state)
            await verify(runtime, state)
        assert state.next_operation() is None
        assert state.state == "failed" and state.error["code"] == "decision_limit"
        assert len(provider.calls) == len(verifier.calls) == 3
        assert state.budget["spent"] == 3

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["identity", "method", "owner"])
def test_worker_drift_refuses_completed_verdict(mutation):
    async def run():
        runtime, state, _, verifier = setup()
        await model(runtime, state)
        action, request = state.next_operation()
        if mutation == "identity":
            verifier.identity = {"kind": "changed"}
        elif mutation == "method":
            verifier.verify = lambda request: CompletionVerdict("accept")
        else:
            runtime.verifier = Verifier()
        response = await runtime.verify_completion(request)
        assert not response["ok"]
        state.accept_completion(action["id"], response)
        assert state.state == "failed"

    asyncio.run(run())


@pytest.mark.parametrize("cancel_after_dispatch", [False, True])
def test_cancellation_preserves_original_terminal_and_skips_memory(cancel_after_dispatch):
    async def run():
        runtime, state, _, _ = setup(memory=True)
        await model(runtime, state)
        operation = state.next_operation() if cancel_after_dispatch else None
        state.command("cancel", {"scope": state.scope, "kind": "cancel"})
        if operation is not None:
            action, request = operation
            state.accept_completion(action["id"], await runtime.verify_completion(request))
        assert state.state == "cancelled" and not state.memory_stages
        assert state.next_operation() is None
        assert state.quiescent

    asyncio.run(run())


@pytest.mark.parametrize("malformed", ["digest", "status", "feedback", "lazy"])
def test_malformed_verdict_cannot_complete_run(malformed):
    async def run():
        runtime, state, _, _ = setup()
        await model(runtime, state)
        action, request = state.next_operation()
        response = await runtime.verify_completion(request)
        if malformed == "digest":
            response["request_digest"] = "foreign"
        elif malformed == "status":
            response["verdict"]["status"] = "unknown"
        elif malformed == "feedback":
            response["verdict"] = {"status": "retry", "feedback": ""}
        else:
            response["verdict"] = {"status": "accept", "feedback": True}
        state.accept_completion(action["id"], response)
        assert state.state == "failed" and state.result is None

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["dict", "coroutine", "contextmanager", "generator"])
def test_lazy_worker_result_is_refused(kind):
    from contextlib import contextmanager

    class Invalid(Verifier):
        def verify(self, request):
            async def coroutine():
                return CompletionVerdict("accept")

            @contextmanager
            def context():
                yield CompletionVerdict("accept")

            return {
                "dict": lambda: {"status": "accept"},
                "coroutine": coroutine,
                "contextmanager": context,
                "generator": lambda: (v for v in []),
            }[kind]()

    async def run():
        runtime, state, _, _ = setup(verifier=Invalid())
        await model(runtime, state)
        await verify(runtime, state)
        assert state.state == "failed" and state.result is None

    asyncio.run(run())


def test_sequence_input_is_previous_normalized_result_and_receipts_are_node_scoped():
    from relf_agent import ToolCall, ToolRegistry, ToolSpec, WorkflowSpec

    class Calls(Provider):
        async def complete(self, messages, tools):
            if messages[0]["content"] == "first" and not any(m["role"] == "tool" for m in messages):
                return ModelResponse(tool_calls=[ToolCall("lookup", {}, "read")])
            return ModelResponse(output='{"count":1}')

    async def lookup(arguments, context):
        return {"found": True}

    async def run():
        verifier = Verifier()
        tools = ToolRegistry()
        tools.register(ToolSpec("lookup", "read", {"type": "object"}), lookup)
        runtime = TemporalRuntime(providers={"default": Calls()}, tools=tools, verifier=verifier)
        definition = WorkflowSpec(
            "sequence",
            [
                AgentSpec("a", "first", ("lookup",), output_schema={"type": "object"}),
                AgentSpec("b", "second", output_schema={"type": "object"}),
            ],
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "submit",
            submission_request(definition, {"original": [1, False]}),
            runtime.manifest,
        )
        for _ in range(10):
            operation = state.next_operation()
            if operation is None:
                break
            action, request = operation
            if action["kind"] == "tool":
                state.accept_tool(action["id"], await runtime.execute_tool(request))
            elif action["kind"] == "agent_completion":
                state.accept_completion(action["id"], await runtime.verify_completion(request))
                state = copy.deepcopy(state)
            else:
                state.accept_model(
                    action["id"],
                    await runtime.complete_model(
                        request, dispatch_guard=lambda r, state=state: grant(state, r)
                    ),
                )
        assert state.state == "succeeded", state.snapshot()
        assert [r["task"] for r in verifier.calls] == [{"original": [1, False]}, {"count": 1}]
        assert len(verifier.calls[0]["receipts"]) == 1
        assert verifier.calls[1]["receipts"] == []

    asyncio.run(run())


def test_tool_receipt_verifier_retries_then_requires_original_approval_and_result():
    from relf_agent import ToolCall, ToolReceiptVerifier, ToolSpec

    class Calls(Provider):
        async def complete(self, messages, tools):
            if any(
                m["content"].startswith("Completion verification:")
                for m in messages
                if isinstance(m.get("content"), str)
            ) and not any(m["role"] == "tool" for m in messages):
                return ModelResponse(tool_calls=[ToolCall("lookup", {"target": "demo"}, "read")])
            return await super().complete(messages, tools)

    calls = []

    async def lookup(arguments, context):
        calls.append(context.effect_key)
        return {"found": True}

    async def run():
        tools = ToolRegistry()
        tools.register(
            ToolSpec("lookup", "read", {"type": "object"}, requires_approval=True), lookup
        )
        runtime = TemporalRuntime(
            providers={"default": Calls()},
            tools=tools,
            verifier=ToolReceiptVerifier(
                "lookup",
                argument_bindings={"target": "/target"},
                result_schema={
                    "type": "object",
                    "required": ["found"],
                    "properties": {"found": {"const": True}},
                },
            ),
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "submit",
            submission_request(AgentSpec("a", "answer", ("lookup",)), "task"),
            runtime.manifest,
        )
        await model(runtime, state)
        await verify(runtime, state)
        await model(runtime, state)
        assert state.next_operation() is None and state.state == "waiting_approval"
        assert not calls
        pending = state.snapshot()["pending"][0]
        payload = {
            "scope": state.scope,
            "kind": "approve",
            "action_id": pending["action_id"],
            "digest": pending["digest"],
            "approved": True,
        }
        receipt = state.command("approve", payload)
        assert state.command("approve", payload) == receipt
        action, request = state.next_operation()
        state.accept_tool(action["id"], await runtime.execute_tool(request))
        await model(runtime, state)
        await verify(runtime, state)
        assert state.state == "succeeded" and len(calls) == 1
        assert [s["verdict"]["status"] for s in state.completion_stages.values()] == [
            "retry",
            "accept",
        ]
        assert state.budget["spent"] == 4

    asyncio.run(run())


def test_invalid_protocol_and_foreign_binding_refused_before_execution():
    from relf_agent.errors import AuthorizationDenied, RalfError
    from relf_agent.temporal_state import validate_manifest

    runtime, state, _, _ = setup(selected=Verifier())
    for mutation in ("protocol", "registration"):
        manifest = runtime.manifest
        if mutation == "protocol":
            manifest["completion_protocol"] = True
        else:
            for record in manifest["binding_catalog"]["records"].values():
                record["configuration"].pop("completion_verifier")
        with pytest.raises(RalfError):
            validate_manifest(manifest)
    with pytest.raises(AuthorizationDenied):
        TemporalRunState(
            "foreign",
            asdict(Scope("other", "principal")),
            "submit",
            state.request,
            runtime.manifest,
        )


@pytest.mark.parametrize("budgeted", [False, True])
def test_managed_context_keeps_latest_completion_feedback_and_following_tool_group(budgeted):
    from relf_agent import BudgetedContextAssembler, ContextAssembler
    from relf_agent.errors import ValidationError

    history = [
        {"role": "system", "content": "answer"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "old" * 1000},
        {"role": "assistant", "content": "candidate"},
        {"role": "user", "content": "Completion verification: need evidence"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call", "content": "found"},
    ]
    assembler = BudgetedContextAssembler() if budgeted else ContextAssembler()
    messages, _ = assembler.assemble(history, [], 700)
    assert messages == history[:2] + history[3:]
    with pytest.raises(ValidationError):
        assembler.assemble(history, [], 335)


def test_local_completion_retry_works_with_managed_default_context(tmp_path):
    from relf_agent import LocalEngine, ManagedContextPipeline, SQLiteStore

    class Once(Verifier):
        def verify(self, request):
            self.calls.append(request.to_dict())
            return (
                CompletionVerdict("retry", "need evidence")
                if request.output["status"] == "resolved"
                else CompletionVerdict("accept")
            )

    class Improved(Provider):
        async def complete(self, messages, tools):
            self.calls.append(copy.deepcopy(messages))
            return ModelResponse(
                output={
                    "status": "resolved" if len(self.calls) == 1 else "proved",
                    "target": "demo",
                }
            )

    async def run():
        with SQLiteStore(tmp_path / "runs.sqlite") as store:
            verifier = Once()
            engine = LocalEngine(
                store,
                providers={"default": Improved()},
                tools=ToolRegistry(),
                verifier=verifier,
                context_assembler=ManagedContextPipeline(),
            )
            try:
                handle = engine.submit(
                    AgentSpec("a", "answer"), {"target": "demo"}, command_id="submit"
                )
                snapshot = await engine.drive(handle.run_id)
                assert snapshot.state == "succeeded", snapshot
                assert len(verifier.calls) == 2
            finally:
                engine.close()

    asyncio.run(run())
