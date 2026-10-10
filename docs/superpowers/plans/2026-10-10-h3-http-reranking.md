# H3 HTTP reranking implementation plan

> For agentic workers: use superpowers:executing-plans inline. User authorizes continuous development and final local commit, no push.

**Goal:** configurable HTTP semantic rerank adapter through existing AsyncReranker/HybridRetriever.
**Architecture:** explicit bounded transport/proposal, original knowledge authority validates source, original factory owns resources; no new Engine state machine.
**Tech:** existing httpx/SQLite/pytest; no dependencies or paid calls.
**Spec:** docs/superpowers/specs/2026-10-10-h3-http-reranking.md

## Global Constraints

- Old rerank strings, presets and retrieval implementations/identities stay fixed when new option absent.
- Explicit model/URL/auth declaration; one request, no retries/redirects/downloads/bootstrap.
- Exact original index mapping, immutable source; full finite/UTF-8 preflight before HTTP.
- SDK clients borrowed, factory resources owned; real request completion gates close.
- Local final commit only; no credentials/files/services from other plans.

## Review Focus

- Empty/partial/duplicate/out-of-range/bool results or nonsensical usage must fail and never become accepted evidence.
- Config/client/method drift during an HTTP await must not adopt an incompatible result or close a borrowed/replaced resource.
- All-task cancellation and concurrent HTTP requests must preserve actual ownership until completion; failed close must block new calls yet allow retry.
- Knowledge source update/expiry during rerank must block model disclosure, even under branch failure_policy=degrade.
- Default old strings/preset identities and original response snapshots recover across wheel versions; new configurations require their original adapter.

### Task 1: HTTP adapter and detached report

**Files:** create src/ralf_agent/rerank_http.py, rerank_response.py; export __init__.py; tests/test_rerank_http.py.
**Interfaces:** HTTPReranker.rerank(query,candidates,limit)->tuple[str,...]; rerank_result(...)->RerankResponse(ids,scores,usage); aclose().

- [x] Write tests: requested model/query/documents/top_n exact; response index1 before0 maps immutable source IDs, usage search_units1 preserved and detached; malformed count/index/score/model/usage, invalid input config and UTF-8; no request for empty candidates.
- [x] Run `.venv/bin/pytest -q tests/test_rerank_http.py`, expected missing API failures.
- [x] Implement immutable report, bounded one-request HTTP, validated subset, fixed registration/owned lazy client with loop affinity and retryable close.
- [x] Add cancel/concurrent/borrowed/failed-close/config and helper drift tests, then run same tests plus embedding and hybrid regressions; expected green.

### Task 2: explicit configuration and source/restore integration

**Files:** knowledge_factories.py, runtime_builder.py, recommended.py; tests/test_rerank_configuration.py, test_rerank_integration.py, rerank_crash_fixture.py, test_rerank_process.py.
**Interfaces:** nested reranker type/config, async knowledge adapter sqlite-hybrid-rerank-http; recommended_profile(...,reranker=None).

- [x] Test sync HTTP config rejection before DB; hash+HTTP async and semantic+HTTP owned assembly, old declarations unchanged, JSON/TOML, complete cleanup when later factory fails; run to observe missing adapter/config failures.
- [x] Add separate rerank_factories.py parser/construction; adapt hybrid_options optionally accepting selected reranker without changing default object identity; async factories own reranker. Register new async adapter, keep pure factory rejection. Add optional explicit semantic profile reranker option.
- [x] Real localhost HTTP fixture verifies evidence ordering through native Agent; source changed during HTTP await rejects before provider; cancelled rerank drains. Failed rerank not silently bypassed under degrade.
- [x] Process exit after model_response_recorded reuses captured knowledge/context (no same-Action rerank) and preserves approval/one effect; Temporal Activity/History port integration; run targeted regressions, expected green.

### Task 3: dev48 acceptance and final local commit

**Files:** docs/http-reranking.md, remaining-work.md, implementation-status.md, harness-runtime.md, framework-capabilities.md, README, CHANGELOG, architecture/reviews/2026-10-10-h3-http-reranking.md, pyproject.toml/__init__.py.
**Interfaces:** installed original and new configured combinations.

- [x] Record protocol primary source, user API/config, lifecycle/disclosure, billing and restart boundaries; bump dev48.
- [x] One fresh reviewer of all working-tree/untracked changes/spec/focus/ledger; fix Important via one RED/GREEN pass.
- [x] Whole `.venv/bin/pytest -q`, Ruff/format/git diff --check, build wheel/sdist; expected green with skips counted.
- [x] Install outside checkout; run new contracts/HTTP/process and unchanged old-combination identity/bidirectional approval snapshots against dev47; expected green.
- [x] Record exact results and all rulings/minors, local commit only, clean own scratch; no push.
