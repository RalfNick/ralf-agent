"""Only public HTTP is scripted; execution, receipts, tools and Sessions are real."""

import asyncio
import copy
import json
import os
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

import relf_agent as r
from relf_agent.planning import ModelPlanner
from relf_agent.types import digest

RAW_ARGUMENTS = ' \n { "quantity" : 3 } \t '
PLAN_TEXT = ' { "steps" : [ { "id" : "first", "member" : "first", "input" : "task" }, { "id" : "second", "member" : "second", "input" : "task" } ] } '


def provider(model, client, **options):
    cls = getattr(r, "OpenAIResponsesReasoningProvider", None)
    assert cls is not None, "Explicit native Responses reasoning Provider is required"
    return cls(
        model,
        api_key="fixture",
        client=client,
        reasoning_effort="high",
        reasoning_context="all_turns",
        **options,
    )


def test_public_responses_reasoning_provider_exists():
    assert getattr(r, "OpenAIResponsesReasoningProvider", None) is not None, (
        "Explicit native Responses reasoning Provider is required"
    )


def text_item(identifier, text, phase="final_answer"):
    return {
        "id": identifier,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "phase": phase,
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def native_output(model, phase="tool-1", task="task"):
    key = f"{model}-{task}-{phase}"
    items = [
        {
            "id": "reasoning-" + key,
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "私有摘要 " + key}],
            "encrypted_content": "opaque-encrypted-original-" + key,
        },
        text_item("commentary-" + key, "Checking " + key, "commentary"),
    ]
    if phase.startswith("tool-"):
        items.append(
            {
                "id": "function-item-" + key,
                "type": "function_call",
                "status": "completed",
                "call_id": "native-call-" + key,
                "name": "calculate",
                "arguments": RAW_ARGUMENTS,
            }
        )
    else:
        items.append(
            text_item(
                "final-item-" + key,
                PLAN_TEXT if model == "planner" else "complete-" + model + "-" + task,
            )
        )
    return items


def completed(output):
    return {
        "id": "fixture-response",
        "object": "response",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": copy.deepcopy(output),
        "usage": {
            "input_tokens": 3,
            "output_tokens": 4,
            "total_tokens": 7,
            "input_tokens_details": {"cached_tokens": 1},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
    }


def wire_response(output, *, stream=False):
    final = completed(output)
    if not stream:
        return httpx.Response(200, json=final)
    events = [
        {
            "type": "response.created",
            "response": {**final, "status": "in_progress", "output": [], "usage": None},
        }
    ]
    for index, item in enumerate(output):
        added = copy.deepcopy(item)
        if item["type"] == "message":
            added.update(status="in_progress", content=[])
        elif item["type"] == "function_call":
            added.update(status="in_progress", arguments="")
        events.append({"type": "response.output_item.added", "output_index": index, "item": added})
        if item["type"] == "message":
            for content_index, part in enumerate(item["content"]):
                identity = {
                    "output_index": index,
                    "content_index": content_index,
                    "item_id": item["id"],
                }
                events.extend(
                    [
                        {
                            "type": "response.content_part.added",
                            **identity,
                            "part": {**part, "text": ""},
                        },
                        {"type": "response.output_text.delta", **identity, "delta": part["text"]},
                        {"type": "response.output_text.done", **identity, "text": part["text"]},
                        {"type": "response.content_part.done", **identity, "part": part},
                    ]
                )
        elif item["type"] == "function_call":
            identity = {"output_index": index, "item_id": item["id"]}
            events.extend(
                [
                    {
                        "type": "response.function_call_arguments.delta",
                        **identity,
                        "delta": item["arguments"],
                    },
                    {
                        "type": "response.function_call_arguments.done",
                        **identity,
                        "arguments": item["arguments"],
                    },
                ]
            )
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    events.append({"type": "response.completed", "response": final})
    wire = "".join(
        "event: "
        + event["type"]
        + "\ndata: "
        + json.dumps({**event, "sequence_number": sequence})
        + "\n\n"
        for sequence, event in enumerate(events)
    )
    return httpx.Response(200, content=wire, headers={"content-type": "text/event-stream"})


def transport(requests, *, loops=1, audit=None):
    def respond(request):
        body = json.loads(request.content)
        model, items = body["model"], body["input"]
        requests.append(copy.deepcopy(body))
        assert body["store"] is False
        assert body["include"] == ["reasoning.encrypted_content"]
        assert body["reasoning"] == {"effort": "high", "context": "all_turns"}
        assert not ({"previous_response_id", "conversation", "background"} & body.keys())
        current = next(
            item["content"]
            for item in reversed(items)
            if item.get("role") == "user" and not item["content"].startswith("Reference memory;")
        )
        task = "turn-two" if current == "turn-two" else "task"
        originals = [
            item for item in items if item.get("type") in {"reasoning", "message", "function_call"}
        ]
        if model == "planner":
            assert not body.get("tools")
            assert originals == []
            output, phase = native_output(model, "final"), "plan-final"
        else:
            declaration = body["tools"][0]
            assert declaration["type"] == "function" and declaration["name"] == "calculate"
            assert declaration["parameters"]["required"] == ["quantity"]
            assert declaration["parameters"]["properties"]["price"]["type"] == "integer"
            past = (
                native_output(model) + native_output(model, "final") if task == "turn-two" else []
            )
            assert originals[: len(past)] == past
            active = originals[len(past) :]
            assert len(active) % 3 == 0
            groups = len(active) // 3
            expected = [
                item
                for index in range(groups)
                for item in native_output(model, f"tool-{index + 1}", task)
            ]
            assert active == expected
            replies = [item for item in items if item.get("type") == "function_call_output"]
            calls = [item for item in originals if item["type"] == "function_call"]
            assert [reply["call_id"] for reply in replies] == [call["call_id"] for call in calls]
            assert all(json.loads(reply["output"]) == {"amount": 6} for reply in replies)
            phase = f"tool-{groups + 1}" if groups < loops else "final"
            output = native_output(model, phase, task)
        if audit:
            audit_row(audit, {"kind": "model", "model": model, "phase": phase})
        return wire_response(output, stream=body.get("stream", False))

    return httpx.MockTransport(respond)


def audit_row(path, row):
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(row) + "\n")
        output.flush()
        os.fsync(output.fileno())


