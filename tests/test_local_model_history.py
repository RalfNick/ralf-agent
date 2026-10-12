"""Complete original model history survives adoption, verification and recovery."""

import asyncio
import copy
import importlib

import pytest

from ralf_agent import AgentSpec, LocalEngine, SQLiteStore, ToolCall
from ralf_agent.completion import CompletionVerdict
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.harness import ModelRequest, NativeHarness
from ralf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from ralf_agent.tools import ToolRegistry
from ralf_agent.types import digest


def history_policy(**kwargs):
    api = importlib.import_module("ralf_agent")
    assert hasattr(api, "CompleteModelHistory"), "Complete model history is a public capability"
    return api.CompleteModelHistory(**kwargs)


class SignedFinal:
    identity = {"kind": "final-history-fixture", "version": "1"}
    continuation_identity = {"protocol": "final-fixture-v1", "owner_digest": "a" * 64}

    def __init__(self, calls):
        self.calls = calls

    async def complete(self, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        retry = any(m.get("content", "").startswith("Completion verification:") for m in messages)
        output = ' { "answer" : "second" } ' if retry else ' { "answer" : "first" } '
        return ContinuedModelResponse(
            output=output,
            continuation=ModelContinuation(
                "final-fixture-v1",
                "a" * 64,
                digest({"output": output, "tool_calls": []}),
                {"opaque": "second-signature" if retry else "first-signature"},
            ),
        )


class RetryFirst:
    identity = {"kind": "retry-first-answer", "version": "1"}

    def verify(self, request):
        return (
            CompletionVerdict("retry", "Need the second answer")
            if request.output["answer"] == "first"
            else CompletionVerdict("accept")
        )


def final_spec():
    return AgentSpec(
        "answer",
        "Answer in JSON",
        output_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
            "additionalProperties": False,
        },
    )


@pytest.mark.parametrize("binding", ["native", "agent", "sequence"])
def test_signed_final_retry_keeps_raw_json_once_and_normalizes_business_result(tmp_path, binding):
    from ralf_agent import AgentDefinition, BoundDefinition, WorkflowSpec

    calls = []
    definition = (
        final_spec()
        if binding == "native"
        else AgentDefinition(final_spec())
        if binding == "agent"
        else BoundDefinition(WorkflowSpec("s", [final_spec()]), {})
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": SignedFinal(calls)},
        tools=ToolRegistry(),
        verifier=RetryFirst(),
        model_continuation=True,
        model_history=history_policy(),
    ) as engine:
        h = engine.submit(definition, "question", command_id="s")
        result = asyncio.run(engine.drive(h.run_id))
        assert result.state == "succeeded" and result.result == {"answer": "second"}
        assert len(calls) == 2
        assistants = [m for m in calls[1] if m["role"] == "assistant"]
        assert len(assistants) == 1
        assert assistants[0]["content"] == ' { "answer" : "first" } '
        assert assistants[0]["model_continuation"]["data"] == {"opaque": "first-signature"}
        record = engine.store.run(h.run_id)
        finals = [m for m in record["messages"] if m["role"] == "assistant"]
        assert [m["content"] for m in finals] == [
            ' { "answer" : "first" } ',
            ' { "answer" : "second" } ',
        ]
        assert engine._step_manifest(record, 0)["kernel"] == "local-6"
        assert engine._step_manifest(record, 0)["model_history_protocol"] == 1
        assert engine.store.budget(h.run_id)["spent"] == 2


class SimulatedExit(BaseException):
    pass


@pytest.mark.parametrize("boundary", ["received", "adopted", "verified"])
def test_restart_between_final_receipt_adoption_and_verification_does_not_repeat(
    tmp_path, boundary
):
    class InterruptedEngine(LocalEngine):
        def _adopt_model_response(self, run_id, action_id):
            if boundary == "received":
                raise SimulatedExit()
            value = super()._adopt_model_response(run_id, action_id)
            if boundary == "adopted":
                raise SimulatedExit()
            return value

        def _commit(self, run, event, payload=None):
            value = super()._commit(run, event, payload)
            if boundary == "verified" and event == "completion_verified":
                raise SimulatedExit()
            return value

    calls, path = [], tmp_path / "runs.sqlite"
    options = dict(
        providers={"default": SignedFinal(calls)},
        tools=ToolRegistry(),
        verifier=RetryFirst(),
        model_continuation=True,
        model_history=history_policy(),
    )
    with InterruptedEngine(SQLiteStore(path), **options) as engine:
        h = engine.submit(final_spec(), "question", command_id="s")
        with pytest.raises(SimulatedExit):
            asyncio.run(engine.drive(h.run_id))
        assert len(calls) == 1
        assert engine.store.run(h.run_id)["actions"][0]["received_response"]["continuation"][
            "data"
        ] == {"opaque": "first-signature"}
    with LocalEngine(SQLiteStore(path), **options) as engine:
        assert engine.submit(final_spec(), "question", command_id="s") == h
        assert asyncio.run(engine.drive(h.run_id)).result == {"answer": "second"}
        assert len(calls) == 2
        final_messages = [
            m for m in engine.store.run(h.run_id)["messages"] if m["role"] == "assistant"
        ]
        assert len(final_messages) == 2
        assert engine.store.budget(h.run_id)["spent"] == 2


