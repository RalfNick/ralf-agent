# Original public deployment lifecycle at Update exhaustion

2026-10-16 · P3-3 necessary recovery, based on `dd543c8`.
Basic SDK/dev99/dev113 remain frozen. Independent P3-3 work is authorized;
P3-2/S2's original 360-second failure remains deferred/open. No later stage unlock.

## Original blocker and bounded repair

The prior immutable end-transport wheel preserves Tool/actual-call end evidence
at exactly 2,000 distinct original Run Updates, but the later evidence-ACK
Activity cannot register its actual call start. Its uncertain begin stays owned;
Run quiescence cannot prove deployment closure. Prior actual 2-pass/1-failure
runs and their `CloseIncomplete`/History evidence remain unchanged in the
[previous record](2026-10-16-temporal-execution-end-capacity.md).

`temporal_deployment_lifecycle_transport` carries only public deployment2/3/4
`deployment_call_started` and `deployment_seal` through original Run Signal/Query
observations. It invokes the complete existing Run/Parent handlers, including
Parent mechanical-begin wake rules, exclusive attempt/invocation, actual-call
ledger capacity, irreversible seal and all original closure/child checks. The
original release Activity still independently verifies the tree, full certificate,
namespace and post-seal readback before Registry retirement. Existing reducers,
four end endpoints, budget/effect adoption and execution authority are unchanged.

Full Scope, payload digest, fixed operation, namespace and original SDK
first/current/original epoch are pinned; envelopes are bounded at2MiB and64
observation entries. Cache eviction never deletes calls, end facts, seals or
business identities. A fresh observation invokes the full handler again. An
allowed begin may become refused after its actual end; a saved observation is
not permission to dispatch another business handler. Query/delivery,30-second
observer timeout/cancellation, eviction or unknown response do not prove no-start
or authorize Update fallback. No new grant is inferred from a capacity error.

Only exact legacy status, original SDK identity and second epoch-pinned status
permit the original fixed begin/seal Update ID. Generic errors never do; after
Signal there is no fallback. Old Workers retain original capacity and semantics.
Default/private modes cannot use this public lifecycle channel.

## Accepted begin versus invalid receipt

Independent review reproduced a new P2 in the first candidate: the original
begin reducer accepted, but the helper rejected an ACK with an extra field.
A broad existing error classification incorrectly called that definite refusal,
released the Owner and stranded a live original ledger call. Real wrapper/Owner/
reducer RED: **2 failed/1.06 seconds**. This did not execute a business handler.

The helper now distinguishes a verified original handler refusal from local
ACK/query/port/namespace validation failure. Only a complete observed handler
error, or pinned legacy SDK `WorkflowUpdateFailedError` with a non-retryable
original `ApplicationError`, can produce internal `LifecycleRefused`. Only that
exact internal type and a fixed refusal code can mark begin not allowed. A bad
ACK leaves the original invocation unknown: end recovery retries the same begin
identity/fixed ID, then records original end without executing business. Persistent
bad ACK retains Owner/`CloseIncomplete`; clearing the fault permits drainage.
Four real-wrapper tests cover transient/persistent invalid ACK and genuine legacy/
Signal refusal. Source inventory includes the error constructor/classifier.

## Compatibility and verification boundaries

The new module and Workflow Signal are pinned in selected publication/composition
implementation inventories. Experimental fingerprints change. Historical selected
public releases still require their matching immutable SDK/Worker; current SDK
publication validation is not loosened to accept older source inventories.

Old-end compatibility uses the original `10c540e` package/current SDK as before.
Old-public lifecycle compatibility uses the immutable `dd543c8` package's own SDK
for submit, original retirement and History replay. Only the new mechanical helper
runs in the current process, re-observing original begin/seal fixed IDs. This is
helper interoperability, not current-Engine acceptance or current replay of an
old selected publication. Default publication/saved default History compatibility
is checked independently.

The first source actual public pressure passes in13.153 seconds, retaining the
original120-second case,60-second Activity and45-second physical thread bounds:
exactly2,000 original Updates, one business write, adopted effect evidence, all
original end facts, seal, Registry held roots zero, Owner close, Worker restart
and original History replay. Final same-wheel/installation results follow below;
this source result alone does not close a release or complete P3-3.

## Remaining gates

This repairs the selected original public Tool/evidence-ACK/closure path only.
The call ledger still has4,096 records and no eviction, and this does not bound
History bytes/events. Registry release-Update exhaustion, Session coordinator,
other original operations, native/Session/graph pressure combinations and the
remaining frozen service matrix retain separate gates. Neither this normal case
nor unit coverage of Parent semantics proves those combinations. No new backend,
Runner, deployment, compaction or generic transport bus is introduced. Full
P3-3/P3-2 remain open; P3-4/5/A remain locked.


