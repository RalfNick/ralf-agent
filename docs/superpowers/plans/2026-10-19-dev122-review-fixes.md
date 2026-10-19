# dev122 review fixes implementation plan

> **For agentic workers:** Use superpowers:executing-plans in this session, then one independent review of the complete diff.

**Goal:** Repair the six confirmed dev121 review findings and protect existing combinations without adding business features.

**Architecture:** Validate approval decisions at the Local authority, preserve failed-host observations in the facade, and distinguish cursor pagination from the existing single-window semantic recall contract through optional structural metadata. Reuse common async-callable checks and the existing CI service environment.

**Tech Stack:** Python 3.11+, pytest, Ruff, setuptools/build, GitHub Actions.

**Spec:** User-approved project review; `docs/agent-api.md`, `docs/extending.md`, `docs/query-and-semantic-recall.md`, `docs/service-audit.md`.

## Global constraints

- No new agent, orchestration, backend, execution authority or dependency.
- Function-fingerprint qualification, S2 and their failure records stay deferred. Do not run those suites or prototypes.
- Preserve dev121 frozen artifacts. A new local installable candidate uses `0.1.0.dev122`.
- Keep Local/Temporal authority and existing legacy cursor-based recall semantics.
- No real model calls; service CI wiring is not a claim that remote tests ran locally.
- Do not push changes. Leave commit/publishing operations outside this batch.

## Review focus

- Invalid approval values never create an approval receipt or permit business writes; explicit booleans retain deduplication.
- Root and child default waits surface a failed deadline host after a transient store error; status remains read-only and explicit recovery still works.
- Scoped semantic recall retains more than one candidate and result, enforces provenance limits and namespaces, and does not silently become cursor pagination.
- Async callable Embedding implementations work in real indexing/retrieval; ordinary sync functions returning coroutines remain invalid.
- Oversized JSON-RPC IDs cannot produce responses exceeding the host limit or accept new business work; ordinary response IDs remain intact.

## Tasks

### Task 1: Local approval input contract

Files: `src/ralf_agent/engine.py`, `tests/test_local_approval_values.py`.

- [x] Add RED tests for invalid SDK/Facade approval values, no write/no durable receipt, then valid boolean recovery and deduplication.
- [x] Reject non-bool decisions before command acceptance; run the new tests and existing approval/control tests.

### Task 2: Failed-host wait contract

Files: `src/ralf_agent/agent_runtime.py`, `tests/test_local_deadline_facade.py`.

- [x] Add RED tests using transient transaction failure, without changing function bindings; cover original root and child waits.
- [x] Check host errors before returning nonterminal pause/control results; retain terminal observation and explicit resume.

### Task 3: Scoped semantic recall

Files: `src/ralf_agent/binding_data.py`, `src/ralf_agent/semantic_memory.py`, `src/ralf_agent/recall.py`, `tests/test_scoped_semantic_recall.py`.

- [x] Add RED tests for related second facts, multiple ranked results, provenance character bounds, foreign Scope and a structural single-window backend.
- [x] Declare optional `recall_mode="window"` for existing single-window recall; legacy backends default to cursor mode. Pin the selected mode and include nondefault mode in scoped resource identity.
- [x] Delegate a window once with the original query bounds, annotate/filter its results, and refuse source pagination or unsupported input cursors. Preserve the old cursor implementation.
- [x] Run scoped data, semantic recall and affected execution/configuration recovery tests.

### Task 4: Embedding and bounded HTTP errors

Files: `src/ralf_agent/vector.py`, `src/ralf_agent/a2a.py`, `tests/test_vector.py`, `tests/test_a2a.py`.

- [x] Add RED tests for real indexing/retrieval with async callable embeddings and bounded responses to oversized IDs.
- [x] Use shared async method validation; reject IDs that cannot fit the response budget before RPC effects and bound fallback responses.
- [x] Run vector, model/embedding and A2A/service/control regressions.

### Task 5: Existing CI gates

Files: `.github/workflows/ci.yml`.

- [x] Fix the two installed-test directory references in `remote-contracts`.
- [x] Add the already-existing P3-4 scope/audit and retention tests to source and installed service steps using the existing Temporal/PG setup.
- [x] Validate workflow structure, test paths and a clean temporary installed-test layout; do not run S2 or add a new service platform.

### Task 6: Verify and document the candidate

Files: version declarations, current docs and `architecture/reviews/2026-10-19-dev122-review-fixes.md`.

- [x] Record the six fixes, optional recall metadata, finite verification scope and unchanged deferred gates.
- [x] Run affected offline tests, Ruff, format and whitespace checks; request one independent review.
- [x] Build a uniquely versioned local wheel/sdist, install outside checkout without network, and run focused installed regressions plus the existing support journey.
- [x] Record exact results and artifact hashes without replacing or upgrading historical qualification evidence.
