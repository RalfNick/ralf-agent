"""Original Local authority owns durable questions and once-only replies."""

import asyncio
import copy

import pytest

import relf_agent as r
from relf_agent.errors import IdempotencyConflict
from tests.helpers import ScriptedProvider


def input_tools(policy=None):
    from relf_agent.user_input import register_user_input

    tools = r.ToolRegistry()
    register_user_input(tools, policy=policy)
    return tools


def question(prompt="Which target?"):
    return r.ModelResponse(tool_calls=(r.ToolCall("request_input", {"prompt": prompt}, "ask-1"),))


def make(path, provider, *, reply_policy=None, **options):
    return r.LocalEngine(
        r.SQLiteStore(path),
        providers={"default": provider},
        tools=input_tools(reply_policy),
        **options,
    )


def request(engine, run_id):
    owner = engine.store.run(run_id)
    records = list(owner.get("input_requests", {}).values())
    if not records:
        records = [
            record
            for state in owner.get("workflow", {}).get("nodes", {}).values()
            for record in state.get("execution", {}).get("input_requests", {}).values()
        ]
    return next(record["request"] for record in records if record["state"] == "pending")


def reply(engine, run_id, pending, value="wire", command_id="answer", **options):
    return engine.send_input(
        run_id,
        pending["pending_id"],
        pending["target_digest"],
        value,
        command_id=command_id,
        **options,
    )


def test_native_question_parks_original_action_and_resumes_after_restart(tmp_path):
    path = tmp_path / "runs.sqlite"
    provider = ScriptedProvider([question()])
    with make(path, provider) as engine:
        handle = engine.submit(r.AgentSpec("a", "Help", ("request_input",)), "task", command_id="s")
        run_id = handle.run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        pending = request(engine, run_id)
        original = copy.deepcopy(engine.store.run(run_id))
        assert engine.store.budget(run_id) == {"limit": 32, "spent": 1, "held": 0}
        assert original["actions"][-1]["attempts"] == []
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        assert engine.store.run(run_id) == original
    provider = ScriptedProvider([r.ModelResponse(output="done")])
    with make(path, provider) as engine:
        receipt = reply(engine, run_id, pending)
        assert receipt.apply_state == "applied"
        tool_receipt = engine.store.run(run_id)["actions"][-1]["receipt"]
        assert set(tool_receipt) == {
            "source",
            "pending_id",
            "target_digest",
            "command_id",
            "reply_digest",
        }
        assert tool_receipt["source"] == "user-input"
        assert tool_receipt["target_digest"] == pending["target_digest"]
        assert asyncio.run(engine.drive(run_id)).result == "done"
        assert engine.store.run(run_id)["input"] == "task"
        assert [m["role"] for m in provider.messages[0]] == ["system", "user", "assistant", "tool"]
        assert provider.messages[0][-1]["content"] == '"wire"'
        assert engine.store.budget(run_id) == {"limit": 32, "spent": 2, "held": 0}
        assert reply(engine, run_id, pending) == receipt
        assert len([e for e in engine.events(run_id) if e.kind == "input_answered"]) == 1


@pytest.mark.parametrize("bad,reason", [(4, "invalid_input"), ("", "invalid_input")])
def test_rejected_reply_is_durable_and_does_not_append_or_unpause(tmp_path, bad, reason):
    with make(tmp_path / "runs.sqlite", ScriptedProvider([question()])) as engine:
        run_id = engine.submit(
            r.AgentSpec("a", "Help", ("request_input",)), "task", command_id="s"
        ).run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        pending = request(engine, run_id)
        before = engine.store.run(run_id)
        receipt = reply(engine, run_id, pending, bad, "bad")
        assert receipt.apply_state == "rejected" and receipt.outcome["reason"] == reason
        assert reply(engine, run_id, pending, bad, "bad") == receipt
        assert engine.store.run(run_id) == before
        with pytest.raises(IdempotencyConflict):
            reply(engine, run_id, pending, "changed", "bad")


