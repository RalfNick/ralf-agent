"""Actual Local worker receipts and the original managed verifier child authority."""

import asyncio
import importlib
import inspect

import pytest

from relf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    TeamSpec,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import ValidationError
from relf_agent.types import digest


def api():
    assert "parent_completion_policies" in inspect.signature(LocalEngine).parameters, (
        "LocalEngine must accept explicit parent completion policy registrations"
    )
    module = importlib.import_module("relf_agent.parent_completion")
    return module


class Provider:
    identity = {"kind": "local-parent-fixture", "version": "1"}

    def __init__(self, *, bad=False, verdicts=None):
        self.bad = bad
        self.verdicts = iter(verdicts or ["accept"])
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(messages)
        if messages[0]["content"] == "judge":
            status = next(self.verdicts)
            return ModelResponse(
                {
                    "status": status,
                    "feedback": "Repair the result" if status == "replan" else None,
                    "evidence_ids": [],
                }
            )
        if not any(m["role"] == "tool" for m in messages):
            return ModelResponse(tool_calls=(ToolCall("measure", {"value": 7}, "measure-1"),))
        return ModelResponse({"value": 99 if self.bad else 7})


def policy(*, model=False, missing="reject"):
    public = api()
    rules = importlib.import_module("relf_agent.parent_completion_rules")
    gate = rules.ReceiptParentCompletionGate(
        [
            {
                "id": "actual-value",
                "member_path": ["worker"],
                "tool": "measure",
                "output_bindings": {"/value": {"source": "candidate", "pointer": "/value"}},
            }
        ],
        on_missing=missing,
    )
    stage = None
    if model:
        stage = importlib.import_module(
            "relf_agent.parent_verification_stage"
        ).ModelParentVerificationStage(instructions="judge")
    return public.ParentCompletionPolicy(gate, model_stage=stage)


def tools(effects):
    result = ToolRegistry()
    result.register(
        ToolSpec(
            "measure",
            "Read measured value",
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            effect="read_only",
        ),
        lambda arguments, context: effects.append(context.effect_key) or arguments,
    )
    return result


def spec(kind, **options):
    members = {"worker": AgentSpec("worker", "worker", tools=("measure",))}
    if kind == "team":
        return TeamSpec("parent", members, completion_policy="business", child_budget=3, **options)
    return DynamicWorkflowSpec(
        "parent", members, completion_policy="business", child_budget=3, plan_mode=kind, **options
    )


@pytest.mark.parametrize("kind", ["flat", "dag", "team"])
@pytest.mark.parametrize("model", [False, True])
def test_real_tool_chain_gates_candidate_and_budgeted_model_stage(tmp_path, kind, model):
    selected, provider, effects = policy(model=model), Provider(), []
    with LocalEngine(
        SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        parent_completion_policies={"business": selected},
    ) as engine:
        handle = engine.submit(spec(kind), {"value": 7}, command_id="s", budget=10)
        final = asyncio.run(engine.drive(handle.run_id))
        assert final.state == "succeeded" and final.result == {"value": 7}
        run = engine.store.run(handle.run_id)
        journal = run["parent_completion_stages"]["r0"]
        assert journal["status"] == "adopted"
        assert journal["source_digest"] == digest(journal["source"])
        assert journal["source"]["receipts"][0]["consumed_by"]
        assert journal["source"]["children"][0]["input_consumed"] is True
        assert run["manifest"]["kernel"] == "local-8"
        assert len(effects) == 1
        children = run["orchestration"]["children"]
        assert [child["role"] for child in children] == (
            ["worker", "verifier"] if model else ["worker"]
        )
        assert engine.diagnostics(handle.run_id).budget == {
            "limit": 10,
            "held": 0,
            "spent": 4 if model else 3,
        }
        if model:
            assert children[-1]["id"] == "r0.verifier.verdict"
            assert children[-1]["member"] == "@verifier"
        before = len(provider.calls)
        assert asyncio.run(engine.drive(handle.run_id)) == final
        assert len(provider.calls) == before


@pytest.mark.parametrize("kind", ["flat", "dag", "team"])
def test_false_but_schema_valid_success_is_rejected_without_model_stage(tmp_path, kind):
    selected, provider, effects = policy(model=True), Provider(bad=True), []
    with LocalEngine(
        SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        parent_completion_policies={"business": selected},
    ) as engine:
        handle = engine.submit(spec(kind), {"value": 7}, command_id="s", budget=10)
        final = asyncio.run(engine.drive(handle.run_id))
        assert final.state == "failed"
        assert len(provider.calls) == 2 and len(effects) == 1
        assert [
            child["role"] for child in engine.store.run(handle.run_id)["orchestration"]["children"]
        ] == ["worker"]


