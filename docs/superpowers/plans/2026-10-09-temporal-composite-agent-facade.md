# Temporal Composite Agent Facade Implementation Plan

> Execute inline with superpowers:executing-plans and test-driven-development; one fresh final reviewer.

**Goal:** H2c2 stateless advanced Temporal definitions through Agent API.
**Architecture:** Existing parent History and pure rules; pinned bounded recursive observation of actual child controls.
**Spec:** docs/superpowers/specs/2026-10-09-temporal-composite-agent-facade.md
**Tech:** Python/asyncio and existing optional Temporal SDK.

## Global Constraints

Preserve dirty dev31–33 work and HEAD; no commits/push/paid calls or sibling private
workspace access. Continue approved architecture inline, record concrete rulings.
Capture SDK/actual dev33 wheel before mutations; preserve private evidence locally.

## Review Focus

Parent aggregated approvals must never target the root or duplicate actual children.
Child provenance/release/resource must be validated at every awaited boundary;
missing/malformed/cyclic/oversized trees must not hide unknown business effects.
Moved configuration/replayed commands, cancelled waits/RPCs and close must preserve
dev33 behavior. Server History, not this facade, owns propagation and settlement.
Exercise actual services as well as network-only doubles of real authorities.

### Task 1: Composite submission and original parent references

**Files:** temporal_agent_runtime.py, temporal_agent_fixture.py, test_temporal_agent_composites.py, existing native rejection test.
**Interfaces:** Same Agent API; capabilities reflect registered orchestration; _info accepts original native/parent diagnostics.

- Write RED tests for graph/team/dynamic/nested submit→parent diagnostic/ref, moved configuration replay and original child approvals.
- Extend only fixture transport to use real TemporalParentState selection/delegation/observation; no alternate production authority.
- Implement subset gates and validated parent diagnostics; update old unsupported tests to lack-of-registration rejection.
- Verify focused facade/state/Local suites; Expected: pass; task-done records the run.

### Task 2: Bounded pinned child control discovery

**Files:** private temporal_agent_controls.py if useful; composite and failure tests.
**Interfaces:** pending returns actual child RunRef; controls via aattach(ref); root cancel/resume retain server authority.

- RED identity/release/started/missing/cycle/size/resource drift, nested unknown effect discovery, observation cancellation and root cancellation tests.
- Implement one pinned traversal; ignore aggregated parent pending, validate child evidence, enforce finite bounds and await checks.
- Verify new and existing lifecycle/control tests with warnings-as-errors; Expected: pass; task-done records the run.

### Task 3: Actual service, packaging, docs and final review

**Files:** actual composite facade service tests; guide/status/design/checklist/review; version dev34.
**Interfaces:** Actual persisted Service/Workers and replay; installed distribution same API and Local compatibility.

- Run actual offline-provider Graph/Team/Dynamic/nested approval/reconnect/cancel probes and original History replay. Record real result.
- Build/install outside checkout; verify actual dev33/new compatibility, package bytes/optional imports/dependencies/starter stability.
- Update support matrix and explicit remaining boundaries; do not imply complete H2/AgentScope parity.
- Dispatch one fresh most-capable read-only reviewer with captured delta, plan/spec/ledger. Important/Critical one RED→GREEN fix pass, no re-review.
- Final full pytest -Werror, Ruff/format/whitespace plus installed/actual checks; Expected: pass. Record gates and rulings; preserve local work/evidence.
