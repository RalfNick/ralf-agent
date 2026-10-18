# Original Coding receipts after Run Update exhaustion

2026-10-18 · P3-3 necessary recovery only. Basic SDK/dev99/dev113 remain frozen.
P3-2/S2 and full P3-3 stay open; P3-4/5/A are not unlocked.

## Reproduction and preserved failures

The immutable 437-file `70a9d59` wheel, SHA256
`6dad78871e44f579109838e45a6f8b7cc98ebc1938cc80570532e0a108748e23`,
failed the original single-Agent Coding stop-ACK case after exactly 2,000
accepted/completed Updates. The stop receipt's fresh Update was rejected by
Temporal's distinct-Update limit. The result candidate remained absent and owned
close failed with the same RPC error. File commitment and a single thread/start
plus turn/start preceded pressure; cleanup did not certify retirement.

First probe repeated one logical drive: **1 failed / 58.238s**, filling in 2.593s.
The final probe repeated the exact original approval from actual History:
**1 failed / 57.665s**, filling in 2.745s. Both retained the original 30s gate,
240s case, 80s Activity/drive and 60s Runner limits. An intermediate approval
reader expected only a Signal, while the original approval was an Update; its
**1 failed / 125.599s** is a fixture failure, not additional product evidence.
All records remain in `/private/tmp/ralf-agent-p3-native-pressure-probe` with
suffixes `-20261018/`, `-v2-20261018/`, and `-v3-20261018/`.

Each probe used real Temporal/PG and existing deterministic native process peers.
The peer performs real subprocess/file work; its Docker inventory and Provider
remain structural. This is neither actual Docker execution nor model quality.
Each probe's owned services stopped. Failed-scenario PG containers/volumes,
schemas, original Temporal DBs, Histories and recovery evidence were retained.
No old service database was changed and service limits were not increased.

## Repair and compatibility boundary

`temporal_coding_recovery_transport` observes only three original handlers:
`coding_receipt`, `admit_coding_stop`, and `coding_owner_stopped`. A fixed Signal
calls the complete existing handler and its original wake rules. Full original
claim/request/phase/owner validation, callback validation before/after I/O, and
typed acknowledgements remain. `admit_coding_phase` stays on its original Update;
observations cannot grant fresh business permission.

Scope, namespace, original Run/first/original epoch, release, exact proof digest
and original Action/request/invocation identities remain bound. SDK handle ports
are pinned. Cache capacity is 64 with no pending eviction, envelope limit 2 MiB
and observer deadline 30s. Lost replies, cancellation, capacity or malformed
acknowledgements never authorize Update fallback. Original reducers remain the
only evidence-adoption and stop authority.

Coding glue pins the transport functions, operation inventory, fixed Workflow
source digest and its reader. Only Worker implementation discovery reads that
fixed file; History checks metadata and original pure rules without SDK imports
or source I/O. Composition/public inventories additionally fix concrete handlers
and sources. Historical selected publications require matching immutable
SDK/Worker. Stable default compatibility is checked independently.

Fixture stop faults still occur before delivery; worker-crash injection occurs
after confirmed original adoption. The real case keeps its original deadlines,
physical-stop/effect-ACK/quota/seal checks. Restart reobserves the original Coding
stop ACK and re-submits the same proof through its full handler. It does not add
an unrelated new approval-transport requirement to this repair.

## Regression evidence

Boundary RED: 12 failures before the module/Signal existed; then 12 passed.
Initial client integration: 19 passed / 12 failed because the fake SDK method
used the same parameter name for Workflow ID and run epoch. Corrected doubles:
31 passed; wider targeted integration: 96 passed.

First 129-module regression: **2,451 passed / 3 failed / 6 skipped / 89.819s**.
Two failures exposed optional-SDK coupling in implementation discovery, fixed by
the fixed-source inventory above. The third routing double expected raw Updates;
it now mocks the new recovery port, separately from complete client boundary
tests. Related pure/routing/client checks: **35 passed / 7.25s**.

Final same 129-module source regression: **2,454 passed / 6 skipped / 89.806s**,
zero failures/errors. All 438 product files remained fixed. The initial
post-regression service-only refinement compared the affected Coding stop ACK;
that intermediate difference is recorded in
`post-regression-service-test-only.json`. Later service/retention refinements and
their separate validation are listed below. Neither record claims all 913 test
inputs stayed identical across all source/install/actual snapshots.

Read-only review found no actionable P1/P2 in proof boundaries, normal grants,
fingerprints, pure-rule separation or retained fault injection. The reviewer did
not run services. Evidence prefix `/private/tmp/ralf-agent-p3-coding-recovery`:
`-source-20261018/`, `-source-final-20261018/`, `-install-final-20261018/`,
and `-live-final-20261018/`.

## Installed and actual acceptance

Isolated 129-module regression: **2,454 passed / 6 skipped / 90.048s**, zero
failures/errors. All 438 product files match the wheel and source; stable defaults
and original/continued saved default Histories pass. The wheel SHA256 is
`62837413eaab1764d00f6ee70ee0565c8f9e00c541eca4992c3988da68ff5426`.