@pytest.mark.parametrize("damage", ["drop", "rewrite", "duplicate"])
def test_harness_cannot_damage_accepted_native_history_before_second_model(tmp_path, damage):
    class DamagingHarness(NativeHarness):
        identity = {"kind": "damaging-history", "version": "1"}

        def prepare(self, spec, messages, tools):
            if any(m.get("role") == "assistant" for m in messages):
                pos = next(i for i, m in enumerate(messages) if m.get("role") == "assistant")
                if damage == "drop":
                    messages.pop(pos)
                elif damage == "rewrite":
                    messages[pos]["model_continuation"]["data"] = {"opaque": "wrong"}
                else:
                    messages.insert(pos, copy.deepcopy(messages[pos]))
            return ModelRequest(messages, tools)

    calls = []
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": SignedFinal(calls)},
        tools=ToolRegistry(),
        verifier=RetryFirst(),
        harness=DamagingHarness(),
        model_continuation=True,
        model_history=history_policy(),
    ) as engine:
        h = engine.submit(final_spec(), "question", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).state == "failed"
        assert len(calls) == 1
        assert engine.store.budget(h.run_id)["spent"] == 1


def test_complete_history_requires_continuation_before_coordinator_acquisition(tmp_path):
    class Coordinator:
        identity = {"kind": "acquire-audit", "version": "1"}

        def acquire(self, resource):
            raise AssertionError("Invalid configuration must be rejected before acquire")

        def release(self):
            pass

    store = SQLiteStore(tmp_path / "runs.sqlite")
    try:
        with pytest.raises(ValidationError):
            LocalEngine(
                store,
                providers={"default": SignedFinal([])},
                tools=ToolRegistry(),
                coordinator=Coordinator(),
                model_history=history_policy(),
            )
    finally:
        store.close()


def test_new_history_release_refuses_old_continuation_engine_before_model_io(tmp_path):
    path, calls = tmp_path / "runs.sqlite", []
    options = dict(
        providers={"default": SignedFinal(calls)}, tools=ToolRegistry(), model_continuation=True
    )
    with LocalEngine(SQLiteStore(path), model_history=history_policy(), **options) as engine:
        h = engine.submit(final_spec(), "question", command_id="s")
    with LocalEngine(SQLiteStore(path), **options) as old:
        with pytest.raises(DefinitionMismatch):
            asyncio.run(old.drive(h.run_id))
    assert calls == []


def test_legacy_continuation_without_history_keeps_original_final_projection(tmp_path):
    calls = []
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": SignedFinal(calls)},
        tools=ToolRegistry(),
        model_continuation=True,
    ) as engine:
        h = engine.submit(final_spec(), "question", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).result == {"answer": "first"}
        record = engine.store.run(h.run_id)
        assert len(record["messages"]) == 2
        assert record["manifest"]["kernel"] == "local-5"
        assert "model_history_protocol" not in record["manifest"]


