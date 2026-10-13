# dev92 Parent completion Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans within the authorized parallel development workflow. Each owner implements its exclusive files; root integrates shared contracts and performs one fresh whole-batch review.

**Goal:** Deliver configurable receipt-backed Plan／Team completion and a replaceable managed model verifier in Local and Temporal.

**Architecture:** Pure gate/stage DTOs propose decisions; original parent authorities freeze sources, drive stable verifier child Runs and adopt verdicts. Old default identities and accepted Runs retain their paths.

**Tech Stack:** Python3.11+, existing JSON Schema／HTTP／SQLite SDK and optional Temporal SDK; no new runtime dependency.

**Spec:** [Parent completion design](../specs/2026-10-13-parent-completion-design.md).

## Global Constraints

- Base dev91 `8ad6664`; independent tasks parallel, shared files have one writer; local commits only, no push.
- Pure prepare/interpret/gate; no model I/O in PlanVerifier or selection Activity; original Local/Temporal remain sole authorities.
- parent_completion_protocol=1; selected Local local-8/bound16; explicit Temporal binding9/temporal-3, old defaults unchanged.
- Source bytes default262144/max1048576; child/receipt bounds1..256; model stage single decision/tool-free; original held credits and real stop preserved.
- Full batch requires actual source/wheel recovery, old compatibility, exact provenance and evidence-specific documentation; fixtures are not real model quality.

## Review Focus

- Kept DAG nodes from old revisions may be legitimate, but unrelated old good receipts must not validate a new candidate; test owned current-plan lineage.
- Verifier inherited context/memory/completion bindings can add unexpected model calls; preflight and measured limits must prove one declared stage.
- Team capacity may allow the single verifier child without allowing duplicate business member execution; pin invalid repeated-member rejection.
- Source digest in a child key could hide drift and repeat costs; fixed original key must fail on source/policy change.
- Temporal binding9 must preserve binding8 Session/native-history/artifact/sandbox behavior; actual composed service recovery and old Worker zero-I/O refusal are required.

## Task 1 — Pure policy, rules and model stage (public-contract owner)

**Files:** Create `src/ralf_agent/parent_completion.py`, `parent_completion_rules.py`, `parent_verification_stage.py`, `parent_completion_protocol.py`; create matching `tests/test_parent_completion.py`, `test_parent_completion_rules.py`, `test_parent_verification_stage.py`.

**Interfaces:** Produce the exact Request/Verdict/Policy/Gate/Stage signatures and strict fields in the spec. `policy.identity` is fixed JSON; shared registration helpers expose detached identity/method digests and pure validation. Runtime helpers may request exact projection/validation functions via root; no owner edits another owner's file.

- [x] Write DTO/gate/stage tests for source limits, wrong task/receipt/result, foreign IDs, input/consumption proof, legal stop cases, lazy returns and drift. Run pytest and save valid RED assertions.
- [x] Implement strict DTOs/registration validation, pure Receipt/Inventory gates and ModelParentVerificationStage; no external I/O. Add exact structured inventory business default and a custom-stage replacement example test.
- [x] Run these tests plus original completion/planning contracts. Save GREEN and check pure source/digest/one-decision constraints.

## Task 2 — Local parent authority (Local owner)

**Files:** Create `src/ralf_agent/local_parent_completion.py`; modify `orchestration.py`, `dag_runtime.py`, `engine.py`, `binding_runtime.py`, `binding_manifests.py`; create `tests/test_local_parent_completion.py`, `tests/parent_completion_crash_fixture.py`, `tests/test_parent_completion_process_recovery.py`.

**Interfaces:** Consume Task1 DTO/Policy. `LocalEngine(...,parent_completion_policies=None)` registers fixed policies; Spec.completion_policy resolves selected policy. Local helper freezes source, controls stable `rN.verifier.verdict`, records received/adopted journal and returns continue/wait/result within existing transactions.

- [x] Write failing tests for parent fake success, pure accept/reject, flat/DAG/Team paths, one stable verifier child, original budget and drift; save RED before implementation.
- [x] Implement original-child evidence projection/role filtering, journal transitions, policy release, managed stage delegation and candidate final save. Correct current new-path verdict recovery before re-evaluation; preserve old paths.
- [x] Add Plan actual feedback/replan, Team capacity/replan rejection, insufficient budget, cancellation/late response, nested ownership/retained DAG node source and pure-context preflight cases.
- [x] Run real process exits after source/child/model receipt/proposal/adoption/save and assert one completed model call/effect, exact held/settled budget, original candidate and Session publication. Save GREEN/PIDs; no service/model provisioning.

