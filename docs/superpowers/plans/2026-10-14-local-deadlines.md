# Local persistent deadlines implementation plan

> **For agentic workers:** Use the existing authorized parallel workflow; shared Engine integration is owned by the root implementer, disjoint storage and tests are delegated.

**Goal:** Implement persistent Local Run/approval deadlines across selected orchestration without releasing real work on expiry.

**Architecture:** Original Store commands and Run/Action facts remain authoritative. Engine-owned timers only invoke original deadline checkpoints; no independent state machine. Capacity admission remains the next part of phase-three batch 2.

**Spec:** `architecture/specs/local-deadline-contract.md`.

## Constraints and review focus

Omitted defaults retain bytes and Schema 1. Opt-in Schema 15 preserves native publications and sessions. Unknown effects and actual handler ownership survive expiry. Duplicate acceptance/approval preserves original receipts. Clock and Worker restart cannot refresh accepted times. Node frames use the original parent authority.

## Storage and policy

- [x] Add RED storage checks: default Schema 1, preparation outside transaction refused, atomic rollback, 14→15 publications/session preservation, readonly 15 and original dev114 Reader refusal.
- [x] Add optional `LocalDeadlineExecutionStore` with `local_deadline_version=1`, `prepare_local_deadlines()->None`. SQLite prepares native history then Session schema 15 within its original transaction; all five existing semantic gates include 15.
- [x] Add `LocalExecutionPolicy`, pure identity/field validation and `execution_policy/local-bounded` factory. Local Profile admits the component; explicit wrong factory values refuse rather than becoming omission.

## Engine and facade

- [x] Add RED tests for preserved accepted UTC times, submission dedupe across default changes, exact parent inheritance and malformed Store capability rejection.
- [x] Implement `local_deadlines` helpers for registration, manifest selection, atomic acceptance, approval time, checkpoint, owner timers and closed-reason preservation. Ordinary and orchestration Run creation call the same acceptance helper.
- [x] Wire `deadline_at` through Engine and Local Facade submission without adding absent request fields. First approval transition records original time; approve checks after receipt lookup and before readiness.
- [x] Deadline watchers retain shielded operation and real thread ownership. Drive starts/resumes the original watcher, expiry uses existing cancel/child propagation, callbacks never dispatch business. Close revokes only timers after actual work is safe to close.
- [x] Model/tool dispatch and final completion checkpoints reject new work after expiry; late errors retain deadline cause and original unknown accounting. Parallel node checkpoints project to the original Engine/Run.

## Recovery and delivery

- [x] Prove held async model and actual sync thread expiry retain ownership; only original completion releases reservations and closes Coordinator. Prove no next sequence/node/member dispatch and parent-child cancellation.
- [x] Use process barriers to record pending approval, terminate owner, resume with original Profile and verify unchanged absolute time, late-approval refusal and original command receipt.
- [x] Run affected source/installed tests; verify all product bytes, omitted default compatibility, Schema/Reader gates, retained failure records and owned process cleanup. Document actual scope, pending capacity/governance gates, then local commit only.
