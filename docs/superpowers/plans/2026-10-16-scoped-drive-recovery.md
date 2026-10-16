# Bounded original scoped mechanical recovery

P3-3 reproduced blocker: UUID SDK drives consume fresh command identities, so a
full scoped Registry refuses original-target recovery. Reusing an identity also
requires repeated Parent recovery without changing old History replay.

- [x] RED capacity and repeated-Parent tests; preserve old collision/Scope checks.
- [x] Original Registry supplies a pure bounded drive ID suggestion and one drive
  protection slot per original submit target. No new authority or backend.
- [x] SDK uses the suggested identity, with at most one conflict refresh; positively
  known legacy Workers retain UUID/Update behavior, no unknown-outcome fallback.
- [x] Repeatable default Parent recovery is gated by an original Temporal patch;
  public behavior stays as delivered and private deployment1 is unchanged.
- [x] Affected source/isolated install, ordinary defaults and saved History checks.
- [x] Actual4096 default Session graph original-save recovery after two inspection
  failures, one command/no repeated root write; old immutable Worker Parent replay.
- [x] Review, exact capability/evidence update and local commit only.

Scoped ordinary manual recovery and remaining Run/native/Registry Update lifecycle
remain required and open. No native result without candidate/fence is authorized.
No stage closes or dependent scope unlocks from this increment.

Exact packages, separate runs, preserved failures and remaining gates: [acceptance](../../../architecture/reviews/2026-10-16-temporal-scoped-drive.md). Local commit follows final artifact verification.
