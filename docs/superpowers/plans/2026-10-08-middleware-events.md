# Middleware and Durable Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline.

**Goal:** Deliver dev23 opt-in invocation observers and resumable event consumption.
**Architecture:** Existing execution authority remains; structural wrappers borrow
components, while an async pull iterator reads persisted scoped Run events.
**Tech Stack:** Python3.11+, existing base dependencies, no new required packages.
**Spec:** [middleware/events](../specs/2026-10-08-middleware-events.md).

## Global constraints

- Preserve default native identities, existing receipts and nineteen starter contents.
- Synchronous completed-None hooks; after errors cannot discard known receipts.
- Scoped readers/immutable finite JSON, bounded pages/records; iterator does not drive.
- No paid calls, credentials, commits/push/publication or destructive checkout cleanup.

## Task1 — invocation middleware

Files: invocation_records.py, middleware.py, middleware_models.py,
middleware_tools.py; tests/test_invocation_middleware.py.
Consumes ModelRequest/ModelResponse, DispatchEnvelope/EffectObservation and current
Provider/Executor ports. Produces InvocationRecord, InvocationMiddleware,
NoopMiddleware, LoggingMiddleware, MiddlewareProvider, MiddlewareToolExecutor.

- [x] RED tests exercise before A/B and after B/A ordering, immutable payloads,
  original authorized arguments/effect keys, approval/restart and after failure:
  `with LocalEngine(..., tool_executor=MiddlewareToolExecutor(PythonToolExecutor(tools), [observer])) as e:`
  `assert snapshot.state == 'succeeded' and writes == [7]`
  when observer.after raises; diagnostic logs must not contain its private text.
- [x] Implement finite immutable records; pinned identity/code and strict hook return
  validation; detached delegates, conditional complete-stream forwarding and cleanup.
  `before(record) -> None`; `after(record) -> None`; refusal of lazy values is explicit.
- [x] GREEN targeted middleware and existing execution component suites. Expected:
  existing low-level approvals/recovery and default identities remain unchanged.

## Task2 — event iterator

Files: event_records.py, event_stream.py; tests/test_run_event_subscription.py.
Consumes scope/status/events from sync/async readers. Produces EventCursor,
EventEnvelope, SyncRunEventSource/AsyncRunEventSource and RunEventSubscription.

- [x] RED: `stream=RunEventSubscription(SQLiteRunReader(path), run_id, follow=False)`;
  `rows=[r async for r in stream]`; reconnect with `after=rows[0].cursor` must yield
  original records without gaps or duplicates after that cursor. Tests cover actual
  concurrent Local drive/approval, terminal drain race, cancellation, reader swaps,
  wrong Scope/run cursor, malformed pages and single-consumer/loop boundaries.
- [x] Implement typed records/token/SSE, binding-pinned reader and bounded pull
  iterator with private read tasks, timeout, wake/close cleanup and terminal drain.
- [x] GREEN target tests and existing event/Task control contracts. Tests must show
  closing or cancelling observation leaves the Engine/handler running.

## Task3 — defaults and installed application

Files: middleware_factories.py, event_watch.py, observable_starter.py; modify
runtime_builder.py, starter.py, cli.py, __init__.py, pyproject.toml, CI/docs.
Consumes Task1 wrappers and Task2 iterator. Produces explicit profile adapters,
ralf-watch-events console and twentieth observable template.

- [x] RED: invalid nested/async/secrets/profile configs leave no DB; run installed
  observable starter with deterministic read-only tools, actual streamed persisted
  records and recovered cursor; CLI snapshot/SSE output and foreign Scope refusal.
- [x] Implement strict factories/CLI/template, public exports/dev23 and usage guide.
- [x] GREEN independent subprocess starter/config tests and optional-import checks.

## Task4 — review and complete gates

- [x] One fresh whole-increment reviewer, classify findings by user effect and perform
  one Important/Critical RED→GREEN fix pass. Defer and report Minor findings.
- [x] Full actual-service suite, actual Temporal middleware/event cases, installed
  wheel/base contracts, actualdev22 local/History/template compatibility, source/
  wheel/sdist/installed byte identities and dependencies/extras unchanged.
- [x] Build/Ruff/format/links/CI/credential exclusion, document evidence, stop owned
  services and retain local-only work/evidence.

## Review focus

1. Mutable/lazy observer results or changed hook code cannot rewrite approvals.
2. Exceptions/cancellation after external response must not erase known receipts.
3. Streaming completion/close cannot leak private data or fabricate decision/usage.
4. Cross-Scope/binding drift, gaps and terminal read races cannot silently lose events.
5. Slow consumers, concurrent iteration or remote reads must not leak tasks/resources.
