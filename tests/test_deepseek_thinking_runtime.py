"""Native HTTP fixtures exercise original runtime authority, not model quality.

Only public HTTP is replaced. Providers, SQLite receipt/adoption, approval,
tools, SessionTurns, retrieval, and composite Agents remain real.
"""

import asyncio
import copy
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

import ralf_agent as r
from ralf_agent.planning import ModelPlanner
from ralf_agent.types import digest

RAW_ARGUMENTS = ' \n { "quantity" : 3 } \t '
PLAN_MESSAGE = {
    "role": "assistant",
    "content": ' { "steps" : [ { "id" : "first", "member" : "first", "input" : "task" }, { "id" : "second", "member" : "second", "input" : "task" } ] } ',
    "reasoning_content": "原始规划推理",
}


def provider(model, client):
    assert importlib.util.find_spec("ralf_agent.deepseek_thinking"), (
        "The dedicated DeepSeek thinking adapter is required for native runtime recovery"
    )
    from ralf_agent.deepseek_thinking import DeepSeekThinkingProvider

    return DeepSeekThinkingProvider(
        model, api_key="fixture", client=client, reasoning_effort="high"
    )


def native_message(model, phase="tool-1", task="task"):
    if phase.startswith("tool-"):
        return {
            "role": "assistant",
            "content": "Checking " + model,
            "reasoning_content": f"原始推理 {model}/{task}/{phase}",
            "tool_calls": [
                {
                    "id": f"native-{model}-{task}-{phase}",
                    "type": "function",
                    "function": {"name": "calculate", "arguments": RAW_ARGUMENTS},
                }
            ],
        }
    return {
        "role": "assistant",
        "content": "complete-" + model + "-" + task,
        "reasoning_content": f"最终原始推理 {model}/{task}",
    }


def completion(message):
    return {
        "id": "fixture-completion",
        "object": "chat.completion",
        "created": 1,
        "model": "fixture",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }


def transport(requests, *, loops=1, audit=None):
    def respond(request):
        body = json.loads(request.content)
        model, messages = body["model"], body["messages"]
        requests.append(copy.deepcopy(body))
        assert body["thinking"] == {"type": "enabled"}
        assert body["reasoning_effort"] == "high"
        # Current RAG evidence remains separate from the original native episode.
        current = next(
            message["content"]
            for message in reversed(messages)
            if message["role"] == "user" and not message["content"].startswith("Reference memory;")
        )
        task = "turn-two" if current == "turn-two" else "task"
        if model == "planner":
            assert not body.get("tools")
            assert not any(message["role"] in {"assistant", "tool"} for message in messages)
            message = PLAN_MESSAGE
            phase = "plan-final"
        else:
            declaration = body["tools"][0]["function"]
            assert declaration["name"] == "calculate"
            assert declaration["parameters"]["required"] == ["quantity"]
            assert declaration["parameters"]["properties"]["price"]["type"] == "integer"
            assistant = [message for message in messages if message["role"] == "assistant"]
            expected_past = (
                [native_message(model), native_message(model, "final")]
                if task == "turn-two"
                else []
            )
            active = assistant[len(expected_past) :]
            assert assistant[: len(expected_past)] == expected_past
            assert active == [
                native_message(model, f"tool-{index + 1}", task) for index in range(len(active))
            ]
            replies = [message for message in messages if message["role"] == "tool"]
            expected_calls = [
                call for original in assistant for call in original.get("tool_calls", [])
            ]
            assert [reply["tool_call_id"] for reply in replies] == [
                call["id"] for call in expected_calls
            ]
            assert all(json.loads(reply["content"]) == {"amount": 6} for reply in replies)
            phase = f"tool-{len(active) + 1}" if len(active) < loops else "final"
            message = native_message(model, phase, task)
        if audit:
            with audit.open("a") as output:
                output.write(json.dumps({"kind": "model", "model": model, "phase": phase}) + "\n")
        return httpx.Response(200, json=completion(message))

    return httpx.MockTransport(respond)


