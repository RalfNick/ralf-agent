"""History-owned parent verification: fixtures prove execution, not model quality."""

import asyncio
import copy
import importlib
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, DynamicWorkflowSpec, ModelResponse, Scope, TeamSpec, ToolRegistry
from ralf_agent.errors import RalfError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import request_release_digest
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.types import canonical, digest, submission_request


class Provider:
    identity = {"kind": "parent-completion-fixture", "version": "1"}

    def __init__(self):
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        return ModelResponse(output={"status": "accept", "feedback": None, "evidence_ids": []})


class Gate:
    identity = {"kind": "temporal-parent-test-gate", "version": "1"}

    def __init__(self, status="accept"):
        self.identity = {**self.identity, "status": status}
        self.calls = []

    def verify(self, request):
        from ralf_agent.parent_completion import ParentCompletionVerdict

        self.calls.append(request.to_dict())
        return ParentCompletionVerdict(
            self.identity["status"],
            feedback=None if self.identity["status"] == "accept" else "use committed evidence",
            evidence_ids=[c["id"] for c in request.children],
        )


def public(name):
    module = importlib.import_module(
        "ralf_agent.parent_verification_stage"
        if name == "ModelParentVerificationStage"
        else "ralf_agent.parent_completion"
    )
    value = getattr(module, name, None)
    assert value is not None, "Missing parent completion public contract: " + name
    return value


def setup(*, kind="team", status="accept", stage=False, budget=20, **runtime_options):
    gate, provider = Gate(status), Provider()
    policy = public("ParentCompletionPolicy")(
        gate,
        model_stage=public("ModelParentVerificationStage")() if stage else None,
        verifier_budget=1,
    )
    runtime = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        parent_completion_policies={"checked": policy},
        **runtime_options,
    )
    members = {"a": AgentSpec("a", "Answer")}
    spec = (
        TeamSpec("team", members, child_budget=4, completion_policy="checked")
        if kind == "team"
        else DynamicWorkflowSpec(
            "plan",
            members,
            child_budget=4,
            max_steps=8,
            max_revisions=2,
            completion_policy="checked",
        )
    )
    state = TemporalParentState(
        "parent",
        asdict(Scope()),
        "first",
        submission_request(spec, {"task": "x"}, budget=budget),
        runtime.orchestration_release,
    )
    return runtime, state, gate, provider


def observe(state, call, result, *, quiet=True, revision=2):
    messages = [
        {"role": "system", "content": "Answer"},
        {"role": "user", "content": canonical(call["input"])},
    ]
    model = {
        "id": call["run_id"] + ":model:0:1",
        "kind": "model",
        "node": 0,
        "status": "completed",
        "dispatch_request": {"messages": messages},
        "response": {
            "output": result,
            "tool_calls": [],
            "decision_evidence": {"prepared_request": {"messages": messages, "tools": []}},
        },
    }
    value = {
        "scope": state.scope,
        "snapshot": {
            "run_id": call["run_id"],
            "state": "succeeded",
            "state_revision": revision,
            "result": result,
            "error": None,
            "pending": [],
            "actions": [model],
            "consistency": "authoritative",
        },
        "manifest": state.manifest,
        "release_digest": request_release_digest(call["request"], state.manifest),
        "budget": {
            "allowance": call["cap"],
            "spent": 1,
            "reserved": 0,
            "unknown": 0,
            "remaining": call["cap"] - 1,
            "reservations": [],
        },
        "workflow": {
            "quiescent": quiet,
            "remote_stop_confirmed": quiet,
            "evidence_ack_pending": False,
            "reconciliation_pending": False,
        },
    }
    state.observe(call["run_id"], value)
    return value


def candidate(state, result=None):
    result = {"answer": 6} if result is None else result
    state.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": {"q": 2}}], "done": False, "result": None}
    )
    call = state.next_calls()[0]
    state.mark_started(call["run_id"])
    observe(state, call, result)
    state.accept_selection({"calls": [], "done": True, "result": result})
    return call


def evaluate(runtime, state):
    action, request = state.next_parent_completion_operation()
    response = asyncio.run(runtime.verify_parent_completion(request))
    state.accept_parent_completion(action["id"], response)
    return action, request, response


def review_dag(*, stage=False):
    from ralf_agent.dag_planning import DAGNode, DAGProposal
    from ralf_agent.workflow import Literal

    runtime, _, gate, provider = setup(kind="dynamic", stage=stage)
    definition = DynamicWorkflowSpec(
        "review",
        {"a": AgentSpec("a", "Answer"), "b": AgentSpec("b", "Answer")},
        plan_mode="dag",
        child_budget=4,
        max_steps=8,
        completion_policy="checked",
    )
    state = TemporalParentState(
        "review-parent",
        asdict(Scope()),
        "first",
        submission_request(definition, {"task": "x"}, budget=20),
        runtime.orchestration_release,
    )
    first = DAGNode("one", "a", input=Literal({"q": 2}))
    state.accept_selection(DAGProposal([first]).to_dict())
    call = state.next_calls()[0]
    observe(state, call, {"answer": 6})
    state.next_calls()
    state.accept_verification({"status": "succeeded", "result": {"answer": 6}})
    return runtime, state, first, call, gate, provider


@pytest.mark.parametrize("managed", [False, True])
def test_review_patch_rejected_while_gate_or_model_awaits(managed):
    from ralf_agent.dag_planning import DAGNode, DAGProposal
    from ralf_agent.workflow import ValueRef

    runtime, state, first, _, _, _ = review_dag(stage=managed)
    if managed:
        evaluate(runtime, state)
    else:
        state.next_parent_completion_operation()
    original = copy.deepcopy(state.dag)
    patch = DAGProposal([first, DAGNode("two", "b", depends_on=("one",), input=ValueRef("one"))])
    with pytest.raises(RalfError):
        state.patch(patch.to_dict(), state.plan_revision)
    assert state.dag == original and state.stage == "parent_completion"


