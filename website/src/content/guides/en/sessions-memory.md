---
title: Sessions, memory & RAG
description: Separate conversation history, lasting facts and source documents. Bound model context and retain traceable evidence.
locale: en
slug: sessions-memory
sources: [docs/session-api.md, docs/recall-and-rag.md, docs/managed-memory.md, docs/document-ingestion.md, docs/hybrid-retrieval.md, docs/context-artifacts.md, docs/support-journey.md, docs/html-ingestion.md, docs/docx-ingestion.md, docs/pdf-ingestion.md]
---

## Four different kinds of data

| Component | What it retains | Typical use |
| --- | --- | --- |
| Session / Turn | Conversation identity, each turn's input, messages and original run reference | Follow-up questions and conversations across processes |
| Facts / long-term memory | Scoped, namespaced, versioned facts with provenance | Confirmed preferences, conventions and observations |
| Knowledge / RAG | Ingested documents, chunks, versions, sources and retrieval references | Find evidence in product docs, runbooks or policies |
| Context / Artifact | Messages and references actually used by a model request; separate large-content records | Bound requests and read large tool results on demand |

The execution store separately retains runs, actions, approvals, response snapshots and receipts. Removing conversation messages does not cancel a task. Replacing a knowledge store does not rewrite execution history.

## Continue a conversation

A session contains ordered turns, each accepted turn linked to its original run. Handle approval, [durable user input](/en/docs/user-input/) or recovery for the preceding turn, then confirm the session is idle before submitting another.

Save this complete, key-free example as `session_agent.py` in a new working directory. Unlike the `AgentSpec` declaration in [models and tools](/en/docs/models-tools/), this creates an `Agent` entry with `open_session` and an owned local runtime.

```python
import asyncio
from relf_agent import Agent, ModelResponse

class OfflineSupport:
    identity = {"kind": "website-session-fixture", "version": "1"}

    async def complete(self, messages, tools):
        found = any("123" in str(message.get("content", ""))
                    for message in messages)
        return ModelResponse(output={"order": "123" if found else None})

async def main():
    async with Agent(
        model=OfflineSupport(), name="support",
        instructions="Keep the customer's order in the conversation.",
        db_path=".ralf/session.sqlite",
    ) as agent:
        session = await agent.open_session("customer-42", command_id="open-42")
        first = await session.submit("My order is 123", command_id="turn-1")
        observed = await first.wait(wait_timeout=10)
        print(observed.snapshot.state, observed.snapshot.result)

        if observed.snapshot.state != "succeeded":
            print(await first.pending())
            return
        for _ in range(100):
            if not (await session.status()).busy:
                break
            await asyncio.sleep(0.01)
        else:
            print("Session still busy; inspect the original run:", first.ref.to_dict())
            return
        second = await session.run("What was the order?", command_id="turn-2")
        print(second.snapshot.state, second.snapshot.result)

asyncio.run(main())
```

Run `python session_agent.py`. Expect two `succeeded` results with `order: 123`. The offline provider looks for saved text; this verifies Session context and execution, not real-model recall quality. The bounded status check allows brief host cleanup; if it stays busy, inspect the original Run instead of submitting another turn. Repeating the unchanged file retrieves the same turns. For cross-process continuation and a real-model option, follow the [application tutorial](/en/docs/app-tutorial/); exact contracts are in [API & CLI reference](/en/docs/api-reference/).

A wait timeout ends the observation window, while the task may still be executing. Keep the original handle and wait again or explicitly control it. Do not submit another turn merely because waiting timed out. A terminal run can briefly leave the session busy while its host and outstanding obligations settle.

Reusing a command ID retrieves its original receipt, including a saved busy rejection. After resolving the blocker and confirming idle, use a new ID for a new submission attempt. Across processes, retain the original session and run references, configuration and data. Attaching or querying status does not resume execution.

## Run an offline knowledge assistant

With the SDK installed, choose a new directory:

```bash
relf init my-knowledge-agent --template rag
cd my-knowledge-agent
python -m agent_app --query 'postgres connection refused'
python -m agent_app --query 'quantum entanglement teleportation'
```

The first query matches documents actually ingested by the template. The second should return `grounded=false`, no references and a refusal. Inspect `document_id`, `version`, `source_uri` and excerpts to see the evidence behind the result.

The template uses SQLite lexical retrieval and an offline provider. It downloads no embeddings and makes no model-service calls. It demonstrates retrieval, references and execution, rather than measuring answer quality. A `local://...` source identifier is not a network request.

The same query uses a stable command ID by default, so repeating it retrieves the original run. To answer again after updating documents, supply a new `--command-id`. Recovering an old run does not replace its recorded response with new documents.

## Ingest your own documents

Use the independent `ingest` template to import UTF-8 Markdown:

