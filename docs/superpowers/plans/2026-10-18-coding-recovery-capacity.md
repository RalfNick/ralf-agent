# Original Coding recovery after Run Update exhaustion

P3-3 necessary recovery only. The fixed 437-file `70a9d59` wheel reproduced
one failure / 58.238s in the original native-stop ACK case. The original Coding
Run had exactly 2,000 accepted/completed Updates (2.593s fill, original 30s gate).
Its stop receipt hit Temporal's distinct-Update limit; no result candidate could
be adopted and owned close failed. One thread/start and turn/start remained;
Temporal DB, PG schema/volume, original History and failure records are retained.
Evidence: `/private/tmp/ralf-agent-p3-native-pressure-probe-20261018/`.

1. Test bounded original Coding recovery observations against complete existing
   `coding_receipt`, `admit_coding_stop` and `coding_owner_stopped` handlers.
   No new `admit_coding_phase` transport or business permission.
2. Add a fixed Signal/Query on original Coding Run History; preserve full original
   proof validation, wake behavior, callback validation and typed replies. Bind
   Scope, namespace, original epoch, Action/request/release/invocation identities.
   Bound cache/envelopes and reject unknown/malformed receipts without fallback.
3. Route only those three original callback operations; ordinary phase grants stay
   on original Update. Pin all new callable/source inventories. Historical
   selected publications keep matching SDK/Worker; defaults stay compatible.
4. Retain fixture fault injection at before-delivery and after-confirmed-adoption
   boundaries when transport changes. Repeat an already-accepted approval for the
   final pressure case, avoiding drive's retry side effects. Keep original outer
   240s, Activity/drive80s, Runner60s and hold30s deadlines. Add Worker restart,
   original receipt/History, actual stop, effect ACK and safe closure assertions.
5. Run affected regression, isolated install and actual Temporal/PG acceptance;
   preserve original failure and retained service data. Update capability docs
   and commit locally only. No full P3-3/P3-2 or native model quality claim.

## Execution decisions and evidence

- First actual drive-fill RED: 1 failed / 58.238s. Final original-approval-fill
  RED: 1 failed / 57.665s; both prove the same original stop Update limit. The
  intermediate reader missed raw approval Updates (1 failed / 125.599s); retained
  as fixture failure, not product proof.
- Boundary tests: 12 RED, then 12 GREEN. Client double signature correction:
  19 passed / 12 failed, then 31 passed. Wider integration: 96 passed.
- First129-module batch: 2,451 passed / 3 failed / 6 skipped / 89.819s. Fixed
  optional-SDK import coupling with fixed source/reader inventory, and adapted
  the routing double. Related35 passed; final129 modules: 2,454 passed / 6 skips /
  89.806s. Isolated same438-file wheel: 2,454 passed / 6 skips / 90.048s; defaults
  and original/continued default History compatibility pass.
- After regression, only service/retention fixtures are refined; unchanged product
  and executed-module coverage are reused, with the changed fixtures verified
  separately. Do not claim all test files were identical across those snapshots.
- Ruling: pressure exercises explicit cancellation while the original stop ACK
  is still held, with PG effect ACK independently blocked. This is the P3-3
  necessary-control scope. Normal four-boundary cases still require success.
  Full-capacity continuation encountered a new model's undispatched provider
  failure (31.721s), consistent with its unchanged Update admission; a late-cancel
  variant also failed (32.615s). These are retained, not accepted or used to
  expand new business-grant transport. No source/model quality conclusion follows.
- The correctly timed cancellation variant reached original Action completion,
  effect adoption, physical stop, root retirement and History replay; restart
  construction failed before old Worker shutdown (30.482s). Shutdown must precede
  replacement construction and retain the same captured client registration.
- Actual retention checks exposed an outdated test evidence reader: it saw only
  old Registry reserve/release Updates, while current transports use Signals.
  Support requires linking successful original submission/bind Update receipts
  and Root release Activity completion to exact Registry Signal requests and SDK
  root History. Signal alone or mutable state Query cannot authorize deletion.
  Missing evidence continues to retain failed service volumes and schemas.
- Final source helper/Session checks: 86 passed / 8.06s. Same isolated wheel
  revised-fixture checks: 86 passed / 9.255s. Source/install test differences are
  exactly service/retention-helper/retention-test files, recorded separately.
- Same438-file wheel actual normal native-stop plus pressure cancellation:
  2 passed / 56.464s. Original stop ACK survives Worker restart and exact proof
  resubmission; one thread/turn, PG adoption, physical end, quota retirement,
  original Histories and safe owned schema/service cleanup all pass. Prior18
  accepted artifact sets unchanged; failed-scenario data remains retained.
- Only the original single Coding Run recovery subgate closes. Coding parent
  pressure, full P3-3, P3-2/S2 and later gates remain open. Local commit only.

- Final review found a test-only cleanup P2: a failed conflicting reserve Update
  hid an unconfirmed submit Signal although the real Registry kept its bound
  root. Both record/bind reproductions failed correctly (2 RED); an earlier
  fixture-root indexing KeyError is excluded from RED evidence. Independent
  Signal-target retention fixes it. Source helper/Session 88 passed / 7.45s,
  installed 88 passed / 8.02s; the reviewer independently checked four refusal/
  positive paths and closed the finding. Same unchanged wheel actual pair
  repeated: 2 passed / 58.684s, strict safe cleanup and service shutdown passed.
  Prior v4 86-test/56.464s metadata remains separately preserved. Final Ruff
  condition wrapping is AST-identical and recorded as formatting-only delta.