@pytest.mark.parametrize(
    "fault",
    [
        "pending",
        "plan",
        "revision",
        "input",
        "result",
        "budget",
        "extra_child",
        "child_pending",
        "child_ack",
        "frozen_rewrite",
    ],
)
def test_review_adoption_rejects_current_business_source_drift(fault):
    runtime, state, _, call, _, _ = review_dag()
    action, request = state.next_parent_completion_operation()
    response = asyncio.run(runtime.verify_parent_completion(request))
    child = next(c for c in state.children if c["id"] == call["id"])
    if fault == "pending":
        state.dag["nodes"]["one"]["state"] = "pending"
    elif fault == "plan":
        state.dag["proposal"]["nodes"][0]["input"] = {"literal": {"q": 999}}
    elif fault == "revision":
        state.plan_revision += 1
    elif fault == "input":
        child["input"] = {"q": 999}
    elif fault == "result":
        child["snapshot"]["result"] = {"answer": 999}
    elif fault == "budget":
        state.request["budget"] += 1
    elif fault == "child_pending":
        child["snapshot"]["pending"] = [{"action_id": "late"}]
    elif fault == "child_ack":
        child["observed_flow"]["evidence_ack_pending"] = True
    elif fault == "frozen_rewrite":
        stage = state.parent_completion_stages["r0"]
        stage["source"]["candidate"] = {"answer": 999}
        stage["source_digest"] = digest(stage["source"])
    else:
        extra = copy.deepcopy(child)
        extra["id"] = "0:foreign"
        state.children.append(extra)
    state.accept_parent_completion(action["id"], response)
    assert state.state == "failed" and state.result is None
    assert state.parent_completion_stages["r0"]["status"] == "failed"


def test_review_settled_business_revision_bump_and_unique_verifier_are_legal():
    runtime, state, _, call, _, _ = review_dag(stage=True)
    evaluate(runtime, state)
    observe(state, call, {"answer": 6}, revision=3)
    verifier = next(c for c in state.next_calls() if c.get("role") == "verifier")
    observe(state, verifier, {"status": "accept", "feedback": None, "evidence_ids": []})
    evaluate(runtime, state)
    assert state.state == "succeeded" and state.budget["spent"] == 2


def test_review_verifier_accounting_normalization_cannot_hide_over_cap_spend():
    runtime, state, _, _, _, _ = review_dag(stage=True)
    evaluate(runtime, state)
    verifier = next(c for c in state.next_calls() if c.get("role") == "verifier")
    observe(state, verifier, {"status": "accept", "feedback": None, "evidence_ids": []})
    next(c for c in state.children if c["id"] == verifier["id"])["spent"] = 2
    evaluate(runtime, state)
    assert state.state == "failed" and state.result is None


def test_review_execution_patch_retains_real_settled_node_lineage():
    from ralf_agent.dag_planning import DAGNode, DAGProposal
    from ralf_agent.workflow import Literal, ValueRef

    runtime, _, _, _ = setup(kind="dynamic")
    definition = DynamicWorkflowSpec(
        "retained",
        {"a": AgentSpec("a", "Answer")},
        plan_mode="dag",
        child_budget=4,
        max_steps=8,
        completion_policy="checked",
    )
    state = TemporalParentState(
        "retained",
        asdict(Scope()),
        "first",
        submission_request(definition, {}, budget=20),
        runtime.orchestration_release,
    )
    first = DAGNode("one", "a", input=Literal({"q": 2}))
    state.accept_selection(DAGProposal([first]).to_dict())
    original = state.next_calls()[0]
    observe(state, original, {"answer": 6})
    patched = DAGProposal([first, DAGNode("two", "a", depends_on=("one",), input=ValueRef("one"))])
    state.patch(patched.to_dict(), state.plan_revision)
    observe(state, state.next_calls()[0], {"answer": 12})
    state.next_calls()
    state.accept_verification({"status": "succeeded", "result": {"answer": 12}})
    source = state.parent_completion_stages["r0"]["source"]
    assert [c["call_id"] for c in source["children"]] == ["one", "two"]
    assert source["children"][0]["run_id"] == original["run_id"]
    evaluate(runtime, state)
    assert state.state == "succeeded" and state.result == {"answer": 12}


@pytest.mark.parametrize("status", ["needs_input", "refused"])
def test_review_stopping_conclusion_has_exact_proposal_and_no_old_business_source(status):
    from ralf_agent import ChildCall, PlanProposal

    runtime, state, gate, _ = setup(kind="dynamic")
    state.accept_selection(PlanProposal([ChildCall("one", "a", {"q": 2})]).to_dict())
    observe(state, state.next_calls()[0], {"answer": 6})
    state.next_calls()
    state.accept_verification({"status": "replan", "result": None})
    conclusion = {"status": status, "reason": "Need new input"}
    state.accept_selection(conclusion)
    frozen = state.parent_completion_stages["r1"]["source"]
    assert frozen["plan"] == frozen["candidate"] == conclusion
    assert frozen["children"] == frozen["receipts"] == []
    restored = copy.deepcopy(state)
    evaluate(runtime, restored)
    assert restored.state == "succeeded" and restored.result == conclusion
    assert gate.calls[-1]["plan"] == conclusion and gate.calls[-1]["children"] == []