def tools(effects, *, approval=False, audit=None):
    def calculate(quantity: int, price: int = 2):
        effect = {"quantity": quantity, "price": price}
        effects.append(effect)
        if audit:
            with audit.open("a") as output:
                output.write(json.dumps({"kind": "tool", **effect}) + "\n")
        return {"amount": quantity * price}

    registry = r.ToolRegistry()
    registry.register_function(
        calculate, effect="unqueryable_write", requires_approval=approval, cost=0
    )
    return registry


def agent(name="first"):
    return r.AgentSpec(name, "Calculate using evidence.", ("calculate",), max_context_chars=24000)


def all_records(engine, run_id):
    record = engine.store.run(run_id)
    return [
        record,
        *[
            child
            for call in record.get("orchestration", {}).get("children", [])
            for child in all_records(engine, call["run_id"])
        ],
    ]


def assert_original_receipt(action, model, phase="tool-1", task="task"):
    raw = action["received_response"]
    original = native_message(model, phase, task)
    continuation = raw["continuation"]
    assert continuation["protocol"] == "deepseek-thinking-v1"
    assert continuation["data"] == {"message": original}
    if phase.startswith("tool-"):
        assert raw["tool_calls"] == [
            {
                "name": "calculate",
                "arguments": {"quantity": 3},
                "call_id": original["tool_calls"][0]["id"],
            }
        ]
    else:
        assert raw["output"] == original["content"] and raw["tool_calls"] == []


def test_actual_agent_rag_keeps_two_exact_reasoning_and_argument_groups(tmp_path):
    async def scenario():
        requests, effects = [], []
        knowledge = r.InMemoryKnowledgeStore()
        knowledge.put(
            r.Scope(),
            "manuals",
            r.Document("original", "calculate documented units DOCUMENT_CANARY"),
            expected_version=0,
        )
        async with httpx.AsyncClient(transport=transport(requests, loops=2)) as client:
            selected = provider("first", client)
            with r.LocalEngine(
                r.SQLiteStore(tmp_path / "runs.sqlite"),
                providers={"default": selected},
                tools=tools(effects),
                knowledge=r.KnowledgeContext(r.LexicalRetriever(knowledge), namespace="manuals"),
                model_continuation=True,
            ) as engine:
                handle = engine.submit(agent(), "calculate documented units", command_id="submit")
                outcome = await engine.drive(handle.run_id)
                assert outcome.state == "succeeded", outcome.error
                assert outcome.result == "complete-first-task"
                assert len(requests) == 3 and len(effects) == 2
                assert effects == [{"quantity": 3, "price": 2}] * 2
                assert any("DOCUMENT_CANARY" in m["content"] for m in requests[0]["messages"])
                models = [
                    a for a in engine.store.run(handle.run_id)["actions"] if a["kind"] == "model"
                ]
                for index, phase in enumerate(("tool-1", "tool-2", "final")):
                    assert_original_receipt(models[index], "first", phase)
                    assert models[index]["received_response"]["continuation"][
                        "owner_digest"
                    ] == digest(selected.identity)
                assert [m for m in requests[-1]["messages"] if m["role"] == "assistant"] == [
                    native_message("first", "tool-1"),
                    native_message("first", "tool-2"),
                ]

    asyncio.run(scenario())


