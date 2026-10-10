"""Actual process loss after durable response; adopted source preparation is reused."""

import asyncio
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from ralf_agent import (
    AgentSpec,
    AliasQueryTransform,
    ComponentRegistry,
    Document,
    KnowledgeContext,
    ModelResponse,
    QueryTransformRetriever,
    RuntimeBuilder,
    RuntimeProfile,
    SemanticMemoryStore,
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


def record(kind):
    with sqlite3.connect(root / "business.sqlite") as db:
        db.execute("INSERT INTO calls VALUES (?)", (kind,))


class FactsTransform(AliasQueryTransform):
    def transform(self, text):
        record("facts_transform")
        return super().transform(text)


class KnowledgeTransform(AliasQueryTransform):
    def transform(self, text):
        record("knowledge_transform")
        return super().transform(text)


class Model:
    identity = {"kind": "query-semantic-process-model", "version": "1"}

    async def complete(self, messages, tools):
        assert "automobile servicing" in str(messages) and "automobile manual" in str(messages)
        record("model")
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

    async def semantic(config, context):
        factory, values = registry.prepare(
            "memory_store",
            {
                "adapter": "semantic-recall-async",
                "config": {
                    "backend": {"adapter": "sqlite"},
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
        )
        base = await factory(values, context)
        return SemanticMemoryStore(
            base.backend, base.embedding, FactsTransform({"car": "automobile"})
        )

    def knowledge(config, context):
        factory, values = registry.prepare(
            "knowledge", {"adapter": "sqlite-lexical", "config": {"namespace": "docs"}}
        )
        base = factory(values, context)
        return KnowledgeContext(
            QueryTransformRetriever(base.retriever, KnowledgeTransform({"car": "automobile"})),
            namespace="docs",
        )

    registry.register_async("memory_store", "fixture-semantic", semantic)
    registry.register("knowledge", "fixture-query", knowledge)
    profile = RuntimeProfile(
        "query-semantic-process",
        "1",
        {"default": {"adapter": "fixture"}},
        {
            "tools": {"adapter": "fixture"},
            "memory_store": {"adapter": "fixture-semantic"},
            "recall_planner": {"adapter": "task-text"},
            "knowledge": {"adapter": "fixture-query"},
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
            source = runtime.knowledge.retriever.retriever.store
            source.put(
                runtime.scope, "docs", Document("guide", "automobile manual"), expected_version=0
            )
        handle = runtime.submit(
            AgentSpec("answer", "Use evidence", tools=("change",)), "car", command_id="s"
        )
        snapshot = await runtime.drive(handle.run_id)
        assert snapshot.state != "failed", snapshot.error
        if mode == "waiting":
            assert snapshot.state == "waiting_approval", snapshot.error
        elif mode == "finish":
            pending = snapshot.pending[0]
            args = (handle.run_id, pending["action_id"], pending["digest"])
            receipt = runtime.approve(*args, command_id="approve")
            assert runtime.approve(*args, command_id="approve") == receipt
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
        print(json.dumps({"state": runtime.status(handle.run_id).state}))
    finally:
        await runtime.aclose()


asyncio.run(main())
