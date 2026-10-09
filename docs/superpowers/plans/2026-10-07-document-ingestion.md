# Document Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline; one fresh final review. Prior continuation authorization covers D1; no extra approval/commit/publication.

**Goal:** Offline replaceable ingestion with atomic knowledge receipts and compatible defaults.
**Architecture:** Pure parser/chunker produce frozen prepared DTO; store owns atomic CAS/doc/chunk/receipt. Coordinator orchestrates bounded snapshots and fixed registrations, no execution authority.
**Tech Stack:** Python3.11+, existing SQLite/async psycopg, no new base dependency.
**Spec:** ../specs/2026-10-07-document-ingestion-design.md

## Global Constraints

- Existing httpx/jsonschema base dependencies and6extras.
- Preserve local-4/default manifests, `_make_chunks`, raw put behavior, original14starter dictionaries and native Temporal v1 History.
- Default1MiB source/parsedtext,4096chunks,4096receipts perScope/namespace.
- Parser/chunker pure synchronous; owned/borrowed storage lifecycle explicit, no hidden model/source fetch.
- Receipt request identity excludes first resolved pipeline; no external exactly-once claim.

## Review Focus

- Lazy/malformed/mutating custom parser/chunker cannot reach durable writes.
- Concurrent same command/different content cannot consume two document versions.
- Cancellation/reply loss after commit must preserve original receipt, not reparse/reingest.
- Partial chunk/term/receipt failure rolls back entire document mutation.
- Old defaults/native recovery remain compatible; explicit ingestion rejects legacy stores.

### Task1: Pure DTOs and parser/chunker contracts
Files ingestion_types.py/document_parsing.py/chunking.py; tests/test_document_ingestion.py.
Produces SourceDocument,ParsedDocument,ChunkSpan,PreparedIngestion,IngestionReceipt;
TextDocumentParser.parse(source);CharacterChunker.split(parsed);ParagraphChunker.split(parsed).
- [x] RED strict UTF8/metadata detachment, legacy literal slices/IDs, invalid coverage/offsets/empty/overlap and lazy custom completion. Expected missing feature.
- [x] Implement frozen JSON snapshots, pure defaults and preflight preparation; GREEN selected cases.

### Task2: Atomic store and coordinator
Files knowledge_ingestion.py/postgres_ingestion.py/ingestion.py; modify retrieval.py/postgres.py; tests_ingestion_storage/crash/postgres_ingestion.
Consumes Task1; produces IngestionCoordinator(store,parser=None,chunker=None).ingest(scope,namespace,source,command_id,expected_version,expires_at=None); structural storage methods.
- [x] RED replay after changed pipeline/delete/expiry, CAS, concurrent conflicts, transaction rollback, cancellation/lostreply/component drift and unsupportedstore preflight. Expected missing atomic ingestion.
- [x] Implement atomic backends/helper writes; no plugin I/O in transaction; GREEN real memory/SQLite/PG and subprocess crash tests.

### Task3: Installed starter and release
Files ingestion_starter.py; modify starter/CLI/__init__/metadata/docs/CI; tests_ingestion_starter.
Consumes Task2; produces15th ingest starter with explicit file ingest and offline grounded Agent query.
- [x] RED template unavailable, standalone user file→ingest→query/empty corpus/repeat/reopen. Expected missing template.
- [x] Implement default CLI/guide/extensions/dev18; original14templates unchanged.
- [x] GREEN actual wheel install/compatibility; fullsuite/one independent review/SDKbytes/optionalimports/cleanup. Real quality remainsnot_run.