def test_stale_revision_cancel_and_consumed_replies_never_reopen(tmp_path):
    with make(tmp_path / "runs.sqlite", ScriptedProvider([question()])) as engine:
        run_id = engine.submit(
            r.AgentSpec("a", "Help", ("request_input",)), "task", command_id="s"
        ).run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        pending = request(engine, run_id)
        bad = reply(engine, run_id, pending, expected_state_revision=0, command_id="old")
        assert bad.outcome["reason"] == "version_conflict"
        accepted = reply(engine, run_id, pending)
        assert (
            reply(engine, run_id, pending, command_id="twice").outcome["reason"]
            == "stale_pending_target"
        )
        engine.cancel(run_id, command_id="cancel")
        assert reply(engine, run_id, pending) == accepted
        assert (
            reply(engine, run_id, pending, command_id="late").outcome["reason"] == "target_closed"
        )
        assert engine.status(run_id).state == "cancelled"


@pytest.mark.parametrize(
    "kind",
    [
        "sequence",
        "serial",
        "parallel",
        "team",
        "nested",
        "bound-agent",
        "bound-parallel",
        "bound-team",
    ],
)
def test_compositions_keep_question_on_original_owner(tmp_path, kind):
    agent = r.AgentSpec("a", "Help", ("request_input",))
    definition = {
        "sequence": r.WorkflowSpec("s", [agent]),
        "serial": r.GraphWorkflowSpec("g", [r.GraphNode("a", agent=agent)]),
        "parallel": r.GraphWorkflowSpec("g", [r.GraphNode("a", agent=agent)], max_concurrency=2),
        "team": r.TeamSpec("t", {"a": agent}),
        "nested": r.TeamSpec("t", {"nested": r.TeamSpec("inner", {"a": agent})}),
        "bound-agent": r.AgentDefinition(agent),
        "bound-parallel": r.BoundDefinition(
            r.GraphWorkflowSpec("g", [r.GraphNode("a", agent=agent)], max_concurrency=2), {}
        ),
        "bound-team": r.BoundDefinition(r.TeamSpec("t", {"a": agent}), {}),
    }[kind]
    with make(
        tmp_path / "runs.sqlite", ScriptedProvider([question(), r.ModelResponse(output="done")])
    ) as engine:
        run_id = engine.submit(definition, "task", command_id="s").run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        owner_id = run_id
        while engine.store.run(owner_id).get("orchestration"):
            owner_id = engine.store.run(owner_id)["orchestration"]["children"][0]["run_id"]
        pending = request(engine, owner_id)
        original_input = copy.deepcopy(engine.store.run(owner_id)["input"])
        reply(engine, owner_id, pending)
        assert asyncio.run(engine.drive(run_id)).state == "succeeded"
        assert engine.store.run(owner_id)["input"] == original_input


@pytest.mark.parametrize("dag", [False, True])
def test_selected_planner_clarification_preserves_task_and_revision(dag, tmp_path):
    from relf_agent.dag_planning import DAGNode, DAGProposal, PlanningConclusion
    from relf_agent.planning import PlanProposal, PlanStep

    calls = []

    class Planner:
        identity = {"kind": "input-test-planner", "version": "1"}

        async def plan(self, request, caller):
            calls.append(request.to_dict())
            if request.revision == 0:
                return PlanningConclusion("needs_input", "Which target?")
            assert request.task == {"operation": "inspect"}
            assert request.clarifications[0]["value"] == "wire"
            return (
                DAGProposal([DAGNode("work", "a", input=r.Literal("wire"))])
                if dag
                else PlanProposal([PlanStep("work", "a", "wire")])
            )

    from relf_agent.user_input import UserInputPolicy

    with make(
        tmp_path / "runs.sqlite",
        ScriptedProvider([r.ModelResponse(output="done")]),
        planners={"custom": Planner()},
        user_input_policies={"human": UserInputPolicy()},
    ) as engine:
        spec = r.DynamicWorkflowSpec(
            "p",
            {"a": r.AgentSpec("a", "A")},
            planner="custom",
            plan_mode="dag" if dag else "flat",
            input_policy="human",
        )
        run_id = engine.submit(spec, {"operation": "inspect"}, command_id="s").run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        assert engine.store.run(run_id)["orchestration"]["children"] == []
        reply(engine, run_id, request(engine, run_id))
        assert asyncio.run(engine.drive(run_id)).state == "succeeded"
        assert [c["revision"] for c in calls] == [0, 1]
        assert engine.store.run(run_id)["input"] == {"operation": "inspect"}
        assert len(engine.store.run(run_id)["orchestration"]["revisions"]) == 2


