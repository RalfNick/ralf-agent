# D3a implementation plan

Spec: [context-artifacts](../specs/2026-10-07-context-artifacts.md). Execute inline under the existing user's authorization; preserve the dirty feature workspace. No commits, pushes or publication requested.

## Task 1: pure context extensions

Interfaces: new context_budget/context_summaries/context_pipeline modules implement ContextBuilder's existing assemble(history, references, max_chars) tuple. Existing default context.py is untouched. Write RED tests for all new public APIs and contracts, implement, then run context/engine/recall tests. Expected: typed, bounded, deterministic completed snapshots with original required task/latest complete group intact; defaults unchanged.

## Task 2: scoped artifact defaults

Interfaces: artifacts module provides sync/async ports and immutable JSON references; application tools explicitly invoke storage. Write RED tests, implement memory/SQLite stores and run them, including real process persistence, concurrency, capacity and crash evidence. Expected: detached finite JSON, strict Scope/backend/reference checks and atomic duplicate/capacity commits; no automatic deletion or hidden I/O.

## Task 3: usable assembly and installed application

Interfaces: add one context factory, SDK exports and seventeenth context template, keeping old factory/template identities. Write RED config/starter/engine recovery tests; implement and verify offline tool/artifact/context/submit-only/factory restart. Expected: no credentials/services/model calls required; lifecycle owned by application; old 16 templates identical.

## Task 4: review, integration and compatibility

One fresh read-only final reviewer, then one RED→GREEN pass for important findings. Use actual dev19 wheel baseline, full actual-service suite, installed-wheel and base-only subsets; compare package bytes/dependencies/native receipts and Temporal History. Update dev20 metadata, public guide/status/architecture/CI/evidence; rebuild final artifacts and stop all task-owned services. Expected: all gates green, unverified intelligent/enterprise/Temporal context boundaries clearly stated.

Review focus: retained/mutated plugin proposals and in-place method changes; lazy and bool/NaN counters; invalid tool-group shapes; optional summary capacity and provenance; UTF-8 size/expiry after reads; artifact tampering/foreign Scope and immutable TTL; transactional capacity under concurrent processes; retained native release identities and installed starter restart/cleanup.
