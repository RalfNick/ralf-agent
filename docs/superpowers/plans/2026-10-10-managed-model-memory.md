# Managed Model Memory Implementation Plan

> Use executing-plans inline, TDD and one fresh final read-only reviewer. User's
> continuous development/local-commit authorization overrides routine approval menus.

**Goal:** H3a2 automatic, grounded model selection in the original Local memory stage.
**Architecture:** Pure ManagedModelMemoryPolicy declares selection; original Engine
journals selector evidence/credits and reuses existing CAS fact recovery.
**Tech Stack:** Python/asyncio, existing ModelRequest/evidence/SQLite authority.
**Spec:** docs/superpowers/specs/2026-10-10-managed-model-memory.md

## Global Constraints

Baseline0d17976/dev41. No paid model call, secrets, dependency change or remote push.
Preserve296 root exports/21 starters/default identities/schemas1–8. Own scratch only.
Local native/sequence only; no standalone selector child Run, hidden I/O or third authority.

## Review Focus

- Missing/contradictory dispatch proofs must prevent paid selector retry or free credits.
- Actual executing provider/policy/target drift cannot hide behind same-release replacements.
- Cancellation during validation and real in-flight work must preserve ownership/no new writes.
- Saved response/selection and empty-key recovery must not repeat model/CAS or close business early.
- Terminal/offline adoption and expired source/grants must distinguish old receipts from new work.

### Task 1: Pure model policy and semantic admission

Files: managed_model_memory.py; memory identity/admission, Engine manifest, Store/session/binding gate; tests/test_managed_model_memory.py.
Interfaces: ManagedModelMemoryPolicy(memory,provider='default',max_context_chars=32768,**kwargs), request(source)->ModelRequest, select(source,response)->list[FactProposal]; stage_identity(...,engine=None) pins provider only at admission.

- [x] RED pure grounded unique field selection, lazy/unsupported outputs and bounded input.
- [x] Implement pure model policy with hook identity and host alias; defaults unchanged.
- [x] RED native/sequence/schema9/per-Agent selection and unsupported/optional Store refusal.
- [x] Add semantic9 and pinned selector provider; GREEN focused policy/admission regressions.

Expected: no model I/O in pure policy; legacy rule/default identities unchanged.

### Task 2: Original selector evidence and recovery

Files: memory_selection.py; managed_memory_stage integration; tests/test_memory_selection.py.
Interfaces: source/intent/dispatch/response/keys markers inside original memory_stages; Store managed_stage_reservation; reuse CAS proposal adoption.

- [x] RED native actual selected field writes/empty selection/invalid/unknown/budget semantics.
- [x] Split grounded proposal adoption from pure rule selection; integrate guarded selector I/O.
- [x] RED dispatch/response/keys/proposal/CAS restart windows, contradictory state/accounting,
  provider/target drift, cancellation/timeout and terminal no-I/O adoption.
- [x] Implement evidence-only recovery and unknown controls; GREEN memory/context/Facade regression.

Expected: selected values remain host-grounded; no repeated business/paid selector/confirmed CAS.

### Task 3: Factory and release verification

Files: managed_memory_factories, config tests, dev42 docs/status/checklist/review/version.
Interfaces: sourced-memory(-async) mode=model/provider/max_context_chars through existing port.

- [x] RED JSON/TOML sync/async selected memory factory and Profile restart; implement factories.
- [x] Build/install, actual dev41/default/schema1–8 compatibility and schema9 refusal/recovery;
  verify modules/exports/21 generated starter trees/metadata/dependencies/links/hygiene.
- [x] One fresh final reviewer, one Important/Critical RED→GREEN pass; no re-review.
- [x] Frozen full warnings-as-errors, installed contracts and static gates; verified local commit.

Expected: complete current subset only; no real-quality/complete H3/AgentScope parity claim.