def test_cancellation_retires_unanswered_journal(tmp_path):
    with make(tmp_path / "runs.sqlite", ScriptedProvider([question()])) as engine:
        run_id = engine.submit(
            r.AgentSpec("a", "Help", ("request_input",)), "task", command_id="s"
        ).run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        pending = request(engine, run_id)
        engine.cancel(run_id, command_id="cancel")
        assert (
            engine.store.run(run_id)["input_requests"][pending["pending_id"]]["state"]
            == "cancelled"
        )
        assert reply(engine, run_id, pending).outcome["reason"] == "target_closed"


def test_input_call_must_not_share_a_model_batch(tmp_path):
    response = r.ModelResponse(
        tool_calls=(
            r.ToolCall("request_input", {"prompt": "One?"}),
            r.ToolCall("request_input", {"prompt": "Two?"}),
        )
    )
    with make(tmp_path / "runs.sqlite", ScriptedProvider([response])) as engine:
        run_id = engine.submit(
            r.AgentSpec("a", "Help", ("request_input",)), "task", command_id="s"
        ).run_id
        assert asyncio.run(engine.drive(run_id)).state == "failed"
        assert not engine.store.run(run_id).get("input_requests")
        assert not any(a["kind"] == "tool" for a in engine.status(run_id).actions)


def test_answer_cannot_reset_original_decision_allowance(tmp_path):
    with make(
        tmp_path / "runs.sqlite",
        ScriptedProvider([question(), r.ModelResponse(output="unexpected")]),
    ) as engine:
        run_id = engine.submit(
            r.AgentSpec("a", "Help", ("request_input",), max_decisions=1), "task", command_id="s"
        ).run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        reply(engine, run_id, request(engine, run_id))
        assert asyncio.run(engine.drive(run_id)).state == "failed"
        assert engine.store.budget(run_id) == {"limit": 32, "spent": 1, "held": 0}


def test_planner_exhaustion_fails_before_impossible_human_wait(tmp_path):
    from relf_agent.dag_planning import PlanningConclusion

    class Planner:
        identity = {"kind": "exhausted-planner", "version": "1"}

        async def plan(self, request, caller):
            return PlanningConclusion("needs_input", "Which target?")

    from relf_agent.user_input import UserInputPolicy

    with make(
        tmp_path / "runs.sqlite",
        ScriptedProvider([]),
        planners={"custom": Planner()},
        user_input_policies={"human": UserInputPolicy()},
    ) as engine:
        spec = r.DynamicWorkflowSpec(
            "p",
            {"a": r.AgentSpec("a", "A")},
            planner="custom",
            max_revisions=1,
            input_policy="human",
        )
        run_id = engine.submit(spec, "original", command_id="s").run_id
        snapshot = asyncio.run(engine.drive(run_id))
        assert snapshot.state == "failed" and snapshot.error["code"] == "plan_revision_limit"
        assert not engine.store.run(run_id).get("input_requests")


def test_parent_completion_sees_reply_lineage_without_control_effect(tmp_path):
    seen = []

    class Gate:
        identity = {"kind": "clarification-gate", "version": "1"}

        def __init__(self, calls):
            self.calls = calls

        def verify(self, request):
            self.calls.append(request.to_dict())
            return r.ParentCompletionVerdict("accept")

    with make(
        tmp_path / "runs.sqlite",
        ScriptedProvider([question(), r.ModelResponse(output="done")]),
        parent_completion_policies={"gate": r.ParentCompletionPolicy(Gate(seen))},
    ) as engine:
        spec = r.TeamSpec(
            "t", {"a": r.AgentSpec("a", "A", ("request_input",))}, completion_policy="gate"
        )
        run_id = engine.submit(spec, "original", command_id="s").run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        child_id = engine.store.run(run_id)["orchestration"]["children"][0]["run_id"]
        reply(engine, child_id, request(engine, child_id))
        assert asyncio.run(engine.drive(run_id)).state == "succeeded"
        assert seen[0]["task"] == "original"
        assert seen[0]["receipts"] == []
        assert seen[0]["clarifications"][0]["value"] == "wire"