def test_original_sqlite_approval_reconstruction_reuses_native_receipt_and_effect_once(tmp_path):
    async def scenario():
        path, requests, effects = tmp_path / "runs.sqlite", [], []
        registry = tools(effects, approval=True)
        async with httpx.AsyncClient(transport=transport(requests)) as client:
            with r.LocalEngine(
                r.SQLiteStore(path),
                providers={"default": provider("first", client)},
                tools=registry,
                model_continuation=True,
            ) as engine:
                handle = engine.submit(agent(), "task", command_id="submit")
                assert (await engine.drive(handle.run_id)).state == "waiting_approval"
                original = copy.deepcopy(engine.store.run(handle.run_id))
                pending = original["actions"][-1]
                assert len(requests) == 1 and effects == []
                assert_original_receipt(original["actions"][0], "first")
                assert pending["arguments"] == {"quantity": 3, "price": 2}
            with r.LocalEngine(
                r.SQLiteStore(path),
                providers={"default": provider("first", client)},
                tools=registry,
                model_continuation=True,
            ) as engine:
                assert engine.submit(agent(), "task", command_id="submit") == handle
                receipt = engine.approve(
                    handle.run_id, pending["id"], pending["digest"], command_id="approve"
                )
                assert (
                    engine.approve(
                        handle.run_id, pending["id"], pending["digest"], command_id="approve"
                    )
                    == receipt
                )
                outcome = await engine.drive(handle.run_id)
                assert outcome.state == "succeeded", outcome.error
                after = engine.store.run(handle.run_id)
                assert after["actions"][0] == original["actions"][0]
                assert_original_receipt(after["actions"][-1], "first", "final")
                assert len(requests) == 2 and effects == [{"quantity": 3, "price": 2}]
                assert await engine.drive(handle.run_id) == outcome
                assert len(requests) == 2 and effects == [{"quantity": 3, "price": 2}]

    asyncio.run(scenario())


def test_two_real_session_turns_reconstruct_and_echo_final_reasoning_with_session_history(tmp_path):
    async def scenario():
        path, requests, effects = tmp_path / "session.sqlite", [], []
        registry = tools(effects)
        session_ref, first_record = None, None
        async with httpx.AsyncClient(transport=transport(requests)) as client:
            for index, task in enumerate(("task", "turn-two")):
                with r.LocalEngine(
                    r.SQLiteStore(path),
                    providers={"default": provider("first", client)},
                    tools=registry,
                    model_continuation=True,
                    model_history=r.CompleteModelHistory(scope="session"),
                ) as engine:
                    async with r.Runtime(engine, owned=False) as runtime:
                        entry = runtime.create_agent(agent())
                        session = (
                            await entry.open_session("thinking", command_id="open")
                            if session_ref is None
                            else runtime.attach_session(session_ref)
                        )
                        session_ref = session.ref
                        turn = await session.submit(task, command_id=f"turn-{index}", budget=8)
                        snapshot = (await turn.wait(wait_timeout=10)).snapshot
                        assert snapshot.state == "succeeded", engine.store.run(turn.ref.run_id).get(
                            "error"
                        )
                        assert snapshot.result == "complete-first-" + task
                        async with asyncio.timeout(2):
                            while (await session.status()).busy:  # noqa: ASYNC110 -- original hosting quiescence
                                await asyncio.sleep(0.01)
                        record = engine.store.run(turn.ref.run_id)
                        if index == 0:
                            first_record = copy.deepcopy(record)
                        else:
                            assert engine.store.run(first_record["id"]) == first_record
                            assert (
                                record["native_model_history"]["stages"]["agent"]["stream"]
                                == first_record["native_model_history"]["stages"]["agent"]["stream"]
                            )
            assert len(requests) == 4 and effects == [{"quantity": 3, "price": 2}] * 2
            # Ordinary Session reference recall may accompany the current turn.
            # It cannot replace or rearrange the original native episode.
            second_start = [
                message
                for message in requests[2]["messages"]
                if not (
                    message["role"] == "user" and message["content"].startswith("Reference memory;")
                )
            ]
            assert [m["role"] for m in second_start] == [
                "system",
                "user",
                "assistant",
                "tool",
                "assistant",
                "user",
            ]
            assert second_start[2] == native_message("first")
            assert second_start[4] == native_message("first", "final")
            assert second_start[-1]["content"] == "turn-two"

    asyncio.run(scenario())


class UnselectedHost:
    identity = {"kind": "must-not-fallback", "version": "1"}

    async def complete(self, messages, tools):
        raise AssertionError("Selected composite Agents must not fall back to the host")


