# Original execution-end observations at Update exhaustion

2026-10-16 · P3-3 necessary recovery only, based on `10c540e`.
The basic SDK, dev99 and dev113 stay frozen. User approval permits independent
P3-3 work; P3-2/S2's original 360-second failure remains deferred/open.
P3-4/5/A are not unlocked.

## Reproduction and bounded repair

An actual Tool has committed one SQLite business write and retains its physical
thread. After its original Run accepts exactly 2,000 distinct SDK Updates, the
original cancellation receipt still correctly reports that remote stop is not
confirmed. Releasing the real thread cannot record its first end ACK through the
old Update transport. The immutable prior wheel fails in **13.439 seconds**;
its original end obligation and owned cleanup evidence are retained. An earlier
1.126-second fixture error omitted the durable effect journal and is not product
failure evidence.

The new `temporal_execution_end_transport` uses the original Run's `execution_ended`
Signal and optional `status` observation Query for four fixed handlers only:
`tool_execution_ended`, `context_execution_ended`, `session_execution_ended`, and
public `deployment_call_ended`. The Signal invokes the complete dynamically
selected handler, including Parent wake/retirement and Session retry rules. It
introduces no grant, admission, business-effect adoption or second execution
state machine. Original stored end facts, Action/effect ACK and retirement remain
independent.

The envelope binds full Scope, complete original proof/digest, namespace, original
SDK first/current/original epoch, fixed operation and bounded observation identity.
Sixty-four observation entries never evict original grants, end facts or business
identities. These four existing handlers complete without suspending; repeated
observation IDs are deduplicated, while a fresh observation runs the original
handler again. Query/delivery is not acceptance. The client pins ports and epoch,
requires the strict per-handler ACK, and waits at most 30 seconds. Timeout,
caller cancellation, eviction or Signal uncertainty never authorize fallback or
clear the original obligation.

Session I/O retains its original four-field end proof, which has no epoch field.
The callback separately captures the actual SDK Activity epoch and namespace
before the Activity can finish, verifies the original request digest and Session
namespace UUID where applicable, and requires the original typed ACK. End evidence
is not reauthorized as a new dispatch. Private deployment1 retains its original
Update transport.

## Compatibility and replacement safety

The optional observation probe preserves the existing status shape for ordinary
queries. Only an exact legacy snapshot, original SDK type/first epoch/namespace,
and second pinned snapshot permit the original fixed end Update ID. Generic errors
or unknown shapes never authorize fallback; once a Signal is sent there is no
fallback. Immutable old Workers keep their own Update limits.

Selected deployment/native/composition implementation closures include the new
module, fixed operation set and Workflow Signal. Their experimental fingerprints
change; old selected Histories require matching immutable Workers. Default Card,
ordinary publication and saved default History compatibility are checked
separately. The Coding observer's read-only wrapper explicitly rejects Signal;
the existing runtime replacement check also pins that method.

## Remaining actual blocker

The first current-source actual run is **2 passed, 1 failed / 24.462 seconds**.
Default Tool pressure and old Worker compatibility pass. In the public case the
Tool end and actual-call end Signals are delivered, the Tool's original end fact
is recorded and its Run is quiescent. A subsequent effect-ACK Activity's
`deployment_call_started` Update still hits the same 2,000-Update limit. Its body
never obtains admission; its uncertain begin obligation prevents the deployment
Owner from closing. The original assertion and `CloseIncomplete` remain retained.
Neither an end Signal nor Run quiescence is a whole-deployment retirement proof.

This batch does not turn begin/seal/retirement into a generic transport bus, grant
new work after capacity, classify an ambiguous begin as not-started, or clear its
Owner administratively. The next bounded investigation is positive original-History
resolution of that failed begin and the remaining lifecycle transport. Public
pressure acceptance, context/Session/native actual pressure, Session-coordinator,
Registry/History lifecycle and full P3-3 remain open. Source-only handler tests
cannot close those service gates.