@pytest.mark.parametrize("context_kind", ["default", "budgeted", "managed-model"])
def test_complete_history_does_not_drop_early_native_tools_or_dispatch_summary(
    tmp_path, context_kind
):
    from ralf_agent import BudgetedContextAssembler, ManagedContextPipeline, ModelResponse

    calls, summary_calls = [], []

    class MultiStep(SignedFinal):
        async def complete(self, messages, tools):
            calls.append(copy.deepcopy(messages))
            completed = sum(m["role"] == "tool" for m in messages)
            raw = [{"name": "read", "arguments": {}, "call_id": "read-" + str(completed)}]
            return ContinuedModelResponse(
                tool_calls=tuple(ToolCall(**c) for c in raw),
                continuation=ModelContinuation(
                    "final-fixture-v1",
                    "a" * 64,
                    digest({"output": None, "tool_calls": raw}),
                    {"round": completed},
                ),
            )

    class Summary:
        identity = {"kind": "summary-audit-fixture", "version": "1"}

        async def complete(self, messages, tools):
            summary_calls.append(messages)
            return ModelResponse(output='{"text":"summary"}')

    def read():
        return "evidence-" + "x" * 1700

    tools = ToolRegistry()
    tools.register_function(read, effect="read_only", cost=0)
    context = (
        None
        if context_kind == "default"
        else BudgetedContextAssembler()
        if context_kind == "budgeted"
        else ManagedContextPipeline(mode="model", provider="summary")
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": MultiStep(calls), "summary": Summary()},
        tools=tools,
        context_assembler=context,
        model_continuation=True,
        model_history=history_policy(),
    ) as engine:
        h = engine.submit(
            AgentSpec("a", "Read", ("read",), max_context_chars=3000), "q", command_id="s"
        )
        assert asyncio.run(engine.drive(h.run_id)).state == "failed"
        assert len(calls) == 2
        assert summary_calls == []
        assert len([m for m in engine.store.run(h.run_id)["messages"] if m["role"] == "tool"]) == 2
        assert engine.store.budget(h.run_id)["spent"] == 2


def test_policy_method_replacement_cannot_reuse_accepted_release(tmp_path):
    calls, policy = [], history_policy()
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": SignedFinal(calls)},
        tools=ToolRegistry(),
        model_continuation=True,
        model_history=policy,
    ) as engine:
        h = engine.submit(final_spec(), "q", command_id="s")
        policy.validate = lambda history, messages: None
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(h.run_id))
        assert calls == []


def test_policy_bound_method_from_another_instance_is_not_the_executing_component(tmp_path):
    calls, policy, other = [], history_policy(), history_policy(allow_tool_result_projection=True)
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": SignedFinal(calls)},
        tools=ToolRegistry(),
        model_continuation=True,
        model_history=policy,
    ) as engine:
        h = engine.submit(final_spec(), "q", command_id="s")
        policy.validate = other.validate
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(h.run_id))
        assert calls == []


def test_unsigned_original_arguments_survive_while_actions_apply_typed_defaults(tmp_path):
    from ralf_agent import ModelResponse

    class Unsigned:
        identity = {"kind": "unsigned-original-arguments", "version": "1"}

        def __init__(self):
            self.calls = []

        async def complete(self, messages, tools):
            self.calls.append(copy.deepcopy(messages))
            if any(m["role"] == "tool" for m in messages):
                return ModelResponse(output="done")
            return ModelResponse(tool_calls=[ToolCall("change", {"value": 7}, "original")])

    def change(value: int, flag: bool = True):
        return {"value": value, "flag": flag}

    provider, tools = Unsigned(), ToolRegistry()
    tools.register_function(change, effect="read_only", cost=0)
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": provider},
        tools=tools,
        model_continuation=True,
        model_history=history_policy(),
    ) as engine:
        h = engine.submit(AgentSpec("a", "Act", ("change",)), "q", command_id="s")
        assert asyncio.run(engine.drive(h.run_id)).result == "done"
        original = next(m for m in provider.calls[1] if m["role"] == "assistant")
        assert original["tool_calls"][0]["function"]["arguments"] == '{"value":7}'
        action = next(a for a in engine.store.run(h.run_id)["actions"] if a["kind"] == "tool")
        assert action["arguments"] == {"value": 7, "flag": True}


@pytest.mark.parametrize("custom", [False, True])
def test_opaque_reference_cannot_be_hidden_by_data_context_excerpts(tmp_path, custom):
    from ralf_agent import InMemoryArtifactStore, ManagedDataContext

    class Custom(history_policy().__class__):
        def assemble(self, history, references, max_chars, *, context):
            return history, {}

    context = ManagedDataContext(InMemoryArtifactStore(), reference_chars=80)
    original = [{"role": "system", "content": "System"}, {"role": "user", "content": "Task"}]
    reference = {
        "key": "evidence",
        "version": 1,
        "value": {
            "model_continuation": {
                "protocol": "fixture-v1",
                "owner_digest": "a" * 64,
                "decision_digest": "b" * 64,
                "data": {"signature": "OPAQUE_HISTORY"},
            }
        },
    }
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": SignedFinal([])},
        tools=ToolRegistry(),
        context_assembler=context,
        model_continuation=True,
        model_history=Custom() if custom else history_policy(),
    ) as engine:
        with pytest.raises(ValidationError):
            engine._assemble_context(original, [reference], 3000)
