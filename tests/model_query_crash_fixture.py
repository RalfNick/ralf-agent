"""Process death after durable response with two native model-query data paths."""

import asyncio
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    Document,
    ModelResponse,
    RuntimeBuilder,
    RuntimeProfile,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)

root, endpoint, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]


class Store(SQLiteStore):
    depth = 0
    trigger = False

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


class Model:
    identity = {"kind": "model-query-process-business", "version": "1"}

    async def complete(self, messages, tools):
        assert "automobile servicing" in str(messages) and "automobile manual" in str(messages)
        with sqlite3.connect(root / "business.sqlite") as db:
            db.execute("INSERT INTO calls VALUES (?)", ("business_model",))
        if not any(m["role"] == "tool" for m in messages):
            return ModelResponse(tool_calls=[ToolCall("change", {}, "write")])
        return ModelResponse(output={"done": True})


def write(args, ctx):
    with sqlite3.connect(root / "business.sqlite") as db:
        db.execute("INSERT INTO effects VALUES (?)", (ctx.effect_key,))
    return {"written": True}


def tools(config, context):
    value = ToolRegistry()
    value.register(
        ToolSpec(
            "change",
            "Change",
            {"type": "object"},
            effect="idempotent_write",
            requires_approval=True,
        ),
        write,
    )
    return value


async def main():
    with sqlite3.connect(root / "business.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY)")
    registry = ComponentRegistry()
    registry.register("provider", "fixture", lambda c, ctx: Model())
    registry.register("tools", "fixture", tools)
    transform = {"type": "model", "config": {"provider": "query"}}
    profile = RuntimeProfile(
        "model-query-process",
        "1",
        {
            "default": {"adapter": "fixture"},
            "query": {
                "adapter": "chat-completions",
                "config": {
                    "model": "queries",
                    "base_url": endpoint,
                    "api_key_env": "QUERY_FIXTURE_KEY",
                    "json_mode": True,
                    "max_output_tokens": 128,
                },
            },
        },
        {
            "tools": {"adapter": "fixture"},
            "memory_store": {
                "adapter": "semantic-recall-async",
                "config": {
                    "backend": {"adapter": "sqlite"},
                    "query_transform": transform,
                    "embedding": {
                        "type": "openai",
                        "config": {
                            "model": "fixture",
                            "dimensions": 2,
                            "base_url": endpoint,
                            "anonymous": True,
                        },
                    },
                },
            },
            "recall_planner": {"adapter": "task-text"},
            "knowledge": {
                "adapter": "sqlite-lexical-query",
                "config": {"namespace": "docs", "query_transform": transform},
            },
        },
    )
    runtime = await RuntimeBuilder(registry, store_factory=Store, base_dir=root).abuild(
        profile, root / "runs.sqlite"
    )
    try:
        if mode == "crash":
            runtime.memory.put_fact(
                runtime.scope, "answer", "fact", "automobile servicing", expected_version=0
            )
            runtime.knowledge.retriever.retriever.store.put(
                runtime.scope, "docs", Document("guide", "automobile manual"), expected_version=0
            )
        handle = runtime.submit(
            AgentSpec("answer", "Use evidence", tools=("change",)), "car", command_id="s"
        )
        snapshot = await runtime.drive(handle.run_id)
        assert snapshot.state == "waiting_approval", snapshot.error
        if mode == "finish":
            pending = snapshot.pending[0]
            args = (handle.run_id, pending["action_id"], pending["digest"])
            receipt = runtime.approve(*args, command_id="approve")
            assert runtime.approve(*args, command_id="approve") == receipt
            snapshot = await runtime.drive(handle.run_id)
            assert snapshot.state == "succeeded", snapshot.error
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
        print(json.dumps({"state": snapshot.state}))
    finally:
        await runtime.aclose()


asyncio.run(main())
