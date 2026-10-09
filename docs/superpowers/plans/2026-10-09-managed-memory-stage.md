# Managed Memory Stage Implementation Plan

Apply executing-plans inline, TDD and one fresh final read-only review. User
authorizes continuous development and verified local commits in this feature
checkout. No push, secrets or paid models.

**Spec:** docs/superpowers/specs/2026-10-09-managed-memory-stage.md
**Baseline:** 9fcbb84/dev39. Own workspace only; capture old wheel before SDK edits.
**Architecture:** Original Local authority; independent auxiliary journal; scoped
host writable resource and grounded synchronous policy. Defaults off.

### Task 1: Host policy, binding and admission

Interfaces: ManagedMemoryPolicy identity/propose/target; optional Store activation;
StepComponents.stage_policy; native/sequence manifests retain original defaults.

- [ ] RED tests for default-off, writable resource, grounded proposal, stage binding.
- [ ] Add bounded rule policy, host catalog ref/inherit/disabled, opt-in schema7.
- [ ] Reject unsupported advanced compositions atomically before accepting Run.
- [ ] GREEN policy/admission/binding tests; record task evidence.

Expected: focused tests pass; existing default release records unchanged.

### Task 2: Durable auxiliary execution and recovery

Interfaces: Task1 policy/identity and schema gate consumed by final-node hook;
separate persistent journal, stable source Action, budget/intent/receipt evidence.

- [ ] RED completion, sequence, lost ack/restart, terminal query-only, budget tests.
- [ ] After required Session save, propose/admit facts, reserve budget, CAS/validate,
  independently journal receipts; preserve unknown credits and auxiliary failures.
- [ ] Reject drift before/after await; maintain cancellation and lease ownership.
- [ ] Expose scope-authorized stage receipts; GREEN recovery and baseline suites.

Expected: recovery cannot repeat business/tool/model or confirmed memory writes.

### Task 3: Configuration, distribution and final review

Interfaces: Task1 policy as SDK/default registry factory; Task2 journal diagnostics;
semantic7 must be refused by captured dev39 wheel.

- [ ] RED JSON/TOML factory and installed-wheel recovery/default compatibility.
- [ ] Add default rule stage factory, docs, checklist and dev40 checkpoint.
- [ ] Validate real local Redis, PostgreSQL configured skips and full regression.
- [ ] One fresh final reviewer; one Important/Critical RED/GREEN fix pass;
  ledger minor findings/rulings without another reviewer.
- [ ] Build/install/lint/format/links/whitespace checks and verified local commit.

Expected: all applicable gates pass; remaining advanced/model/Temporal stages clear.
