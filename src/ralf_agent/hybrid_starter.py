"""Installed offline hybrid application; indexing stays an explicit command."""


def hybrid_files(ingest_files):
    runtime = ingest_files["agent_app/runtime.py"]
    runtime = runtime.replace(
        "from ralf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry",
        "from ralf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry, HybridRetriever, HashEmbeddingProvider, SQLiteVectorIndex, VectorRetriever",
    )
    runtime = runtime.replace(
        "        self.knowledge_store = knowledge_store",
        '        self.vector_index = options.pop("vector_index")\n        self.knowledge_store = knowledge_store',
    )
    runtime = runtime.replace(
        "        self.knowledge_store.close()",
        "        self.vector_index.close()\n        self.knowledge_store.close()",
    )
    runtime = runtime.replace(
        "    knowledge_store = None", "    knowledge_store = None\n    vector_index = None"
    )
    runtime = runtime.replace(
        "        scope = Scope()",
        '        vector_index = SQLiteVectorIndex(store.path + ".vectors.sqlite", dimensions=128)\n        scope = Scope()',
    )
    runtime = runtime.replace(
        "            knowledge_store,\n",
        "            knowledge_store,\n            vector_index=vector_index,\n",
    )
    runtime = runtime.replace(
        'KnowledgeContext(LexicalRetriever(knowledge_store), namespace="runbooks")',
        'KnowledgeContext(HybridRetriever(knowledge_store, {"lexical":LexicalRetriever(knowledge_store), "vector":VectorRetriever(knowledge_store, vector_index, HashEmbeddingProvider())}), namespace="runbooks")',
    )
    runtime = runtime.replace(
        "        if knowledge_store is not None:\n            knowledge_store.close()",
        "        if vector_index is not None:\n            vector_index.close()\n        if knowledge_store is not None:\n            knowledge_store.close()",
    )
    runtime = runtime.replace(
        '    query = sub.add_parser("query")',
        '    index = sub.add_parser("index")\n    index.add_argument("--document-id", required=True)\n    query = sub.add_parser("query")',
    )
    runtime = runtime.replace(
        "        else:\n            with create_engine(args.db) as engine:",
        '        elif args.command == "index":\n            with create_engine(args.db) as engine:\n                asyncio.run(engine.knowledge.retriever.retrievers["vector"].index_document(Scope(), "runbooks", args.document_id))\n                print(json.dumps({"status":"index_call_completed", "document_id":args.document_id, "embedding":"offline-token-hash"}))\n        else:\n            with create_engine(args.db) as engine:',
    )
    return {
        **ingest_files,
        "agent_app/runtime.py": runtime,
        "README.md": """# My hybrid document Agent

Install the preview SDK and run from this directory. No model credentials or
external service are needed. The corpus starts empty; provide your own UTF-8
text/Markdown source (<=1MiB). Ingestion and vector indexing are explicit steps:

```shell
python -m agent_app ingest /absolute/path/runbook.md --document-id runbook --command-id ingest-first --expected-version 0
python -m agent_app index --document-id runbook
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

SQLite owns source documents and immutable knowledge_committed receipts;
.vectors.sqlite holds derived vectors from the offline HashEmbeddingProvider.
Parallel lexical/vector candidates are deduplicated and source-validated before
RRF ranking. The default ranker preserves order; copy the runtime to choose
TokenOverlapReranker or your structural sync/async ranker. Rerankers return only
existing candidate IDs. The offline Provider copies evidence and cites source
URI/document/version; grounded means evidence was present, not verified semantic
relevance or real AI answer quality. Hash vectors are a lexical baseline.

Repeat identical ingestion with the original command ID to recover its receipt;
updates require a new command ID and expected version. Then explicitly index
again. A failed/partial index call requires retry; knowledge_committed never
means all vectors are ready. Deletion, expiry and old versions are rejected by
authority reads even if stale vectors remain. No cross-service transaction.

```shell
python -m agent_app query --query 'pool timeout' --command-id queued --submit-only
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

Keep original configuration/code/databases for Run recovery. The SDK provides
OpenAIEmbeddingProvider for explicit compatible float HTTP endpoints; select
model/URL/dimensions/credentials yourself, without implicit paid calls. It uses
an async owned lifetime, so use abuild and the documented sqlite-hybrid-http or
postgres-qdrant-hybrid profiles when switching to HTTP. Do not reuse an existing
index for a different model/profile; create a new index and explicitly reindex.
The SDK hybrid-retrieval guide describes defaults, extension ports, budgets,
strict/degrade behavior and independently tracked embedding usage.
""",
    }