def test_review_policy_then_original_verifier_replans_reach_actual_revision2_model_planner():
    from ralf_agent import ChildCall, ModelPlanner
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.temporal_control_activities import select
    from ralf_agent.temporal_state import TemporalRunState

    class ReplanGate:
        identity = {"kind": "review-mixed-gate", "version": "1"}

        def verify(self, request):
            from ralf_agent.parent_completion import ParentCompletionVerdict

            return (
                ParentCompletionVerdict("replan", feedback="first policy feedback")
                if request.revision == 0
                else ParentCompletionVerdict("accept")
            )

    class OldVerifier:
        identity = {"kind": "review-mixed-old-verifier", "version": "1"}

        def verify(self, request):
            from ralf_agent import Verification

            return (
                Verification("replan")
                if request.revision == 1
                else Verification("succeeded", request.results[-1]["result"])
            )

    class PlannerProvider:
        identity = {"kind": "review-mixed-planner-provider", "version": "1"}

        def __init__(self):
            self.inputs = []

        async def complete(self, messages, tools):
            import json

            value = json.loads(messages[1]["content"])
            self.inputs.append(value)
            return ModelResponse(
                output={
                    "steps": [
                        {"id": "work" + str(value["revision"]), "member": "a", "input": {"q": 2}}
                    ]
                }
            )

    async def run():
        planner = PlannerProvider()
        runtime = TemporalRuntime(
            providers={"default": Provider(), "planner": planner},
            tools=ToolRegistry(),
            planners={"model": ModelPlanner(provider="planner")},
            plan_verifiers={"old": OldVerifier()},
            parent_completion_policies={"checked": ParentCompletionPolicy(ReplanGate())},
        )
        definition = DynamicWorkflowSpec(
            "mixed",
            {"a": AgentSpec("a", "Answer")},
            planner="model",
            verifier="old",
            child_budget=4,
            max_steps=8,
            max_revisions=3,
            completion_policy="checked",
        )
        state = TemporalParentState(
            "mixed",
            asdict(Scope()),
            "first",
            submission_request(definition, {}, budget=20),
            runtime.orchestration_release,
        )
        for revision in range(3):
            planning = state.planning_request()
            assert planning["revision"] == revision
            managed = state.delegate(ChildCall("planner", "@planner", planning))
            child = TemporalRunState(
                managed["run_id"],
                state.scope,
                managed["command_id"],
                managed["request"],
                state.manifest,
            )
            await drive_native(runtime, child)
            state.observe(managed["run_id"], {"scope": state.scope, **child.diagnostics()})
            proposal = await select(
                runtime,
                {
                    "runtime_manifest": state.manifest,
                    "kind": "plan",
                    "definition": state.definition,
                    "planning_request": planning,
                    "planner_snapshot": child.snapshot(),
                },
            )
            state.accept_selection(proposal)
            observe(state, state.next_calls()[0], {"answer": 6})
            state.next_calls()
            verification = await select(
                runtime,
                {
                    "runtime_manifest": state.manifest,
                    "kind": "verify",
                    "definition": state.definition,
                    "planning_request": state.planning_request(),
                },
            )
            state.accept_verification(verification)
            if state.stage == "parent_completion":
                action, request = state.next_parent_completion_operation()
                state.accept_parent_completion(
                    action["id"], await runtime.verify_parent_completion(request)
                )
        assert state.state == "succeeded" and state.result == {"answer": 6}
        assert [value["revision"] for value in planner.inputs] == [0, 1, 2]
        assert (
            "verification_feedback" not in planner.inputs[0]
            and "verification_feedback" not in planner.inputs[2]
        )
        assert planner.inputs[1]["verification_feedback"]["revision"] == 0
        assert (
            state.parent_completion_stages["r0"]["adopted_verdict"]["feedback"]
            == "first policy feedback"
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "pending",
        "budget",
        "allowance",
        "receipt",
        "stopped",
        "foreign",
        "duplicate",
        "extra_child",
    ],
)
@pytest.mark.parametrize("lost_reply", [False, True])
def test_review_final_session_publication_rechecks_source_and_exact_one_credit(fault, lost_reply):
    _review_final_session_publication(fault, lost_reply=lost_reply)


@pytest.mark.parametrize(
    "fault",
    [
        "proof_missing",
        "proof_scope",
        "proof_action",
        "proof_request",
        "proof_release",
        "proof_extra",
        "proof_unadmitted",
    ],
)
def test_review_lost_session_reply_requires_exact_original_end_proof(fault):
    _review_final_session_publication(fault, lost_reply=True)


@pytest.mark.parametrize("fault", ["ack_revision", "ack_stopped"])
def test_review_received_session_ack_must_still_match_revision_and_stop(fault):
    _review_final_session_publication(fault)


def _review_final_session_publication(fault, *, lost_reply=False):
    from ralf_agent import InMemoryMemory
    from ralf_agent.dag_planning import DAGNode, DAGProposal
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.temporal_session_state import TemporalSessionState
    from ralf_agent.temporal_session_topology import CompositeSessionTopology
    from ralf_agent.temporal_state import TemporalRunState
    from ralf_agent.workflow import Literal, ValueRef
    from tests.test_temporal_memory_bindings import grant
    from tests.test_temporal_session_tree_execution import complete_child, ended, root_operation

    class Business:
        identity = {"kind": "review-session-business", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output={"answer": 6})

    async def run():
        host = TemporalRuntime(
            providers={"default": Business()},
            tools=ToolRegistry(),
            parent_completion_policies={"checked": ParentCompletionPolicy(Gate())},
            enable_sessions=True,
            session_writes=True,
            session_store=InMemoryMemory(),
            session_topology=CompositeSessionTopology(),
        )
        definition = DynamicWorkflowSpec(
            "checked",
            {"a": AgentSpec("a", "Answer")},
            plan_mode="dag",
            child_budget=4,
            completion_policy="checked",
        )
        session = TemporalSessionState(
            {
                "scope": asdict(Scope()),
                "namespace_id": "owned",
                "session_namespace": None,
                "session_id": "chat",
                "command_id": "open",
                "request": submission_request(definition, None),
                "manifest": host.orchestration_release,
                "task_queue": "q",
                "activity_timeout": 3,
            }
        )
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": {"task": "x"},
                "budget": 20,
            }
        )
        intent = session.active
        parent = TemporalParentState(
            intent["run_id"],
            session.scope,
            intent["command_id"],
            intent["request"],
            intent["manifest"],
        )
        try:
            assert await root_operation(host, parent)
            first = DAGNode("one", "a", input=Literal({"q": 2}))
            parent.accept_selection(DAGProposal([first]).to_dict())
            call = parent.next_calls()[0]
            parent.children[0]["dispatch_started"] = True
            parent.mark_started(call["run_id"])
            child = TemporalRunState(
                call["run_id"], parent.scope, call["command_id"], call["request"], parent.manifest
            )
            await complete_child(host, child)
            parent.observe(call["run_id"], {"scope": parent.scope, **child.diagnostics()})
            parent.next_calls()
            parent.accept_verification({"status": "succeeded", "result": {"answer": 6}})
            action, request = parent.next_parent_completion_operation()
            parent.accept_parent_completion(
                action["id"], await host.verify_parent_completion(request)
            )
            assert parent.stage == "session-save" and parent.state == "running"
            reached = False
            end_confirmed = asyncio.Event()

            async def session_ended(proof):
                await ended(parent, proof)
                end_confirmed.set()

            while (operation := parent.next_session_operation()) is not None:
                action, request = operation
                if action["phase"] == "adopt":
                    reached = True
                    assert request["received_inspection"]["receipt"]["message"]["content"] == {
                        "answer": 6
                    }
                    patch = DAGProposal(
                        [first, DAGNode("two", "a", depends_on=("one",), input=ValueRef("one"))]
                    )
                    with pytest.raises(RalfError):
                        parent.patch(patch.to_dict(), parent.plan_revision)
                    if fault == "pending":
                        parent.dag["nodes"]["one"]["state"] = "pending"
                    elif fault == "budget":
                        parent.request["budget"] += 1
                    elif fault == "allowance":
                        parent.reservations[parent.root_write_allowance]["amount"] = 2
                    elif fault == "receipt":
                        parent.session_stages["root"]["received_inspection"]["receipt"]["message"][
                            "content"
                        ] = {"answer": 999}
                    elif fault == "stopped":
                        parent.session_stages["root"]["execution_stopped"] = False
                    elif fault == "foreign":
                        parent.reservations["foreign"] = {
                            "id": "foreign",
                            "amount": 1,
                            "status": "settled",
                            "actual": 0,
                        }
                    elif fault == "duplicate":
                        parent.reservations["duplicate"] = {
                            "id": "duplicate",
                            "amount": 1,
                            "status": "settled",
                            "actual": 1,
                        }
                    elif fault == "extra_child":
                        extra = copy.deepcopy(parent.children[0])
                        extra["id"] = "0:foreign"
                        parent.children.append(extra)
                    elif fault and fault.startswith("proof_"):
                        write = next(
                            a
                            for a in parent.actions
                            if a["id"] == parent.session_stages["root"]["write_action"]
                        )
                        if fault == "proof_missing":
                            del write["execution_end_proof"]
                        elif fault == "proof_unadmitted":
                            write["dispatch_grant"]["allowed"] = False
                        elif fault == "proof_extra":
                            write["execution_end_proof"]["unknown"] = True
                        else:
                            key = {
                                "proof_scope": "scope",
                                "proof_action": "action_id",
                                "proof_request": "request_digest",
                                "proof_release": "release_digest",
                            }[fault]
                            write["execution_end_proof"][key] = (
                                {"workspace": "foreign", "principal": "anonymous"}
                                if key == "scope"
                                else "foreign"
                            )
                response = await host.manage_session(
                    request,
                    dispatch_guard=lambda value: grant(parent, value),
                    on_end=session_ended,
                )
                if action["phase"] == "session-write":
                    await asyncio.wait_for(end_confirmed.wait(), 5)
                    assert "execution_end_proof" in action
                    if lost_reply:
                        response = {
                            "ok": False,
                            "code": "activity_outcome_unknown",
                            "dispatched": True,
                            "execution_stopped": False,
                        }
                    elif fault == "ack_revision":
                        response["revision"] += 1
                    elif fault == "ack_stopped":
                        response["execution_stopped"] = False
                parent.accept_session(action["id"], response)
                if parent.state == "waiting_reconciliation" and action["phase"] == "session-write":
                    assert lost_reply or fault == "ack_revision"
                    parent.retry_blocked()
            assert reached
            expected = (
                "succeeded"
                if fault is None
                else "waiting_reconciliation"
                if fault in {"receipt", "stopped"}
                else "failed"
            )
            assert parent.state == expected, parent.diagnostics()
            assert parent.result == ({"answer": 6} if fault is None else None)
            if fault is None:
                assert parent.budget["spent"] == 3 and parent.budget["reserved"] == 0
        finally:
            await host.close_session_execution(wait_timeout=5)

    asyncio.run(run())