def tools(effects, *, approval=False, audit=None):
    def calculate(quantity: int, price: int = 2):
        effect = {"quantity": quantity, "price": price}
        effects.append(effect)
        if audit:
            audit_row(audit, {"kind": "tool", **effect})
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
    raw, original = action["received_response"], native_output(model, phase, task)
    assert raw["continuation"]["protocol"] == "openai-responses-reasoning-v1"
    assert raw["continuation"]["data"] == {"output": original}
    if phase.startswith("tool-"):
        assert raw["output"] is None
        assert raw["tool_calls"] == [
            {
                "name": "calculate",
                "arguments": {"quantity": 3},
                "call_id": original[-1]["call_id"],
            }
        ]
    else:
        assert raw["output"] == original[-1]["content"][0]["text"] and raw["tool_calls"] == []


@pytest.mark.parametrize("stream", [False, True], ids=["json", "sse"])
def test_two_original_tool_groups_and_rag_survive_the_real_agent(tmp_path, stream):
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
            selected = provider("first", client, stream=stream)
            with r.LocalEngine(
                r.SQLiteStore(tmp_path / "runs.sqlite"),
                providers={"default": selected},
                tools=tools(effects),
                knowledge=r.KnowledgeContext(r.LexicalRetriever(knowledge), namespace="manuals"),
                model_continuation=True,
                model_history=r.CompleteModelHistory(),
            ) as engine:
                handle = engine.submit(agent(), "calculate documented units", command_id="submit")
                outcome = await engine.drive(handle.run_id)
                assert outcome.state == "succeeded", outcome.error
                assert outcome.result == "complete-first-task"
                assert len(requests) == 3 and effects == [{"quantity": 3, "price": 2}] * 2
                assert any(
                    "DOCUMENT_CANARY" in item.get("content", "") for item in requests[0]["input"]
                )
                models = [
                    a for a in engine.store.run(handle.run_id)["actions"] if a["kind"] == "model"
                ]
                for action, phase in zip(models, ("tool-1", "tool-2", "final"), strict=True):
                    assert_original_receipt(action, "first", phase)
                    assert action["received_response"]["continuation"]["owner_digest"] == digest(
                        selected.identity
                    )
                assert [
                    item
                    for item in requests[-1]["input"]
                    if item.get("type") in {"reasoning", "message", "function_call"}
                ] == native_output("first") + native_output("first", "tool-2")
                assert not client.is_closed

    asyncio.run(scenario())


@pytest.mark.parametrize("stream", [False, True], ids=["json", "sse"])
def test_approval_reopen_reuses_original_receipt_and_duplicate_control_once(tmp_path, stream):
    async def scenario():
        path, requests, effects = tmp_path / "runs.sqlite", [], []
        registry = tools(effects, approval=True)
        async with httpx.AsyncClient(transport=transport(requests)) as client:

            def open_engine():
                return r.LocalEngine(
                    r.SQLiteStore(path),
                    providers={"default": provider("first", client, stream=stream)},
                    tools=registry,
                    model_continuation=True,
                    model_history=r.CompleteModelHistory(),
                )

            with open_engine() as engine:
                handle = engine.submit(agent(), "task", command_id="submit", budget=10)
                assert (await engine.drive(handle.run_id)).state == "waiting_approval"
                original = copy.deepcopy(engine.store.run(handle.run_id))
                pending = original["actions"][-1]
                assert len(requests) == 1 and effects == []
                assert_original_receipt(original["actions"][0], "first")
                assert pending["arguments"] == {"quantity": 3, "price": 2}
            with open_engine() as engine:
                assert engine.submit(agent(), "task", command_id="submit", budget=10) == handle
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
                assert engine.store.run(handle.run_id) == after
                assert len(requests) == 2 and effects == [{"quantity": 3, "price": 2}]

    asyncio.run(scenario())