@pytest.mark.parametrize("parallel", [False, True])
def test_signed_session_history_publishes_question_reply_only_after_original_success(
    tmp_path, parallel
):
    from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
    from relf_agent.types import digest

    class SignedProvider:
        identity = {"kind": "input-signed-fixture", "version": "1"}
        continuation_identity = {"protocol": "input-signed-v1", "owner_digest": "a" * 64}

        def __init__(self):
            self.messages = []

        async def complete(self, messages, tools):
            self.messages.append(copy.deepcopy(messages))
            call = r.ToolCall("request_input", {"prompt": "Which target?"}, "native-original-id")
            calls = () if messages[-1]["role"] == "tool" or len(self.messages) > 2 else (call,)
            output = "done" if not calls else None
            return ContinuedModelResponse(
                output=output,
                tool_calls=calls,
                continuation=ModelContinuation(
                    "input-signed-v1",
                    "a" * 64,
                    digest(
                        {
                            "output": output,
                            "tool_calls": [
                                {"name": c.name, "arguments": c.arguments, "call_id": c.call_id}
                                for c in calls
                            ],
                        }
                    ),
                    {"signature": "original-question" if calls else "original-final"},
                ),
            )

    provider = SignedProvider()
    agent = r.AgentSpec("a", "Help", ("request_input",))
    spec = (
        r.GraphWorkflowSpec("g", [r.GraphNode("a", agent=agent)], max_concurrency=2)
        if parallel
        else agent
    )
    with make(
        tmp_path / "runs.sqlite",
        provider,
        model_continuation=True,
        model_history=r.CompleteModelHistory(scope="session"),
    ) as engine:
        first = engine.submit(spec, "first", command_id="first", session_id="same").run_id
        assert asyncio.run(engine.drive(first)).state == "waiting_input"
        assert (
            engine.store.conn.execute(
                "SELECT count(*) FROM native_history_publications"
            ).fetchone()[0]
            == 0
        )
        reply(engine, first, request(engine, first))
        assert asyncio.run(engine.drive(first)).state == "succeeded"
        second = engine.submit(spec, "second", command_id="second", session_id="same").run_id
        assert asyncio.run(engine.drive(second)).state == "succeeded"
        past = provider.messages[2]
        assert [m["role"] for m in past[:6]] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
            "user",
        ]
        assert past[2]["tool_calls"][0]["id"] == "native-original-id"
        assert past[2]["model_continuation"]["data"] == {"signature": "original-question"}
        assert past[3]["content"] == '"wire"'


def test_session_stays_busy_while_question_survives_close(tmp_path):
    from relf_agent.errors import SessionBusy

    async def scenario():
        path = tmp_path / "runs.sqlite"
        spec = r.AgentSpec("a", "Help", ("request_input",))
        async with r.Runtime(make(path, ScriptedProvider([question()])), owned=True) as runtime:
            session = await runtime.create_agent(spec).open_session("same", command_id="open")
            run = await session.submit("original", command_id="first")
            assert (await run.wait(wait_timeout=3)).snapshot.state == "waiting_input"
            assert (await session.status()).busy
            run_ref, session_ref = run.ref, session.ref
        async with r.Runtime(
            make(path, ScriptedProvider([r.ModelResponse(output="done")])), owned=True
        ) as runtime:
            session = runtime.attach_session(session_ref)
            assert (await session.status()).busy
            with pytest.raises(SessionBusy):
                await session.submit("new task", command_id="second")
            pending = request(runtime.engine, run_ref.run_id)
            reply(runtime.engine, run_ref.run_id, pending)
            run = await runtime.resume(run_ref)
            assert (await run.wait(wait_timeout=3)).snapshot.state == "succeeded"
            turns = await session.turns()
            assert len(turns) == 1 and turns[0].run.run_id == run_ref.run_id

    asyncio.run(scenario())


