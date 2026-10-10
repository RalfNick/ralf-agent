# H3 Query Transformation and Semantic Recall Implementation Plan

> For agentic workers: use superpowers:executing-plans inline; user authorizes continuous local execution and final commit, no push.

**Goal:** replaceable query transform and bounded semantic Facts recall through existing authorities.
**Architecture:** composition wrappers of Retriever and Facts; source authority stays original storage and recovery stays original Run/History.
**Tech Stack:** existing embedding ports/httpx/SQLite/pytest, no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-10-h3-query-semantic-recall.md

## Global Constraints

- Original seven Profiles, default pure selectors, Hybrid/Knowledge classes, Engine/History and absent-option identities stay unchanged.
- Up to4 transformed queries,4096 chars/query,16384 total; max256 Facts candidates and262144 candidate chars; no hidden full read, cache, retry, paid/default model or ranked cursor.
- SDK resources borrowed; factories reuse owned ledger. Strict source/version/TTL/Scope/port/method/config validation across awaits.
- .venv for all source regressions, installed package outside checkout for package regressions; local commit only, no push/credentials/remote-service claim.

## Review Focus

- Lazy/contextmanager transforms or sync ports yielding awaitables, candidate mutations and forged output must fail before downstream disclosure.
- Query fanout and embedding count×dimensions, input UTF-8, original item/character limits remain bounded across multiquery composition.
- Source update/expiry or component/method/resource replacement during embedding/transformation must fail even if a subsequent validator returns success.
- Cancellation must complete request ownership; factories close only owned resources and failed assembly remains retryable via original ledger.
- Recovery must use original snapshots with no same-Action transform/embedding replay; old identities and approval snapshots remain valid across wheel versions.

### Task 1: query ports, defaults and bounded retrieval wrapper

**Files:** query_transform.py, query_retrieval.py, __init__.py; tests/test_query_transform.py and tests/test_query_retrieval.py.
**Interfaces:** QueryTransform/AsyncQueryTransform.transform(str)->tuple[str,...]; IdentityQueryTransform(), AliasQueryTransform(aliases,include_original=True); QueryTransformRetriever(retriever,transform=None,max_candidates=128,max_candidate_chars=64000).retrieve(scope,namespace,RetrievalQuery)->RetrievalResult, validate(...)->None.

- [x] Tests call `AliasQueryTransform({"car":"automobile"}).transform(" car   safety ")` and assert literal `("car safety","automobile safety")`; invalid/bool/oversized limits, Unicode, duplicate/empty/lazy/mutating proposals. Run `.venv/bin/pytest -q tests/test_query_transform.py tests/test_query_retrieval.py`, expected missing API failures.
- [x] Implement detached bounded default transforms, captured completed sync/async invocation and fixed identities; wrapper reads sequential query budgets, rejects duplicate ID body conflicts, calls original validate before/after subsequent awaits, returns original bounds.
- [x] Retrieve source document `automobile safety` from query `car safety` via aliases, with original docs/provenance preserved; strict child failure, expiry during second query, source/transform method drift and malformed completed results. Run same files plus tests/test_hybrid_retrieval.py; expected green.

### Task 2: bounded semantic Facts and task-aware planner

**Files:** semantic_memory.py, semantic_recall.py; tests/test_semantic_memory.py and tests/test_semantic_recall_engine.py; exports.
**Interfaces:** SemanticMemoryStore(backend,embedding,transform=None,max_candidates=256,max_candidate_chars=64000,min_score=-1).recall(scope,namespace,RecallQuery)->RecallPage; validate_facts and delegated CAS/inspection; TaskRecallPlanner(policy=None).plan(...,text)->MemoryRecallPolicy(max_pages=1).

- [x] Tests with native InMemoryMemory and deterministic fixture vectors `[1,0]` for `car`/`automobile` and `[0,1]` for unrelated facts: select original automobile Fact despite no lexical overlap, preserve stable versions/TTL, max_items/max_chars/scope. Source must see text=None and bounded scan; run target files, expected missing APIs.
- [x] Implement borrowed composed backend with derived fixed identity and genuine declared port invocation; validate full finite candidates before embedding, validate source before/after awaits, dimensions/norm/count/volume and actual readonly candidate text copies; rank stable cosine and bounded unchanged records, cursor unsupported. Task planner binds current task with fixed Session query.
- [x] Add source mutation/TTL/bool/NaN/wrong dimensions, duplicate keys, injected source/embedding/transform drift, all-query budgets, no candidates/no HTTP and cancellation tests; original Local Engine receives sourced Fact and validates before provider. Run target files plus tests/test_recall.py tests/test_memory.py tests/test_relevant_context.py; expected green.

### Task 3: explicit assembly, defaults and recovery

**Files:** query_factories.py, semantic_memory_factories.py, semantic_embedding.py, semantic_selection.py, relevant_context_factories.py, knowledge_factories.py, runtime_builder.py, recommended.py; tests/test_semantic_configuration.py, test_query_semantic_process.py, query_semantic_crash_fixture.py, test_query_semantic_temporal.py, test_query_semantic_integration.py, test_semantic_embedding.py.
**Interfaces:** optional query_transform type/config on existing Hybrid, sqlite-lexical-query; semantic-recall-async nested backend/embedding/transform and task-text planner; semantic-memory Profile and semantic-knowledge(...,query_transform=None).

- [x] Test invalid/sync/recursive declarations reject before DB, explicit owned async SQLite+HTTP embedding/transform assembly, JSON/TOML and cleanup on failure; original seven Profile declarations stay unchanged. Run tests/test_semantic_configuration.py, expected missing factory/Profile failures.
- [x] Add preflight factory parsers and async original-ledger ownership; support backend native sync/async without full reads, optionally combine transform in new knowledge paths only.
- [x] Localhost embeddings exercise native Agent and scoped Facts bindings in advanced workflows; process os._exit(77) after model_response_recorded, recovery skips same-Action query transform/embed, approval duplicate + finish yields single business effect. Temporal Context/History pure registration uses original ports; no Worker protocol change. Run four new test files plus tests/test_h3_combinations.py tests/test_rerank_configuration.py; expected green.

### Task 4: dev49 acceptance and local commit

**Files:** docs/query-and-semantic-recall.md, capability/architecture/status/remaining-work docs, CHANGELOG/README/version, architecture/reviews/2026-10-10-query-semantic-recall.md.
**Interfaces:** installed new combinations plus old exact identities/snapshots.

- [x] Document API/profile/bounded-candidate/raw storage/fee/quality/lifecycle/recovery boundaries and bump dev49; self-check all local links.
- [x] One fresh final reviewer of complete current diff/untracked/spec/plan/focus/ledger; regrade actual user impact and fix Important once with failing regressions.
- [x] Run full `.venv/bin/pytest -q`, Ruff/format/diff checks and wheel/sdist build. Install outside checkout, test new contracts, old dev48↔49 approval snapshots and accurate identities, old wheel refuses new declarations before storage. Expected green; preserve exact counts and skips.
- [x] Record all results/rulings/deferred minors, final local commit and own scratch cleanup; no push.