def test_explicit_registry_publishes_protocol9_without_changing_old_release():
    runtime, state, _, _ = setup()
    assert runtime.manifest["binding_protocol"] == 9
    assert runtime.manifest["parent_completion_protocol"] == 1
    assert state.parent_completion_enabled
    old = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    assert "parent_completion_protocol" not in old.manifest
    assert "parent_completion_policies" not in old.manifest
    with pytest.raises(RalfError):
        old.validate_release(runtime.orchestration_release)


@pytest.mark.parametrize("status", ["accept", "reject"])
def test_pure_gate_freezes_owned_source_and_adopts_without_model(status):
    runtime, state, gate, provider = setup(status=status)
    call = candidate(state)
    assert state.state == "running" and state.result is None
    stage = state.parent_completion_stages["r0"]
    source = stage["source"]
    assert source["children"][0]["run_id"] == call["run_id"]
    assert source["children"][0]["input_consumed"] is True
    assert stage["source_digest"] == digest(source)
    evaluate(runtime, state)
    assert state.state == ("succeeded" if status == "accept" else "failed")
    assert len(gate.calls) == 1 and provider.calls == []
    assert stage["status"] == "adopted"
    restored = copy.deepcopy(state)
    assert restored.next_parent_completion_operation() is None
    assert len(gate.calls) == 1


def test_managed_stage_has_one_fixed_child_and_business_results_exclude_verifier():
    runtime, state, gate, _ = setup(stage=True)
    candidate(state)
    evaluate(runtime, state)
    calls = state.next_calls()
    verifier = next(c for c in calls if c.get("role") == "verifier")
    assert verifier["id"] == "r0.verifier.verdict"
    assert verifier["member"] == "@verifier" and verifier["cap"] == 1
    assert verifier["request"]["definition"]["steps"][0]["max_decisions"] == 1
    assert state.next_calls() == calls
    state.mark_started(verifier["run_id"])
    observe(state, verifier, {"status": "accept", "feedback": None, "evidence_ids": []})
    assert "@verifier" not in state.results
    assert state.parent_completion_stages["r0"]["status"] == "proposal_received"
    received = copy.deepcopy(state)
    evaluate(runtime, received)
    assert received.state == "succeeded" and received.result == {"answer": 6}
    assert len(gate.calls) == 1 and len(received.children) == 2


def test_managed_policy_activity_accepts_actual_temporal_json_normalization():
    import json

    runtime, state, _, _ = setup(stage=True)
    candidate(state)
    _, request = state.next_parent_completion_operation()
    wire = json.loads(canonical(request))
    response = asyncio.run(runtime.verify_parent_completion(wire))
    assert response["ok"] is True, response