def composite(kind):
    members = {name: agent(name) for name in ("first", "second")}
    if kind in {"graph", "nested"}:
        graph = r.GraphWorkflowSpec(
            "graph",
            [
                r.GraphNode("first", agent=members["first"]),
                r.GraphNode("second", agent=members["second"], depends_on=["first"]),
            ],
        )
        definition, prefix = (
            (graph, "graph/nodes/")
            if kind == "graph"
            else (
                r.TeamSpec("outer", {"nested": graph}, child_budget=16),
                "team/members/nested/graph/nodes/",
            )
        )
    elif kind == "team":
        definition, prefix = r.TeamSpec("team", members), "team/members/"
    else:
        definition, prefix = (
            r.DynamicWorkflowSpec("plan", members, planner="model", child_budget=8),
            "dynamic/members/",
        )
    return r.BoundDefinition(
        definition,
        {
            prefix + name: r.AgentBindingDescriptor(provider=r.BindingSelection.ref(name, "1"))
            for name in members
        },
    )


@pytest.mark.parametrize("kind", ["graph", "team", "plan", "nested"])
def test_actual_composite_agents_keep_independent_native_owners_and_original_tool_calls(
    tmp_path, kind
):
    async def scenario():
        requests, effects = [], []
        async with httpx.AsyncClient(transport=transport(requests)) as client:
            catalog = r.BindingCatalog(scope=r.Scope())
            selected = {name: provider(name, client) for name in ("first", "second", "planner")}
            for name in ("first", "second"):
                catalog.register("provider", name, "1", selected[name])
            with r.LocalEngine(
                r.SQLiteStore(tmp_path / "runs.sqlite"),
                providers={"default": UnselectedHost(), "planner": selected["planner"]},
                tools=tools(effects),
                binding_catalog=catalog,
                planners={"model": ModelPlanner(provider="planner")},
                model_continuation=True,
                model_history=r.CompleteModelHistory(),
            ) as engine:
                handle = engine.submit(composite(kind), "task", command_id="submit", budget=32)
                result = await engine.drive(handle.run_id)
                records = all_records(engine, handle.run_id)
                assert result.state == "succeeded", [
                    {"state": rec["state"], "error": rec.get("error")} for rec in records
                ]
                assert effects == [{"quantity": 3, "price": 2}] * 2
                assert Counter(body["model"] for body in requests) == {
                    "first": 2,
                    "second": 2,
                    **({"planner": 1} if kind == "plan" else {}),
                }
                model_actions = [
                    a for rec in records for a in rec["actions"] if a["kind"] == "model"
                ]
                assert len(model_actions) == (5 if kind == "plan" else 4)
                owners = set()
                for action in model_actions:
                    continuation = action["received_response"]["continuation"]
                    original = continuation["data"]["message"]
                    label = (
                        "planner"
                        if original["reasoning_content"] == "原始规划推理"
                        else original["reasoning_content"].split(" ", 1)[1].split("/", 1)[0]
                    )
                    assert continuation["owner_digest"] == digest(selected[label].identity)
                    owners.add(continuation["owner_digest"])
                    if label == "planner":
                        assert continuation["data"] == {"message": PLAN_MESSAGE}
                        assert action["received_response"]["output"] == PLAN_MESSAGE["content"]
                        assert action["received_response"]["tool_calls"] == []
                    else:
                        assert_original_receipt(
                            action, label, "tool-1" if original.get("tool_calls") else "final"
                        )
                if kind == "plan":
                    planner_child = next(
                        call
                        for call in engine.store.run(handle.run_id)["orchestration"]["children"]
                        if call["member"] == "@planner"
                    )
                    planner_record = engine.store.run(planner_child["run_id"])
                    assert planner_record["definition"]["steps"][0]["tools"] == []
                    assert planner_record["result"] == {
                        "steps": [
                            {"id": "first", "member": "first", "input": "task"},
                            {"id": "second", "member": "second", "input": "task"},
                        ]
                    }
                assert len(owners) == (3 if kind == "plan" else 2)
                tool_actions = [a for rec in records for a in rec["actions"] if a["kind"] == "tool"]
                assert Counter(a["call_id"] for a in tool_actions) == {
                    "native-first-task-tool-1": 1,
                    "native-second-task-tool-1": 1,
                }
                assert all(a["arguments"] == {"quantity": 3, "price": 2} for a in tool_actions)

    asyncio.run(scenario())


