"""Process fixture that audits retrieval and actual model calls independently."""

import argparse
import asyncio
import json
import sqlite3
from dataclasses import asdict

from relf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, ToolRegistry
from relf_agent.retrieval import (
    Document,
    KnowledgeContext,
    KnowledgeVersionConflict,
    LexicalRetriever,
    SQLiteKnowledgeStore,
)

from .receipt_runtime import ReceiptWindowStore


class AuditedKnowledge(KnowledgeContext):
    def __init__(self, retriever, audit_path):
        super().__init__(retriever, namespace="runbooks")
        self.audit_path = str(audit_path)

    async def references(self, scope, text):
        record(self.audit_path, "retrieval")
        return await super().references(scope, text)


def record(path, kind):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS calls(kind TEXT PRIMARY KEY, count INTEGER)")
        connection.execute(
            "INSERT INTO calls VALUES (?,1) ON CONFLICT(kind) DO UPDATE SET count=count+1", (kind,)
        )


class EvidenceProvider:
    identity = {"kind": "knowledge-process-fixture", "version": "1"}

    def __init__(self, audit_path):
        self.audit_path = str(audit_path)

    async def complete(self, messages, tools):
        record(self.audit_path, "model")
        content = next(
            message["content"]
            for message in messages
            if isinstance(message.get("content"), str)
            and message["content"].startswith("Reference memory;")
        )
        reference = json.loads(content.partition("\n")[2])[0]
        return ModelResponse(
            output={"answer": reference["value"]["text"], "version": reference["version"]}
        )


class KnowledgeEngine(LocalEngine):
    def __init__(self, store, knowledge_store, **kwargs):
        self.knowledge_store = knowledge_store
        super().__init__(store, **kwargs)

    def close(self):
        super().close()
        self.knowledge_store.close()


def create_engine(database, trigger=None):
    store = ReceiptWindowStore(database, trigger_event=trigger)
    knowledge_store = SQLiteKnowledgeStore(str(store.path) + ".knowledge.sqlite")
    try:
        try:
            knowledge_store.put(
                Scope(),
                "runbooks",
                Document(
                    "cache", "Cache timeout: inspect connection pool.", source_uri="fixture://cache"
                ),
                expected_version=0,
            )
        except KnowledgeVersionConflict:
            pass
        audit = str(store.path) + ".audit.sqlite"
        return KnowledgeEngine(
            store,
            knowledge_store,
            providers={"default": EvidenceProvider(audit)},
            tools=ToolRegistry(),
            knowledge=AuditedKnowledge(LexicalRetriever(knowledge_store), audit),
        )
    except BaseException:
        knowledge_store.close()
        store.close()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--run-id")
    parser.add_argument("--trigger")
    parser.add_argument("--delete-source", action="store_true")
    args = parser.parse_args()
    with create_engine(args.database, args.trigger) as engine:
        run_id = args.run_id
        if run_id is None:
            run_id = engine.submit(
                AgentSpec("knowledge", "Answer from source evidence", model_credits=2),
                "cache timeout",
                command_id="start",
            ).run_id
        if args.delete_source:
            engine.knowledge_store.delete(Scope(), "runbooks", "cache", expected_version=1)
        if args.trigger:
            print(json.dumps({"run_id": run_id}), flush=True)
        print(json.dumps(asdict(asyncio.run(engine.drive(run_id)))))


if __name__ == "__main__":
    from tests.knowledge_runtime import main as canonical_main

    canonical_main()
