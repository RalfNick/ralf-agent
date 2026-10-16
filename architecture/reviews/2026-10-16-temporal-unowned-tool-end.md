# Preserve original unowned Tool end evidence

2026-10-16 · P3-3 safety prerequisite, found while reviewing scoped manual
admission. P3-2/S2's original360-second failure and all remaining gates stand.
No new backend, execution authority, adapter or manual-clear API.

## P1 and repair

Default Temporal without ToolExecutionOwner: Tool A times out; operator or effect
query confirms A's business effect; Tool B succeeds. Previously B recomputed
aggregate uncertainty from unknown Action status only. A was already completed,
so the original still-running handler ceased to protect parent settlement. Two
zero-credit calls reproduce this: after confirmation uncertainty=true; after B,
uncertainty=false and quiescent=true with no A end evidence.

Newly marked Runs keep `execution_unconfirmed` per unknown ordinary Tool Action.
Effect confirmation/ACK and another Tool result cannot clear it. A genuine original
A result clears only A's end debt and never overwrites an already adopted effect.
Quiescence checks each debt independently of the aggregate flag. Existing parent
observation therefore retains escrow. Existing Owner/native protocols are unchanged.

`ralf-unowned-tool-end-evidence-v1` gates the changed state evolution. Default
Card and ordinary publication remain equal, but old no-marker Histories preserve
the original behavior for deterministic replay. They are **not retroactively
repaired**. A successful legacy replay is compatibility evidence, not safety
acceptance. Old unknown no-Owner Runs still need a separately validated handling
or migration policy; no administrative bypass is added here.

## Exact artifact and verification

`dist/p3-tool-end-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`
SHA256 `832e255bd2c8f31377e03d94948f2b518382a79e7b2bfd04426aabbf1ba7201e`.

Affected54-module source **1,176 passed/31.389s**; isolated installed wheel
**1,176 passed/26.045s**, zero failures/errors/skips.430 product Python/JSON files
match source/wheel/site. Default Card/ordinary publication equality with immutable
basic SDK and offline replay of original/continued saved default Histories pass.
All prior ten accepted local artifact checksum sets remain unchanged. This is
an affected regression set, not a new full13k offline run or full service matrix.

New five reducer cases cover operator/query adoption, zero-cost Tools, another
Tool's success, cancellation's stop facts, restored state, genuine original late
result with another debt, preserved committed output and legacy compatibility.
Initial RED **3 failed/2 passed** is retained.

Installed actual Temporal, same wheel, second independent attempt:
**2 passed/19.339s**. Both use owned Worker processes and real synchronous thread
handlers, Activity1/overall90-second per-case bounds, with deterministic Provider.

- Current package: original slow thread times out and remains physically live;
  manual effect confirmation and fast Tool success complete the child's business
  result and settle effect credits, while child/parent stay non-quiescent, original
  child unsettled and parent escrow retained. After actual thread exit, restart
  the same selected Worker; the missing History end receipt remains an obligation.
  Original manual receipt repeats identically; root/child/Registry replay and the
  child patch marker are verified.
- Immutable `basic-sdk-b871f61` Worker: the same sequence demonstrates the old
  premature quiescence/parent settlement with thread still live. Restart and
  current-code replay preserve the no-marker behavior. This passing test is an
  explicit **legacy risk baseline**, not a second protected scenario.

For each case actual thread termination precedes resource cleanup; two owned
Worker processes exit with shutdown evidence, three owned Histories close,
facade closes and no cleanup failure occurs. No external model, PG or Docker
call. This is not real model quality, arbitrary remote stop proof or all adapters.
Temporal normally does not deliver a timed-out Activity's eventual thread result.
The reducer's genuine late-result case therefore does not promise automatic
clearance after timeout. An external file observing thread exit cannot fabricate
an original Workflow callback. The no-Owner path stays conservative if no original
end receipt arrives; explicit Owner's managed evidence remains a separate path.

## Retained failures and review

First actual run **2 failed/5.980s**: Parent's child reservation was observed
before the original child Workflow existed. The test queried child status and
raised NotFound instead of continuing its wait. Only this test observer now treats
that not-yet-started child as pending; all other errors still propagate. Product,
wheel, faults and time bounds were unchanged for retry. Original cases and owned
cleanup records remain; first copied tests were not edited in place.

Independent read-only review found no remaining P1/P2 in the repair or candidate
service test. Reviewer did not run services. Source regression, isolated package,
actual current safety and legacy risk are separate evidence scopes.

Evidence: `/private/tmp/ralf-agent-p3-tool-end-20261016/` (source/RED/build),
`/private/tmp/ralf-agent-p3-tool-end-install-20261016/` (immutable installation and
offline compatibility), `/private/tmp/ralf-agent-p3-tool-end-live-20261016/`
(first failed run), `/private/tmp/ralf-agent-p3-tool-end-live-v2-20261016/`
(corrected independent runner, actual Histories/process/thread records and final
verification). Artifact directory holds `verification.json` and `SHA256SUMS`.

## Scoped manual audit and remaining work

Scoped manual capacity was not implemented in this batch. Its proof must bind the
original SDK epoch/request and actual adopted Action inventory M, including
zero-cost calls; do not substitute a fixed4096-per-Run bound or the cancel/drive
`3C` bound. Existing read-only CONTROL transport can be reused without a new
execution authority, but scoped targets may legitimately use different queues
and releases. The exact dispatch-evidence requirement is still to be specified.
The [capacity contract](../specs/temporal-recovery-capacity-contract.md#ordinary-tool-physical-end-prerequisite)
records these constraints and this safety prerequisite.

Next batch remains the smallest scoped ordinary Tool manual-admission proof and
its tests, followed by original Update/History lifecycle gates. No new stage,
backend or deployment combination is unlocked. P3-3 is open; old no-marker safety
handling also remains open. P3-2/S2's deferred performance gate is unchanged.
