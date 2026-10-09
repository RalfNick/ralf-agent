# dev39 — H2b4b remote composite root conversations

Baseline: e6a6de7/dev38. Implements the [plan](../../docs/superpowers/plans/2026-10-09-remote-composite-sessions.md)
and [delivery spec](../../docs/superpowers/specs/2026-10-09-remote-composite-sessions.md).
No new execution authority: Local admits Turns, accepts final proposals, records
required save evidence and commits the business Run outcome.

## Delivered

Graph (serial/parallel/direct transform), Team, Dynamic Plan/DAG and nested Local
Sessions can fix an explicit host receipt-v1 conversation resource. Root/member
storage and capability bindings remain separate. Existing session-resource
Profile factories wrap SQLite/Redis/PostgreSQL with host namespaces and original
async owned/borrowed lifecycle; colocated defaults remain unchanged.

The accepted final result, corresponding workflow/orchestration marker and exact
required save intent precede remote I/O. Final skipped decisions are accepted and
persisted atomically with that proposal. Original receipt-v1 inspection/CAS/append/
confirmation is bounded; there is no open SQLite transaction across network I/O.
Recovery completes the frozen result directly without another planner/verifier/
interpreter selection, child Run, model or business-tool dispatch.

Cancellation while recovering a frozen result reaches cancelled through the
original authority, including unavailable inspection. Terminal recovery queries
only, preserves failed/cancelled state, and retains unresolved saves/actual workers.
Journal/source-marker loss refuses capacity release. idle native↔composite rebind
keeps one remote address and original historical revisions. First accepted remote
composite activates semantic schema6 through optional admission marker5; old38
refuses it. Defaults/schema1–5 keep original identities and receipts.

## Independent review and one fix pass

Fresh read-only dev39_final_review found one Important and one Minor finding:

- Important: save-only recovery bypassed original cancellation finalization,
  leaving Run cancelling, Session busy and owned close incomplete. Fourteen RED
  cases cover seven kinds and available/unavailable inspection. Original authority
  now finalizes cancellation after the managed observation settles.
- Minor: final graph skipped decisions were lost when acknowledgement failed
  before the original final transaction. Two RED cases cover serial/parallel graphs.
  The accepted skipped list is journaled with the final proposal and projected
  once, preserving skipped state/events during save-only recovery.

Both fixed in one TDD pass. No re-review; no deferred Minor findings. Reviewer
focused gate49 passed with warnings as errors. Final focused gate80 passed includes
original Dynamic DAG conclusions. Preliminary full regression found a remaining
sync DAG-conclusion caller of the new async finalizer; adoption remains synchronous
inside its transaction and finalization is awaited outside it. No network service
or paid-model call was required for the review.

## Verification

- Final full warnings-as-errors regression:2570 passed,65 configured-service skips.
- Installed wheel contracts359 passed; actual installed import path asserted.
- Actual old38/new39 distributions:26 bidirectional schema1 native/bound/sequence/
  graph/parallel/team/plan/DAG/nested and schema2/3/4/5 Session recovery cases, plus
  all7 new schema6 composite kinds with old reader refusal/new unknown-save
  recovery:33 cases passed. Original RunRefs/releases, approval replay receipts
  and separate real SQLite business effect counts are checked.
- Real isolated Redis7 root kinds lost-ack/restart: source and installed probes
  passed. Source combined service/config/fault gate53 passed/7 PostgreSQL skips;
  installed services7 passed/7 PostgreSQL skips. PostgreSQL was not configured.
- All154 packaged SDK modules byte-equal to source;294 root exports and21 actual
  rendered starter trees unchanged against old38. Dependencies unchanged.
- Ruff/format/edited links/Git whitespace and distribution credential/config
  hygiene pass. No private workspaces/tests/config secrets are packaged.

## Rulings and costs

1. Reuse root conversation resource and receipt-v1; member bindings remain
   independent. Cost: no cross-authority Session lease or Temporal binding.
2. Opt-in schema6/admission marker5 separates new completion semantics. Cost:
   old38 cannot read databases that accepted remote composite capability; original
   schema1–5 remain supported and identity-compatible.
3. Persist final proposal and independent source marker before remote I/O, then
   save-only recovery. Cost: remote/local publication is not an atomic transaction;
   a saved observation message is not proof of business success.
4. User requested continuous implementation/local commits. Choices and reviewed
   fixes proceed inline. Cost: no routine approval/menu stop.
5. Preserve actual worker/descendant/unknown-effect occupancy; terminal absence of
   remote receipt is not proof of non-execution. Cost: unresolved evidence can hold
   a lane until trusted recovery/governance is supplied.
6. Existing duplicate control replay can request another managed drive. Tests
   isolate lost-ack recovery before asserting duplicate approval receipts; they
   do not redefine that existing wake behavior. Real business effects stay single.
7. Real Redis verified; absent PG/Temporal shared Session/quality remains explicit.
   No broad model quality, framework parity or enterprise readiness claim follows.

Continue the original [remaining capability list](../../docs/remaining-work.md):
Temporal bindings/shared Sessions, cross-authority leases, FIFO/input/deadline,
automatic Harness stages, recommended intelligence bundles and enterprise governance.
