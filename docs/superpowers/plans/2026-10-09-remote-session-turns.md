# Remote Session Turns Implementation Plan

> Use superpowers:executing-plans inline, TDD, one fresh final reviewer. User requests
> continuous implementation and verified local commits without approval stops.

**Goal:** Durable native/sequence Turns with replaceable remote Session data.
**Architecture:** Keep Local admission/Run authority; journal required remote save
intent and receipt. Explicit resume reconciles source evidence, never replays tools.
**Tech Stack:** Existing Python/SQLite/async Redis/psycopg, no dependencies.
**Spec:** docs/superpowers/specs/2026-10-09-remote-session-turns.md

## Global Constraints

Baseline1f27300/dev37; current checkout. Own private workspace only; capture old
wheel before edits. Keep defaults/schema1/2/3/4,294 exports and21 starters. No paid
calls, secret dumps, remote push or repeated approval stops. Commit verified stages.

## Review Focus

1. Acknowledgement alone must not mean saved output; malformed/missing/cross-scope
   receipts and metadata loss must never silently downgrade or produce success.
2. Lost append response, lost local commit or restart must reuse original message,
   adopted model output and business receipts without another write/tool attempt.
3. Caller/whole-loop cancellation and terminal unknowns cannot release busy lanes
   or actual handlers; terminal recovery never upgrades failure/cancellation.
4. Raw/bound alias paths must respect remote registered addresses; mismatched
   sequence resources/ref revision and custom lazy activation refuse atomically.
5. Colocated defaults/member bindings and actual old schemas/receipts remain
   compatible; unavailable remote services do not become a delivery claim.

### Task 1: Bounded remote inspection contract

**Files:** new session_receipts.py, tests/remote_session_fixture.py,
tests/test_session_receipts.py; modify binding_sessions.py/redis_memory.py/postgres.py.
**Interfaces:** supports_remote_session(backend)->bool;
validate_inspection(value,scope,address,message_id)->detached dict;
async inspect_message(scope,address,message_id)->scoped revision/receipt snapshot.

- [ ] RED exact missing/matching receipts from real foreign SQLite fixture;
  malformed revisions/Scope/address/payload/lazy returns reject.
  ```python
  snapshot = await backend.inspect_message(scope, "s", "m")
  assert snapshot["revision"] == 1
  assert snapshot["receipt"]["message"] == {"role": "assistant", "content": "answer"}
  ```
- [ ] Implement strict finite JSON validation and SessionView namespace delegation;
  Redis atomic LLEN/HGET/LINDEX, PG revision/receipt in original scoped transaction.
- [ ] GREEN contract and current Redis/PG/namespace suites; expect pass or explicit
  configured-service skips. task-done records actual gate.

### Task 2: Admission and required save recovery

**Files:** new remote_session_saves.py, test_remote_session_turns.py and
test_remote_session_recovery.py; modify local_sessions/session_ports/sqlite_sessions/
storage/engine/agent_runtime.py.
**Interfaces:** optional prepare_remote_sessions()->None, marker4/schema5;
check_remote_session_run(engine,run)->None;
await save_remote_result(engine,run_id,result)->bool;
await reconcile_terminal_saves(engine,run_id)->None; pure receipt eligibility.

- [ ] RED native/sequence actual remote-data Turns, namespace/alias/restart approval;
  append commits then raises, malformed receipt and metadata loss; current open
  refuses non-colocated stores. No model/tool dispatch on rejected admission.
- [ ] Pin remote descriptor in binding and admitted Run, conservative routes and
  optional transactional schema5. Journal intent/attempt/validated receipt;
  pause on unavailable confirmation and return False to stop this drive.
- [ ] GREEN recovery/cancel/receipt/config/default/session/binding suites.
  ```python
  first = await session.submit("q", command_id="one")
  # append committed remotely but acknowledgement failed
  assert (await first.wait()).snapshot.state == "waiting_reconciliation"
  resumed = await runtime.resume(first.ref)
  assert (await resumed.wait()).snapshot.state == "succeeded"
  ```
- [ ] task-done; full pending recovery keeps original authority/lifecycle.

### Task 3: Distribution, services and checkpoint

**Files:** dev38 init/pyproject/current docs/checklist and public review record.
**Interfaces:** original Redis/PG factories and remote receipt port; actual old/new
schema1/2/3/4 compatibility, old5 refusal/new recovery and installed contracts.

- [ ] Build/install actual distributions; default21 starters identical,294 exports
  optional-free, source/package bytes and credential hygiene pass.
- [ ] Run locally configured Redis/PG probes with actual CAS/receipt/restart; absent
  services explicit skips. No paid-model quality claim.
- [ ] Fresh read-only reviewer; grade actual effects, one Important/Critical TDD fix
  pass, no re-review; ledger all scope rulings/minor deferrals.
- [ ] Full pytest -W error, installed contracts, lint/format/links/whitespace pass;
  record actual evidence, commit locally and continue the next capability.