def test_plan_model_replan_preserves_effects_and_supplies_feedback_to_actual_planner(tmp_path):
    from relf_agent import PlanProposal, PlanStep

    requests = []

    class Planner:
        identity = {"kind": "feedback-planner", "version": "1"}

        async def plan(self, request, caller):
            requests.append(request.to_dict())
            return PlanProposal([PlanStep("work", "worker", {"value": 7})])

    selected, provider, effects = policy(model=True), Provider(verdicts=["replan", "accept"]), []
    with LocalEngine(
        SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        planners={"repair": Planner()},
        parent_completion_policies={"business": selected},
    ) as engine:
        handle = engine.submit(
            spec("flat", planner="repair"), {"value": 7}, command_id="s", budget=14
        )
        final = asyncio.run(engine.drive(handle.run_id))
        assert final.state == "succeeded"
        assert "verification_feedback" not in requests[0]
        assert requests[1]["verification_feedback"]["feedback"] == "Repair the result"
        assert len(effects) == 2
        assert set(engine.store.run(handle.run_id)["parent_completion_stages"]) == {"r0", "r1"}


def test_team_replan_policy_is_refused_before_business_calls(tmp_path):
    selected, provider = policy(missing="replan"), Provider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.sqlite"),
        providers={"default": provider},
        tools=tools([]),
        parent_completion_policies={"business": selected},
    ) as engine:
        with pytest.raises(ValidationError):
            engine.submit(spec("team"), {}, command_id="s")
        assert provider.calls == []


@pytest.mark.parametrize("container", ["team", "sequence", "graph"])
def test_nested_owned_container_exposes_original_final_consumption(tmp_path, container):
    from relf_agent import GraphNode, GraphWorkflowSpec, WorkflowSpec

    public = api()
    captured = []

    class Gate:
        identity = {"kind": "inspect-owned-evidence", "version": "1"}

        def verify(self, request):
            self.requests.append(request.to_dict())
            return api().ParentCompletionVerdict("accept")

    gate = Gate()
    gate.requests = captured
    leaf = AgentSpec("leaf", "worker", tools=("measure",))
    nested = (
        TeamSpec("nested", {"leaf": leaf}, child_budget=3)
        if container == "team"
        else WorkflowSpec("nested", [leaf])
        if container == "sequence"
        else GraphWorkflowSpec("nested", [GraphNode("leaf", agent=leaf)])
    )
    parent = DynamicWorkflowSpec(
        "parent", {"group": nested}, completion_policy="business", child_budget=5
    )
    provider, effects = Provider(), []
    with LocalEngine(
        SQLiteStore(tmp_path / "nested.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        parent_completion_policies={"business": public.ParentCompletionPolicy(gate)},
    ) as engine:
        handle = engine.submit(parent, {"value": 7}, command_id="s", budget=9)
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        source = captured[0]
        assert source["children"][0]["member_path"] == ["group"]
        assert source["children"][0]["final_action_id"] is None
        assert source["receipts"][0]["member_path"] == (
            ["group", "steps", "0"] if container == "sequence" else ["group", "leaf"]
        )
        assert source["receipts"][0]["consumed_by"]
        model_slots = [slot for child in source["children"] for slot in child["final_models"]]
        assert len(model_slots) == 1 and model_slots[0]["input_consumed"] is True
        assert len(effects) == 1


def test_unknown_business_evidence_cannot_run_gate(tmp_path):
    public = api()
    calls = []

    class Gate:
        identity = {"kind": "known-source-only", "version": "1"}

        def verify(self, request):
            self.requests.append(request)
            return api().ParentCompletionVerdict("accept")

    class UnknownProvider:
        identity = {"kind": "lost-model", "version": "1"}

        async def complete(self, messages, tools):
            raise RuntimeError("lost after model dispatch")

    gate = Gate()
    gate.requests = calls
    with LocalEngine(
        SQLiteStore(tmp_path / "unknown.sqlite"),
        providers={"default": UnknownProvider()},
        tools=tools([]),
        parent_completion_policies={"business": public.ParentCompletionPolicy(gate)},
    ) as engine:
        handle = engine.submit(spec("flat"), {}, command_id="s", budget=7)
        assert asyncio.run(engine.drive(handle.run_id)).state == "outcome_unknown"
        assert calls == []
        assert engine.diagnostics(handle.run_id).budget["held"] == 3


def test_verifier_budget_exhaustion_prevents_model_dispatch(tmp_path):
    selected, provider = policy(model=True), Provider()
    with LocalEngine(
        SQLiteStore(tmp_path / "budget.sqlite"),
        providers={"default": provider},
        tools=tools([]),
        parent_completion_policies={"business": selected},
    ) as engine:
        handle = engine.submit(spec("team"), {}, command_id="s", budget=3)
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        assert len(provider.calls) == 2


def test_model_verifier_cancel_waits_for_real_call_and_retains_late_evidence(tmp_path):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        selected = policy(model=True)

        class SlowProvider(Provider):
            async def complete(self, messages, tools):
                if messages[0]["content"] == "judge":
                    started.set()
                    await release.wait()
                return await super().complete(messages, tools)

        provider = SlowProvider()
        with LocalEngine(
            SQLiteStore(tmp_path / "cancel.sqlite"),
            providers={"default": provider},
            tools=globals()["tools"]([]),
            parent_completion_policies={"business": selected},
        ) as engine:
            handle = engine.submit(spec("team"), {}, command_id="s", budget=7)
            drive = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), timeout=3)
            engine.cancel(handle.run_id, command_id="cancel")
            for _ in range(5):
                await asyncio.sleep(0)
            assert not drive.done()
            assert engine.diagnostics(handle.run_id).budget["held"] > 0
            release.set()
            final = await drive
            assert final.state == "cancelled" and final.result is None
            child = engine.store.run(
                engine.store.run(handle.run_id)["orchestration"]["children"][-1]["run_id"]
            )
            assert child["actions"][-1].get("received_response") is not None
            assert engine.diagnostics(handle.run_id).budget["held"] == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("status", ["needs_input", "refused"])
