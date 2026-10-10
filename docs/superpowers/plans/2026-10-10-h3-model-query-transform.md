# H3 Model Query Transformation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline under user's continuous implementation authorization; one fresh whole-increment review.

**Goal:** opt-in replaceable model-backed query transform with configuration and original recovery.
**Architecture:** borrow existing ModelProvider through QueryTransform; original stores/Run/History remain authorities. Built providers are resolved by original factories.
**Tech Stack:** existing Python/httpx/SQLite/pytest, no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-10-h3-model-query-transform.md

## Global Constraints

- Input4096 chars; model1..4 queries, max_queries<=3 if include_original; final<=4/16384chars; raw output32768chars; instructions4096chars; strict JSON and no tools/retries/default activation.
- Async ModelProvider only, borrowed/fixed objects/methods/identities; provider inputs detached and unmodified. No new state machine, billable ceiling or Temporal Facts.
- Old eight declarations and absent-option identities unchanged; alias errors before DB; only native known query-capable configs interpreted. .venv full regression, installed wheel outside checkout, local commit only.

## Review Focus

- Provider changing methods/identity or input DTOs during await must fail before retrieval dispatch.
- Oversized/refusal/tool/duplicate/lazy output must not degrade to original query or dispatch source reads.
- Nested data binding model aliases must preflight, while unrelated custom fields remain uninterpreted.
- Sharing a provider between business and query paths must preserve declared ownership/cancellation and no extra close.
- Recovery reuse must be of original accepted Action, not an implicit guarantee against paid preparation repeats.

### Task 1: SDK model query port

**Files:** src/ralf_agent/model_query.py; src/ralf_agent/__init__.py; tests/test_model_query.py.
**Interfaces:** ModelQueryTransform(provider, *, max_queries=2, include_original=True, instructions="").transform(text)->tuple[str,...]; pure model_query_options(config)->dict.

- [x] Write real LexicalRetriever consumer test: model proposes automobile for car; output is original car document then original automobile document. Add strict JSON/object/tool/no-tool/output limits, max_queries/include-original, input mutation, method/identity/owner drift, cancellation and async-only validation.
- [x] Run `.venv/bin/pytest -q tests/test_model_query.py`; Expected missing API failures. Implement fixed completed async invocation, bounded detached prompt and strict response validation.
- [x] Run same plus tests/test_query_transform.py tests/test_query_retrieval.py; Expected green.

### Task 2: named-provider assembly

**Files:** query_factories.py, knowledge_factories.py, semantic_memory_factories.py, runtime_builder.py, runtime_lifecycle.py; tests/test_model_query_configuration.py.
**Interfaces:** query_transform_config(declaration)->validated declaration; configured_query_transform(declaration=None, *, context=None); transformed_retriever(...,context=None); preflight_query_providers(profile)->None; BuildContext.providers maps existing validated instances.

- [x] Write configuration tests for same query provider object, unchanged original deterministic transforms, JSON/TOML, Knowledge/Facts scoped bindings, missing aliases top/nested before DB, unrelated custom config, borrowed lifetime and later-factory-failure cleanup.
- [x] Run target file; Expected unsupported model declaration failure. Implement pure validation separated from context resolution, known native adapter traversal and original ownership.
- [x] Run target plus test_semantic_configuration.py test_runtime_builder.py test_h3_combinations.py; Expected green.

### Task 3: HTTP, process and Temporal recovery

**Files:** tests/model_query_crash_fixture.py, tests/test_model_query_recovery.py; extend original Temporal Query snapshot test with model transform case.
**Interfaces:** original RuntimeBuilder/Run/Context; native OpenAIChatProvider calls localhost chat endpoint, original managed Embedding calls local embeddings.

- [x] Write localhost fixture/real HTTP consumer and os._exit77 after committed model_response_recorded. Restart waiting/approve+finish twice: same Action no query/model/embed replay, final two query preparations per data source, original business effect once.
- [x] Add model transform to original pure Temporal Knowledge/History acceptance; Expected no repeated query call after recorded context result.
- [x] Run `.venv/bin/pytest -q tests/test_model_query_recovery.py tests/test_query_semantic_temporal.py`; Expected green; independently compare original accepted counts.

### Task 4: dev50 acceptance, capability roadmap and local commit

**Files:** guide/remaining-work/implementation-status/harness/framework capabilities/README/CHANGELOG/version; architecture/reviews/2026-10-10-model-query-transform.md.
**Interfaces:** explicit model declaration examples, bounded preparation/quality/Temporal scope and recorded remaining roadmap.

- [x] Update capability documents; clearly distinguish delivered adapter from query policy/quality/global corpus index and H4/H5 work.
- [x] One fresh reviewer of complete diff/new files/spec/plan/focus; grade findings, one Important RED→GREEN fix pass.
- [x] Full `.venv/bin/pytest -q`, Ruff/format/whitespace, wheel/sdist, installed contracts, dev49↔50 old8 declarations/approval compatibility and old wheel rejection before DB; Expected green.
- [x] Commit locally after acceptance, record decisions/evidence and remove only this plan scratch. No push.
