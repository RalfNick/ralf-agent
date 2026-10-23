"""Native past Turns are model input, independently of reference recall."""

import asyncio
import copy
import json

import pytest

import relf_agent as r
from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from relf_agent.types import canonical, digest

FIRST_FINAL = ' { "answer" : "first-original" } '
SECOND_FINAL = ' { "answer" : "second-original" } '


class TwoTurnProvider:
    identity = {"kind": "native-two-turn-fixture", "version": "1"}
    continuation_identity = {"protocol": "native-two-turn-v1", "owner_digest": "a" * 64}

    def __init__(self, requests):
        self.requests = requests

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        index = len(self.requests) - 1
        calls = [r.ToolCall("lookup", {}, "same-original-id")] if index % 2 == 0 else []
        output = None if calls else FIRST_FINAL if index == 1 else SECOND_FINAL
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
                "native-two-turn-v1", "a" * 64, digest(decision), {"signature": f"sig-{index}"}
            ),
        )


class CurrentKnowledge:
    identity = {"kind": "current-task-knowledge", "version": "1"}
    limit, max_chars = 4, 2000

    def __init__(self, queries):
        self.queries = queries

    async def references(self, scope, query):
        self.queries.append(query)
        return []

    async def validate(self, scope, references):
        return None


def spec(max_context_chars=16000):
    return r.AgentSpec(
        "same-name",
        "Use lookup and return JSON",
        ("lookup",),
        max_context_chars=max_context_chars,
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    )


def tools():
    registry = r.ToolRegistry()
    registry.register(
        r.ToolSpec("lookup", "Lookup", {"type": "object"}),
        lambda arguments, context: {"original": "complete-tool-evidence"},
    )
    return registry


def options(requests, queries):
    return {
        "providers": {"default": TwoTurnProvider(requests)},
        "tools": tools(),
        "knowledge": CurrentKnowledge(queries),
        "model_continuation": True,
        "model_history": r.CompleteModelHistory(scope="session"),
    }


@pytest.mark.parametrize("facade", [False, True])
def test_two_turns_keep_original_native_messages_and_current_knowledge_query(tmp_path, facade):
    async def scenario():
        requests, queries, runs = [], [], []
        engine = r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"), **options(requests, queries)
        )
        if facade:
            async with r.Runtime(engine, owned=True) as runtime:
                session = await runtime.create_agent(spec()).open_session("same", command_id="open")
                for index, task in enumerate(("first-task", "second-task")):
                    run = await session.submit(task, command_id=f"turn-{index}")
                    waited = await run.wait(wait_timeout=2)
                    assert waited.snapshot.state == "succeeded"
                    runs.append(engine.store.run(run.ref.run_id))
        else:
            with engine:
                for index, task in enumerate(("first-task", "second-task")):
                    handle = engine.submit(
                        spec(), task, session_id="same", command_id=f"turn-{index}"
                    )
                    assert (await engine.drive(handle.run_id)).state == "succeeded"
                    runs.append(engine.store.run(handle.run_id))
        assert len(requests) == 4
        second = requests[2]
        assert [m["role"] for m in second[:6]] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
            "user",
        ]
        assert second[1]["content"] == "first-task" and second[5]["content"] == "second-task"
        assert second[4]["content"] == FIRST_FINAL
        assert second[4]["model_continuation"]["data"] == {"signature": "sig-1"}
        assert len(second) == 7 and second[6]["content"].startswith("Reference memory;")
        assert "complete-tool-evidence" in canonical(second[3])
        assert [m["tool_calls"][0]["id"] for m in requests[3] if m.get("tool_calls")] == [
            "same-original-id"
        ] * 2
        assert queries == ["first-task", "first-task", "second-task", "second-task"]
        assert runs[1]["messages"][1]["content"] == "second-task"
        assert runs[1]["manifest"]["model_history_protocol"] == 2
        assert runs[1]["manifest"]["kernel"] == "local-7"

    asyncio.run(scenario())


def test_native_history_survives_new_engine_without_repeating_first_turn(tmp_path):
    async def scenario():
        requests, queries, path = [], [], tmp_path / "restart.sqlite"
        with r.LocalEngine(r.SQLiteStore(path), **options(requests, queries)) as engine:
            handle = engine.submit(spec(), "first-task", session_id="same", command_id="first")
            assert (await engine.drive(handle.run_id)).state == "succeeded"
        with r.LocalEngine(r.SQLiteStore(path), **options(requests, queries)) as engine:
            handle = engine.submit(spec(), "second-task", session_id="same", command_id="second")
            assert (await engine.drive(handle.run_id)).state == "succeeded"
            assert (
                engine.submit(spec(), "second-task", session_id="same", command_id="second").run_id
                == handle.run_id
            )
        assert len(requests) == 4
        assert requests[2][4]["content"] == FIRST_FINAL

    asyncio.run(scenario())