def test_planning_conclusion_is_gated_with_no_stale_business_source(tmp_path, status):
    from relf_agent.dag_planning import PlanningConclusion

    public = api()
    captured = []

    class Planner:
        identity = {"kind": "stopped-plan", "version": "1"}

        async def plan(self, request, caller):
            return PlanningConclusion(status, "Task cannot proceed")

    class Gate:
        identity = {"kind": "verify-stopped-plan", "version": "1"}

        def verify(self, request):
            self.requests.append(request.to_dict())
            return api().ParentCompletionVerdict("accept")

    provider, gate = Provider(), Gate()
    gate.requests = captured
    with LocalEngine(
        SQLiteStore(tmp_path / "conclusion.sqlite"),
        providers={"default": provider},
        planners={"stop": Planner()},
        tools=tools([]),
        parent_completion_policies={"business": public.ParentCompletionPolicy(gate)},
    ) as engine:
        handle = engine.submit(spec("dag", planner="stop"), {}, command_id="s")
        final = asyncio.run(engine.drive(handle.run_id))
        assert final.state == "succeeded" and final.result["status"] == status
        assert captured[0]["plan"] == final.result
        assert captured[0]["children"] == captured[0]["receipts"] == []
        assert provider.calls == []


@pytest.mark.parametrize(
    "mutation", ["unknown_field", "bad_status", "adopted_foreign_id", "false_child_link"]
)
def test_original_journal_rejects_malformed_saved_authority(tmp_path, mutation):
    from relf_agent.errors import DefinitionMismatch

    with LocalEngine(
        SQLiteStore(tmp_path / "journal.sqlite"),
        providers={"default": Provider()},
        tools=tools([]),
        parent_completion_policies={"business": policy()},
    ) as engine:
        handle = engine.submit(spec("team"), {}, command_id="s", budget=7)
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        run = engine.store.run(handle.run_id)
        journal = run["parent_completion_stages"]["r0"]
        if mutation == "unknown_field":
            journal["unpublished"] = True
        elif mutation == "bad_status":
            journal["status"] = "child_pending"
        elif mutation == "adopted_foreign_id":
            journal["adopted_verdict"]["evidence_ids"] = ["child:" + "a" * 64]
        else:
            journal.update(
                child_key="r0.verifier.verdict",
                child_run_id="foreign",
                child_release_digest="a" * 64,
            )
        with pytest.raises(DefinitionMismatch):
            engine._check_release(run)


def test_policy_registry_requires_named_mapping_before_any_dispatch(tmp_path):
    with pytest.raises(ValidationError):
        LocalEngine(
            SQLiteStore(tmp_path / "mapping.sqlite"),
            providers={"default": Provider()},
            tools=tools([]),
            parent_completion_policies=["business"],
        )


