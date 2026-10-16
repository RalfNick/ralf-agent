# Existing HTTP controls and cursors with Temporal/PostgreSQL

2026-10-16. P3-3 functional service evidence; no product-code change. Basic SDK,
dev99/dev113 and P3-2/S2 remain frozen. Original360s S2 failure and all other
capacity/native/scoped gates remain open. No new deployment or model protocol.

## Installed package and scope

Reuse the immutable `5646260` candidate:
`dist/p3-manual-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`, SHA256
`9cfc29575a407b6839635e56df2e4be43008e99b2292b02d6acbf6570ae24087`.
All429 product Python/JSON files match current source and installed package;
all seven earlier artifact directories retain their original checksums. No
wheel rebuild, new package version or default-release change was needed.

Use existing borrowed `A2AApplication`, native async `TemporalEngine`, original
public2 Registry/Run/Worker, `PostgresEffectJournal`, separate real PostgreSQL
business writes, and a persistent SQLite Inbox. Each test owns one schema and one
unique deployment. Actual loopback Uvicorn HTTP hosts are independent subprocesses;
the original Worker stays host-owned and alive across HTTP host restart.

Final installed cases: **3 passed/21.370s**, zero failures/errors/skips.

| Case | Actual business writes | Recovery and result |
| --- | --- | --- |
| Approval | 1 | Pause at original Action, close first HTTP host, repeat original message on replacement, resume and approve; exact repeated receipt, PG effect adopted |
| Unknown write | 1 | Real PG commit followed by handler response loss; original unknown Action confirmed with actual PG result after host restart; duplicate receipt, PG effect adopted |
| Cancellation | 0 | Original pending approval survives host restart; explicit existing HTTP cancellation; SDK original cancel receipt repeats, no dispatched PG effect |

All cases verify existing authentication refusal, Inbox capacity1 refusing fresh
business while original lookup/control remain usable, unchanged paused Run after
HTTP host shutdown, same Task/message identity after restart, original event
cursor continuity and complete final event sequence, root retirement to0 and
original seal/History replay. Final sequences contain23/22/13 events respectively.
Standard cancellation still returns a Task and refuses a terminal Task with
`-32002`; this test does not change it into the receipt extension.

Six HTTP processes exited after positive Engine/Inbox closure records. Their
borrowed facade closure did not cancel business or close the independent Worker.
Each original Run and Registry History replayed; owned Run/Registry termination
and Worker shutdown passed after retirement. The final three PG schemas were
deleted only after those gates. A subsequent read-only PostgreSQL query confirmed
their absence. No external model API was called; the deterministic Provider proves
runtime behavior, not model quality. This is ordinary public2 Agent evidence,
not a new Coding Session, graph/Team or closing-Assembly matrix result.

## Failures, fixes and affected checks

First installed attempt: **2 failed/10.312s**, retained. Both stopped at a missing
host-close marker: Uvicorn can re-raise SIGTERM before `serve()` returns, so a
finalizer after that call failed to establish owned resource closure. Move host
Engine/Inbox closure into its lifespan shutdown before ACK; no product changed.

Independent review also found the existing test fixture could replace an original
startup failure with Registry NOT_FOUND during cleanup. Two RED tests reproduce
that. The fixture now treats definitive Registry absence as harmless only when
all owned Runs are absent, continues resource closure, and preserves simultaneous
body/cleanup failures as a BaseExceptionGroup. No service limit or deadline changed.

Second installed two-case attempt: **2 passed/16.201s**, separate evidence. Adding
the existing cancel route produced the final three-case run above, not a merged
five-case claim. Source and installed affected offline checks each **47 passed**,
zero failures/errors/skips. Copied tests and product remained unchanged during
each installed run. Final independent read-only review found no P1/P2; it did not
run tests or services.

First-attempt owned PG evidence stays retained: one empty approval schema and one
unknown-write schema with one business call and a `dispatched` effect. Read-only
queries confirmed this; a later passing candidate does not authorize deleting
original unresolved evidence. No old schema is silently reused by the retries.

Evidence directories:

- `/private/tmp/ralf-agent-p3-http-temporal-20261016/`: original failures and tests.
- `/private/tmp/ralf-agent-p3-http-temporal-v2-20261016/`: corrected two-case run.
- `/private/tmp/ralf-agent-p3-http-temporal-v3-20261016/`: final XML, source/installed
  checks, original Histories, process/schema cleanup, `verification.json` and
  `evidence-sha256.json`.

## Remaining gate and next batch

This closes the ordinary Agent functional HTTP/Temporal/PG evidence gap for the
listed routes. It does not close full P3-3: remaining Run/Registry Update lifecycle
and necessary scoped/native capacity recovery require their own original-authority
proofs and actual service evidence. P3-4/5/A are not unlocked. Next batch audits
one such capacity boundary and implements only a reproduced blocker; estimate
one focused review/fix batch, with service acceptance scheduled from its actual
scope. No credible total-project percentage or full completion date is inferred.
