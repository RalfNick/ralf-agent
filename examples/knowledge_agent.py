"""Offline retrieval with real local documents and explicit evidence citations.

Run with the SDK installed from the repository root:
    python -m examples.knowledge_agent --query '缓存连接失败怎么恢复'

The provider only copies retrieved evidence. It evaluates integration behavior,
not a real model's answer quality. No external model or embedding is called.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry
from ralf_agent.errors import RalfError
from ralf_agent.memory import MemoryRecallPolicy
from ralf_agent.retrieval import (
    Document,
    KnowledgeContext,
    KnowledgeVersionConflict,
    LexicalRetriever,
    SQLiteKnowledgeStore,
)

SEED_DOCUMENTS = (
    Document(
        "cache-recovery",
        "缓存连接失败恢复手册：首先检查缓存服务健康状态和网络连通性；"
        "确认连接地址与凭证；修复后重新验证缓存读写。没有审批时不要执行服务重启。",
        source_uri="local://runbooks/cache-recovery",
        metadata={"language": "zh", "kind": "runbook"},
    ),
    Document(
        "postgres-recovery",
        "Postgres connection refused recovery: confirm the database host and port, "
        "check the server's health and firewall rules, then verify a read-only connection. "
        "Do not restart the service without approval.",
        source_uri="local://runbooks/postgres-recovery",
        metadata={"language": "en", "kind": "runbook"},
    ),
    Document(
        "cafeteria-hours",
        "Office cafeteria: lunch starts at noon and vegetarian options are available.",
        source_uri="local://office/cafeteria-hours",
        metadata={"language": "en", "kind": "office"},
    ),
)


def seed_documents(store, scope):
    """Initial ingest uses CAS; starting the app never rewrites user revisions."""
    for document in SEED_DOCUMENTS:
        if store.get(scope, "runbooks", document.document_id) is not None:
            continue
        try:
            store.put(scope, "runbooks", document, expected_version=0)
        except KnowledgeVersionConflict:
            # Respect all prior versions, including retired/expired documents.
            # A concurrent initializer may also have won the create-only CAS.
            pass


class EvidenceProvider:
    identity = {"kind": "offline-evidence-copy", "version": "1"}

    async def complete(self, messages, tools):
        references = []
        for message in messages:
            content = message.get("content")
            if not isinstance(content, str) or not content.startswith("Reference memory;"):
                continue
            # This fixture reads the default ContextAssembler's JSON evidence.
            for reference in json.loads(content.partition("\n")[2]):
                if isinstance(reference, dict) and "_knowledge" in reference:
                    references.append(reference)
        citations = [
            {
                "document_id": reference["value"]["document_id"],
                "source_uri": reference["value"]["source_uri"],
                "version": reference["version"],
                "excerpt": reference["value"]["text"],
            }
            for reference in references
        ]
        return ModelResponse(
            output={
                "grounded": bool(citations),
                "answer": "\n\n".join(citation["excerpt"] for citation in citations)
                if citations
                else "No supporting evidence found / 没有找到相关证据，无法回答。",
                "citations": citations,
            },
            usage={"input_tokens": 0, "output_tokens": 0, "source": "offline-evidence-copy"},
        )


def agent_spec():
    return AgentSpec(
        "knowledge-agent",
        "Use only the provided knowledge evidence. Cite document ID, version and source URI. "
        "If no evidence supports the question, say that no supporting evidence was found.",
        output_schema={
            "type": "object",
            "properties": {
                "grounded": {"type": "boolean"},
                "answer": {"type": "string", "minLength": 1},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "document_id": {"type": "string", "minLength": 1},
                            "source_uri": {"type": "string", "minLength": 1},
                            "version": {"type": "integer", "minimum": 1},
                            "excerpt": {"type": "string", "minLength": 1},
                        },
                        "required": ["document_id", "source_uri", "version", "excerpt"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["grounded", "answer", "citations"],
            "additionalProperties": False,
            "allOf": [
                {
                    "if": {"properties": {"grounded": {"const": True}}},
                    "then": {"properties": {"citations": {"minItems": 1}}},
                    "else": {"properties": {"citations": {"maxItems": 0}}},
                }
            ],
        },
    )


class KnowledgeEngine(LocalEngine):
    """This application owns its injected knowledge connection."""

    def __init__(self, store, knowledge_store, **options):
        self.knowledge_store = knowledge_store
        super().__init__(store, **options)

    def close(self):
        # Refusing to close active operations also keeps their knowledge alive.
        super().close()
        self.knowledge_store.close()


def create_engine(db_path):
    store = SQLiteStore(db_path)
    knowledge_store = None
    try:
        # Anchor to the canonical execution path, not the current working directory.
        knowledge_store = SQLiteKnowledgeStore(store.path + ".knowledge.sqlite")
        scope = Scope()
        seed_documents(knowledge_store, scope)
        return KnowledgeEngine(
            store,
            knowledge_store,
            providers={"default": EvidenceProvider()},
            tools=ToolRegistry(),
            scope=scope,
            recall_policy=MemoryRecallPolicy(),
            knowledge=KnowledgeContext(LexicalRetriever(knowledge_store), namespace="runbooks"),
        )
    except BaseException:
        if knowledge_store is not None:
            knowledge_store.close()
        store.close()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    parser.add_argument("--query", default="缓存连接失败怎么恢复")
    parser.add_argument("--command-id")
    parser.add_argument("--submit-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        with create_engine(args.db) as engine:
            handle = engine.submit(
                agent_spec(),
                {"query": args.query},
                command_id=args.command_id
                or "knowledge:" + hashlib.sha256(args.query.encode()).hexdigest()[:20],
            )
            snapshot = (
                engine.status(handle.run_id)
                if args.submit_only
                else asyncio.run(engine.drive(handle.run_id))
            )
            print(
                json.dumps(
                    {
                        "run_id": snapshot.run_id,
                        "state": snapshot.state,
                        "pending": snapshot.pending,
                        "result": snapshot.result,
                        "submission": asdict(handle.receipt),
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
        return 0
    except RalfError as exc:
        print(
            json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    from examples.knowledge_agent import main as canonical_main

    raise SystemExit(canonical_main())
