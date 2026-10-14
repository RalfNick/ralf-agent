# Temporal serial Agent graph Coding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extend original Temporal Coding to serial static Agent graphs with durable parent/child identity, independent physical stopping and owned closure recovery.

**Architecture:** Reuse existing parent and leaf Histories, the dev106 native loop and the original PG EffectJournal. New opt-in composition protocol fixes child execution identity and original root admission; neither Registry nor PG decides Run results or budgets.

**Tech Stack:** Existing Python 3.11–3.13 SDK, Temporal SDK/History, PostgreSQL and Codex containment; no new runtime dependencies.

**Spec:** `architecture/specs/temporal-coding-composition-contract.md` (same finite contract shared with parallel implementers).

## Global Constraints

- Explicit `coding_composition=True` requires `coding_execution=True`, exact bool; false/omitted preserve legacy bytes.
- temporal-3/binding protocol12/new composition marker; current11/default publication and replay preserved.
- Static Graph Agent-only, max_concurrency=1, one-level child Runs first; full R01–R26 remains open.
- Keep every106 pinned native/pure/glue callable body unchanged; independently publish new helpers.
- Preserve unknown effects and original leaf reservation/whole child cap after physical stop.
- Same-host original roots/Docker Unix resource, borrowed/owned lifecycle; no native authentication or new model calls.
- Existing user authorization is sustained parallel implementation and local commits only; no push.

## Review Focus

- Root accepted but not yet started or no native row: owned close persists original admission closure, late Root start never receives business permission.
- Child Start response lost or SDK reset: verify exact original parent/link/request/epoch before adopting any observed child.
- Physical leaf fence plus failed ancestor adoption: retry/cold close rescans original fenced records and Registry candidates, retains same ledger.
- Ambiguous ordinary/model/context owner: physical proof stays false, unknown credits remain held; empty Coding action list is insufficient.
- Group fingerprints do not transitively capture globals: new full Worker and pure History groups pin every helper without discovering IO during replay.

---

### Task 1: Publication, configuration and finite admission

**Files:** Create `src/ralf_agent/temporal_coding_composition_protocol.py`; modify `temporal_activities.py` constructor/publication only, `temporal_profile.py`, `temporal_builder.py`, `temporal_bindings.py`, unpinned `temporal_coding_protocol.validate_protocol`, joint allowlists, `temporal.py` root Registry metadata.

**Interfaces:** Consume the spec's pure/SDK helper names and fixed shapes. Produce `enabled(manifest)`, `validate_protocol(manifest)`, `validate_topology(request,manifest)` and selected publication; preserve actual106 implementation groups.

- [x] Write configuration tests: false/omitted bytes, dependency rejection before factory IO, strict booleans, missing/foreign marker.
- [x] Run focused tests; expected feature/API missing failures, preserve RED logs.
- [x] Implement finite effective leaf selection and protocol12 metadata, keep direct/parallel/nested/Team/Dynamic/patch refusals.
- [x] Run focused publication/selection/joint suites; expected pass and legacy106 bytes equal; defer commit to root integration.

### Task 2: Original History linkage and physical stopping

**Files:** Create `temporal_coding_composition_state.py`; modify `temporal_state.py`, `temporal_workflow.py`, `temporal_parent_state.py`, `temporal_parent_workflow.py`; add exact pure registry/link/epoch/stop tests.

**Interfaces:** Consume protocol enabled/topology and namespace admission response. Produce initialize/initialize_namespace, project_child_link, validate_child_link, pin_child_execution, request_parent_stop, refresh_parent_stop, physical_stop_view, adopt_child_stop, coding_requests plus new original Registry query/close/admission and Workflow Updates from spec.

- [x] Write pure tests for original link/full request/cap, reset/epoch rejection, first immutable terminal intent and no business during stopping.
- [x] Run to observe required missing features fail; preserve RED.
- [x] Implement typed physical evidence, exact child SDK handle pinning and selected root admission before context/scheduling.
- [x] Test unknown-cap retention after physical cancellation, failed ordinary/native owner proof, same-revision contradiction, no-start vs uncertain dispatch, legacy default transitions/replay metadata; expected pass.

### Task 3: SDK control and owned lifetime

**Files:** Create `temporal_coding_composition_control.py`; modify `temporal_control_activities.py`, `temporal_session_activities.py`, `temporal_assembly_lifecycle.py`; add only new `PostgresRunnerJournal.composition_resources` method and own control/lifecycle tests.

**Interfaces:** Consume exact pure views/Updates, Registry candidates/closed admission, namespace link, original SDK epoch; produce root_admission, control, validate_activity and close.

- [x] Write tests for actual info mismatch, original epoch-only control, failed closure after fenced PG row, no-native Root closure and retained shielded task.
- [x] Observe RED before implementations, no generic quarantine bypass.
- [x] Implement direct bounded query/Update shutdown and original resources rescan, preserving native106 callable bodies and financial state.
- [x] Run lifecycle/control/PG query tests; expected pass; unknown/unavailable proof retains resources for same-loop retry.

### Task 4: Integration, recovery and release

**Files:** Root owns actual service fixtures, new acceptance record, capability/usage docs, final version/package checks.

**Interfaces:** Consume all three tasks with the exact shared contract; resolve disagreements against spec before editing.

- [x] Integrate focused suites and compare actual installed106 default/current11 manifests and pinned function groups.
- [x] Run independent review and fix blocking findings with reproducing RED→GREEN tests.
- [x] Run actual Temporal/PG serial graphs, root/child/grant faults, original counters, zero-native closure and ancestor retry; fetch/replay original Histories.
- [x] Build frozen wheel and test outside checkout, actual old106 refusal and current11 resume, SDK/JSON/TOML identity.
- [x] Run risk-organized full regression only after source freeze; source/wheel/install/sdist bytes and docs/fixture equality; preserve failures and scoped evidence.
- [x] Stop/wait own services; sync actual capability status and acceptance record; prepare only local commit, no push. Exact container removal and final sdist equality are checked before committing.

## Execution and progress

The user already selected sustained parallel development and autonomous local delivery. Shared contract is fixed before three authors edit disjoint files. Root integrates/reviews and completes real/installed gates; source implementation starts after this plan. The full objective remains active after this finite gate, with parallel/direct/nested/Team/Dynamic Coding, native authentication/real quality and remaining R01–R26 work still tracked.