def test_default_managed_stage_executes_plain_chat_without_native_protocols():
    from ralf_agent.temporal_state import TemporalRunState

    async def run():
        runtime, parent, gate, provider = setup(stage=True)
        candidate(parent)
        action, request = parent.next_parent_completion_operation()
        parent.accept_parent_completion(
            action["id"], await runtime.verify_parent_completion(request)
        )
        call = parent.next_calls()[0]
        child = TemporalRunState(
            call["run_id"], parent.scope, call["command_id"], call["request"], parent.manifest
        )
        await drive_native(runtime, child)
        parent.observe(call["run_id"], {"scope": parent.scope, **child.diagnostics()})
        action, request = parent.next_parent_completion_operation()
        parent.accept_parent_completion(
            action["id"], await runtime.verify_parent_completion(request)
        )
        assert parent.state == "succeeded" and len(provider.calls) == len(gate.calls) == 1
        assert "model_history_protocol" not in runtime.manifest
        assert "model_continuation_protocol" not in runtime.manifest
        assert parent.budget["spent"] == 2

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["fake", "wrapped-reader"])
def test_verifier_context_registration_rejects_fake_builtin_and_reader_wrappers(kind):
    from ralf_agent import (
        AgentBindingDescriptor,
        BindingCatalog,
        BindingSelection,
        BudgetedContextAssembler,
    )
    from ralf_agent.errors import ValidationError
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage

    class FakeContext:
        identity = {"kind": "bounded-context", "version": "2"}

        def assemble(self, history, references, max_chars):
            from ralf_agent import ContextAssembler

            return ContextAssembler().assemble(history, references, max_chars)

    class Reader:
        identity = {"kind": "reader-counter", "version": "1"}

        def count(self, messages):
            raise AssertionError("A custom reader must never run during verifier preflight")

    catalog = BindingCatalog(scope=Scope())
    context = FakeContext() if kind == "fake" else BudgetedContextAssembler(counter=Reader())
    catalog.register("context", "selected", "1", context)
    stage = ModelParentVerificationStage(
        bindings=AgentBindingDescriptor(context=BindingSelection.ref("selected", "1"))
    )
    with pytest.raises(ValidationError):
        TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            binding_catalog=catalog,
            parent_completion_policies={
                "checked": ParentCompletionPolicy(Gate(), model_stage=stage)
            },
        )


def test_cancelled_parent_charges_late_verifier_and_cannot_adopt_it():
    runtime, state, _, _ = setup(stage=True)
    candidate(state)
    evaluate(runtime, state)
    verifier = next(c for c in state.next_calls() if c.get("role") == "verifier")
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    observe(state, verifier, {"status": "accept", "feedback": None, "evidence_ids": []})
    assert state.state == "cancelled" and state.result is None
    assert state.budget["spent"] == 2 and state.budget["reserved"] == 0
    assert state.next_parent_completion_operation() is None


def test_gate_refusal_never_dispatches_model_stage_and_insufficient_cap_fails():
    runtime, state, gate, provider = setup(status="reject", stage=True)
    candidate(state)
    evaluate(runtime, state)
    assert state.state == "failed" and len(state.children) == 1
    assert len(gate.calls) == 1 and provider.calls == []
    runtime, state, _, _ = setup(stage=True, budget=0)
    state.accept_selection({"calls": [], "done": True, "result": {"answer": 6}})
    evaluate(runtime, state)
    assert state.state == "failed" and not state.children


def test_saved_source_drift_cannot_create_second_verifier_identity():
    runtime, state, _, _ = setup(stage=True)
    candidate(state)
    evaluate(runtime, state)
    stage = state.parent_completion_stages["r0"]
    stage["source"]["candidate"] = {"answer": 999}
    with pytest.raises(RalfError):
        state.prepare_parent_completion({"answer": 999})
    assert len([c for c in state.children if c.get("role") == "verifier"]) == 1


def test_checked_team_cannot_execute_same_business_member_under_new_call_id():
    _, state, _, _ = setup()
    candidate(state)
    # Before the pure gate, the original completed member cannot be redispatched.
    with pytest.raises(RalfError):
        state.accept_selection(
            {
                "calls": [{"id": "two", "member": "a", "input": {"q": 2}}],
                "done": False,
                "result": None,
            }
        )


def test_host_child_limit_counts_verifier_and_does_not_release_business_spend():
    from ralf_agent.governance import TemporalExecutionPolicy

    runtime, state, _, provider = setup(
        stage=True, execution_policy=TemporalExecutionPolicy(max_children=1)
    )
    candidate(state)
    evaluate(runtime, state)
    assert state.state == "failed" and state.budget["spent"] == 1
    assert len(state.children) == 1 and provider.calls == []


@pytest.mark.parametrize("mutation", ["frame", "foreign_run", "scope", "release", "unsettled"])
def test_parent_source_rejects_missing_or_foreign_original_child_evidence(mutation):
    _, state, _, _ = setup()
    state.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": {"q": 2}}], "done": False, "result": None}
    )
    call = state.next_calls()[0]
    observe(state, call, {"answer": 6})
    original = state.children[0]
    if mutation == "frame":
        original["snapshot"]["actions"][0]["response"].pop("decision_evidence")
    elif mutation == "foreign_run":
        original["run_id"] = "foreign"
    elif mutation == "scope":
        state.scope["principal"] = "other"
    elif mutation == "release":
        original["request"]["definition"]["steps"][0]["instructions"] = "forged"
    else:
        original["settled"] = False
    with pytest.raises(RalfError):
        state.prepare_parent_completion({"answer": 6})


def test_plan_replan_feedback_is_next_actual_planning_input_and_bounded():
    from ralf_agent import ChildCall, PlanProposal

    runtime, state, gate, provider = setup(kind="dynamic", status="replan")
    state.accept_selection(PlanProposal([ChildCall("one", "a", {"q": 2})]).to_dict())
    call = state.next_calls()[0]
    observe(state, call, {"answer": 6})
    state.next_calls()
    state.accept_verification({"status": "succeeded", "result": {"answer": 6}})
    evaluate(runtime, state)
    assert state.planning_revision == 1 and state.stage == "plan"
    request = state.planning_request()
    assert request["verification_feedback"] == {
        "revision": 0,
        "feedback": "use committed evidence",
        "evidence_ids": state.parent_completion_stages["r0"]["adopted_verdict"]["evidence_ids"],
        "source_digest": state.parent_completion_stages["r0"]["source_digest"],
    }
    assert request["revision"] == 1
    state.accept_selection(PlanProposal([ChildCall("two", "a", {"q": 3})]).to_dict())
    call = state.next_calls()[0]
    observe(state, call, {"answer": 9})
    state.next_calls()
    state.accept_verification({"status": "succeeded", "result": {"answer": 9}})
    evaluate(runtime, state)
    assert state.state == "failed" and state.error["code"] == "plan_revision_limit"
    assert len(gate.calls) == 2 and provider.calls == []
    assert len(state.parent_completion_stages["r1"]["source"]["children"]) == 1


def test_protocol9_preserves_complete_session_history2_composition():
    from ralf_agent import CompleteModelHistory
    from ralf_agent.temporal_state import validate_manifest

    runtime, _, _, _ = setup(
        model_continuation=True,
        model_history=CompleteModelHistory(scope="session"),
        enable_sessions=True,
    )
    manifest = runtime.orchestration_release
    assert manifest["binding_protocol"] == 9 and manifest["model_history_protocol"] == 2
    assert validate_manifest(manifest) == manifest


