"""Published native episodes follow actual Local member paths and fresh input."""

import asyncio
import copy
from collections import Counter, defaultdict

import pytest

import ralf_agent as r
from ralf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from ralf_agent.types import canonical, digest
from tests.test_local_session_model_history import CurrentKnowledge, tools


class MemberProvider:
    identity = {"kind": "native-local-members", "version": "1"}
    continuation_identity = {"protocol": "native-local-members-v1", "owner_digest": "a" * 64}

    def __init__(self, requests):
        self.requests = requests

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        await asyncio.sleep(0)
        member = messages[0]["content"]
        calls = [] if messages[-1]["role"] == "tool" else [r.ToolCall("lookup", {}, "original-id")]
        output = None if calls else ' { "answer" : "' + member + '" } '
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
                "native-local-members-v1",
                "a" * 64,
                digest(decision),
                {"signature": ("tool-" if calls else "final-") + member},
            ),
        )


def definition(kind):
    members = {
        name: r.AgentSpec(
            name,
            "member-" + name,
            ("lookup",),
            max_context_chars=24000,
            output_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )
        for name in ("a", "b")
    }
    if kind == "sequence":
        return r.WorkflowSpec("sequence", list(members.values()))
    if kind in {"graph", "parallel"}:
        return r.GraphWorkflowSpec(
            "graph",
            [r.GraphNode(name, agent=agent) for name, agent in members.items()],
            max_concurrency=2 if kind == "parallel" else 1,
        )
    if kind in {"team", "nested"}:
        if kind == "nested":
            members["a"] = r.WorkflowSpec("nested-sequence", [members["a"]])
        return r.TeamSpec("team", members, child_budget=32, max_depth=4)
    return r.DynamicWorkflowSpec(
        "plan", members, child_budget=32, plan_mode="dag" if kind == "dynamic-dag" else "flat"
    )


def current_task(messages):
    return next(
        m["content"]
        for m in reversed(messages)
        if m["role"] == "user" and not m["content"].startswith("Reference memory;")
    )


@pytest.mark.parametrize(
    "kind", ["sequence", "graph", "parallel", "team", "nested", "dynamic", "dynamic-dag"]
)
@pytest.mark.parametrize("facade", [False, True])
def test_two_turn_compositions_restore_each_original_member_episode(tmp_path, kind, facade):
    async def scenario():
        requests, queries, roots = [], [], []
        engine = r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": MemberProvider(requests)},
            tools=tools(),
            knowledge=CurrentKnowledge(queries),
            model_continuation=True,
            model_history=r.CompleteModelHistory(scope="session"),
        )
        try:
            if facade:
                async with r.Runtime(engine, owned=False) as runtime:
                    session = await runtime.create_agent(definition(kind)).open_session(
                        "same", command_id="open"
                    )
                    for index, task in enumerate(("first-task", "second-task")):
                        handle = await session.submit(task, command_id=f"turn-{index}", budget=64)
                        waited = await handle.wait(wait_timeout=10)
                        assert waited.snapshot.state == "succeeded", engine.store.run(
                            handle.ref.run_id
                        ).get("error")
                        roots.append(engine.store.run(handle.ref.run_id))
                        async with asyncio.timeout(2):
                            while (await session.status()).busy:  # noqa: ASYNC110 -- observe original hosting quiescence
                                await asyncio.sleep(0.01)
            else:
                for index, task in enumerate(("first-task", "second-task")):
                    handle = engine.submit(
                        definition(kind),
                        task,
                        session_id="same",
                        command_id=f"turn-{index}",
                        budget=64,
                    )
                    snapshot = await engine.drive(handle.run_id)
                    assert snapshot.state == "succeeded", engine.store.run(handle.run_id).get(
                        "error"
                    )
                    roots.append(engine.store.run(handle.run_id))
            assert len(requests) == 8
            by_member = defaultdict(list)
            for messages in requests:
                by_member[messages[0]["content"]].append(messages)
            assert set(by_member) == {"member-a", "member-b"}
            for member, member_requests in by_member.items():
                second = member_requests[2]
                assert [m["role"] for m in second[:6]] == [
                    "system",
                    "user",
                    "assistant",
                    "tool",
                    "assistant",
                    "user",
                ]
                assert second[4]["content"] == ' { "answer" : "' + member + '" } '
                assert second[4]["model_continuation"]["data"]["signature"] == "final-" + member
                assert "complete-tool-evidence" in canonical(second[3])
                assert [
                    m["tool_calls"][0]["id"] for m in member_requests[3] if m.get("tool_calls")
                ] == ["original-id", "original-id"]
            assert Counter(queries) == Counter(current_task(messages) for messages in requests)
            assert roots[0]["result"] == roots[1]["result"]
        finally:
            engine.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["sequence", "parallel", "team", "dynamic-dag", "nested"])
@pytest.mark.parametrize("selected", ["disabled", "run"])
def test_member_history_selection_changes_only_that_actual_agent(tmp_path, kind, selected):
    async def scenario():
        from ralf_agent.binding_paths import agent_paths
        from ralf_agent.spec_codec import encode_spec

        spec = definition(kind)
        paths = agent_paths(encode_spec(spec))
        path_b = next(path for path, agent in paths.items() if agent["name"] == "b")
        catalog = r.BindingCatalog(scope=r.Scope())
        catalog.register("model_history", "complete", "1", r.CompleteModelHistory())
        choice = (
            r.BindingSelection.disabled()
            if selected == "disabled"
            else r.BindingSelection.ref("complete", "1")
        )
        bound = r.BoundDefinition(spec, {path_b: r.AgentBindingDescriptor(model_history=choice)})
        requests = []
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": MemberProvider(requests)},
            tools=tools(),
            binding_catalog=catalog,
            model_continuation=True,
            model_history=r.CompleteModelHistory(scope="session"),
        ) as engine:
            for i, task in enumerate(("first-task", "second-task")):
                handle = engine.submit(
                    bound, task, session_id="same", command_id=f"turn-{i}", budget=64
                )
                snapshot = await engine.drive(handle.run_id)
                assert snapshot.state == "succeeded", engine.store.run(handle.run_id).get("error")
        by_member = defaultdict(list)
        for request in requests:
            by_member[request[0]["content"]].append(request)
        assert [m["role"] for m in by_member["member-a"][2][:6]] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
            "user",
        ]
        assert not any(
            m.get("model_continuation", {}).get("data", {}).get("signature") == "final-member-b"
            for m in by_member["member-b"][2]
        )

    asyncio.run(scenario())
