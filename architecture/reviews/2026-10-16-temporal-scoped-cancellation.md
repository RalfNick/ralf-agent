# Default scoped cancellation at command capacity

2026-10-16 · P3-3 necessary cancellation repair. P3-2/S2, its original360-second
failure, and every other stage gate remain unchanged. No new backend or execution
authority. Basic SDK delivery `b871f61` and all earlier artifacts stay immutable.

## Trigger and minimal change

The default scoped Registry refused the first cancellation of a submitted target
once normal command capacity was exhausted. Its Update-only reservation path also
encountered the actual Service2000 distinct-Update limit before logical4096.

At capacity, the original Registry now permits one exact pure cancellation per
original submitted target. Global command identity/conflict checks remain first;
normal admission and arbitrary fresh commands keep their old limits. No original
record is evicted. Additional records are at most original submit targets, so total
records are bounded by twice normal capacity. This is a logical target allowance,
not a deployment-root proof or physical-stop certificate.

Only seven synchronous Run reservation kinds switch to bounded Signal/Query
observations on that same Registry, using its existing `commands.reserve` rules.
Original SDK epoch, namespace, Scope and complete request bind observations;
64 transport observations do not evict command identities. Delivery is not
acceptance. Unknown outcomes and waiter cancellation never trigger another write
transport. Exact positive legacy configuration detection, before any Signal,
retains an old Worker's Update contract and old limits. Sessions keep their
original Update path. Details: [capacity contract](../specs/temporal-recovery-capacity-contract.md#default-scoped-first-cancellation).

## Frozen candidate and checks

New candidate: `dist/p3-scoped-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`.
SHA256 `aee467b087ad28712d9211b2a89e75b2a72ddff31ad7385a1e9d1d3f28d4036c`.
All430 product Python/JSON files match source, wheel and isolated installation.
The seven earlier artifact directories retain their checksums. Selected source
fingerprints change; old selected Histories still need their matching immutable
Worker. No package version or ordinary default publication change is claimed.

Final51-module affected checks: source **1,131 passed/20.983s**, isolated installed
package **1,131 passed/21.701s**, zero failures/errors/skips. Default Card and
ordinary Temporal publication match the frozen basic SDK; original and continued
saved default Histories replay offline. No complete13k-suite rerun was needed.

The first expanded development run retained **1,116 passed/6 failed**: six old
SDK fakes lacked the real Client namespace or original Query/receipt contract.
Those fixtures were corrected; production validation was not weakened. A later
independent review found a real Session routing regression: the new Run-only
helper captured `session_open/submit/rebind`. Three real-Engine guard tests failed
before the routing fix and pass after it. The reviewer also found legacy-probe
cleanup could leave its Registry running after a failed assertion. Cleanup now
always checks/terminates the owned Registry, closes process and facade separately,
and preserves body plus cleanup failures. Final read-only review found no P1/P2;
it did not run services or tests.

## Actual installed Service acceptance

Existing local Temporal Service, default namespace, distinct owned task queues:
**2 passed/123.093s**, zero failures/errors/skips; no model or PostgreSQL calls.

- Current default scoped Worker: **118.406s**. Confirm4096 normal records, refuse
  fresh submission, accept original first cancellation as record4097, repeat exact
  receipt, refuse a different cancellation ID, verify cancelled/quiescent Run,
  zero Tool dispatch, replay original Run and Registry Histories. Owned Histories,
  Worker and facade close positively. Activity5/overall180-second limits unchanged.
- Original immutable basic SDK Worker: **4.164s**. Current installed facade detects
  its exact legacy configuration before writing, reserves by Update, sends zero
  Signals, and replays that actual legacy Registry History with current code.
  Original package path, owned Registry termination and Worker/facade closure are
  verified. No selected experimental historical compatibility is inferred.

Source and installed product plus copied tests stayed unchanged during acceptance.
Evidence: `/private/tmp/ralf-agent-p3-scoped-20261016/` (development failures/final
source), `/private/tmp/ralf-agent-p3-scoped-install-20261016/` (isolation/default
compatibility), `/private/tmp/ralf-agent-p3-scoped-live-20261016/` (actual cases,
Histories, cleanup, `verification.json`, `evidence-sha256.json`).

## Remaining gate and next step

This closes only the tested default scoped first-cancellation gap. Full P3-3
remains open: scoped drive/manual recovery, native necessary recovery, and other
Run/Registry Update/History lifecycle gates still need their own proof and actual
service evidence. No Continue-as-New or unlimited-history guarantee is delivered.
The zero-dispatch scoped case does not prove held-handler stop or unknown-effect
recovery. P3-4/5/A are not unlocked. Next action is one bounded review of the
remaining necessary recovery paths; implement only a reproduced blocker and
reuse unaffected frozen evidence. No new feature or performance scope is added.
