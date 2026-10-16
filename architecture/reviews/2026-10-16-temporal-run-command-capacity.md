# Original Run controls after distinct Update exhaustion

2026-10-16 · P3-3 necessary-control availability only. Basic SDK/dev99/dev113
remain frozen. P3-2/S2 and its original360-second failure stay deferred/open;
P3-4/5/A are not unlocked.

## Reproduced blocker and bounded repair

On the immutable prior accepted scoped-manual installation, one ordinary Agent Run waited
for approval.2,000 fresh SDK Updates repeated a single logical drive; its first
SDK cancel then failed with Temporal's distinct-Update limit. The original
Registry was not full and only one logical drive existed. Actual RED:
**1 failed/9.642s**, with original History retention and owned cleanup. No business
Tool or external model call occurred. Registry admission capacity and the original
Run's SDK Update ledger are independent limits.

New `temporal_command_transport.py` changes only necessary `cancel`, `drive`, and
manual `reconcile(query=False)` transport on default/public Runs. It sends an
observation through the original Run's Signal and reads the original Run's Query.
It invokes the complete existing `Run.command` or dynamically selected
`Parent.command`, preserving retries, notification reset, Parent recovery/child
reads, History patch/seal rules and wake revisions. Business state, approvals,
Action identities and receipts remain with that same execution authority.

Each fresh observation executes the complete handler before confirmation, even
when the logical command already has a receipt. Retransmitting the same observation
is deduplicated. A64-entry observation cache can evict observations only; it never
deletes business identities. Pending/evicted observations, delivery failure,
30-second observer timeout or observer cancellation do not prove rejection or
undo acceptance. After Signal there is no Update fallback or new business ID.
This is not a bound on total History events, bytes or server limits.

Exact envelope/request shape, canonical digest, full Scope, namespace name,
original SDK workflow/first/original epoch and bounded observation ID are checked.
The client pins its ports, namespace and the returned epoch before sending;
responses and receipts require the original command/run/kind and typed fields.
The existing scoped manual binding additionally retains its namespace UUID and
original target epoch verification. Signal delivery itself is never an acceptance.

## Compatibility and scope

A new status-kind observation probe lets an old Worker return its exact existing
RunSnapshot. Only that complete legacy shape, original SDK type/namespace/first
Run identity and a second epoch-pinned status authorize the old Update path.
Generic `validation_error`, unknown/malformed replies and changed ports never do.
Old Worker compatibility retains its original Update limit; this repair does not
retroactively add Signal support to an immutable old Worker.

Existing public ordinary/Coding internal child control uses the new helper only
after its original admission/ancestry/evidence checks. Post-await verification is
retained. Private deployment1 and private composition helpers keep original
Updates/fixed IDs. Other commands, native grants/receipts/end-ACK, begin/end/seal,
Registry strong verification and Session transport are unchanged.

The new module is included in deployment source publication and the composition
worker callable inventory, including the inherited Signal handler. Selected
experimental fingerprints change; historical selected releases still need their
matching immutable Worker. Default Card/publication equality and saved default
History replay are checked independently.

## Verification

Source affected60-module regression: **1,272 passed/25.029s**, no failures/errors/
skips. New39 cases cover ordinary Agent/Parent complete handlers, repeat recovery/seals,
observation eviction/conflicts, typed replies, positive legacy detection, epoch/
namespace and changed port refusals, and no post-Signal fallback on timeout or
cancellation. Existing delegated-control fakes now implement the same genuine
handler observation; private Update assertions remain.

First wider source run retained **2 failed/1,267 passed**: the independent private
publication fixture omitted the newly pinned source module. Update that explicit
expected inventory; keep production closure validation. The Parent unit fixture's
initial kernel2 memory-revision expectation was also corrected to the existing
kernel3-only contract. These are fixture failures, not service acceptance.

Read-only final review found no reproducible P1/P2 in the transport or integration;
it did not run services or confer stage acceptance.