def test_acceptance_failure_does_not_activate_native_schema(tmp_path):
    class FailingStore(r.SQLiteStore):
        def insert_run(self, data):
            super().insert_run(data)
            raise RuntimeError("after original insert")

    with r.LocalEngine(FailingStore(tmp_path / "rollback.sqlite"), **options([], [])) as engine:
        original = engine.store.conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()[0]
        with pytest.raises(RuntimeError, match="original insert"):
            engine.submit(spec(), "first-task", session_id="same", command_id="first")
        assert (
            engine.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == original
        )
        assert engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    "mutation", ["root-failed", "receipt-missing", "wrong-action", "wrong-final"]
)
def test_past_native_data_requires_original_success_and_exact_publication_evidence(
    tmp_path, mutation
):
    async def scenario():
        requests, queries = [], []
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"), **options(requests, queries)
        ) as engine:
            first = engine.submit(spec(), "first-task", session_id="same", command_id="first")
            assert (await engine.drive(first.run_id)).state == "succeeded"
            with engine.store.transaction():
                if mutation == "root-failed":
                    original = engine.store.run(first.run_id)
                    original["state"] = "failed"
                    engine.store.save_run(original)
                else:
                    row = engine.store.conn.execute(
                        "SELECT rowid,data FROM native_history_publications"
                    ).fetchone()
                    data = json.loads(row[1])
                    if mutation == "receipt-missing":
                        data["receipt"]["receipt"] = None
                    elif mutation == "wrong-action":
                        data["source_action"] = "another-model-action"
                    else:
                        original = engine.store.run(first.run_id)
                        action = next(
                            a for a in reversed(original["actions"]) if a["kind"] == "model"
                        )
                        action["response"]["output"] = "changed original final"
                        engine.store.save_run(original)
                    engine.store.conn.execute(
                        "UPDATE native_history_publications SET data=? WHERE rowid=?",
                        (canonical(data), row[0]),
                    )
            second = engine.submit(spec(), "second-task", session_id="same", command_id="second")
            snapshot = await engine.drive(second.run_id)
            assert snapshot.state == "failed"
            assert engine.store.run(second.run_id)["error"]["code"] == "definition_mismatch"
            assert len(requests) == 2

    asyncio.run(scenario())


def test_nullable_schema_preserves_original_null_between_successful_turns(tmp_path):
    class NullableProvider:
        identity = {"kind": "nullable-native-history", "version": "1"}

        async def complete(self, messages, tools):
            requests.append(copy.deepcopy(messages))
            return r.ModelResponse(output=None)

    async def scenario():
        nullable = r.AgentSpec("nullable", "Return null", output_schema={"type": "null"})
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": NullableProvider()},
            tools=r.ToolRegistry(),
            model_continuation=True,
            model_history=r.CompleteModelHistory(scope="session"),
        ) as engine:
            for i in range(2):
                handle = engine.submit(
                    nullable, f"task-{i}", session_id="same", command_id=f"turn-{i}"
                )
                snapshot = await engine.drive(handle.run_id)
                assert snapshot.state == "succeeded", engine.store.run(handle.run_id).get("error")
                assert snapshot.result is None
        assert requests[1][:4] == [
            {"role": "system", "content": "Return null"},
            {"role": "user", "content": "task-0"},
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "user", "content": "task-1"},
        ]

    requests = []
    asyncio.run(scenario())


@pytest.mark.parametrize("host", [None, "run"])
def test_selected_session_history_can_be_enabled_without_global_session_policy(tmp_path, host):
    async def scenario():
        requests, queries = [], []
        selected = r.CompleteModelHistory(scope="session")
        catalog = r.BindingCatalog(scope=r.Scope())
        catalog.register("model_history", "native", "2", selected)
        bound = r.AgentDefinition(
            spec(), r.AgentBindingDescriptor(model_history=r.BindingSelection.ref("native", "2"))
        )
        config = options(requests, queries)
        config["model_history"] = None if host is None else r.CompleteModelHistory()
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "runs.sqlite"), binding_catalog=catalog, **config
        ) as engine:
            for i in range(2):
                handle = engine.submit(
                    bound, f"task-{i}", session_id="same", command_id=f"turn-{i}"
                )
                assert (await engine.drive(handle.run_id)).state == "succeeded"
            assert requests[2][4]["content"] == FIRST_FINAL
            assert engine.store.run(handle.run_id)["messages"][1]["content"] == "task-1"

    asyncio.run(scenario())