## Final immutable package and acceptance

Final wheel: `dist/p3-deployment-lifecycle-final-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`.
SHA256 `e71780943d331351aa47192aca83d4278a55ab027b103ba8141c3da564040a67`.
The same435 product files match source/wheel/isolated site; copied tests do not
change during runs. All15 earlier frozen artifact checksum sets remain unchanged,
including the prior limited end-repair candidate with its explicitly failed
public gate. The first lifecycle candidate is kept separately, not overwritten.

- Final source123-module regression: **2,381 passed/6 skipped**,91.257 seconds
  (JUnit suite time). Isolated installed regression: **2,381 passed/6 skipped**,
  96.931 seconds. The same four remote-context and two selected no-submit service
  cases remain skipped/unaccepted; no real-model quality claim is made.
- Default Card and ordinary Temporal publication equality, plus saved original/
  continued default History offline replay, pass. Whole-project Ruff and1,346-file
  format/Git whitespace checks pass. Final independent review has no outstanding
  P1/P2 in the bounded repair; it did not run services.
- Same final wheel actual suite: **3 passed/21.426 seconds**. Public pressure:
 12.022-second testcase, exactly2,000 original Run accepted/completed Updates,
  one SQLite business write, original cancellation receipt, physical end proofs,
  adopted evidence ACK, original seal, zero held roots, Owner drainage, Worker
  restart and Run/Registry History replay. Original time bounds are unchanged.
- Old-end compatibility:3.276-second testcase, unchanged original10c540e package,
  two original Tool calls/end Updates, repeated original end ID, zero new end
  Signals, original History replay and owned closure.
- Old-public lifecycle helper compatibility:5.405-second testcase, immutable
  dd543c8 package uses its own SDK/Worker/replayer to submit and retire. Current
  helper re-observes original begin/seal twice each, with the original fixed IDs;
  accepted Update identities do not grow and no `deployment_lifecycle` Signal
  appears. Two original tools/end facts, original namespace/epoch, old Run/Registry
  replay and both Owners/old Engine shutdown are confirmed. Existing old end
  Signals are expected and are not misreported as absent. Current SDK acceptance
  of that old selected release is explicitly **not** claimed.

Development failures are retained separately:

1. Missing server module12 failures; private-HEAD client missing-module RED1
   failure. The concurrently written client's first current-source run was
   already passing and is not described as RED.
2. Accepted-begin/invalid-ACK RED2 failures, then4 wrapper tests passed including
   genuine legacy/Signal definite refusals. No function re-execution is used as
   recovery.
3. Adding the refusal constructor to the callable inventory exposed zero-argument
   `super()` capturing non-JSON `__class__`. Source and first installed broad
   runs each had119 failures/2 errors, all with that fingerprint root cause.
   Explicit `RalfError.__init__` removes the capture without relaxing the
   fingerprint validator. Related126 checks pass before the final full runs.
4. The next source run hit its original180-second wrapper limit at a pre-existing
   Local HTTP unknown-effect control test, after1,422 reported outcomes. That
   single case passed independently; an unchanged-product full recheck with
   faulthandler then passed as recorded above. Its root cause remains unconfirmed;
   it is not presented as a fixed product bug or a passed run. Neither source
   watchdog nor any original business deadline was increased.

The earlier source pressure13.153s and initial-candidate actual3 passed/31.021s
are separate snapshots, not added to the final suite. No external model/PG calls,
new service/Docker configuration, backend or deployment combination occur.

Evidence roots under `/private/tmp/ralf-agent-`: `p3-deployment-lifecycle-20261016`
(source, preserved errors/timeout), `p3-lifecycle-service-probe-20261016`,
`p3-deployment-lifecycle-install-20261016`, `p3-deployment-lifecycle-live-20261016`,
`p3-deployment-lifecycle-final-install-20261016`, and
`p3-deployment-lifecycle-final-live-20261016`. Focused client records live under
`/private/tmp/ralf-deployment-lifecycle-client-20261016`; uncertain-begin and
constructor records use `/private/tmp/ralf-lifecycle-*`. Final`verification.json`,
`SHA256SUMS` and evidence hash inventory distinguish each snapshot and failure.

This batch closes only the reproduced public2 Tool/evidence-ACK/closure capacity
subgate. Next batch audits the remaining frozen P3-3 matrix against existing
artifacts before implementing any further change: one evidence/contract review
batch, with service runs only for an identified missing gate. No time promise for
full P3-3, P3-2/S2 or R01–R26 follows from this subgate. Local commit only; no push.