@pytest.mark.parametrize("fault", ["old-input", "old-tool-only"])
def test_parent_consumption_never_uses_a_previous_native_session_turn(fault):
    _, state, _, _ = setup()
    state.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": {"q": 2}}], "done": False, "result": None}
    )
    call = state.next_calls()[0]
    observe(state, call, {"answer": 6})
    model = state.children[0]["snapshot"]["actions"][0]
    current = model["response"]["decision_evidence"]["prepared_request"]["messages"]
    past = [
        current[0],
        current[1],
        {"role": "tool", "tool_call_id": "same-call", "content": '{"answer":6}'},
    ]
    model["dispatch_request"]["model_history_frame"] = {
        "turns": [{"history": past}],
        "history": current,
    }
    model["response"]["decision_evidence"]["prepared_request"]["messages"] = [
        *past,
        current[1] if fault == "old-tool-only" else {"role": "user", "content": '{"q":9}'},
    ]
    if fault == "old-tool-only":
        state.children[0]["snapshot"]["actions"].insert(
            0,
            {
                "id": "current-tool",
                "kind": "tool",
                "node": 0,
                "status": "completed",
                "call_id": "same-call",
                "tool": "calculate",
                "arguments": {"q": 2},
                "result": {"answer": 6},
                "receipt": {"source": "committed"},
                "effect_key": "original-key",
            },
        )
    state.prepare_parent_completion({"answer": 6})
    source = state.parent_completion_stages["r0"]["source"]
    if fault == "old-input":
        assert source["children"][0]["input_consumed"] is False
    else:
        assert source["receipts"][0]["consumed_by"] == []


async def drive_native(runtime, state):
    from tests.test_temporal_memory_bindings import grant

    for _ in range(30):
        operation = state.next_operation()
        if operation is None:
            pending = state.snapshot()["pending"]
            if pending:
                item = pending[0]
                state.command(
                    "approval",
                    {
                        "kind": "approve",
                        "scope": state.scope,
                        "action_id": item["action_id"],
                        "digest": item["digest"],
                        "approved": True,
                    },
                )
                continue
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
            assert action["kind"] == "tool", action
            state.accept_tool(action["id"], await runtime.execute_tool(request))
        while state.pending_acks:
            assert (await runtime.acknowledge_evidence(state.pending_acks.pop(0)))["ok"]
    assert state.state == "succeeded" and state.quiescent, state.diagnostics()


@pytest.mark.parametrize("kind", ["team-pure", "team", "plan", "dag"])
def test_actual_native_receipts_are_consumed_before_configured_gate_and_managed_stage(
    tmp_path, kind
):
    from ralf_agent import ChildCall
    from ralf_agent.temporal_control_activities import select
    from ralf_agent.temporal_state import TemporalRunState
    from tests.temporal_parent_completion_worker import runtime as fixture_runtime

    async def run():
        runtime, spec, clients, _ = fixture_runtime(tmp_path, kind)
        parent = TemporalParentState(
            "parent",
            asdict(Scope()),
            "submit",
            submission_request(spec, {"quantity": 3}, budget=20),
            runtime.orchestration_release,
        )
        try:
            for _ in range(30):
                completion = parent.next_parent_completion_operation()
                if completion is not None:
                    action, request = completion
                    parent.accept_parent_completion(
                        action["id"], await runtime.verify_parent_completion(request)
                    )
                    continue
                for call in parent.next_calls():
                    parent.mark_started(call["run_id"])
                    child = TemporalRunState(
                        call["run_id"],
                        parent.scope,
                        call["command_id"],
                        call["request"],
                        parent.manifest,
                    )
                    await drive_native(runtime, child)
                    parent.observe(call["run_id"], {"scope": parent.scope, **child.diagnostics()})
                if parent.state in {"succeeded", "failed"}:
                    break
                if parent.stage not in {"plan", "select", "verify"}:
                    continue
                previous = None
                if parent.stage == "plan":
                    planner = parent.manifest["orchestration"]["planners"][
                        parent.definition["planner"]
                    ]
                    previous = next(
                        (
                            c
                            for c in parent.children
                            if c["member"] == "@planner"
                            and c["planning_revision"] == parent.planning_revision
                        ),
                        None,
                    )
                    if planner["agent"] is not None and previous is None:
                        parent.delegate(ChildCall("planner", "@planner", parent.planning_request()))
                        continue
                value = {
                    "runtime_manifest": parent.manifest,
                    "definition": parent.definition,
                    "kind": "team" if parent.stage == "select" else parent.stage,
                    "input": parent.request["input"],
                    "results": parent.results,
                    "planning_request": previous["input"]
                    if previous
                    else parent.planning_request(),
                    "planner_snapshot": previous["snapshot"] if previous else None,
                }
                proposal = await select(runtime, value)
                if parent.stage == "verify":
                    parent.accept_verification(proposal)
                else:
                    parent.accept_selection(proposal)
            assert parent.state == "succeeded" and parent.result == {"amount": 6}, (
                parent.diagnostics()
            )
            stage = parent.parent_completion_stages["r0"]
            assert stage["status"] == "adopted"
            source = stage["source"]
            assert len(source["children"]) == len(source["receipts"]) == 1
            tool = source["receipts"][0]
            assert tool["result"] == source["candidate"] == {"amount": 6}
            final = source["children"][0]["final_models"][0]
            assert tool["consumed_by"] == ["model:" + digest([tool["run_id"], final["action_id"]])]
            assert final["input_consumed"] is True
            assert parent.budget["spent"] == 3 + int(kind != "team-pure") + int(kind == "plan")
            import json

            rows = [
                json.loads(line)
                for line in (tmp_path / "parent-audit.jsonl").read_text().splitlines()
            ]
            assert len([r for r in rows if r["kind"] == "model"]) == 2 + int(
                kind != "team-pure"
            ) + int(kind == "plan")
            business = [r for r in rows if r["kind"] == "model" and r["provider"] == "business"]
            assert any(
                i.get("type") == "reasoning" and i.get("encrypted_content")
                for i in business[-1]["body"]["input"]
            )
        finally:
            for client in clients:
                await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("container", ["sequence", "graph"])