def process_worker(root, mode):
    """Abrupt exit happens only after the original receipt transaction commits."""

    class CrashStore(r.SQLiteStore):
        depth, trigger = 0, False

        @contextmanager
        def transaction(self):
            self.depth += 1
            try:
                with super().transaction():
                    yield
            finally:
                self.depth -= 1
            if not self.depth and self.trigger:
                os._exit(77)

        def emit(self, run_id, event, data=None):
            super().emit(run_id, event, data)
            if mode == "crash" and event == "model_response_recorded":
                self.trigger = True

    async def scenario():
        audit, requests, effects = root / "runtime-audit.jsonl", [], []
        async with httpx.AsyncClient(transport=transport(requests, audit=audit)) as client:
            with r.LocalEngine(
                CrashStore(root / "runs.sqlite"),
                providers={"default": provider("first", client)},
                tools=tools(effects, audit=audit),
                model_continuation=True,
            ) as engine:
                handle = engine.submit(agent(), "task", command_id="submit")
                if mode == "crash":
                    (root / "run-id").write_text(handle.run_id)
                else:
                    assert handle.run_id == (root / "run-id").read_text()
                result = await engine.drive(handle.run_id)
                if mode == "crash":
                    raise AssertionError("Original receipt checkpoint not reached")
                assert result.state == "succeeded", result.error
                assert await engine.drive(handle.run_id) == result
                record = engine.store.run(handle.run_id)
                assert_original_receipt(record["actions"][0], "first")
                assert_original_receipt(record["actions"][-1], "first", "final")
                print(
                    json.dumps(
                        {"state": result.state, "requests": len(requests), "effects": effects}
                    )
                )

    asyncio.run(scenario())


def test_received_before_adoption_process_exit_preserves_original_sqlite_authority(tmp_path):
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            (str(Path(r.__file__).parent.parent), str(Path(__file__).parent.parent))
        ),
    }
    for mode, expected_code in (("crash", 77), ("resume", 0)):
        process = subprocess.run(
            [sys.executable, str(Path(__file__)), str(tmp_path), mode],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == expected_code, process.stderr or process.stdout
        if mode == "crash":
            with r.SQLiteStore(tmp_path / "runs.sqlite", readonly=True) as store:
                record = store.run((tmp_path / "run-id").read_text())
                assert record["state"] == "running"
                assert (
                    len(record["actions"]) == 1
                    and record["actions"][0]["status"] == "response_received"
                )
                assert_original_receipt(record["actions"][0], "first")
                original = copy.deepcopy(record["actions"][0]["received_response"])
                assert store.budget(record["id"])["spent"] == 1
        else:
            assert json.loads(process.stdout) == {
                "state": "succeeded",
                "requests": 1,
                "effects": [{"quantity": 3, "price": 2}],
            }
            with r.SQLiteStore(tmp_path / "runs.sqlite", readonly=True) as store:
                assert (
                    store.run((tmp_path / "run-id").read_text())["actions"][0]["received_response"]
                    == original
                )
    rows = [
        json.loads(line) for line in (tmp_path / "runtime-audit.jsonl").read_text().splitlines()
    ]
    assert [row["phase"] for row in rows if row["kind"] == "model"] == ["tool-1", "final"]
    assert [row for row in rows if row["kind"] == "tool"] == [
        {"kind": "tool", "quantity": 3, "price": 2}
    ]


if __name__ == "__main__":
    process_worker(Path(sys.argv[1]), sys.argv[2])
