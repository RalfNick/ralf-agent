"""Managed ModelPlanner and business Agent keep distinct native Session streams."""

import asyncio
import copy
import json
from collections import defaultdict

import pytest

import relf_agent as r
from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from relf_agent.planning import ModelPlanner
from relf_agent.types import digest

PLANNER_SYSTEM = "Return the original JSON plan; use the current PlanningRequest only."
BUSINESS_SYSTEM = "Business member: call lookup, then return the original JSON answer."
PLAN_JSON = {
    "first-task": ' { "steps" : [ { "id" : "answer", "member" : "worker", "input" : { "task" : "first-task", "plan_marker" : "first-plan" } } ] } ',
    "second-task": ' { "steps" : [ { "id" : "answer", "member" : "worker", "input" : { "task" : "second-task", "plan_marker" : "second-plan" } } ] } ',
}
FINAL_JSON = {
    "first-task": ' { "answer" : "first-business-original" } ',
    "second-task": ' { "answer" : "second-business-original" } ',
}


def fresh_task(messages):
    return json.loads(
        next(
            message["content"]
            for message in reversed(messages)
            if message["role"] == "user" and not message["content"].startswith("Reference memory;")
        )
    )


class PlannerAndBusinessProvider:
    identity = {"kind": "native-session-model-planner-contract", "version": "1"}
    continuation_identity = {
        "protocol": "native-session-model-planner-v1",
        "owner_digest": "a" * 64,
    }

    def __init__(self, requests):
        self.requests = requests

    async def complete(self, messages, tools):
        role = "planner" if messages[0]["content"] == PLANNER_SYSTEM else "business"
        self.requests.append(
            {"owner": role, "messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)}
        )
        current = fresh_task(messages)
        task = current["task"]
        if role == "planner":
            output, calls, signature = PLAN_JSON[task], [], "planner-final-" + task
        elif messages[-1]["role"] == "tool":
            output, calls, signature = FINAL_JSON[task], [], "business-final-" + task
        else:
            output, calls, signature = (
                None,
                [r.ToolCall("lookup", {"task": task}, "same-business-call-id")],
                "business-tool-" + task,
            )
        decision = {
            "output": output,
            "tool_calls": [
                {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
                for call in calls
            ],
        }
        return ContinuedModelResponse(
            output=output,
            tool_calls=calls,
            continuation=ModelContinuation(
                "native-session-model-planner-v1",
                "a" * 64,
                digest(decision),
                {"signature": signature},
            ),
        )


class CurrentPlanKnowledge:
    identity = {"kind": "native-planning-current-query-contract", "version": "1"}
    limit, max_chars = 4, 2000

    def __init__(self, queries):
        self.queries = queries

    async def references(self, scope, query):
        self.queries.append(query)
        return []

    async def validate(self, scope, references):
        return None


def workflow():
    return r.DynamicWorkflowSpec(
        "managed-plan",
        {
            "worker": r.AgentSpec(
                "worker",
                BUSINESS_SYSTEM,
                ("lookup",),
                max_context_chars=24000,
                output_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            ),
        },
        planner="model",
        child_budget=32,
        max_steps=8,
        max_depth=4,
    )


def engine_at(path, requests, queries, *, history_scope="session"):
    tools = r.ToolRegistry()
    tools.register(
        r.ToolSpec(
            "lookup",
            "Return original business evidence",
            {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        ),
        lambda arguments, context: {
            "evidence": "original-tool-" + arguments["task"],
            "integer": 9007199254740997,
        },
    )
    return r.LocalEngine(
        r.SQLiteStore(path),
        providers={"default": PlannerAndBusinessProvider(requests)},
        tools=tools,
        knowledge=CurrentPlanKnowledge(queries),
        planners={"model": ModelPlanner(instructions=PLANNER_SYSTEM)},
        model_continuation=True,
        model_history=(
            None
            if history_scope is None
            else (
                r.CompleteModelHistory()
                if history_scope == "run"
                else r.CompleteModelHistory(scope=history_scope)
            )
        ),
    )


@pytest.mark.parametrize("facade", [False, True])
@pytest.mark.parametrize("restart", [False, True])
def test_two_turn_model_planner_and_business_native_histories_keep_current_inputs_and_owners(
    tmp_path, facade, restart
):
    async def run():
        requests, queries, roots, children = [], [], [], []
        path = tmp_path / "managed-planner.sqlite"
        engine = engine_at(path, requests, queries)
        try:
            session_ref = None
            for index, task in enumerate(("first-task", "second-task")):
                if facade:
                    async with r.Runtime(engine, owned=False) as runtime:
                        agent = runtime.create_agent(workflow())
                        session = (
                            await agent.open_session("same", command_id="open")
                            if session_ref is None
                            else runtime.attach_session(session_ref)
                        )
                        session_ref = session.ref
                        handle = await session.submit(task, command_id=f"turn-{index}", budget=128)
                        snapshot = (await handle.wait(wait_timeout=10)).snapshot
                        run_id = handle.ref.run_id
                        assert snapshot.state == "succeeded", engine.store.run(run_id).get("error")
                        async with asyncio.timeout(2):
                            while (await session.status()).busy:  # noqa: ASYNC110 -- original hosting quiescence
                                await asyncio.sleep(0.01)
                else:
                    handle = engine.submit(
                        workflow(), task, session_id="same", command_id=f"turn-{index}", budget=128
                    )
                    run_id = handle.run_id
                    snapshot = await engine.drive(run_id)
                    assert snapshot.state == "succeeded", {
                        "root": engine.store.run(run_id).get("error"),
                        "children": [
                            {
                                "member": call["member"],
                                "state": engine.store.run(call["run_id"])["state"],
                                "error": engine.store.run(call["run_id"]).get("error"),
                            }
                            for call in engine.store.run(run_id)["orchestration"]["children"]
                        ],
                    }
                root = engine.store.run(run_id)
                roots.append(root)
                children.append(
                    {
                        call["member"]: engine.store.run(call["run_id"])
                        for call in root["orchestration"]["children"]
                    }
                )
                if restart and index == 0:
                    engine.close()
                    engine = engine_at(path, requests, queries)
            by_owner = defaultdict(list)
            for request in requests:
                by_owner[request["owner"]].append(request)
            assert len(requests) == 6 and set(by_owner) == {"planner", "business"}
            assert len(by_owner["planner"]) == 2 and len(by_owner["business"]) == 4
            planning = by_owner["planner"][1]["messages"]
            business = by_owner["business"][2]["messages"]
            assert [message["role"] for message in planning[:4]] == [
                "system",
                "user",
                "assistant",
                "user",
            ]
            assert planning[2]["content"] == PLAN_JSON["first-task"]
            assert planning[2]["model_continuation"]["data"] == {
                "signature": "planner-final-first-task"
            }
            assert json.loads(planning[1]["content"]) == {
                "task": "first-task",
                "members": ["worker"],
                "results": [],
                "revision": 0,
            }
            assert json.loads(planning[3]["content"]) == {
                "task": "second-task",
                "members": ["worker"],
                "results": [],
                "revision": 0,
            }
            assert all(request["tools"] == [] for request in by_owner["planner"])
            assert not any(message["role"] == "tool" for message in planning)
            assert [message["role"] for message in business[:6]] == [
                "system",
                "user",
                "assistant",
                "tool",
                "assistant",
                "user",
            ]
            assert business[4]["content"] == FINAL_JSON["first-task"]
            assert business[4]["model_continuation"]["data"] == {
                "signature": "business-final-first-task"
            }
            assert json.loads(business[3]["content"]) == {
                "evidence": "original-tool-first-task",
                "integer": 9007199254740997,
            }
            assert json.loads(business[5]["content"]) == {
                "task": "second-task",
                "plan_marker": "second-plan",
            }
            assert [
                message["tool_calls"][0]["id"]
                for message in by_owner["business"][3]["messages"]
                if message.get("tool_calls")
            ] == ["same-business-call-id"] * 2
            assert not any(
                message.get("content") == PLAN_JSON["first-task"] for message in business
            )
            assert [json.loads(query) for query in queries] == [
                {"task": "first-task", "members": ["worker"], "results": [], "revision": 0},
                {"task": "first-task", "plan_marker": "first-plan"},
                {"task": "first-task", "plan_marker": "first-plan"},
                {"task": "second-task", "members": ["worker"], "results": [], "revision": 0},
                {"task": "second-task", "plan_marker": "second-plan"},
                {"task": "second-task", "plan_marker": "second-plan"},
            ]
            streams = []
            for root, owned in zip(roots, children, strict=True):
                assert set(owned) == {"@planner", "worker"}
                assert root["orchestration"]["request"]["task"] == root["input"]
                streams.append(
                    {
                        member: child["native_model_history"]["stages"]["agent"]["stream"]
                        for member, child in owned.items()
                    }
                )
                assert owned["@planner"]["definition"]["steps"][0]["tools"] == []
                for child in owned.values():
                    episode = child["native_model_history"]["episodes"]["agent"]["envelope"]
                    assert (
                        episode["source"]["root_run_id"] == root["id"]
                        and episode["source"]["run_id"] == child["id"]
                    )
            assert streams[0] == streams[1] and streams[0]["@planner"] != streams[0]["worker"]
            assert roots[0]["result"] == {"answer": "first-business-original"}
            assert roots[1]["result"] == {"answer": "second-business-original"}
        finally:
            engine.close()

    asyncio.run(run())


@pytest.mark.parametrize("history_scope", [None, "run"], ids=["no-history", "run-history"])
def test_legacy_model_planner_session_facade_keeps_the_persisted_binding(tmp_path, history_scope):
    async def run():
        requests, queries = [], []
        with engine_at(
            tmp_path / "legacy-planner.sqlite", requests, queries, history_scope=history_scope
        ) as engine:
            async with r.Runtime(engine, owned=False) as runtime:
                agent = runtime.create_agent(workflow())
                session = await agent.open_session("legacy", command_id="open")
                for index, task in enumerate(("first-task", "second-task")):
                    handle = await session.submit(task, command_id=f"turn-{index}", budget=128)
                    snapshot = (await handle.wait(wait_timeout=10)).snapshot
                    assert snapshot.state == "succeeded", engine.store.run(handle.ref.run_id).get(
                        "error"
                    )
                    assert snapshot.result == {"answer": task.split("-")[0] + "-business-original"}
                    async with asyncio.timeout(2):
                        while (await session.status()).busy:  # noqa: ASYNC110 -- original hosting quiescence
                            await asyncio.sleep(0.01)
            planning = [request for request in requests if request["owner"] == "planner"]
            assert len(planning) == 2
            assert fresh_task(planning[1]["messages"])["task"] == "second-task"
            assert not any(message["role"] == "assistant" for message in planning[1]["messages"])
            assert [json.loads(query)["task"] for query in queries] == [
                "first-task",
                "first-task",
                "first-task",
                "second-task",
                "second-task",
                "second-task",
            ]

    asyncio.run(run())
