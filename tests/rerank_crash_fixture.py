"""Actual process exit after durable model response; source preparation is reused."""

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
    identity = {"kind": "rerank-process-model", "version": "1"}

    async def complete(self, messages, tools):
        with sqlite3.connect(root / "business.sqlite") as db:
            db.execute("INSERT INTO calls VALUES ('model')")
        if not any(m["role"] == "tool" for m in messages):
            return ModelResponse(tool_calls=[ToolCall("change", {}, "write")])
        return ModelResponse(output={"done": True})


def write(args, ctx):
    with sqlite3.connect(root / "business.sqlite") as db:
        db.execute("INSERT INTO effects VALUES (?)", (ctx.effect_key,))
    return {"written": True}


def tool_factory(config, context):
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change",
            "Change",
            {"type": "object"},
            effect="idempotent_write",
            requires_approval=True,
        ),
        write,
    )
    return tools


async def main():
    with sqlite3.connect(root / "business.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY)")
    registry = ComponentRegistry()
    registry.register("provider", "fixture", lambda c, ctx: Model())
    registry.register("tools", "fixture", tool_factory)
    profile = RuntimeProfile(
        "rerank-process",
        "1",
        {"default": {"adapter": "fixture"}},
        {
            "tools": {"adapter": "fixture"},
            "knowledge": {
                "adapter": "sqlite-hybrid-rerank-http",
                "config": {
                    "namespace": "docs",
                    "limit": 1,
                    "reranker": {
                        "type": "http",
                        "config": {"model": "fixture", "base_url": endpoint, "anonymous": True},
                    },
                },
            },
        },
    )
    runtime = await RuntimeBuilder(registry, store_factory=Store, base_dir=root).abuild(
        profile, root / "runs.sqlite"
    )
    try:
        if mode == "crash":
            hybrid = runtime.knowledge.retriever
            hybrid.store.put(
                runtime.scope, "docs", Document("guide", "car safety manual"), expected_version=0
            )
            await hybrid.retrievers["vector"].index_document(runtime.scope, "docs", "guide")
        handle = runtime.submit(
            AgentSpec("answer", "Use evidence", tools=("change",)), "car", command_id="s"
        )
        snapshot = await runtime.drive(handle.run_id)
        if mode == "waiting":
            assert snapshot.state == "waiting_approval", snapshot.error
        elif mode == "finish":
            pending = snapshot.pending[0]
            a = runtime.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            assert (
                runtime.approve(
                    handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
                )
                == a
            )
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
        print(json.dumps({"state": runtime.status(handle.run_id).state}))
    finally:
        await runtime.aclose()


asyncio.run(main())