def test_parallel_mixed_pause_keeps_all_owners_and_unknown_reservation(tmp_path):
    class Provider:
        identity = {"kind": "mixed-input-fixture", "version": "1"}

        async def complete(self, messages, tools):
            if messages[-1]["role"] == "tool":
                return r.ModelResponse(output="done")
            name = messages[0]["content"]
            return (
                question()
                if name == "question"
                else r.ModelResponse(tool_calls=(r.ToolCall(name, {}),))
            )

    def unknown(arguments, context):
        raise RuntimeError("lost effect response")

    tools = input_tools()
    tools.register(
        r.ToolSpec("approval", "Approve", {"type": "object"}, requires_approval=True),
        lambda a, c: "approved",
    )
    tools.register(
        r.ToolSpec("unknown", "Unknown effect", {"type": "object"}, effect="unqueryable_write"),
        unknown,
    )
    spec = r.GraphWorkflowSpec(
        "mixed",
        [
            r.GraphNode("ask", agent=r.AgentSpec("ask", "question", ("request_input",))),
            r.GraphNode("approve", agent=r.AgentSpec("approve", "approval", ("approval",))),
            r.GraphNode("uncertain", agent=r.AgentSpec("uncertain", "unknown", ("unknown",))),
        ],
        max_concurrency=3,
    )
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "runs.sqlite"), providers={"default": Provider()}, tools=tools
    ) as engine:
        run_id = engine.submit(spec, "original", command_id="s").run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_reconciliation"
        record = engine.store.run(run_id)
        assert {s["state"] for s in record["workflow"]["nodes"].values()} == {
            "waiting_input",
            "waiting_approval",
            "waiting_reconciliation",
        }
        assert {p.get("kind", "approval") for p in engine.status(run_id).pending} == {
            "input",
            "approval",
        }
        assert engine.store.budget(run_id) == {"limit": 32, "spent": 3, "held": 1}
        reply(engine, run_id, request(engine, run_id))
        assert asyncio.run(engine.drive(run_id)).state == "waiting_reconciliation"
        assert engine.store.budget(run_id) == {"limit": 32, "spent": 4, "held": 1}


def test_plan_reply_retains_completed_revision_and_finished_child(tmp_path):
    from relf_agent.dag_planning import PlanningConclusion
    from relf_agent.planning import PlanProposal, PlanStep, Verification
    from relf_agent.user_input import UserInputPolicy

    class Planner:
        identity = {"kind": "retained-input-planner", "version": "1"}

        async def plan(self, request, caller):
            if request.revision == 1:
                return PlanningConclusion("needs_input", "Which second target?")
            if request.revision == 2:
                assert request.task == "original"
                assert request.results[0]["result"] == "initial"
                assert request.clarifications[0]["value"] == "wire"
            return PlanProposal(
                [PlanStep("work", "a", "first" if request.revision == 0 else "wire")]
            )

    class Verifier:
        identity = {"kind": "retained-input-verifier", "version": "1"}

        def verify(self, request):
            return (
                Verification("replan")
                if request.revision == 0
                else Verification("succeeded", request.results[-1]["result"])
            )

    provider = ScriptedProvider(
        [r.ModelResponse(output="initial"), r.ModelResponse(output="final")]
    )
    with make(
        tmp_path / "runs.sqlite",
        provider,
        planners={"custom": Planner()},
        plan_verifiers={"custom": Verifier()},
        user_input_policies={"human": UserInputPolicy()},
    ) as engine:
        spec = r.DynamicWorkflowSpec(
            "plan",
            {"a": r.AgentSpec("a", "A")},
            planner="custom",
            verifier="custom",
            input_policy="human",
            max_revisions=3,
        )
        run_id = engine.submit(spec, "original", command_id="s").run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        child_id = engine.store.run(run_id)["orchestration"]["children"][0]["run_id"]
        original_child = copy.deepcopy(engine.store.run(child_id))
        reply(engine, run_id, request(engine, run_id))
        assert asyncio.run(engine.drive(run_id)).result == "final"
        assert engine.store.run(child_id) == original_child
        assert engine.store.budget(run_id) == {"limit": 32, "spent": 2, "held": 0}