def test_nested_container_keeps_real_run_ids_and_final_model_slots(container):
    from ralf_agent import GraphNode, GraphWorkflowSpec, ToolCall, WorkflowSpec
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.temporal_state import TemporalRunState

    class CalculationProvider:
        identity = {"kind": "container-receipt-provider", "version": "1"}

        async def complete(self, messages, tools):
            if tools and not any(m["role"] == "tool" for m in messages):
                return ModelResponse(
                    tool_calls=[ToolCall("calculate", {"quantity": 3}, "committed-call")]
                )
            return ModelResponse(output={"answer": 6})

    async def run():
        tools = ToolRegistry()

        def calculate(quantity: int):
            return {"answer": quantity * 2}

        tools.register_function(calculate, effect="read_only", requires_approval=False, cost=1)
        runtime = TemporalRuntime(
            providers={"default": CalculationProvider()},
            tools=tools,
            parent_completion_policies={"checked": ParentCompletionPolicy(Gate())},
        )
        calculator = AgentSpec("calculator", "Calculate", ("calculate",), max_decisions=2)
        nested = (
            WorkflowSpec("sequence", [calculator, AgentSpec("writer", "Use evidence")])
            if container == "sequence"
            else GraphWorkflowSpec("graph", [GraphNode("calculation", agent=calculator)])
        )
        spec = TeamSpec("outer", {"inner": nested}, child_budget=8, completion_policy="checked")
        parent = TemporalParentState(
            "parent",
            asdict(Scope()),
            "submit",
            submission_request(spec, {"quantity": 3}, budget=20),
            runtime.orchestration_release,
        )
        parent.accept_selection(
            {
                "calls": [{"id": "inner-call", "member": "inner", "input": {"quantity": 3}}],
                "done": False,
                "result": None,
            }
        )
        call = parent.next_calls()[0]
        cls = TemporalRunState if container == "sequence" else TemporalParentState
        child = cls(
            call["run_id"], parent.scope, call["command_id"], call["request"], parent.manifest
        )
        if container == "sequence":
            await drive_native(runtime, child)
        else:
            leaf_call = child.next_calls()[0]
            leaf = TemporalRunState(
                leaf_call["run_id"],
                child.scope,
                leaf_call["command_id"],
                leaf_call["request"],
                child.manifest,
            )
            await drive_native(runtime, leaf)
            child.observe(leaf_call["run_id"], {"scope": child.scope, **leaf.diagnostics()})
            child.next_calls()
            assert child.state == "succeeded"
        parent.observe(call["run_id"], {"scope": parent.scope, **child.diagnostics()})
        parent.accept_selection({"calls": [], "done": True, "result": child.result})
        action, request = parent.next_parent_completion_operation()
        parent.accept_parent_completion(
            action["id"], await runtime.verify_parent_completion(request)
        )
        assert parent.state == "succeeded"
        source = parent.parent_completion_stages["r0"]["source"]
        top = source["children"][0]
        assert top["run_id"] == child.run_id and top["input_consumed"] is None
        assert top["final_action_id"] is top["final_snapshot_digest"] is None
        assert len(top["final_models"]) == (2 if container == "sequence" else 0)
        assert len(source["receipts"]) == 1
        owner = next(
            c for c in source["children"] if c["run_id"] == source["receipts"][0]["run_id"]
        )
        slot = next(
            f
            for f in owner["final_models"]
            if f["member_path"] == source["receipts"][0]["member_path"]
        )
        assert source["receipts"][0]["consumed_by"] == [
            "model:" + digest([owner["run_id"], slot["action_id"]])
        ]
        assert all(f["input_consumed"] for f in owner["final_models"])

    asyncio.run(run())


def test_public_receipt_dsl_uses_logical_member_paths_across_original_authorities():
    from ralf_agent import LocalEngine, SQLiteStore, ToolCall
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_completion_rules import ReceiptParentCompletionGate
    from ralf_agent.temporal_state import TemporalRunState

    class Calculator:
        identity = {"kind": "portable-parent-receipt-fixture", "version": "1"}

        async def complete(self, messages, tools):
            return (
                ModelResponse(output={"answer": 6})
                if any(m["role"] == "tool" for m in messages)
                else ModelResponse(
                    tool_calls=[ToolCall("calculate", {"quantity": 3}, "actual-call")]
                )
            )

    async def run():
        tools = ToolRegistry()

        def calculate(quantity: int):
            return {"answer": quantity * 2}

        tools.register_function(calculate, effect="read_only", requires_approval=False, cost=1)
        gate = ReceiptParentCompletionGate(
            [
                {
                    "id": "calculation",
                    "member_path": ["worker"],
                    "tool": "calculate",
                    "argument_bindings": {"quantity": {"source": "task", "pointer": "/quantity"}},
                    "output_bindings": {"/answer": {"source": "candidate", "pointer": "/answer"}},
                }
            ],
            required_members=[["worker"]],
        )
        policy = ParentCompletionPolicy(gate)
        spec = TeamSpec(
            "portable",
            {"worker": AgentSpec("worker", "Calculate", ("calculate",), max_decisions=2)},
            child_budget=4,
            completion_policy="checked",
        )
        runtime = TemporalRuntime(
            providers={"default": Calculator()},
            tools=tools,
            parent_completion_policies={"checked": policy},
        )
        parent = TemporalParentState(
            "parent",
            asdict(Scope()),
            "submit",
            submission_request(spec, {"quantity": 3}, budget=12),
            runtime.orchestration_release,
        )
        parent.accept_selection(
            {
                "calls": [{"id": "one", "member": "worker", "input": {"quantity": 3}}],
                "done": False,
                "result": None,
            }
        )
        call = parent.next_calls()[0]
        child = TemporalRunState(
            call["run_id"], parent.scope, call["command_id"], call["request"], parent.manifest
        )
        await drive_native(runtime, child)
        parent.observe(call["run_id"], {"scope": parent.scope, **child.diagnostics()})
        parent.accept_selection({"calls": [], "done": True, "result": child.result})
        action, request = parent.next_parent_completion_operation()
        parent.accept_parent_completion(
            action["id"], await runtime.verify_parent_completion(request)
        )
        assert parent.state == "succeeded", parent.diagnostics()
        source = parent.parent_completion_stages["r0"]["source"]
        assert (
            source["children"][0]["member_path"]
            == source["receipts"][0]["member_path"]
            == ["worker"]
        )
        with LocalEngine(
            SQLiteStore(":memory:"),
            providers={"default": Calculator()},
            tools=tools,
            parent_completion_policies={"checked": policy},
        ) as local:
            handle = local.submit(spec, {"quantity": 3}, budget=12, command_id="portable")
            result = await local.drive(handle.run_id)
            assert result.state == "succeeded" and result.result == parent.result

    asyncio.run(run())


