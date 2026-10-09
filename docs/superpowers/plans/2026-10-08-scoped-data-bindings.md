# H1d Local Facts and Knowledge Resource Bindings Implementation Plan

> Execute inline with superpowers:executing-plans, TDD and verification-before-completion. Continued implementation of the existing H1 contract is authorized; preserve all prior changes and private evidence locally, without Git commit/push/publication.

**Goal:** Select host-allowlisted Facts/Knowledge namespaces per Local Agent through immutable views and existing storage/retrieval ports, and measure bounded DeepSeek business and scoped-data usage.
**Architecture:** FactsBindingResource maps Agent logical recall namespaces to fixed physical namespaces and attaches source provenance. KnowledgeBindingResource uses fresh KnowledgeContext views of one borrowed retriever, retaining existing source hydration and validation. BindingCatalog fixes identities; Local remains the only execution authority. Explicit scoped data refs use local-bindings-4; unscoped/native/H1a/H1b/H1c release bytes stay unchanged.
**Spec:** architecture/specs/agent-capability-binding-contract.md (H1 resource identities and host scopes); architecture/viewpoints/harness-runtime.md; docs/remaining-work.md R01/R15/R17/R26. H2/other roles/Temporal bindings remain deferred.
**Tech Stack:** Existing sync/async MemoryStore/Recall/KnowledgeContext, SQLite and configured remote adapters; no new base dependencies.

## Global Constraints

- Namespace allowlists contain nonempty strings of at most128 characters and an explicit default; no source ACL/enterprise identity or semantic sharing policy is inferred.
- Raw Facts/Knowledge refs retain existing behavior and reject new selectors; only explicit resource wrappers authorize namespace selection. No shared-client mutation or ambient current_agent.
- Facts views are read-only recall/validation ports, not MemoryPipeline writers. Scoped references carry backend/Scope/namespace/value provenance; cross-view references/cursors refuse, legacy references are unchanged.
- Knowledge resource requires KnowledgeContext over the existing retriever interface; custom raw references/validate contexts remain usable without selectors. Host registration must not imply a namespace projection unsupported by its interface.
- Capture source identity and configuration before I/O; enforce Scope and selected identity before/after every await. Reject selected-view re-registration/default assembly before accepting a Run.
- Session refs mixed with scoped-data refs retain actual-address admission; scoped data alone cannot require the optional Session admission port.
- JSON/TOML wrappers preserve sync/async factory type, validate before client creation and delegate ownership to actual underlying resources. No hidden credential/model I/O or new runtime state machine.
- Preserve the current dirty feature checkout, current HEAD and baseline SDK. No commit, push, cleanup, reset or sibling private-workspace access.
- DeepSeek credential only in process memory via non-echo stdin, never source/config/reports. One fixed deepseek-flash/non-thinking/JSON configuration,1536 output tokens,45s per call; business8cases×2,max32calls/600s; scoped-data4cases,max4calls/240s. No retries, changed oracle or cherry-picked replacement result; authentication failure ends live tests without blocking SDK work.

## Review Focus

- Identical logical Agent names/key/version values in two namespaces must not cross-read, reuse cursors or validate foreign facts; provenance tampering/source expiry must refuse.
- Source backend/retriever/config drift during asynchronous recall or validation cannot confirm an old release, even if content/IDs coincide.
- Selected-view/invalid allowlist/nested wrapper configurations cannot bypass projection identity or close borrowed clients; constructor failure cleans only owned clients.
- Mixed Session refs and scoped-data refs retain kernel3 Session admission and claims; scoped-data-only refs work with legacy stores, and actual old wheel refuses new kernel4 before dispatch.
- Original submit/control receipts and original native/H1a/H1b/H1c releases recover from actual dev27 wheel, with original namespace/provider and one business effect.

### Task 1: Resource views and provenance

**Files:** new src/ralf_agent/binding_data.py; binding_catalog.py; tests/test_data_binding_resources.py.
**Interfaces:** FactsBindingResource(backend, *, namespaces=("default",), default_namespace="default"); KnowledgeBindingResource(context, same options); immutable scoped views; strict data_namespace_options and original-component identity helpers. Facts facts/recall/validate_facts are async read-only and preserve source cursors with bounded provenance accounting.

- [x] Write real memory/SQLite/retriever tests: allowed/refused selectors, immutable Scope, separate namespace values, foreign cursors/references, stale facts/documents, legacy recall fallback, async drift and selected-view refusal. Watch missing-wrapper/selector RED.
- [x] Implement explicit wrappers, pure selection and before/after guards; run resource tests and original catalog/recall/knowledge contracts GREEN.

### Task 2: Local routing, releases and factories

**Files:** binding_runtime.py; session_resources.py; binding_manifests.py if needed; runtime_builder.py; engine.py; __init__.py; pyproject.toml; tests/test_data_binding_execution.py; tests/test_data_binding_configuration.py; tests/test_data_binding_remote.py.
**Interfaces:** scoped ref detection → local-bindings-4; Session ref detection independent of kernel name; facts-resource(memory_store)/knowledge-resource(knowledge) nested declarations reuse original factories. Catalog capabilities list each actual namespace selector role.

- [x] Write native/sequence/parallel graph/team/dynamic/nested shared-client routing and source metadata tests; mixed Session admission/unsupported authority/replay/restart/drift; JSON/TOML/sync+async owned lifecycle/frozen config. Watch RED.
- [x] Implement routing and release fixed identities, strict selected-view default refusal and wrapper factories; preserve all original versions when wrappers are absent. Expose wrappers and dev28 metadata.
- [x] Verify existing binding/Session/composite crash contracts plus actual Redis Facts and configured-only PG Knowledge. Keep service skips explicit.

### Task 3: Package, live quality and final review

**Files:** docs/data-bindings.md; docs/live-model-quality-dev28.md; architecture/reviews/2026-10-08-scoped-data-bindings.md; CHANGELOG/README/support/remaining-work/progress; sanitized evals/results/deepseek-dev28.json if live tests run. Private runners/evidence under this plan workspace only.
**Interfaces:** actual installed SDK/runtime origins and original/new wheel refusal/recovery; fixed business dataset identity and explicit scored namespace facts/citation cases. No real secrets or raw business databases in distributables.

- [x] Build wheel/sdist and test installed binding/data contracts outside checkout. Real dev27 wheel old-release approval recovery plus old-runtime new scoped release refusal;9 legacy-style releases including H1c and a large schema retain receipts/Manifest/effects.
- [x] Authenticate provided DeepSeek key without logging it; if usable, run the single fixed bounded business8×2 and scoped-data4 suite, preserve all failures and sanitized scores/usage/latency/call limits. Do not modify baseline instructions/oracles for a failed trial.
- [x] Run full pytest, Ruff/format/whitespace, SDK/source/wheel/installed byte and packaged private-data checks. Exactly one fresh-context reviewer of this increment; one TDD fix pass for important findings, no rereview. Update actual capability/quality boundaries and final evidence.
