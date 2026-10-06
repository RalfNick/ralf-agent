# dev12 parallel Workflow review and disposition

Date: 2026-10-06. Scope: BASE `3d53456` to implementation `c0676d9`, plus the
verified repair pass. This delivers local bounded static graph execution, not
AgentScope parity, full M1, teams or distributed execution.

## Architecture

Static plan v3 is explicit for max_concurrency=2..32; default 1 retains v1/v2
source and Manifest identity. A pure scheduler proposes ready work and a common
boundary validates dependency/binding/skip/completion/cap semantics. Each node
uses an isolated durable native frame over the parent's ExecutionStore; parent
Actions, credits, commands, event sequence, Scope and Coordinator remain the only
authority. Original node input and Session names survive recovery.

The parent tracks supervisor, every worker Task and actual managed synchronous
threads/MCP workers. Session ownership includes accepted root/derived names and a
durable quiescent marker, including failed Runs whose append is still underway.
Terminal recovery under a new exclusive owner clears abandoned activity markers
after normalizing attempts and adopting stored evidence. Independent waiting
branches do not prevent ready work; blocked frames attempt once per drive.

## One independent review

A fresh read-only gpt-6-astra reviewer inspected the range and independently ran
85 focused tests with warnings as errors. No implementer subagent or second
reviewer was used. It reproduced two Important and one Minor findings:

| Finding | Final grade and repair | Behavioral evidence |
| --- | --- | --- |
| Policy can reconcile a write while the native loop still redispatches it | Important; stop completed/received Actions after callback and immediately before reservation; applies to serial and parallel native paths | Both serial and parallel confirmed-write tests RED→GREEN; one handler invocation/attempt, immutable operator result |
| Failed parent releases Session before a sibling append finishes | Important; persist quiescent=false while workers own resources, retain session_ids ownership for terminal Runs, clear only after actual exit or exclusive terminal recovery | Async append reproduction RED→GREEN; bulk-cancelled real memory thread still reserves Session until drain; stale crash marker cleared by terminal recovery |
| Branch failure has no parent run_failed event | Regraded Important: event consumers otherwise cannot reliably observe terminal failure. Emit once when parent failure becomes authoritative, including approval rejection | Branch validation and repeated approval rejection tests RED→GREEN; one parent event across repeat drive/commands |

The original two reproduction scripts live in temporary review storage. Product
regressions and repairs are committed in the repository. No reported finding is
deferred. The repair pass is verified by failing tests and a full green suite;
there is no second review verdict.

## Rulings on reviewer exclusions

- Ruling: live model quality and performance remain unjudged — this increment's
  deterministic receivers/barriers establish runtime behavior only — cost if
  wrong: real tasks may have poor quality/latency until separately evaluated.
- Ruling: distributed scheduling and global capacity remain out of this increment
  — concurrency is per Run under one local Coordinator — cost if wrong: hosts
  that launch many Runs without independent limits can overload resources.
- Ruling: the reviewer did not repeat installed dev11 upgrade verification; the
  coordinator performed it with actual wheels outside checkout — evidence is
  retained and no independent duplicate claim is made — cost if wrong: packaging
  validation has one executor's blind spots rather than two independent runs.
- Ruling: missing parent failure events are an Important reliability issue, despite
  the reviewer's Minor label — event consumers need the parent lifecycle fact —
  cost if wrong: added v3 events may require consumer compatibility; default
  legacy paths retain their prior event behavior.

## Verification

Pre-review: 915 passed in 78.47s; focused repair/lifecycle suites: 101 passed.
Seven additional repair regressions passed, including the two original failures
and native serial reuse. Final suite, artifact hashes and installation proof are
recorded in the completion evidence below.

Installed dev11-to-dev12 tests preserve native/v1/v2 records exactly before
resume, resolve original receipts/profiles, execute native/MCP business writes
once, collect queued HTTP once then zero times on repeated drive, and reject v3
on dev11 before dispatch. Five original starter dictionaries remain identical.
The parallel starter runs with retained historical profiles; 117 public symbols
import; pip check passes. All 37 SDK modules match wheel/sdist/source/installation.

Five real-process windows cover model response receiving, tool receipt receiving,
external business commit, node completion and Session append. A not-yet-received
sibling model call may retry and retain unknown credits. Business effects still
require downstream idempotency or verified lookup; arbitrary external writes do
not receive an exactly-once promise.

## Completion evidence

Final full suite: **922 passed in 75.81s** with warnings as errors. Ruff, format
(107 Python files) and Git whitespace pass. Both artifacts build successfully.
Document links and Python/shell/TOML snippets pass. All reported review findings
were addressed in the single RED→GREEN repair pass; no deferred minors.
