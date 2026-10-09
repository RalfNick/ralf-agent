# Async execution handoff implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, then one independent whole-increment review. User implementation authorization persists; no repeated approval or Git publication.

**Goal:** Make A2A usable with native async execution and shared durable handoff while preserving local defaults.

**Architecture:** TaskControlBridge validates completed controls from a trusted, borrowed authority. PostgreSQL Inbox/Outbox persist handoff evidence independently of execution History; ASGI host owns service lifetime.

**Tech Stack:** Python3.11+, httpx/jsonschema base, optional psycopg/Temporal/uvicorn.

**Spec:** [async-handoff-design](../specs/2026-10-07-async-handoff-design.md).

## Global constraints

- No new base dependencies; postgres/server/temporal extras stay optional.
- Retain existing12 starter dictionaries and legal Run/request/Manifest identities.
- Trusted Scope before/after each control; no lazy completion or unrecorded dispatch.
- Capacity10000default, configurable1..1000000; pending/flush pages1..1000.
- Real-service evidence, one fresh review, final wheel/sdist/upgrade checks; stop temporary services.

## Review focus

- Cancelled caller during remote submit: shared inbox still repairs with original command identity.
- Two server processes race on accept/complete: originalRun and immutable receipt retained.
- Control implementations drift while awaiting: reject before another call/wakeup.
- PostgreSQL transport/close failure: no sensitive SQL/credentials leak, cleanup retriable.
- Host shutdown during real local handler: wait before coordinator release.

### Task1: Completed task controls and async A2A

Files: new src/ralf_agent/task_controls.py, tests/test_task_controls.py, tests/test_a2a_async.py; modify a2a.py/__init__.py.

Interfaces: SyncTaskControls/AsyncTaskControls and TaskControlBridge(engine, scope); async submit/status/cancel return original typed SDK DTOs. A2A factory remains sync, returned authority may be nativeasync.

- [x] RED nativeasync send/get/cancel, Scope drift, wrongDTO and innercoroutine return; verify existing sync path.
- [x] Implement pinned borrowed bridge and await calls in A2A; same auth/dedup/polling behavior.
- [x] GREEN task controls + A2A + ToolSource contracts and actual Temporal bridge tests.

### Task2: Shared PostgreSQL Inbox/Outbox

Files: new postgres_handoff.py/test_postgres_handoff.py/handoff_pg_crash_fixture.py; modify exports.

Interfaces: PostgresInbox/PostgresOutbox.connect(dsn, backend_id=..., max_entries=10000), initialize/aclose; asyncexistingports unchanged.

- [x] RED missing adapter plus actual PG two-connection receive/dedup/capacity/immutable complete, safeerrors, ownership.
- [x] Implement explicit tables/atomic scope lock/finite validation; outbox commits publication evidence after broker reply.
- [x] GREEN real Redis replay/claim with PGInbox; actual process exit after authority accepted and after publication.

### Task3: Installed A2A service composition

Files: new a2a_starter.py/service_lifecycle.py/test_a2a_starter.py/test_service_lifecycle.py; modify starter/CLI help, fixtures and docs/CI/dev16 metadata.

Interfaces: a2a starter's host lifespan tracked drive/real handler drain, borrowed gateway; shared Temporal/PG example through sameApplication.

- [x] RED installed starter unavailable, realHTTP run/dedup/restart/cancel and closewhilehandleractive.
- [x] Implement minimal offline default service plus explicit auth configuration, trackedhostlifecycle and sharedbackend example.
- [x] GREEN actual twoHTTP process+Temporal+Postgres same message/kill before inbox complete and originalreceipt repair; installedstarter/conformance.

### Final gates

- [x] One independent review; Important findings fixed RED→GREEN, no second reviewer.
- [x] Full actual-services suite and installed contracts, dev15 compatibility12templates/native/flat/DAG/nested, metadata/optionalimport and SDKbyte equality.
- [x] Docs/quality checks and truthful boundaries; stop services; no paid model calls without resolved configuration.