Three same-wheel actual failures are retained separately. The first normal
continuation pressure case failed its success assertion (**31.721s**): native
stop/tool result/effect ACK/root retirement and owned close succeeded, but the
next model returned `provider_error` with `dispatched=False`. New context/model
admission retains its original Update backpressure; its precise RPC was not
separately captured. Moving cancellation after the deferred effect ACK was too
late and also failed (**32.615s**). Neither is accepted as successful continuation.

The next variant explicitly cancelled while the original native stop ACK was
held, preserving a separate PG ACK gate. It completed the original Action,
adopted its effect, physically stopped, retired the root and replayed History.
Replacement Worker construction before old Worker shutdown then failed
(**30.482s**); the test now shuts down first and reuses its captured SDK client.
Only the pressure branch expects cancellation; all four original normal-boundary
cases retain their success assertion and original deadlines.

All three attempts retained their owned data. The fixture's old Registry reader
also refused deletion because it recognized reserve/release Updates but not the
current Signal transports. It must use original successful submission/bind
Update receipts and completed Root release Activity receipts, cross-checked with
the exact original Registry Signals and SDK root History. A Signal alone is not
acceptance, and no mutable Workflow Query is used to permit deletion. This
test-only evidence update is independently verified before final service rerun.

The cleanup reader was corrected without weakening its proof boundary. New
positive cases first failed without Signal-linked acceptance; additional
untracked-submit Signal cases also failed before the guard was completed.
Source helper/Session validation: **86 passed / 8.06s** in the authorized
environment, including the original eight bind-only Unix socket cases. The
earlier 76-pass/eight-socket-permission-failure batch remains separate. Offline
verification of the saved cancelled-root History also proved one accepted and
retired root, no missing evidence, zero Workflow state Queries and no data change.

These helper changes and the pressure test refinement followed the main
regressions. Exactly three test files differ from those earlier source/install
snapshots: `temporal_deployment_coding_retention.py`, its test module and
`test_temporal_deployment_coding_service.py`. Product bytes remain fixed. The same
installed wheel independently ran the revised helper/Session modules:
**86 passed / 9.255s**, zero skips/failures/errors. This is additional affected
coverage, not a retroactive claim of a single final full regression.

Before final review, actual normal/necessary-cancellation acceptance passed on the same wheel:
**2 passed / 56.464s**, zero failures/errors/skips. The original normal native-stop
baseline succeeds. In the pressure case exactly 2,000 accepted/completed Updates
were filled by repeating the original approval (2.431s). While the original
native stop ACK was held, explicit cancellation and its identical repeated
receipt applied. Original stop/candidate adoption, physical end and effect ACK
each completed; the held root stayed protected until the ACK was released.
The final Run is cancelled with its original Action completed and one adopted
PG effect. Only one thread/start and turn/start occurred.

The replacement Worker reobserved the original stop ACK and re-submitted its
exact original proof through the complete handler; receipts matched, the root
stayed retired and all original Histories replayed. The old Worker was shut down
before replacement construction, with its original captured client retained.
Owned assemblies closed. Both cases' evidence permitted schema cleanup; both
schemas were removed, owned services stopped and only the successful candidate's
container/volume was removed. Every earlier failed-scenario volume/schema and
original Temporal DB remains retained. No old database was touched.

### Final review: unresolved Signal retention

Fresh review found one P2 in the test-only cleanup reader: a failed conflicting
`reserve` Update for the same target could subtract a submit Signal lacking
completed acceptance evidence. The real Registry still retained its held-bound
root, but the reader incorrectly allowed deletion. Both submission-record and
bind paths reproduced this with **2 failed** assertions. An initial test fixture
indexed the root map by Run ID rather than its Scope/command digest; its two
KeyErrors are not counted as valid RED evidence.

The reader now checks unresolved Signal targets independently of rejected
Updates. Source helper/Session checks passed **88 tests / 7.45s**, and the same
installed wheel passed **88 tests / 8.02s**. The independent reviewer confirmed
both refusal paths and both complete acceptance/release paths (four checks),
and verified its original reproduction now refuses deletion. Product bytes and
the wheel remain unchanged; this fix only tightens fixture cleanup evidence.
Evidence: `/private/tmp/ralf-coding-retention-review-red-20261018.log`,
`/private/tmp/ralf-coding-retention-review-green-20261018.xml`, and
`/private/tmp/ralf-agent-p3-coding-recovery-live-v5-20261018/`.
The earlier v4 service result and its pre-review metadata remain separate.

After this fix, the unchanged wheel repeated the same actual normal/pressure
pair: **2 passed / 58.684s**, zero skips/failures/errors. Original stop ACK,
effect adoption, physical stop, root retirement, restart/replay and strict owned
cleanup all passed. Inputs remained fixed within the run; the final Ruff-only
wrap of the cleanup condition has identical AST and is recorded separately.
Owned services stopped; earlier failed-scenario data remains retained. The v4
56.464s result is preserved rather than overwritten as final-review evidence.

Final artifact: `dist/p3-coding-recovery-final-20261018/`, with wheel,
`verification.json` and `SHA256SUMS`. All eighteen prior accepted artifact checksum
sets remain valid. Only the single Coding Run necessary-recovery subgate closes.

The affected single Coding Run is distinct from Coding parent adoption and
Registry pressure. No all-topology capacity matrix, arbitrary History size,
unlimited operation, new PG/HTTP endpoint coverage or model-quality claim follows.
Current scope and remaining evidence stay in the implementation summary. Local
commit only; no push or public release.
