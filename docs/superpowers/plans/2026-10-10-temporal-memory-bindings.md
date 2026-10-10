# Temporal memory and bindings implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Existing user authorization covers continuous implementation and local commit.

**Goal:** History-owned automatic grounded memory and scoped per-Agent bindings across Temporal actual Agent workflows.
**Architecture:** Add temporal-3 registration, deterministic binding projection, worker-only components and phase-separated memory evidence. Preserve temporal-1/2.
**Tech Stack:** Python, existing Temporal SDK, SQLite fixture memory and pytest; no new dependency.
**Spec:** docs/superpowers/specs/2026-10-10-temporal-memory-bindings.md

## Global Constraints

- No new authority, Local execution store, secrets or remote push.
- Borrowed component ownership; fixed release/path/Scope across awaits.
- Selector/CAS maximum_attempts=1, each one independent execution credit.
- Original wrappers/descriptors used; unsupported roles/selectors rejected explicitly.

## Review Focus

- Same named members at different nested paths must retain their individual write targets.
- Cancel accepted during read or model preparation must deny later dispatch.
- Target replacement with same backend identity must fail after awaits.
- CAS timeout plus a found fact must retain remote-stop uncertainty and parent allowance.
- Native temporal-1/2 release/history replay must remain unchanged.

### Task 1: Registered binding selection

**Files:** src/ralf_agent/temporal_bindings.py; temporal_activities.py, temporal_state.py, temporal.py, temporal_parent_state.py; tests/test_temporal_memory_bindings.py.
**Interfaces:** normalize_request(request), step_descriptor(request,node), effective_manifest(manifest,descriptor), selected_runtime(runtime,request); existing BindingCatalog resolve.

- [x] Add tests using AgentDefinition/BoundDefinition with provider/context/knowledge/tool_set/stage_policy version references, assert selected actual provider and child binding subtree; reject scope/unsupported role/selector.
- [x] Run `.venv/bin/pytest -q tests/test_temporal_memory_bindings.py`; expected failure: constructor does not accept binding_catalog/stage_policy.
- [x] Add explicit temporal-3 catalog records and worker object pins; normalize caller wrappers without changing unbound request; project child bindings in original parent delegate; route Activities through fixed selected worker views and pure state manifests.
- [x] Run `.venv/bin/pytest -q tests/test_temporal_memory_bindings.py tests/test_temporal_engine.py tests/test_temporal_composites.py tests/test_temporal_managed_context.py`; expected pass.

### Task 2: Original History memory phases

**Files:** src/ralf_agent/temporal_memory.py, temporal_memory_state.py; temporal_state.py, temporal_workflow.py, temporal_activities.py, temporal_managed_context.py; tests/test_temporal_memory_stages.py.
**Interfaces:** prepare(state,action,result), next_stage(state), accept_stage(state,id,response), execute(runtime,request,dispatch_guard); pure memory_stages query and explicit terminal drive recovery.

- [x] Add rule/model native/sequence tests, completion held until optional stage finishes, original source keys and stable fact identity, selector response adoption without repeat.
- [x] Run `.venv/bin/pytest -q tests/test_temporal_memory_stages.py`; expected unsupported/missing memory stage behavior.
- [x] Implement prepare/select/adopt/read/write/verify phases, History grants, original budget settlement/unknown retention and read-only terminal recovery; generic query/diagnostics/registered Activity.
- [x] Add cancellation during read/admission, same-ID backend/provider replacement, malformed selector/receipt, depleted budget and unknown child resource tests.
- [x] Run `.venv/bin/pytest -q tests/test_temporal_memory_stages.py tests/test_temporal_memory_bindings.py tests/test_temporal_managed_context.py tests/test_temporal_child_evidence_projection.py`; expected pass.

### Task 3: Service recovery and dev46 release

**Files:** tests/temporal_memory_worker.py, tests/test_temporal_memory_service.py; docs/temporal-memory-bindings.md, capability/implementation/remaining documents, architecture/reviews/2026-10-10-temporal-memory-bindings.md, README, CHANGELOG, package version.
**Interfaces:** consume registered phases and original binding subtrees; produce dev46 acceptance artifacts.

- [x] Add actual Worker process restart tests using independent SQLite audit, selector-before-adoption and CAS-before-verification gates, cancellation and parent/child replay. Start cached local Temporal CLI without downloads; test service through configured address.
- [x] Run `.venv/bin/pytest -q tests/test_temporal_memory_service.py` against actual local Service; expected pass, no model network calls.
- [x] Update capability matrix, registration/ownership examples, exact inspection and remote-stop limitations; bump dev46.
- [x] Run `.venv/bin/pytest -q`, Ruff check/format, whitespace check; expected green with skips counted.
- [x] Build wheel/sdist with installed build deps, run installed memory/binding/recovery contracts and protocol identity checks; expected pass.
- [x] One fresh read-only reviewer, Important fixes one RED→GREEN pass, then local commit and remove only this plan scratch; no push.