## Final artifact and independent actual evidence

Final wheel `dist/p3-run-command-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`,
SHA256 `185b1d23c5967ba29daad647be9d56f9a3ac36559150dc9ac14d275165c900b2`.
Isolated installed regression: **1,272 passed/28.062s**, zero failures/errors/skips.
All432 product files match source/wheel/site. Default Card/publication equality and
original/continued saved default History replay pass. The prior twelve accepted
artifact checksum sets remain unchanged. `verification.json`/`SHA256SUMS` record
exact source, installation and case snapshots; no prior artifact is overwritten.

Three actual SDK scenarios passed on this same wheel in independent runs:

- Ordinary Agent case (original test parameter `native`, not a Coding Runner): **passed/14.198s** (testcase time). Original History has exactly
  2,000 accepted/completed Updates, followed by original control Signals. First
  cancel applies; repeated original receipt, Worker restart, two History replays
  and owned cleanup pass. No Tool dispatch occurs.
- Graph parent/child: **1 passed/16.672s** (independent pytest run). Both original
  Histories have exactly2,000 accepted/completed Updates. First parent cancel is
  accepted with its original immutable `remote_stop_confirmed=False`; subsequent
  child cancellation and both original quiescent observations prove tree stop
  separately. Parent and child control Signals, restarted Worker/original receipt,
  three History replays and owned closure pass. No Tool dispatch occurs.
- Immutable basic SDK old Worker: **passed/9.247s** (testcase time). Current SDK
  controls the original parent and ordinary Agent child through positively discovered
  legacy Updates. Both Run Histories and Registry contain zero Signals. Repeated
  commands/drive, current-code replay, owned History closure and the separate old
  Worker process shutdown pass. This proves API compatibility, not removal of the
  old Worker's Update limit or retroactive repair of its unsafe Tool unknowns.

These are not a single all-green three-case pytest run. First actual runner:
**1 failed/2 passed,17.379s**; its graph observation caught raw RPCError but the
SDK correctly mapped the not-yet-started child to `NotFound`. Fix only that bounded
wait. Second runner: **1 failed/2 passed,33.265s**; both parent and child reached
2,000 Updates, but the test incorrectly required immediate physical stop in the
parent's cancellation receipt. Preserve production's correct `False`, then check
actual descendant cancellation/quiescence separately. Only that failed graph case
is rerun; unchanged ordinary Agent/legacy passes retain their own frozen case snapshots.
Both failed runners retain Histories and successful owned cleanup, with no product
or deadline change. The original180-second per-pressure-case bound stays intact.

The final graph run retains one Temporal sandbox warning: the inherited Parent
handler dynamically imports `temporal_command_transport` after initial load. The
pure module loads and both live execution/replay pass; this is not an exception or
stage acceptance. Record it for later preload cleanup rather than expand this
blocking correctness repair. No warning suppression was added.

Evidence roots under `/private/tmp/ralf-agent-`:
`p3-run-command-20261016` (source/RED), `p3-run-command-install-20261016`
(isolated package), `p3-run-command-red-20261016` (immutable prior-package failure),
`p3-run-command-live-20261016` and `p3-run-command-live-v2-20261016` (retained failed
runners; latter includes accepted ordinary Agent/legacy cases), and
`p3-run-command-live-v3-20261016` (accepted graph, verification and evidence hashes).
Product and copied tests stay immutable during each run. This batch uses no
external model/PG call and makes no service/Docker configuration change. It does
not renew the separate HTTP/PG matrix, model quality or complete service coverage.

## Remaining gates

Only the original Run's necessary business-command transport is addressed. Other
Run/Registry distinct Updates, native fencing/end evidence, Session control,
History byte/event limits and remaining selected service combinations stay open.
The old no-marker unowned Tool safety risk and retained obligations are unchanged.
No new backend, orchestration, scheduler, compaction or execution authority is
introduced. Full P3-3 and all later stages remain unaccepted.