## Task 3 — Temporal History authority (Temporal owner)

**Files:** Create `src/ralf_agent/temporal_parent_completion.py`, `temporal_parent_completion_state.py`; own `temporal_parent_state.py`, `temporal_parent_workflow.py`, `temporal_control_activities.py`, `temporal_activities.py`, `temporal_components.py`, `temporal_state.py`, `temporal_bindings.py`, `temporal_session_tree.py`, `temporal_session_model_history.py`, `temporal_decision_state.py` and required protocol validator files. Create `tests/test_temporal_parent_completion.py`, `tests/temporal_parent_completion_worker.py`, `tests/test_temporal_parent_completion_service.py`.

**Interfaces:** Consume Task1 protocol; `TemporalActivityRuntime(...,parent_completion_policies=None)` publishes explicit registry/protocol9. New pure Activity name `ralf.temporal.parent_completion.v1`; Workflow owns source/journal/stable verifier child/receipt/adoption; original control/selection maximum_attempts=1 and child stop remain.

- [x] Write valid RED state/release tests for stage role, source ownership, saved proposal/adoption, Team reject, budgets/cancel and protocol9+history2 compositions.
- [x] Implement pure registered Activity and patched new Workflow branch, original child control/registration, role/source journals and final gate; no Local DB execution authority.
- [x] Extend all protocol9 validators/Session/model history/source projection; preserve older release and History paths. Assert old release bytes, old Worker zero-Activity rejection and one stable new child.
- [x] Build real Worker fixtures for Plan/DAG/Team, business approval, verifier model receipt loss/adoption, cancel/unknown/real stop, parent final Session, native history and replay; root provisions one private service. Each Worker records PID and is reaped; recover exits gracefully0.

## Task 4 — Shared declarations and usable reference chains (root)

**Files:** Own `orchestration_types.py`, `planning.py`, `spec_codec.py`, `binding_paths.py`, `runtime_config.py`, `runtime_builder.py`, `temporal_profile.py`, `temporal_builder.py`, `__init__.py`; new `parent_completion_factories.py` and installed `parent_completion_starter.py`; recommended/profile/evaluation files and `tests/test_parent_completion_assembly.py`, `tests/test_parent_completion_starter.py`, `tests/test_parent_completion_evaluation.py`.

**Interfaces:** Add optional Spec.completion_policy and PlanningRequest.verification_feedback omitted by default. ComponentRegistry family parent_completion_policies/configured validates gate/stage declarations before owned factories and passes policies into original authority constructors. SDK exports Task1 types.

- [x] Write valid RED Spec roundtrip/default bytes, absent registration, malformed factory, provider/ref/pure-context, source/credits and sync/async/Temporal declaration zero-I/O tests.
- [x] Implement shared fields, codec/binding path hooks, factory/preflight and builder arguments. Root applies exact owner-requested shared patches sequentially; no overlapping edits.
- [x] Add installed SDK/TOML inventory Plan/Team defaults, explicit pure gate and independent model-stage/provider replacement; retain original recommended v1/v2 defaults. Extend evaluation with an explicit gate mode/independent current-lineage oracle; retain old reports/defaults.
- [x] Test Schema-valid fake success, correct total with wrong/missing receipt, legitimate needs_input/not_found and one bounded Plan replan with actual planner feedback. Fixtures remain model_quality=null.

## Task 5 — Integrated acceptance and local commit (root)

**Files:** `docs/parent-completion.md`, architecture review record, remaining-work/implementation-status/framework-capabilities/harness/M1/CHANGELOG/README; version/CI only after coherent integration. Private evidence `/private/tmp/ralf-agent-dev92-fqocahc1/evidence`.

- [x] Integrate three owners and inspect diff; one fresh independent whole-batch reviewer; findings get valid RED→coordinated repair→same-review targeted verification.
- [x] Freeze product, run full pytest/Ruff/format/Git whitespace; provision root-owned actual Temporal, run source and checkout-external installed recovery; keep invalid attempts/skips separate.
- [x] Build wheel/sdist, install independent core/SDK, run original guide/TOML/custom replacement, actual old91 default/Run/Worker compatibility and exact module bytes; rerun only when meaningful changes justify it.
- [x] Stop owned services and actually wait/reap, fill scope-specific evidence/docs and verify local links/no credentials; local commit with Git receipt, no push. Keep full R01–R26 active.