```bash
relf init my-doc-agent --template ingest
cd my-doc-agent
python - <<'PY'
from pathlib import Path
Path("runbook.md").write_text(
    "Pool timeout: inspect the connection pool and service health.",
    encoding="utf-8",
)
PY
python -m agent_app ingest runbook.md --document-id runbook \
  --command-id ingest-first --expected-version 0
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

`expected_version=0` creates only when the document is absent. Updates use the current version to avoid overwriting concurrent changes. An identical ingestion command and source retrieve the original receipt; changed content uses a new command. Source digests, document versions, chunks and receipts are retained together.

Text and Markdown are the defaults. HTML, DOCX and text PDFs have dedicated parsers and restrictions; PDF needs an optional dependency. Image OCR and visual page understanding are outside this text pipeline. See [document ingestion (Chinese)](repo:docs/document-ingestion.md) and its format-specific guides.

## From lexical to semantic retrieval

| Retrieval | Useful starting point | Configuration to consider |
| --- | --- | --- |
| Lexical | Explicit terminology and small local runbooks | Query terms, chunks, source versions and result counts |
| Vector | Retrieval by semantic similarity | Explicit embeddings, dimensions, model identity and reindexing |
| Hybrid | Combine keyword and vector candidates | Branch bounds, fusion, total candidates and optional reranking |

Local vector implementations use linear search; they are not ANN indexes or managed vector databases. Offline hash embeddings are an integration baseline. Real embedding and reranking services need explicit credentials and cost management. Reindex after source changes rather than assuming old vectors represent new text. See [hybrid retrieval (Chinese)](repo:docs/hybrid-retrieval.md).

## Run ingest, index and hybrid retrieval

After installation, use another new directory. The corpus starts empty; this sequence creates the source, commits it, builds vectors and queries it:

```bash
relf init my-hybrid-agent --template hybrid
cd my-hybrid-agent
python - <<'TEXT'
from pathlib import Path
Path("runbook.md").write_text("Pool timeout: inspect the connection pool and service health.", encoding="utf-8")
TEXT
python -m agent_app ingest runbook.md --document-id runbook --command-id ingest-first --expected-version 0
python -m agent_app index --document-id runbook
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

Expect ingestion status `knowledge_committed`, index status `index_call_completed`, and a query result with `grounded=true` plus the `runbook` version/source. Edit `agent_app/runtime.py` to change retrieval composition. The default is HashEmbedding + lexical candidates + RRF, with preserved ranking order: hash vectors are a lexical integration baseline, not a semantic model. A failed index call does not undo ingestion; retry indexing explicitly. After document changes, ingest with the current expected version and a new command ID, index again, and query with a new ID.

### Verify a semantic embedding endpoint explicitly

This optional complete probe makes a real HTTP request and may incur provider fees. Provide the four environment variables below using your credential manager; choose a float `/embeddings` endpoint and the actual model dimensions. Save as `semantic_probe.py`, then run `python semantic_probe.py`:

```python
import asyncio
import os
from relf_agent import OpenAIEmbeddingProvider

async def main():
    async with OpenAIEmbeddingProvider(
        model=os.environ["RELF_EMBED_MODEL"],
        base_url=os.environ["RELF_EMBED_BASE_URL"],
        api_key=os.environ["RELF_EMBED_API_KEY"],
        dimensions=int(os.environ["RELF_EMBED_DIMENSIONS"]),
    ) as embedding:
        report = await embedding.embed_result(["connection pool exhausted"])
        print(len(report.vectors), len(report.vectors[0]), report.usage)

asyncio.run(main())
```

Expect one vector with the configured dimensions; missing usage remains unknown. This checks a narrow protocol response, not semantic retrieval quality. Use `send_dimensions=True` only if the selected model supports that request field. To compose this provider into RAG, select a **new** profile/index, use knowledge adapter `sqlite-hybrid-http`, and set `embedding.type="openai"` with `config.model`, `dimensions`, `base_url` and `api_key_env`. Use `await RuntimeBuilder(base_dir=...).abuild(profile, db_path)` and `await assembly.aclose()` for the async resource lifetime. The application must ingest sources and explicitly call the selected vector retriever's `index_document(scope, namespace, document_id)` before retrieval; building the profile does not index documents. Keep the original profile and index for old runs. Reindex all sources when switching models or dimensions, then evaluate retrieval and answer quality separately in [testing and evaluation](/en/docs/testing/).

## Lasting memory and bounded context

Start with facts explicitly written by a trusted host. To extract memory automatically, select a managed pipeline and configure allowed fields and source paths. Business success and memory completion have separate receipts; a successful business run alone does not establish that memory was saved. Model claims do not automatically become confirmed facts.

Recall can bound item counts, characters and candidate scans. Context assembly still chooses complete message groups, facts and references actually sent to the model. Large tool results can be explicitly stored as artifacts and read on demand. Character or estimated-token limits are not exact provider token or spending caps.

Retrieved sources are checked for version, digest and expiry; the application still validates generated answers and citations. Trusted scopes and resource bindings constrain reads, but do not independently provide authentication or enterprise document ACLs. Continue to [runtime and deployment](/en/docs/operations/) to manage component configuration and ownership.