@pytest.mark.parametrize("context_kind", ["custom", "budget-reader", "managed-reader"])
def test_verifier_inherited_context_requires_proven_auxiliary_isolation(tmp_path, context_kind):
    from relf_agent import InMemoryArtifactStore
    from relf_agent.context import ContextAssembler
    from relf_agent.context_budget import ContextMeasure
    from relf_agent.context_pipeline import BudgetedContextAssembler
    from relf_agent.data_context import ManagedDataContext

    calls = []

    class Reader:
        identity = {"kind": "unowned-reader", "version": "1"}

        def count(self, messages):
            self.calls.append("read")
            return ContextMeasure(1, "characters", True)

    class Context(ContextAssembler):
        identity = {"kind": "opaque-context", "version": "1"}

    reader = Reader()
    reader.calls = calls
    context = (
        Context()
        if context_kind == "custom"
        else BudgetedContextAssembler(counter=reader)
        if context_kind == "budget-reader"
        else ManagedDataContext(InMemoryArtifactStore())
    )
    provider = Provider()
    with LocalEngine(
        SQLiteStore(tmp_path / "isolation.sqlite"),
        providers={"default": provider},
        tools=tools([]),
        context_assembler=context,
        parent_completion_policies={"business": policy(model=True)},
    ) as engine:
        with pytest.raises(ValidationError):
            engine.submit(spec("team"), {}, command_id="s")
        assert provider.calls == calls == []