## Final evidence

Final wheel: `dist/p3-execution-end-final-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`.
SHA256 `9cbea0c142741001ff445ec0179f50195ae1f41e03146a943b81f79c576169f7`. It is a bounded P3-3 repair candidate, not a
completed public-pressure or stage release.

- Final affected source regression, 120 modules: **2,340 passed / 6 skipped**,
  91.881 seconds (JUnit suite time). The same isolated installed regression:
  **2,340 passed / 6 skipped**, 94.443 seconds. Four skipped actual remote-context
  cases and two selected no-submit service probes were not run or accepted.
- All 434 product files match source, wheel and installed package. Copied tests
  stay unchanged. Default Card/ordinary publication equality and saved original/
  continued default History offline replay pass. All fourteen prior accepted
  artifact checksum sets remain unchanged; the earlier candidate wheel is kept
  separately without replacing it.
- Same final wheel actual suite: **2 passed / 1 failed, 24.730 seconds**. Default
  pressure passes (10.425-second testcase): exactly 2,000 original accepted and
  completed Updates, one committed write, original physical end and ACK, repeated
  original cancellation, Worker restart and both Run/Registry History replays.
  Genuine immutable `10c540e` Worker compatibility passes (2.309-second testcase):
  two original Tool calls/end Updates, two current-client re-observations using
  the original fixed Update ID, zero new end Signals and original History replay.
- Public pressure **fails** (11.272-second testcase). Tool end and both recorded
  actual-call ends are confirmed; all original ledger calls are stopped. Its
  later `ralf.temporal.evidence.v1` begin Updates fail at capacity and deployment
  Owner close returns `CloseIncomplete`. Both owned Histories are terminated only
  for test cleanup; this is not successful workflow retirement or Owner drainage.
  Original threads and Workers end, and failure evidence remains intact.
- Eight retained failed original Histories (old RED and public failures from
  source, first installed candidate and final installed candidate) replay offline.
  No service mutation is used to replace their failures. No external model,
  PostgreSQL or Docker configuration change occurs in this batch.

Development REDs remain: missing server module 16 failures, missing client module
one failure, and the read-only Signal replacement pin two failures/one pass.
The latter catches both before-read and during-await replacement, then passes
with the added existing source pin (41 related checks). Review also fixed pressure
fixture cleanup to aggregate each resource failure and attempt original History
termination even when export fails. Old SDK fixtures now positively identify
legacy transport and retain their complete ACK/epoch fault assertions; in
particular `describe` must not overwrite injected bad first epochs. A final
read-only review has no outstanding P1/P2 in the bounded end repair; it does not
reclassify the known public begin blocker.

Initial broad fixture failures (22), a subsequent sandbox-only UNIX socket set
(8 source and 8 installed), and both earlier actual 2-pass/1-failure suites are
retained, not described as all-green or summed with final counts. Final socket
checks ran with permission while real service/model environment stayed empty.
Full Ruff, 1,342-file format and Git whitespace checks pass.

Evidence roots under `/private/tmp/ralf-agent-`: `p3-execution-end-20261016`,
`p3-execution-end-red-20261016`, `p3-execution-end-red-v2-20261016`,
`p3-execution-end-service-probe-20261016`, `p3-execution-end-install-20261016`,
`p3-execution-end-live-20261016`, `p3-execution-end-final-install-20261016`, and
`p3-execution-end-final-live-20261016`. Focused client/pin records are under
`/private/tmp/ralf-execution-end-client-20261016`. Final `verification.json`,
`SHA256SUMS` and evidence hash inventory separate the passing subset and retained
public failure. This batch is locally committed only; no remote push.

Next batch is limited to the original failed evidence-Activity begin and its
positive no-start/closure evidence, estimated as one targeted investigation and
necessary repair/verification batch. No fixed time or stage completion is
promised before that evidence exists. Other lifecycle gates remain separately open.