def test_authorization_cancellation_prevents_intrinsic_question_adoption(tmp_path):
    def policy(scope, spec, arguments):
        engine.cancel(run_id, command_id="policy-cancel")

    with make(tmp_path / "runs.sqlite", ScriptedProvider([question()]), policy=policy) as engine:
        run_id = engine.submit(
            r.AgentSpec("a", "A", ("request_input",)), "original", command_id="s"
        ).run_id
        assert asyncio.run(engine.drive(run_id)).state == "cancelled"
        assert not engine.store.run(run_id).get("input_requests")


@pytest.mark.parametrize("dag", [False, True])
def test_managed_planner_reply_uses_new_child_identity(dag, tmp_path):
    from relf_agent.dag_planning import DAGNode, DAGProposal, ModelDAGPlanner
    from relf_agent.planning import ModelPlanner
    from relf_agent.user_input import UserInputPolicy

    planned = (
        DAGProposal([DAGNode("work", "a", input=r.Literal("wire"))]).to_dict()
        if dag
        else {"steps": [{"id": "work", "member": "a", "input": "wire"}]}
    )
    provider = ScriptedProvider(
        [
            r.ModelResponse(output={"status": "needs_input", "reason": "Which target?"}),
            r.ModelResponse(output=planned),
            r.ModelResponse(output="done"),
        ]
    )
    planner = ModelDAGPlanner() if dag else ModelPlanner(input_requests=True)
    with make(
        tmp_path / "runs.sqlite",
        provider,
        planners={"custom": planner},
        user_input_policies={"human": UserInputPolicy()},
    ) as engine:
        spec = r.DynamicWorkflowSpec(
            "p",
            {"a": r.AgentSpec("a", "A")},
            planner="custom",
            plan_mode="dag" if dag else "flat",
            input_policy="human",
        )
        run_id = engine.submit(spec, "original", command_id="s").run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        first_id = engine.store.run(run_id)["orchestration"]["children"][0]["run_id"]
        original_child = copy.deepcopy(engine.store.run(first_id))
        reply(engine, run_id, request(engine, run_id))
        assert asyncio.run(engine.drive(run_id)).state == "succeeded"
        children = engine.store.run(run_id)["orchestration"]["children"]
        assert [c["id"] for c in children] == [
            "r0.planner.planner",
            "r1.planner.planner",
            "r1.step.work",
        ]
        assert children[0]["run_id"] != children[1]["run_id"]
        assert engine.store.run(first_id) == original_child
        assert engine.store.budget(run_id) == {"limit": 32, "spent": 3, "held": 0}


def test_original_tool_control_receipt_cannot_satisfy_business_completion(tmp_path):
    with make(
        tmp_path / "runs.sqlite",
        ScriptedProvider([question(), r.ModelResponse(output="done")]),
        verifier=r.ToolReceiptVerifier("request_input", on_missing="reject"),
    ) as engine:
        run_id = engine.submit(
            r.AgentSpec("a", "A", ("request_input",)), "original", command_id="s"
        ).run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        reply(engine, run_id, request(engine, run_id))
        snapshot = asyncio.run(engine.drive(run_id))
        assert snapshot.state == "failed" and snapshot.error["code"] == "completion_rejected"


def test_reply_adopts_detached_command_payload_before_store_callback(tmp_path):
    from relf_agent.user_input import UserInputPolicy

    value = {"target": "wire"}

    class CallbackStore(r.SQLiteStore):
        def command(self, scope, command_id, kind, payload, run_id, apply):
            if kind == "send_input":
                value["target"] = "changed-after-payload"
            return super().command(scope, command_id, kind, payload, run_id, apply)

    tools = input_tools(
        UserInputPolicy(
            {
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
                "additionalProperties": False,
            }
        )
    )
    with r.LocalEngine(
        CallbackStore(tmp_path / "runs.sqlite"),
        providers={"default": ScriptedProvider([question()])},
        tools=tools,
    ) as engine:
        run_id = engine.submit(
            r.AgentSpec("a", "A", ("request_input",)), "original", command_id="s"
        ).run_id
        assert asyncio.run(engine.drive(run_id)).state == "waiting_input"
        pending = request(engine, run_id)
        receipt = reply(engine, run_id, pending, value)
        assert receipt.apply_state == "applied"
        assert engine.store.run(run_id)["actions"][-1]["result"] == {"target": "wire"}
        assert reply(engine, run_id, pending, {"target": "wire"}) == receipt