@pytest.mark.parametrize("project_current", [False, True])
def test_native_history_consumption_uses_current_turn_not_same_old_call_id(
    tmp_path, project_current
):
    import copy

    from relf_agent import CompleteModelHistory
    from relf_agent.harness import ModelRequest, NativeHarness
    from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
    from relf_agent.parent_completion_rules import ReceiptParentCompletionGate
    from relf_agent.types import canonical

    class NativeProvider:
        identity = {"kind": "current-turn-receipt-fixture", "version": "1"}
        continuation_identity = {"protocol": "receipt-fixture-v1", "owner_digest": "a" * 64}

        def __init__(self):
            self.calls = []

        async def complete(self, messages, tools):
            self.calls.append(copy.deepcopy(messages))
            calls = (
                [ToolCall("measure", {"value": 7}, "repeated-call")] if len(self.calls) % 2 else []
            )
            output = None if calls else {"value": 7}
            decision = {
                "output": output,
                "tool_calls": [
                    {"name": c.name, "arguments": c.arguments, "call_id": c.call_id} for c in calls
                ],
            }
            return ContinuedModelResponse(
                output=output,
                tool_calls=calls,
                continuation=ModelContinuation(
                    "receipt-fixture-v1",
                    "a" * 64,
                    digest(decision),
                    {"signature": str(len(self.calls))},
                ),
            )

    class Projection(NativeHarness):
        identity = {"kind": "current-tool-projection", "version": "1"}

        def prepare(self, spec, messages, descriptions):
            request = super().prepare(spec, messages, descriptions)
            current = copy.deepcopy(request.messages)
            indexes = [i for i, item in enumerate(current) if item["role"] == "tool"]
            if len(indexes) == 2:
                current[indexes[-1]]["content"] = canonical({"summary": "value 7"})
            return ModelRequest(current, request.tools)

    selected = api().ParentCompletionPolicy(
        ReceiptParentCompletionGate(
            [
                {
                    "id": "value",
                    "member_path": ["worker"],
                    "tool": "measure",
                    "output_bindings": {"/value": {"source": "candidate", "pointer": "/value"}},
                }
            ],
            required_members=(["worker"],),
        )
    )
    provider, effects = NativeProvider(), []
    with LocalEngine(
        SQLiteStore(tmp_path / "native.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        model_continuation=True,
        model_history=CompleteModelHistory(scope="session", allow_tool_result_projection=True),
        harness=Projection() if project_current else None,
        parent_completion_policies={"business": selected},
    ) as engine:
        first = engine.submit(
            spec("team"), {"turn": 1}, session_id="same", command_id="one", budget=9
        )
        assert asyncio.run(engine.drive(first.run_id)).state == "succeeded"
        second = engine.submit(
            spec("team"), {"turn": 2}, session_id="same", command_id="two", budget=9
        )
        result = asyncio.run(engine.drive(second.run_id))
        assert result.state == ("failed" if project_current else "succeeded")
        source = engine.store.run(second.run_id)["parent_completion_stages"]["r0"]["source"]
        assert source["children"][0]["input_consumed"] is True
        assert bool(source["receipts"][0]["consumed_by"]) is (not project_current)
        assert len(provider.calls) == 4 and len(effects) == 2


@pytest.mark.parametrize("kind", ["flat", "dag"])
def test_previous_revision_good_receipt_cannot_prove_current_candidate(tmp_path, kind):
    from relf_agent import Verification

    class OldVerifier:
        identity = {"kind": "revision-candidate", "version": "1"}

        def verify(self, request):
            return (
                Verification("replan")
                if request.revision == 0
                else Verification("succeeded", {"value": 7})
            )

    class ProviderWithoutNewReceipt(Provider):
        async def complete(self, messages, tools):
            if len(self.calls) == 2:
                self.calls.append(messages)
                return ModelResponse({"value": 7})
            return await super().complete(messages, tools)

    provider, effects = ProviderWithoutNewReceipt(), []
    with LocalEngine(
        SQLiteStore(tmp_path / "revision.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        plan_verifiers={"candidate": OldVerifier()},
        parent_completion_policies={"business": policy(model=True)},
    ) as engine:
        handle = engine.submit(
            spec(kind, verifier="candidate", max_revisions=2), {}, command_id="s", budget=10
        )
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed"
        source = engine.store.run(handle.run_id)["parent_completion_stages"]["r1"]["source"]
        assert len(source["children"]) == 1 and source["children"][0]["planning_revision"] == 1
        assert source["receipts"] == []
        assert len(provider.calls) == 3 and len(effects) == 1


def test_nested_plan_internal_revision_keeps_root_source_revision(tmp_path):
    from relf_agent import Verification

    class OldVerifier:
        identity = {"kind": "nested-revision", "version": "1"}

        def verify(self, request):
            return (
                Verification("replan")
                if request.revision == 0
                else Verification("succeeded", {"value": 7})
            )

    class Capture:
        identity = {"kind": "root-revision-source", "version": "1"}

        def verify(self, request):
            self.source = request.to_dict()
            return api().ParentCompletionVerdict("accept")

    gate, effects = Capture(), []
    inner = DynamicWorkflowSpec(
        "inner",
        {"leaf": AgentSpec("leaf", "worker", tools=("measure",))},
        verifier="repair",
        child_budget=3,
        max_revisions=2,
    )
    outer = TeamSpec("outer", {"group": inner}, completion_policy="business", child_budget=7)
    with LocalEngine(
        SQLiteStore(tmp_path / "nested-revision.sqlite"),
        providers={"default": Provider()},
        tools=tools(effects),
        plan_verifiers={"repair": OldVerifier()},
        parent_completion_policies={"business": api().ParentCompletionPolicy(gate)},
    ) as engine:
        handle = engine.submit(outer, {}, command_id="s", budget=9)
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        assert [child["planning_revision"] for child in gate.source["children"]] == [0, 0]
        assert len(gate.source["receipts"]) == 1 and len(effects) == 2


@pytest.mark.parametrize("mode", ["foreign-id", "tool-proposal", "replacement"])
def test_managed_verifier_proposal_cannot_expand_authority(tmp_path, mode):
    class InvalidJudge(Provider):
        async def complete(self, messages, descriptions):
            if messages[0]["content"] == "judge":
                self.calls.append(messages)
                if self.mode == "tool-proposal":
                    return ModelResponse(tool_calls=[ToolCall("measure", {"value": 8}, "unowned")])
                return ModelResponse(
                    {"status": "accept", "feedback": None, "evidence_ids": ["child:" + "a" * 64]}
                    if self.mode == "foreign-id"
                    else {
                        "status": "accept",
                        "feedback": None,
                        "evidence_ids": [],
                        "candidate": {"value": 8},
                    }
                )
            return await super().complete(messages, descriptions)

    provider, effects = InvalidJudge(), []
    provider.mode = mode
    with LocalEngine(
        SQLiteStore(tmp_path / "judge.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        parent_completion_policies={"business": policy(model=True)},
    ) as engine:
        handle = engine.submit(spec("team"), {}, command_id="s", budget=8)
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed" and result.result is None
        assert len(provider.calls) == 3 and len(effects) == 1
        assert engine.diagnostics(handle.run_id).budget["held"] == 0


def test_dynamic_verification_consumes_original_step_allowance(tmp_path):
    provider, effects = Provider(), []
    with LocalEngine(
        SQLiteStore(tmp_path / "steps.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        parent_completion_policies={"business": policy(model=True)},
    ) as engine:
        handle = engine.submit(spec("flat", max_steps=1), {}, command_id="s", budget=7)
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        assert len(provider.calls) == 2 and len(effects) == 1
        assert len(engine.store.run(handle.run_id)["orchestration"]["children"]) == 1
        assert engine.diagnostics(handle.run_id).budget["held"] == 0


def test_bound_parent_stage_uses_independent_provider_and_pure_context(tmp_path):
    from relf_agent import (
        AgentBindingDescriptor,
        BindingCatalog,
        BindingSelection,
        BoundDefinition,
        Scope,
    )
    from relf_agent.context import ContextAssembler
    from relf_agent.parent_verification_stage import ModelParentVerificationStage

    worker, judge, effects = Provider(), Provider(), []
    catalog = BindingCatalog(scope=Scope())
    catalog.register("provider", "worker", "1", worker)
    catalog.register("context", "audit", "1", ContextAssembler())
    selected = api().ParentCompletionPolicy(
        policy().gate,
        model_stage=ModelParentVerificationStage(
            provider="audit",
            instructions="judge",
            bindings=AgentBindingDescriptor(context=BindingSelection.ref("audit", "1")),
        ),
    )
    definition = BoundDefinition(
        spec("team"),
        {
            "team/members/worker": AgentBindingDescriptor(
                provider=BindingSelection.ref("worker", "1")
            )
        },
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "bound.sqlite"),
        providers={"default": Provider(), "audit": judge},
        tools=tools(effects),
        binding_catalog=catalog,
        parent_completion_policies={"business": selected},
    ) as engine:
        handle = engine.submit(definition, {}, command_id="s", budget=8)
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        run = engine.store.run(handle.run_id)
        assert run["manifest"]["kernel"] == "local-bindings-16"
        assert len(worker.calls) == 2 and len(judge.calls) == 1 and len(effects) == 1
        verifier = engine.store.run(run["orchestration"]["children"][-1]["run_id"])
        assert verifier["definition"]["steps"][0]["provider"] == "audit"
        assert "model_history_protocol" not in verifier["manifest"]


def test_changed_business_source_is_rejected_before_verifier_io(tmp_path):
    from relf_agent.parent_verification_stage import ModelParentVerificationStage

    class MutatingGate:
        identity = {"kind": "source-corruption-fixture", "version": "1"}

        def verify(self, request):
            with self.engine.store.transaction():
                child = self.engine.store.run(request.children[0]["run_id"])
                child["result"] = {"value": 99}
                self.engine.store.save_run(child)
            return api().ParentCompletionVerdict("accept")

    gate, provider = MutatingGate(), Provider()
    selected = api().ParentCompletionPolicy(
        gate, model_stage=ModelParentVerificationStage(instructions="judge")
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "source.sqlite"),
        providers={"default": provider},
        tools=tools([]),
        parent_completion_policies={"business": selected},
    ) as engine:
        gate.engine = engine
        handle = engine.submit(spec("team"), {}, command_id="s", budget=8)
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        assert len(provider.calls) == 2


@pytest.mark.parametrize("require_consumed", [False, True])
def test_graph_direct_tool_receipt_requires_explicit_no_consumption_policy(
    tmp_path, require_consumed
):
    from relf_agent import GraphNode, GraphWorkflowSpec, Literal, ValueRef
    from relf_agent.parent_completion_rules import ReceiptParentCompletionGate
    from relf_agent.parent_verification_stage import ModelParentVerificationStage

    rule = {
        "id": "direct-measurement",
        "member_path": ["group", "measurement"],
        "tool": "measure",
        "output_bindings": {"/value": {"source": "candidate", "pointer": "/value"}},
    }
    if not require_consumed:
        rule["require_consumed"] = False
    gate = ReceiptParentCompletionGate([rule])
    selected = api().ParentCompletionPolicy(
        gate,
        model_stage=ModelParentVerificationStage(instructions="judge")
        if require_consumed
        else None,
    )
    graph = GraphWorkflowSpec(
        "direct-tool",
        [GraphNode("measurement", tool="measure", input=Literal({"value": 7}))],
        output=ValueRef("measurement"),
    )
    definition = TeamSpec("parent", {"group": graph}, completion_policy="business", child_budget=1)
    provider, effects = Provider(), []
    with LocalEngine(
        SQLiteStore(tmp_path / "direct-tool.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        parent_completion_policies={"business": selected},
    ) as engine:
        handle = engine.submit(definition, {}, command_id="s", budget=4)
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == ("failed" if require_consumed else "succeeded")
        assert provider.calls == [] and len(effects) == 1
        run = engine.store.run(handle.run_id)
        assert "parent_completion_stages" in run, (
            "A real unconsumed receipt must reach the declared pure gate"
        )
        stage = run["parent_completion_stages"]["r0"]
        assert stage["gate_verdict"]["status"] == ("reject" if require_consumed else "accept")
        child = engine.store.run(run["orchestration"]["children"][0]["run_id"])
        assert [action["kind"] for action in child["actions"]] == ["tool"]
        assert stage["source"]["children"][0]["final_models"] == []
        assert stage["source"]["children"][0]["final_action_id"] is None
        receipt = stage["source"]["receipts"][0]
        action = child["actions"][0]
        assert receipt["run_id"] == child["id"] and receipt["action_id"] == action["id"]
        assert receipt["member_path"] == ["group", "measurement"]
        assert receipt["result"] == receipt["arguments"] == {"value": 7}
        assert receipt["effect_key"] == action["effect_key"] == effects[0]
        assert receipt["receipt"] == action["receipt"] and receipt["consumed_by"] == []
        assert len(run["orchestration"]["children"]) == 1
        assert engine.diagnostics(handle.run_id).budget == {"limit": 4, "held": 0, "spent": 1}


class CustomVerificationStage:
    identity = {"kind": "custom-pure-verification-stage-fixture", "version": "1"}

    def __init__(self, agent):
        self.agent = agent

    def prepare(self, request):
        return request.to_dict()

    def interpret(self, request, output):
        return api().ParentCompletionVerdict.from_dict(output)


def custom_verification_stage(*, context=None, provider="default", history=False):
    from relf_agent import AgentBindingDescriptor, AgentDefinition, BindingSelection

    disabled = {
        name: BindingSelection.disabled()
        for name in (
            "facts",
            "knowledge",
            "stage_policy",
            "verifier",
            "workspace",
            "skills",
            "sandbox",
            "tool_set",
        )
    }
    if not history:
        disabled.update(
            session=BindingSelection.disabled(), model_history=BindingSelection.disabled()
        )
    if context is not None:
        disabled["context"] = context
    return CustomVerificationStage(
        AgentDefinition(
            AgentSpec(
                "judge",
                "judge",
                provider=provider,
                max_decisions=1,
                output_schema=api().PARENT_COMPLETION_VERDICT_SCHEMA,
            ),
            AgentBindingDescriptor(**disabled),
        )
    )


@pytest.mark.parametrize("selected", ["inherit", "ref"])
@pytest.mark.parametrize("context_kind", ["opaque", "wrapped-reader"])
def test_custom_stage_actual_context_is_proven_independently_of_artifact_binding(
    tmp_path, selected, context_kind
):
    from relf_agent import BindingCatalog, BindingSelection, Scope
    from relf_agent.context import ContextAssembler
    from relf_agent.context_budget import ContextMeasure
    from relf_agent.context_pipeline import BudgetedContextAssembler

    class OpaqueContext(ContextAssembler):
        identity = {"kind": "opaque-external-stage-context", "version": "1"}

        def assemble(self, history, references, max_chars):
            self.reads.append("unbudgeted-read")
            return super().assemble(history, references, max_chars)

    class Reader:
        identity = {"kind": "opaque-context-counter", "version": "1"}

        def count(self, messages):
            self.reads.append("unbudgeted-read")
            return ContextMeasure(1, "characters", True)

    reads, provider = [], Provider()
    reader = Reader()
    reader.reads = reads
    opaque = OpaqueContext()
    opaque.reads = reads
    context = opaque if context_kind == "opaque" else BudgetedContextAssembler(counter=reader)
    catalog = BindingCatalog(scope=Scope())
    if selected == "ref":
        catalog.register("context", "selected", "1", context)
    stage = custom_verification_stage(
        context=BindingSelection.ref("selected", "1") if selected == "ref" else None
    )
    assert stage.agent.bindings.artifacts.mode == "inherit"
    selected_policy = api().ParentCompletionPolicy(policy().gate, model_stage=stage)
    with LocalEngine(
        SQLiteStore(tmp_path / "custom-context.sqlite"),
        providers={"default": provider},
        tools=tools([]),
        context_assembler=context if selected == "inherit" else ContextAssembler(),
        binding_catalog=catalog,
        parent_completion_policies={"business": selected_policy},
    ) as engine:
        with pytest.raises(ValidationError, match="Context"):
            engine.submit(spec("team"), {}, command_id="s", budget=8)
        assert reads == provider.calls == []
        assert engine.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["flat", "dag"])
def test_mixed_completion_and_original_verifier_replans_consume_feedback_once(tmp_path, kind):
    from relf_agent import Literal, PlanProposal, PlanStep, Verification
    from relf_agent.dag_planning import DAGNode, DAGProposal

    class Planner:
        identity = {"kind": "mixed-replans-planner", "version": "1"}

        async def plan(self, request, caller):
            self.requests.append(request.to_dict())
            return (
                DAGProposal([DAGNode("work", "worker", input=Literal({"value": 7}))])
                if self.kind == "dag"
                else PlanProposal([PlanStep("work", "worker", {"value": 7})])
            )

    class Gate:
        identity = {"kind": "first-policy-replan", "version": "1"}

        def verify(self, request):
            return (
                api().ParentCompletionVerdict("replan", feedback="Repair revision zero")
                if request.revision == 0
                else api().ParentCompletionVerdict("accept")
            )

    class OldVerifier:
        identity = {"kind": "second-original-replan", "version": "1"}

        def verify(self, request):
            return (
                Verification("replan")
                if request.revision == 1
                else Verification("succeeded", request.results[-1]["result"])
            )

    planner, provider, effects = Planner(), Provider(), []
    planner.kind, planner.requests = kind, []
    with LocalEngine(
        SQLiteStore(tmp_path / "mixed-replans.sqlite"),
        providers={"default": provider},
        tools=tools(effects),
        planners={"mixed": planner},
        plan_verifiers={"original": OldVerifier()},
        parent_completion_policies={"business": api().ParentCompletionPolicy(Gate())},
    ) as engine:
        handle = engine.submit(
            spec(kind, planner="mixed", verifier="original", max_revisions=3),
            {},
            command_id="s",
            budget=12,
        )
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {"value": 7}
        assert [request["revision"] for request in planner.requests] == [0, 1, 2]
        assert "verification_feedback" not in planner.requests[0]
        assert planner.requests[1]["verification_feedback"]["revision"] == 0
        assert planner.requests[1]["verification_feedback"]["feedback"] == "Repair revision zero"
        assert "verification_feedback" not in planner.requests[2]
        run = engine.store.run(handle.run_id)
        assert (
            run["parent_completion_stages"]["r0"]["adopted_verdict"]["feedback"]
            == "Repair revision zero"
        )
        assert set(run["parent_completion_stages"]) == {"r0", "r2"}
        assert "verification_feedback" not in run["orchestration"]
        assert len(provider.calls) == 6 and len(effects) == 3
        assert engine.diagnostics(handle.run_id).budget == {"limit": 12, "held": 0, "spent": 9}


@pytest.mark.parametrize("native_history", [False, True])
@pytest.mark.parametrize("context_kind", ["builtin", "budgeted"])
def test_custom_stage_keeps_pure_context_provider_and_optional_session_history(
    tmp_path, native_history, context_kind
):
    from relf_agent import BindingCatalog, BindingSelection, CompleteModelHistory, Scope
    from relf_agent.context import ContextAssembler
    from relf_agent.context_pipeline import BudgetedContextAssembler
    from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation

    class NativeProvider(Provider):
        continuation_identity = {"protocol": "custom-verifier-fixture-v1", "owner_digest": "a" * 64}

        async def complete(self, messages, descriptions):
            response = await super().complete(messages, descriptions)
            decision = {
                "output": response.output,
                "tool_calls": [
                    {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
                    for call in response.tool_calls
                ],
            }
            return ContinuedModelResponse(
                output=response.output,
                tool_calls=response.tool_calls,
                continuation=ModelContinuation(
                    "custom-verifier-fixture-v1",
                    "a" * 64,
                    digest(decision),
                    {"signature": str(len(self.calls))},
                ),
            )

    worker = NativeProvider() if native_history else Provider()
    judge = NativeProvider() if native_history else Provider()
    catalog = BindingCatalog(scope=Scope())
    catalog.register(
        "context",
        "pure",
        "1",
        ContextAssembler() if context_kind == "builtin" else BudgetedContextAssembler(),
    )
    stage = custom_verification_stage(
        provider="audit", context=BindingSelection.ref("pure", "1"), history=native_history
    )
    effects = []
    with LocalEngine(
        SQLiteStore(tmp_path / "custom-pure.sqlite"),
        providers={"default": worker, "audit": judge},
        tools=tools(effects),
        binding_catalog=catalog,
        model_continuation=native_history,
        model_history=CompleteModelHistory(scope="session") if native_history else None,
        parent_completion_policies={
            "business": api().ParentCompletionPolicy(policy().gate, model_stage=stage)
        },
    ) as engine:
        handle = engine.submit(spec("team"), {}, command_id="s", budget=8)
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        run = engine.store.run(handle.run_id)
        child = engine.store.run(run["orchestration"]["children"][-1]["run_id"])
        entry = child["manifest"]["agent_bindings"]["steps"]["agent"]
        assert entry["manifest"]["context_builder"]["kind"] == (
            "bounded-context" if context_kind == "builtin" else "budgeted-context"
        )
        assert (entry["manifest"].get("model_history_protocol") == 2) is native_history
        assert len(worker.calls) == 2 and len(judge.calls) == 1 and len(effects) == 1
        assert engine.diagnostics(handle.run_id).budget == {"limit": 8, "held": 0, "spent": 4}


def test_custom_agent_spec_stage_checks_actual_context_before_auxiliary_admission(tmp_path):
    from relf_agent.context import ContextAssembler

    class OpaqueContext(ContextAssembler):
        identity = {"kind": "raw-verifier-opaque-context", "version": "1"}

        def assemble(self, history, references, max_chars):
            raise AssertionError("Unowned reader must never run")

    provider = Provider()
    stage = CustomVerificationStage(
        AgentSpec(
            "judge", "judge", max_decisions=1, output_schema=api().PARENT_COMPLETION_VERDICT_SCHEMA
        )
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "raw-stage.sqlite"),
        providers={"default": provider},
        tools=tools([]),
        context_assembler=OpaqueContext(),
        parent_completion_policies={
            "business": api().ParentCompletionPolicy(policy().gate, model_stage=stage)
        },
    ) as engine:
        with pytest.raises(ValidationError, match="pure Context"):
            engine.submit(spec("team"), {}, command_id="s", budget=8)
        assert provider.calls == []
        assert engine.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
