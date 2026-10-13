# Managed automatic Facts index maintenance

This opt-in H3 increment refreshes a bounded Facts index before an ordinary
reader Agent. It supplies native SQLite/Hash defaults and configurable SDK,
JSON and TOML composition. It preserves the existing Local/Temporal execution
authorities, original Run/Action/Attempt/Session/Turn contracts and existing
`IndexedMemoryStore` implementation and identity. It does not certify semantic
quality, remote index maintenance or Temporal maintenance.

## Public composition

`GenerationIndexedMemoryStore` borrows the original source, embedding, vector
index and metadata catalog. A trusted fixed Scope and namespace select one
Facts corpus. `source_snapshot` observes current source identity;
`rebuild_for_snapshot(..., expected_snapshot, max_pages=64)` reuses the original
accepted-embedding, upsert and checkpoint algorithm. Ordinary recall independently
validates current source identity. `GenerationSourceChanged` is a typed refusal.

Build and active metadata keys include the source snapshot digest. A late old
generation may retain historical metadata but cannot replace the current source
generation. A per-instance ContextVar pins each maintenance invocation without
introducing mutable global selection or a second scheduler. Live component and
method checks compare object identity, never supplier-defined equality. All
constructor resources are borrowed; the index itself owns no close operation.

`FactIndexMaintenanceToolSource` offers `facts_index_ensure_current`. Host policy
registers an idempotent write with the reserved original effect key and its exact
reconciler. Caller arguments cannot select Scope, namespace, resources or limits.
The original ToolExecutionOwner tracks actual handlers and delegated threads.
Successful owner drain precedes closure of any borrowed databases.

Before index effects, a separate CAS journal fixes original Run/Action/key,
request, selected definition, source snapshot and bounds. Same-key recovery keeps
that snapshot; it never silently chooses newer source. Query/reconciliation
returns the exact historical completed receipt even after source updates. A
reader subsequently validates current source independently. Missing exact effect
evidence cannot be replaced with current index metadata.

Terminal outcomes are `ready`, `partial` (actual building state), and typed
`source_changed`. Generic CAS, budget and malformed-port failures retain pending
intent and their original exception; they do not become success or partial
receipts. Limits are per dispatch, inherited total records, and original Engine
execution credits; no cumulative per-effect page or monetary cap is claimed.
There is no hidden retry loop.

The default composition is an existing sequential Graph: maintenance ToolAction,
ready-only output Schema, then the reader Agent with explicit MemoryRecallPolicy.
Partial or source-changed maintenance stops before the reader. A later original
Action/Turn with a new effect key can continue bounded work. Automatic grounded
memory writes retain the existing managed stage and provenance validation.

## Assembly and recovery

Additive factory registration creates native SQLite source/vector/catalog and a
HashEmbeddingProvider, then owns the async ToolSource last so reverse teardown
drains it first. The paired memory component borrows the exact selected index.
Factory validation fixes scope, namespace, dimensions, resource identity and
bounds before allocation. Configuration helpers calculate pairing identities;
users do not paste opaque hashes. Weak BuildContext entries must not retain their
keys. The SDK borrowed owner follows the same drain-first contract.

First factories reject unsupported remote/custom ports and Temporal before I/O.
They use original RuntimeBuilder.abuild; synchronous assembly refuses before
opening backends. Read-only status/events/diagnostics use original ProfiledEngine
without discovery or seeding. Async application recovery resolves the recorded
profile with SQLiteRunReader and RuntimeCatalog, then uses original Runtime
references and continuation. A changed default alias cannot replace that profile.
Original synchronous ProfiledEngine CLI resume is not advertised for async tools.

Standalone and shared owner shutdown preserve CloseIncomplete/cancellation and
retain the original owner for same-loop retry. Do not close source databases while
an original handler is active. No implicit seed on restart or observation.

## Acceptance

Require native source updates, expiry/deletion refusal, bounded partial gating,
late old publication, competing same-generation CAS, historical receipts,
identity-safe mutation checks and actual owner/thread drain tests. Recover original
ToolAction/Session after process death around accepted embedding, vector commit,
page checkpoint, active publication and exact tool receipt. Wait/reap every owned
process; retain actual Run/Action/Attempt/budget and database evidence.

Verify the editable default app in installed core and SDK wheels across
SDK/JSON/TOML and owned/borrowed construction, original profile recovery and two
Session turns with grounded memory and current-source recall. Run regression,
Ruff/format, document links and byte provenance; preserve prior native index and
Run compatibility. One fresh whole-increment review gates acceptance. Commit
locally only, never push. Unsupported services, semantic quality and remaining
R01–R26/H3/M1 requirements stay open.
