# Per-Agent Artifact Bindings Implementation Plan

> Required execution: superpowers:executing-plans inline, no implementer agents.
> One fresh strongest read-only reviewer at the end; all findings/Declined regraded
> before one Important RED→GREEN fix pass, Minor deferred. Continuous local-only work.

**Goal:** Reuse original ArtifactStore and managed Context/Run/History phases while
allowing separate per-Agent target/namespace and disabled offload, with useful defaults.
**Spec:** docs/superpowers/specs/2026-10-12-artifact-bindings-design.md.
**Architecture:** borrowed scoped resource → pure Context prediction/derivation →
existing Local/Temporal auxiliary intents, actual execution owners and receipts.
**Baseline:**30e1746/dev83 accepted5280/418,core182/SDK149,actual32/32,287modules.

## Global constraints

- Required version and bounded ordinary resource/reference/namespace fields; no I/O in
  constructor/selector/Context prediction. Scope and physical resource fixed before/after
  I/O; missing original never silently falls back. JSON1MiB bound unchanged.
- Structural store port, memory/SQLite/file defaults and custom sync/async replacements;
  injection borrowed, declaration owned, reverse cleanup, no fake successful store.
- inherit byte-identical; explicit ref/disabled unsupported Context fails before Run.
  Preserve model summary/assembler/projection settings; cache weak and assembly-only.
- Verify old83 pure marker5 refusal before implementation; legacy1/2/3/4 and22templates
  unchanged. Product stays83 until required actual six-composition gates pass.
- One original Local Coordinator / Temporal History; no new Run state machine or hidden
  model/storage I/O in pure policy. Actual readers/writes own capacity until real end.
- Version84 only after actual subset evidence; final full/core/SDK/actual/old83/frozen
  provenance gates. Never build concurrently with full-suite wheel fixtures.
- Do not touch dev83 deferredM1/M2 during this new Artifact scope; record them separately.
  AllR01–R26/quality/enterprise/remote/binary/GC/cache remain open.

### Task 1: Scoped resource and pure Context port

**Files:** create binding_artifacts.py,artifact_binding_context.py; modify public exports;
add tests/test_artifact_bindings.py,test_artifact_binding_context.py.
**Interfaces:** ArtifactBindingResource/backend/version/namespace allowlist;
borrowed ArtifactView asyncput/get; pure artifact_binding_identity+bind_artifacts.

- [ ] Readspec/brief, verify old83 installed unsupported artifacts/marker5 rejects before
  any I/O, write bounded/raw/lazy/Scope/namespace/identity/method-drift and borrowed
  lifecycle tests BEFORE code. Expected missing public API RED.
- [ ] Implement ordinary resource identity/pins, class-bound raw reference validation,
  sync/async memory_call delegation and post-await target check. Preserve raw physical
  references. Shared target remains usable; no backend close/delete grants.
- [ ] Write pure prediction/realization equality, unchanged inherit, preserved summary/
  reference excerpts, disabled no-offload/no fake receipts and custom port tests RED.
  Implement new derived contexts without changing existing default class identities.
- [ ] Validate no allocation/I/O during binding, source mutations before/after await,
  actual delegated thread lifetime and completed returns. Focused original Artifact/
  data-context/summary regression GREEN; ledger and localcommit.

### Task 2: Local binding, weak phase cache and configuration

**Files:** modify binding_catalog.py,binding_runtime.py,binding_manifests.py,runtime_builder.py;
create artifact_binding_factories.py; tests/test_artifact_binding_execution.py,
test_artifact_binding_configuration.py; docs/artifact-bindings.md.
**Interfaces:** original artifacts role ref/disabled/namespace selector, local-bindings15;
artifacts/scoped-store nested artifact_store declarations; stable weak derived Context.

- [ ] Write six-member selective storage/namespace, grants unchanged, unavailable original,
  shared lifetime, original post-await _actual context and weak cache retention RED.
- [ ] Integrate pure selected effective Context and resolved records; preserve inherited
  defaults/manifests; memoize weakly only after validating origins. No per-Run state cache.
- [ ] Write sync/async declaration and no-resource-allocation preflight/owned rollback RED;
  reuse original artifact_store defaults/custom factories and resource ledger. Document
  SDK replacement and installed Profile defaults plus explicit disabled behavior.
- [ ] Execute actual SQLite/file six compositions, approval restart/lost Artifact receipt/
  completed result/actual-thread cancellation cases and original context regressions.
  Required real evidence before Task2complete/localcommit.

### Task 3: Temporal joint admission and original History recovery

**Files:** modify temporal_bindings.py,temporal_state.py,temporal_context.py,
temporal_managed_context.py and existing protocol validators as required;
tests/test_artifact_binding_temporal.py,test_artifact_binding_temporal_service.py.
**Interfaces:** recognized binding_protocol5/artifacts_binding_protocol1, metadata-only
pure prediction and selected runtime realization through existing Context stages/owners.

- [ ] Confirm actual old83 pure admission first; write joint/partial/unsupported markers,
  context/target mismatch, selected member scopes/namespace and legacy identities RED.
- [ ] Publish strict joint metadata and effective pure policy, realize matching borrowed
  Context view; keep public validators strict. Preserve original stage dispatch proof,
  intents/receipts/actual end/quiescence and accepted result adoption.
- [ ] Actual native/sequence/graph/Team/dynamic/nested SQLite/file binding with Worker
  restart/receipt-loss/replay; async replacement, cancellation/global-loop/actual reader
  end. No fake stop evidence or claim transferred by metadata alone.
- [ ] Original default/Sandbox/Workspace/Skills/context/Session protocol regressions and
  original new-profile pre-Activity refusal. Localcommit after real contracts pass.

### Task 4: Honest capability delivery and sole final review

**Files:** version/API/CI/status/progress/remaining/framework/harness/CHANGELOG and
architecture/reviews/2026-10-12-artifact-bindings.md.
**Interfaces:** fourteenth selectable role subset, fixed published release/evidence.

- [ ] Update actual supported scope and defaults/config/replaceable examples; version84
  only after Task3actual evidence. Keep all unverified broader capabilities explicitly open.
- [ ] Sole strongest fresh read-only whole-batch review; regrade ALL findings/ALL Declined
  BEFORE one unified Important test RED→GREEN fix pass; defer Minor, no secondreview.
- [ ] Freeze fixedsource; full suite, fresh installedcore/SDK/real service zero required
  skips, old83 two-way defaults and nativeSandbox/history/22templates, actual oldWorker
  new protocol refusal, exact source/wheel/sdist/docs/fixture/CIargv provenance.
- [ ] Stop only own service/resources and wait actual exit; finaldocument-only rebuild
  afterfull, localclosurecommit, archiveONLYownSDD. GoalR01–R26 remainsactive/no push.
