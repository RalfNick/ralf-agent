# Repeatable original scoped recovery at command capacity

2026-10-16 · P3-3 necessary recovery repair. Basic SDK/dev99/dev113 remain frozen;
P3-2/S2's original360-second failure and all stage gates remain unchanged.

## Reproduced blocker and minimal repair

Default scoped SDK `drive` generated a new UUID each time. A full Registry refused
an original target's recovery. Simply reusing a command was insufficient for
Parent: its repeated recovery path only covered public deployments.

The original scoped Registry now supplies a pure stable drive-ID suggestion,
preserving conflicting original IDs through bounded deterministic alternatives.
At full normal capacity it protects one pure drive per original submit target,
with no additional arbitrary IDs. Normal records plus cancel/drive protection are
at most `3 * capacity`; no business identity is evicted. The suggestion is not
acceptance. All original reservation, Scope and target checks still apply.

Current SDK reuses that ID; exact positive legacy configuration retains old UUID
behavior. One definitive identity conflict allows one refreshed suggestion/retry;
unknown delivery, timeouts or cancellation do not switch transports. Repeated
Run Updates still consume History and distinct-Update traffic.

Default Parent repeats retry original session/memory evidence and child observation
under patch `ralf-scoped-parent-repeat-drive-v1`. Old Histories without the marker
replay the original behavior. Public behavior and private deployment1 stay as
delivered. Receipts, stop intent, seals and separate physical-end obligations are
preserved. No new backend, execution authority or native result bypass.

## Candidate and final package evidence

Successful capacity candidate:
`dist/p3-drive-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`, SHA256
`c70ff487cdaeb05fec9f3ec0f6ca8c1bf1f811a7cd9fd78b4e2cc6ef541dd415`.
Its affected source and isolated installed checks each **1,169 passed**, zero
failures/errors/skips.430 product Python/JSON files matched that frozen candidate.

The final package adds only narrow SDK NOT_FOUND conversion in the hint Query:
`dist/p3-drive-errors-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`, SHA256
`9de619ccadc9981575cd98cba153e9c81a9439f51b8bbc56a0d71bfae868998d`.
Final53-module source and isolated installed checks each **1,171 passed**, zero
failures/errors/skips. All430 current product files match this wheel/installation.
Both packages preserve default Card/ordinary publication equality and offline
replay of saved original/continued default Histories. Earlier artifacts stay
immutable; selected experimental fingerprints still require matching old Workers.

Only `temporal_scoped_reservation.py` differs between the two installed packages.
AST comparison confirms the previous successful path is unchanged after removing
only the new SDK import/lookup and narrow Query exception wrapper. Thus the valid
Run service evidence below is explicitly reused for its unaffected scope; it is
not reported as a full matrix run against the final error-conversion package.

## Actual installed Service evidence

Capacity candidate, second independent attempt: **2 passed/133.942s**.

- Default scoped Session graph, **127.242s**: original root inspection fails twice;
  fill4096 normal reservations; first drive creates record4097 but inspection
  fails again; second drive reuses that command and recovers the original root
  aggregate. One model invocation, one root message write, one drive command,
  zero remaining reserved/unknown credits; original Turn releases. Patch marker
  present; root/child/Session/Registry Histories replay, all four owned Histories
  terminate and Worker/facade close. Activity3/overall180-second limits unchanged.
- Immutable basic SDK old Worker, **6.109s**: original Registry reserves via Update
  with zero Signals; actual original graph Parent receives three Updates for one
  drive command, plus two SDK drives retaining legacy fresh IDs. Original Parent,
  child and Registry Histories replay with current code and no new patch marker.
  Owned Histories, old process and facade close; original package path verified.

Final error-conversion package, independent actual empty-Scope case:
**1 passed/0.840s**. `drive("missing-run")` raises RALF `NotFound`; actual Registry
remains absent and facade closes. UNAVAILABLE same-instance propagation, closed
facade/invalid target zero-I/O rejection, and no write/fallback have offline
regressions. These counts are separate runs/packages, not one three-case matrix.
No external model or PostgreSQL call occurred; deterministic Provider invocations
are runtime evidence, not model quality.

## Failures and review

First actual capacity attempt: **1 failed/1 passed,42.913s**, retained. The failed
case never reached capacity filling: the test looked for `session_stages` inside
Parent diagnostics.workflow, where that field is not exposed. Original History
confirms root inspect `memory_backend_error`, no write dispatch, one child message
and no root message. All four original Histories were read-only confirmed
TERMINATED. Correct only the observer: use existing reconciliation flag plus the
original `session_stages` Query. No product, deadline or fault changed for retry.

Initial unit RED:5 failed/1 passed. Review additionally reproduced and fixed four
closed/invalid-target pre-I/O failures, and one missing-target failure with an
UNAVAILABLE passing control. The latter final fix converts only SDK NOT_FOUND;
other transport/timeout/cancel outcomes propagate unchanged. Review also corrected
actual-test cleanup: discover ABANDON descendants from original History even if
the body wait fails, close known resources independently, retain original plus
cleanup failures. A real HistoryEvent tree regression covers early discovery.
Final read-only review found no P1/P2; it did not run tests or services.

Evidence directories: `/private/tmp/ralf-agent-p3-drive-20261016/` (source/RED),
`/private/tmp/ralf-agent-p3-drive-install-20261016/` (capacity candidate install),
`/private/tmp/ralf-agent-p3-drive-live-20261016/` (original failure/Histories),
`/private/tmp/ralf-agent-p3-drive-live-v2-20261016/` (capacity/legacy results),
`/private/tmp/ralf-agent-p3-drive-errors-install-20261016/` (final installation),
`/private/tmp/ralf-agent-p3-drive-errors-live-20261016/` (actual missing target and
final `verification.json`/`evidence-sha256.json`). Pre-review wheel is separate and
not used for acceptance. Copied tests/installations are unchanged during each run.

## Remaining gates and next batch

Full P3-3 remains open. Default scoped ordinary unknown Tool manual evidence is
still refused at full capacity: its protection must prove the original SDK epoch,
Action and request, with an actual Action inventory bound; public-only dispatch
ledgers cannot be assumed for default runs. Native stop/grant/receipt already use
original Run Updates and need no generic Registry slot. Arbitrary native results
without the original fence/candidate must remain refused with unknown retained.
Other Run/native/Registry/Session Update and History lifecycle gates are also open;
existing actual2000 failure evidence is Registry-only. No Continue-as-New or
unlimited-history guarantee is supplied. P3-4/5/A stay locked; P3-2/S2 is not closed.
Next batch is a bounded review of original scoped Action evidence/cardinality,
then the smallest necessary manual-recovery repair and affected acceptance.
Estimated work: one focused design/reproduction batch before fixing its service
matrix; no defensible total completion percentage/date is inferred.