def test_two_session_turns_reopen_and_echo_original_final_phase_and_encrypted_reasoning(tmp_path):
    async def scenario():
        path, requests, effects = tmp_path / "session.sqlite", [], []
        registry, session_ref, first_record = tools(effects), None, None
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
                            await entry.open_session("reasoning", command_id="open")
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
            second_start = [
                item
                for item in requests[2]["input"]
                if not (
                    item.get("role") == "user" and item["content"].startswith("Reference memory;")
                )
            ]
            assert second_start[:2] == requests[0]["input"][:2]
            assert second_start[2:5] == native_output("first")
            assert second_start[5] == {
                "type": "function_call_output",
                "call_id": "native-call-first-task-tool-1",
                "output": '{"amount":6}',
            }
            assert second_start[6:9] == native_output("first", "final")
            assert second_start[9] == {"role": "user", "content": "turn-two"}

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
def test_bound_composite_agents_keep_distinct_native_owners_and_actual_model_planner(
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
                    original = continuation["data"]["output"]
                    label = original[0]["id"].removeprefix("reasoning-").split("-task-", 1)[0]
                    assert continuation["owner_digest"] == digest(selected[label].identity)
                    owners.add(continuation["owner_digest"])
                    assert_original_receipt(
                        action,
                        label,
                        "tool-1" if original[-1]["type"] == "function_call" else "final",
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
                    "native-call-first-task-tool-1": 1,
                    "native-call-second-task-tool-1": 1,
                }
                assert all(a["arguments"] == {"quantity": 3, "price": 2} for a in tool_actions)

    asyncio.run(scenario())


def process_worker(root, window, mode):
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
            if mode == "crash" and event == window:
                self.trigger = True

    async def scenario():
        audit, requests, effects = root / "runtime-audit.jsonl", [], []
        async with httpx.AsyncClient(transport=transport(requests, audit=audit)) as client:
            with r.LocalEngine(
                CrashStore(root / "runs.sqlite"),
                providers={"default": provider("first", client)},
                tools=tools(effects, audit=audit),
                model_continuation=True,
                model_history=r.CompleteModelHistory(),
            ) as engine:
                handle = engine.submit(agent(), "task", command_id="submit", budget=10)
                if mode == "crash":
                    (root / "run-id").write_text(handle.run_id)
                else:
                    assert handle.run_id == (root / "run-id").read_text()
                result = await engine.drive(handle.run_id)
                if mode == "crash":
                    raise AssertionError("Original committed checkpoint not reached")
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


@pytest.mark.parametrize("window", ["model_response_recorded", "decision_adopted"])
def test_committed_process_death_preserves_original_received_or_adopted_decision(tmp_path, window):
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            (str(Path(r.__file__).parent.parent), str(Path(__file__).parent.parent))
        ),
    }
    for mode, expected_code in (("crash", 77), ("resume", 0)):
        process = subprocess.run(
            [sys.executable, str(Path(__file__)), str(tmp_path), window, mode],
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
                model = record["actions"][0]
                assert model["status"] == (
                    "response_received" if window == "model_response_recorded" else "completed"
                )
                assert_original_receipt(model, "first")
                original = copy.deepcopy(model["received_response"])
                assert store.budget(record["id"])["spent"] == 1
                assert len(record["actions"]) == (1 if window == "model_response_recorded" else 2)
                assert len([m for m in record["messages"] if m["role"] == "assistant"]) == (
                    0 if window == "model_response_recorded" else 1
                )
        else:
            assert json.loads(process.stdout) == {
                "state": "succeeded",
                "requests": 1,
                "effects": [{"quantity": 3, "price": 2}],
            }
            with r.SQLiteStore(tmp_path / "runs.sqlite", readonly=True) as store:
                record = store.run((tmp_path / "run-id").read_text())
                assert record["actions"][0]["received_response"] == original
                assert store.budget(record["id"]) == {"limit": 10, "held": 0, "spent": 2}
    rows = [
        json.loads(line) for line in (tmp_path / "runtime-audit.jsonl").read_text().splitlines()
    ]
    assert [row["phase"] for row in rows if row["kind"] == "model"] == ["tool-1", "final"]
    assert [row for row in rows if row["kind"] == "tool"] == [
        {"kind": "tool", "quantity": 3, "price": 2}
    ]


if __name__ == "__main__":
    process_worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
