# Remote Composite Sessions Implementation Plan

> Apply executing-plans inline, TDD and one fresh final read-only review. User
> explicitly requests continuous implementation/local commits without interruptions.

**Goal:** H2b4b remote root conversations across existing Local composites.
**Architecture:** Original interpreter/team/planner proposes final result; original
Engine owns intent, receipt and success. Reuse receipt-v1, no network SQLite txn.
**Baseline:** e6a6de7/dev38. Own workspace only. Capture old wheel before SDK edits.
**Spec:** docs/superpowers/specs/2026-10-09-remote-composite-sessions.md

## Constraints/review focus

Defaults/schema1–5,294 exports,21 starter trees and dependencies stay stable. New
semantic6 rejects old reader. Inspect before append; exact result/source marker and
receipt must match original admission. No model/planner/child/tool replay on save
recovery; no terminal upgrade. Real workers retain leases; opaque raw aliases and
None/missing metadata refuse. No paid calls, secrets, push or routine approval stop.

### Task 1: Root remote admission and receipt publication

Files: new remote_composite_saves.py/test_remote_composite_sessions.py; modify
session_conversations/local_sessions/session_ports/sqlite_sessions/storage,
remote_session_saves/engine/workflow_runtime/workflow_parallel/orchestration.

- [ ] RED foreign data native/sequence-independent remote composite root admission.
- [ ] Marker5/schema6 optional atomic admission; fix root descriptor/address.
- [ ] Root immutable intent and workflow/orchestration source marker; shared exact
  receipt protocol; finish async outside transaction and early save-only resume.
- [ ] GREEN all kinds/namespace/history/busy/defaults; task-done before next task.

### Task 2: Fault recovery and async configuration

Files: test_remote_composite_recovery.py/test_remote_composite_services.py plus
runtime_builder factory registration and current remote-root docs/tests.

- [ ] RED lost-ack restart, failed/cancelled metadata omission, busy real descendants,
  mixed member data/approvals and root binding drift; no repeat business effects.
- [ ] Reuse existing session-resource async factory for conversation_resource;
  preserve owned cleanup and static defaults.
- [ ] GREEN required recovery/configuration/real local Redis or explicit PG skips;
  task-done records evidence.

### Task 3: Distribution/review/checkpoint

Files: dev39 version/current docs/checklist/public review.

- [ ] Actual old/new schema1–5 original recovery, schema6 old refusal/new recovery;
  installed SDK/source equality,294 exports/21 starters stable and hygiene.
- [ ] One fresh read-only reviewer, one Important/Critical TDD fix pass, no re-review;
  ledger every ruling/minor deferral.
- [ ] Full warnings-as-errors/install/service/lint/format/link/whitespace gates;
  verified local commit and continue the capability list.