def test_custom_stage_bound_provider_session_and_native_history_use_original_scope_and_caps():
    from ralf_agent import (
        AgentBindingDescriptor,
        AgentDefinition,
        BindingCatalog,
        BindingSelection,
        BudgetedContextAssembler,
        CompleteModelHistory,
        InMemoryMemory,
        SessionBindingResource,
    )
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_verification_stage import ModelParentVerificationStage
    from ralf_agent.temporal_session_state import TemporalSessionState
    from ralf_agent.temporal_session_topology import CompositeSessionTopology
    from ralf_agent.temporal_state import TemporalRunState
    from tests.test_temporal_session_model_history import drive

    class Judge(Provider):
        identity = {"kind": "independent-bound-native-judge", "version": "1"}

    class Business(Provider):
        identity = {"kind": "bound-native-business", "version": "1"}

        async def complete(self, messages, tools):
            self.calls.append(copy.deepcopy(messages))
            return ModelResponse(output={"answer": 6})

    class CustomStage:
        def __init__(self):
            baseline = ModelParentVerificationStage()
            descriptor = baseline.agent.bindings.to_dict()
            descriptor["provider"] = BindingSelection.ref("judge", "1").to_dict()
            descriptor["context"] = BindingSelection.ref("judge-context", "1").to_dict()
            descriptor["session"] = BindingSelection.ref("judge-memory", "1").to_dict()
            descriptor["model_history"] = BindingSelection.ref("judge-native", "1").to_dict()
            self.agent = AgentDefinition(
                baseline.agent.spec, AgentBindingDescriptor.from_dict(descriptor)
            )

        @property
        def identity(self):
            return {
                "kind": "custom-bound-native-session-stage",
                "version": "1",
                "agent": self.agent.to_dict(),
            }

        def prepare(self, request):
            return request.to_dict()

        def interpret(self, request, output):
            from ralf_agent.parent_completion import ParentCompletionVerdict

            return ParentCompletionVerdict.from_dict(output)

    async def run():
        scope, business, judge = Scope(), Business(), Judge()
        memory = InMemoryMemory()
        catalog = BindingCatalog(scope=scope)
        catalog.register("provider", "judge", "1", judge)
        catalog.register("context", "judge-context", "1", BudgetedContextAssembler(max_units=32768))
        catalog.register(
            "session",
            "judge-memory",
            "1",
            SessionBindingResource(memory, namespaces=("judge",), default_namespace="judge"),
        )
        catalog.register(
            "model_history", "judge-native", "1", CompleteModelHistory(scope="session")
        )
        policy = ParentCompletionPolicy(Gate(), model_stage=CustomStage(), verifier_budget=2)
        host = TemporalRuntime(
            providers={"default": business},
            tools=ToolRegistry(),
            binding_catalog=catalog,
            parent_completion_policies={"checked": policy},
            enable_sessions=True,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
            model_continuation=True,
            model_history=CompleteModelHistory(scope="session"),
        )
        spec = TeamSpec(
            "checked",
            {"worker": AgentSpec("worker", "Answer")},
            child_budget=4,
            completion_policy="checked",
        )
        session = TemporalSessionState(
            {
                "scope": asdict(scope),
                "namespace_id": "owned-ns",
                "session_namespace": None,
                "session_id": "chat",
                "command_id": "open",
                "request": submission_request(spec, None),
                "manifest": host.orchestration_release,
                "task_queue": "q",
                "activity_timeout": 3,
            }
        )
        try:
            for turn in range(2):
                session.command(
                    {
                        "kind": "submit",
                        "scope": session.scope,
                        "command_id": str(turn),
                        "session_ref": session.ref.to_dict(),
                        "input": {"turn": turn},
                        "budget": 12,
                    }
                )
                intent = session.active
                parent = TemporalParentState(
                    intent["run_id"],
                    session.scope,
                    intent["command_id"],
                    intent["request"],
                    intent["manifest"],
                )
                descendants = []
                parent.accept_selection(
                    {
                        "calls": [{"id": "work", "member": "worker", "input": {"turn": turn}}],
                        "done": False,
                        "result": None,
                    }
                )
                for phase in ("business", "verifier"):
                    call = parent.next_calls()[0]
                    entry = next(c for c in parent.children if c["run_id"] == call["run_id"])
                    entry["dispatch_started"] = True
                    parent.mark_started(call["run_id"])
                    child = TemporalRunState(
                        call["run_id"],
                        parent.scope,
                        call["command_id"],
                        call["request"],
                        parent.manifest,
                    )
                    await drive(host, child)
                    assert child.state == "succeeded" and child.quiescent, child.diagnostics()
                    descendants.append(
                        {"scope": parent.scope, "request": child.request, **child.diagnostics()}
                    )
                    parent.observe(call["run_id"], descendants[-1])
                    if phase == "business":
                        parent.accept_selection({"calls": [], "done": True, "result": child.result})
                    action, request = parent.next_parent_completion_operation()
                    parent.accept_parent_completion(
                        action["id"], await host.verify_parent_completion(request)
                    )
                assert parent.state == "succeeded" and parent.result == {"answer": 6}
                assert (
                    parent.budget["spent"] == 3
                    and parent.budget["reserved"] == parent.budget["unknown"] == 0
                )
                verifier = descendants[-1]
                assert verifier["budget"]["allowance"] == verifier["budget"]["spent"] == 2
                assert len(verifier["native_history_episodes"]) == 1
                assert session.adopt_observation(
                    {
                        "scope": session.scope,
                        "request": parent.request,
                        **parent.diagnostics(),
                        "descendants": descendants,
                    }
                )
            assert len(judge.calls) == len(business.calls) == 2
            assert all(not call for call in [session.active])
            assert len(session.native_history) == 2 and all(
                len(records) == 2 for records in session.native_history.values()
            )
            current_task = parent.parent_completion_stages["r0"]["source"]["task"]
            assert (
                current_task == {"turn": 1}
                and parent.parent_completion_stages["r0"]["source"]["children"][0]["input_consumed"]
                is True
            )
        finally:
            await host.close_context_execution(wait_timeout=5)
            await host.close_session_execution(wait_timeout=5)

    asyncio.run(run())
