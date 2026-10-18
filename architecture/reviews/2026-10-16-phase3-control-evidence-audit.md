# P3-3 frozen-scope evidence audit

2026-10-16 · Runtime source `0fedebe`, package `0.1.0.dev120`.
This audit reconciles existing delivery evidence with the frozen requirements.
It adds no runtime feature, transport, backend or acceptance gate. P3-2/S2 stays
deferred and open; independent P3-3 work is explicitly authorized by the user.
P3-4/5/A are not unlocked.

## Requirement coverage

| Frozen P3-3 requirement | Available evidence | Conclusion and limit |
| --- | --- | --- |
| Submit/query/approve/cancel/reconcile/resume using original identities | Installed Local HTTP process-restart tests; ordinary public2 HTTP/Temporal/PostgreSQL tests below | Basic functional routes delivered; resume is a host wakeup, not a durable completion receipt |
| Durable HTTP events and cursor reconnection | Original authority records, bounded pages, prefix cursors; both HTTP hosts observe the original Run | Delivered polling extension; no SSE/push or hosted subscription is required for this batch |
| Disconnect does not cancel business | Existing observation tests and actual host restart while the original Run remains paused | Observation and business cancellation remain separate; socket disconnect does not guarantee immediate completion of an underlying Query |
| Bounded backpressure and existing control access | Page/response bounds; full Inbox still permits original-message lookup and controls | Delivered finite bounds; this does not establish global service scheduling or unlimited History |
| Necessary cancellation/recovery after cumulative command exhaustion | Separate immutable scoped/manual, Run/parent-child, end-ACK and public begin/seal evidence | Only the exact tested subsets pass. Registry pressure and selected native Coding recovery still need evidence; full P3-3 stays open |

The [frozen matrix](../../docs/phase3-support-matrix.md) remains authoritative for
scope. Session coordinator/Turn capacity and the original S2 performance gate
belong to P3-2; this audit does not move them into a new P3-3 implementation queue.

## Current installed wheel: actual HTTP/Temporal/PostgreSQL

The already frozen wheel is reused without rebuilding:
`dist/p3-deployment-lifecycle-final-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`,
SHA256 `e71780943d331351aa47192aca83d4278a55ab027b103ba8141c3da564040a67`.
Its 435 product files match source and isolated site-packages; copied test inputs
remain unchanged. The previous HTTP evidence used the older 429-file candidate;
the following is a separate current-wheel run, not a merged result.

Installed affected offline checks: **47 passed**. Actual existing
`test_a2a_temporal_http_service.py`: **3 passed / 26.847s**, zero failures,
errors or skips, with unchanged original 180-second case bounds.

| Case | Owned HTTP hosts | Actual PG business writes | Original events observed | Result |
| --- | --- | --- | --- | --- |
| Approval across restart | 2 | 1 | 23 | Original approval/receipt, adopted effect, cursor continuation and root retirement |
| Unknown write and manual confirmation | 2 | 1 | 22 | Original Action confirmed without another business write; adopted effect and root retirement |
| Explicit cancellation across restart | 2 | 0 | 13 | Original cancel receipt, cursor continuation and root retirement |

All six hosts report Engine and Inbox closure. Original Worker/History cleanup
checks pass. Each test removes only its own fresh PG schema after verified
retirement/closure; a separate read-only query confirms those three schemas absent.
Older unresolved evidence schemas are untouched. There are no model API calls.
The run retains a Temporal SDK `query task not found, or already expired` warning;
its cause is not established or claimed fixed by these passing cases.

Evidence is local under
`/private/tmp/ralf-agent-p3-http-temporal-current-20261016/`: installed XML/logs,
`result-v3.json`, frozen inputs, original Histories, per-case HTTP/closure/cleanup
records, and `postgres-absence.json`. Audit checks and evidence hashes are under
`/private/tmp/ralf-phase3-audit-20261016/`. All sixteen existing artifact checksum
sets remain valid; their original metadata and failure records are not rewritten.

## Remaining capacity evidence and next action

1. Public Registry strong manual recovery still uses its original asynchronous
   reserve/CONTROL proof path. Scoped manual transport evidence does not prove
   this different public path under Registry Update exhaustion.
2. Public root retirement still calls the original Registry release Update.
   The latest begin/seal pressure filled the **Run** with 2,000 Updates, not the
   Registry. This is a source risk and evidence gap, not a reproduced HEAD defect.
3. Selected native Coding receipt/stop/parent adoption and assembly closure have
   distinct original handlers. The run-command test parameter `native` means an
   ordinary `AgentSpec`, with no Coding Runner and zero Tool dispatch; it cannot
   supply native Coding capacity evidence. Original XML/test names remain intact.

The next batch is one existing public2 Registry-pressure retirement probe, retaining
original identities, full release/seal proofs, deadlines and owned cleanup. Implement
a transport change only if that probe reproduces a blocker of the frozen requirement.
Do not add compaction, Continue-As-New, a general control bus, additional recovery
slots or an all-topology pressure matrix from source inspection alone.

Fresh work may still encounter documented backpressure. Arbitrary History size,
indefinite operation and old unmarked Tool safety defects are not newly delivered
capabilities. Old selected releases require matching immutable Workers and retained
unknown handling. P3-3 is not complete; P3-2's original failure and all later gates
remain unchanged. This batch is a local documentation/evidence commit only.

## Subsequent retirement evidence, 2026-10-18

The recommended original Registry-pressure probe subsequently reproduced the
retirement blocker. The [bounded repair and same-wheel acceptance](2026-10-18-temporal-registry-retirement-capacity.md)
close only that subset. The original audit and its 435-file HTTP/PG evidence remain
unchanged; public strong manual proof and native Coding pressure remain open.
