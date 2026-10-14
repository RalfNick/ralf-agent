# Temporal Deployment Admission Implementation Plan

> **For agentic workers:** Use executing-plans for root integration and independent parallel workers with disjoint file ownership. User has authorized continuous parallel execution and local commits only.

**Goal:** Build the original CommandRegistry History's atomic deployment admission and SDK root binding, then continue its required full execution/release integration.

**Architecture:** An explicit mode of the existing Registry owns policy, scoped command identity and held root claims. Original Run/Parent History remains sole business authority. The initial slice keeps public activation rejected until dispatch, physical closure and release are ready.

**Tech Stack:** Python 3.12, Temporal SDK, pytest; actual local Temporal service for History evidence.

**Spec:** `architecture/specs/temporal-deployment-admission-contract.md`

## Global Constraints

- Default scoped Registry, Engine/Profile and execution-policy identities stay unchanged.
- Full phase-three batch 2 and R01–R26 remain open after the foundational slice.
- No model credentials, no model/network quality claims from deterministic fixtures, no remote push.
- Missing closure evidence never releases quota. No release API in the foundational slice.

## Review Focus

- Full deployment: duplicate receipts and controls must work; refused fresh work must leave no identity.
- Same command in different Scope: independent commands, aggregate bounds and no foreign locators.
- Manifest alias changes: first accepted release retained; binding rejects a changed original release.
- Namespace recreation or changed policy: cannot move registry or substitute its original namespace.
- Worker absence or uncertain startup: held claims remain, replay cannot refresh or lose acceptance.

### Task 1: Deterministic original Registry mode

**Files:** Create `src/ralf_agent/temporal_deployment_admission.py`, `tests/test_temporal_deployment_admission_state.py`; modify Registry class only in `src/ralf_agent/temporal_state.py`.

**Interfaces:** `registry_id(deployment_id) -> str`, `root_run_id(deployment_id, scope, command_id) -> str`; optional `TemporalCommandRegistryState(scope=None, admission_policy=None, namespace=None, capacity=4096)`; deployment `.reserve(request)`, `.bind_deployment_root(request)`, `.deployment_admission(request)` return detached dicts.

- [x] Write and observe failing tests for atomic limits, unchanged duplicate, scoped commands, policy/namespace/source pinning, controls while full and no record on refusal.
- [x] Implement exact validation before mutations, original held-unbound→held-bound identity and bounded detached observations; no release.
- [x] Run new state tests and existing Registry/Coding tests; record failures and final evidence.

### Task 2: Existing Workflow History integration

**Files:** Modify Registry class only in `src/ralf_agent/temporal_workflow.py`; create `tests/test_temporal_deployment_admission_workflow.py`.

- [x] First write tests for actual namespace/registry-ID init refusal, typed capacity errors, query privacy and SDK binding update.
- [x] Delegate deployment initialization to state, route exact binding and observation, refuse old composition routes in selected mode; default branch unchanged.
- [x] Run Workflow/Engine/Coding regressions and independent review of shared mode boundary.

### Task 3: Actual History, installation and evidence

**Files:** Create `tests/test_temporal_deployment_admission_service.py`, `architecture/reviews/2026-10-14-temporal-deployment-admission.md`; synchronize implementation status, remaining work, phase-three matrix, changelog and version.

- [x] Implement service cases for concurrent clients/Scopes, full refusal/duplicates/controls, immutable binding, Worker absence/restart and History replay.
- [x] Run actual original local Temporal service; retain unique IDs, results and terminal owned-service cleanup evidence. Report absent service evidence honestly.
- [x] Freeze changed product/test bytes; build wheel/sdist and run affected source/independent installed checks. Verify original default bytes and matching Worker rejection scope.
- [x] Independent review; necessary fixes with reproducing RED→GREEN tests, final affected checks and docs.
- [x] Local commit only after verification; report remaining full integration as required, not completed.

### Task 4: Required following integration (not part of first-slice completion)

- [ ] Add public SDK/Profile selection and full namespace-ID retrieval with preflight and lifecycle.
- [ ] Bind original Run/Parent root before all Activities; propagate root identity to supported descendants.
- [ ] Recover uncertain startup and original receipts; retain quota on unknown effects and live handlers.
- [ ] Add original-authority safe-release proof and diagnostics; verify real service recovery for selected compilation matrix.
- [ ] Only after all batch-2 gates pass, close batch 2 and continue hosted observation/service controls.
