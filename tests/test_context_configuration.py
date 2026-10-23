import asyncio
import importlib

import pytest

from relf_agent import AgentSpec, RuntimeBuilder, RuntimeProfile
from relf_agent.errors import ValidationError


def profile(**config):
    return RuntimeProfile(
        "context",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"context_assembler": {"adapter": "budgeted", "config": config}},
    )


def test_budgeted_context_factory_sync_async_and_fixed_config(tmp_path):
    for mode in ["sync", "async"]:

        async def run(mode=mode):
            builder = RuntimeBuilder(base_dir=tmp_path)
            p = profile(
                counter="utf8-estimate", max_units=200, summarizer="excerpt", summary_max_chars=300
            )
            runtime = (
                builder.build(p, tmp_path / f"{mode}.sqlite")
                if mode == "sync"
                else await builder.abuild(p, tmp_path / f"{mode}.sqlite")
            )
            try:
                handle = runtime.submit(
                    AgentSpec("answer", "Use the task"), "hello", command_id="one"
                )
                assert (await runtime.drive(handle.run_id)).state == "succeeded"
                action = runtime.status(handle.run_id).actions[0]
                assert action["context_manifest"]["measurement"]["estimated"] is True
                assert action["context_manifest"]["measurement"]["units"] <= 200
                assert runtime.context.identity["kind"] == "budgeted-context"
            finally:
                if mode == "sync":
                    runtime.close()
                else:
                    await runtime.aclose()

        asyncio.run(run())


@pytest.mark.parametrize(
    "config",
    [
        {"unknown": 1},
        {"counter": "magic-tokenizer"},
        {"max_units": True},
        {"summarizer": "model"},
        {"max_excerpts": 1000000},
        {"summary_max_chars": 1000000},
    ],
)
def test_bad_context_factory_declarations_fail_before_store_created(tmp_path, config):
    path = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder(base_dir=tmp_path).build(profile(**config), path)
    assert not path.exists()


def test_harness_transform_is_measured_at_actual_request_boundary(tmp_path):
    from relf_agent import LocalEngine, ModelRequest, ModelResponse, SQLiteStore, ToolRegistry
    from relf_agent.harness import NativeHarness

    a = importlib.import_module("relf_agent.context_pipeline")
    called = []

    class Provider:
        identity = {"kind": "request-probe", "version": "1"}

        async def complete(self, messages, tools):
            called.append(messages)
            return ModelResponse(output="done")

    class Expanded(NativeHarness):
        identity = {"kind": "expanded", "version": "1"}

        def prepare(self, spec, messages, descriptions):
            messages[1]["content"] += "x" * 500
            return ModelRequest(messages, descriptions)

    with LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": Provider()},
        tools=ToolRegistry(),
        context_assembler=a.BudgetedContextAssembler(max_units=300),
        harness=Expanded(),
    ) as engine:
        handle = engine.submit(
            AgentSpec("answer", "Complete", max_context_chars=2000), "hello", command_id="one"
        )
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "failed" and called == []


def test_real_request_snapshot_survives_reopen_with_opt_in_builder(tmp_path):
    from relf_agent import LocalEngine, ModelResponse, SQLiteStore, ToolCall, ToolRegistry, ToolSpec

    a = importlib.import_module("relf_agent.context_pipeline")
    path = tmp_path / "runs.sqlite"
    dispatches = []
    writes = []

    class Provider:
        identity = {"kind": "context-restart", "version": "1"}

        async def complete(self, messages, tools):
            dispatches.append(messages)
            if not any(m.get("role") == "tool" for m in messages):
                return ModelResponse(tool_calls=(ToolCall("write", {}, "one"),))
            return ModelResponse(output="confirmed")

    def handler(arguments, context):
        writes.append(context.effect_key)
        return {"confirmed": True}

    def factory():
        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "write",
                "Write test evidence",
                {"type": "object", "additionalProperties": False},
                effect="idempotent_write",
                requires_approval=True,
            ),
            handler,
        )
        return LocalEngine(
            SQLiteStore(path),
            providers={"default": Provider()},
            tools=tools,
            context_assembler=a.BudgetedContextAssembler(summarizer=a.ExcerptContextSummarizer()),
        )

    with factory() as engine:
        handle = engine.submit(
            AgentSpec("answer", "Complete", tools=("write",)), "hello", command_id="one"
        )
        first = asyncio.run(engine.drive(handle.run_id))
        assert first.state == "waiting_approval" and len(dispatches) == 1
    with factory() as engine:
        pending = engine.status(handle.run_id).pending[0]
        engine.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="approve")
        last = asyncio.run(engine.drive(handle.run_id))
        assert last.state == "succeeded" and len(writes) == 1 and len(dispatches) == 2
        assert last.actions[-1]["context_manifest"]["measurement"]["units"] <= 32000
