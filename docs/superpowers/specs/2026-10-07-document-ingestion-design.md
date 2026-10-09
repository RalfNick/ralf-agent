# dev18 D1 document ingestion

Continues the approved intelligent-data-pipeline D1: replaceable pure parser and
chunker, atomic knowledge ingestion and durable scoped receipts with an offline
installed starter. Native runtime/manifest/old14templates remain unchanged. No
paid model, external source fetch, enterprise identity or semantic quality claim.

SourceDocument(document_id,data:bytes,media_type='text/plain',source_uri='',metadata={})
is immutable with detached JSON metadata. ParsedDocument contains Document and
source_sha256; TextDocumentParser supports strict UTF-8 text/plain/text/markdown,
keeps decoded content intact. Custom DocumentParser.parse(source) finishes synchronously.
CharacterChunker(size=1000,overlap=100) reproduces legacy slices/IDs; ParagraphChunker
is opt-in. Chunker.split(parsed) returns ordered bounded ChunkSpan(start,end,metadata)
with valid parsed-character offsets and complete nonwhitespace coverage. Metadata
per span is optional, stored under _chunk; collision rejected. Default metadata is
unchanged. Inputs/outputs, bounds and pinned methods/identity checked before write.

PreparedIngestion is an immutable JSON snapshot of request_digest (caller source,
expected_version,expiry; resolved parser/chunker excluded), document, spans and
resolved pipeline identity. Actual Chunk IDs remain digest([docid,version,start]).
IngestionReceipt stores scope,namespace,command_id,request_digest,backend_id, version,
source/parsed digests, pipeline, chunk_ids/locators. Result is knowledge_committed,
not indexed. Historical receipt replay survives doc update/delete/expiry; no reingest
or parser/config re-resolution. Changed caller content conflicts. Default limits:
1MiB source,1MiB parsedtext chars,4096chunks; per Scope/namespace4096receipts.

IngestionKnowledgeStore/AsyncIngestionKnowledgeStore structurally extend knowledge
ports with ingest(scope,namespace,prepared,command_id) and ingestion_receipt. One
atomic transaction validates CAS and writes document/chunks/lexical terms/receipt.
InMemory under RLock; SQLite transaction and additive table; PostgreSQL one document+
command scoped advisory-lock transaction, additive initialize table. Do not emulate
this contract with separate legacy put calls. Custom legacy stores fail preflight.
No parser/chunker/plugin code or network executes inside storage transaction.
Receipt replay precedes current component checks; new work pins component objects,
identity/method binding and storage backend/methods before/after awaited I/O.
Coordinator borrows store; user owns its lifecycle. Cancel/lost reply may leave a
committed receipt, recovered with the same command. No claim to stop arbitrary
remote writes on coroutine cancellation. Explicit vector indexing remains existing
VectorRetriever.index_document; D1 does not supply a cross-service transaction,
index-retry scheduler or hidden embeddings.

Deliver public SDK DTOs/ports/defaults/coordinator, real PG conformance, atomic crash
windows, a15th ingest starter, extension guide/status/dev18 metadata. Existing raw
put and default `_make_chunks` behavior/SQLiteSchema v1/nativeHistory unchanged.
Test from installed wheel; actual dev17 local receipts/templates/History remain
compatible. One independent final review; fix Important via RED→GREEN; full tests,
package/optional imports and cleanup. Old worktree changes preserved/no publication.
