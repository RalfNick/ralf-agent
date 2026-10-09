# Local Session/Turn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans inline and test-driven-development.

**Goal:** Deliver H2b1 colocated durable native/sequence Sessions with original release recovery.
**Architecture:** Optional authority-bound admission store, shared first acceptance, durable route/Turn records and pure Session handles. Raw native contracts remain unchanged absent activation.
**Tech Stack:** Python3.11+, asyncio, existing SQLite/command transactions; no dependencies.
**Spec:** docs/superpowers/specs/2026-10-09-local-session-turns.md

## Global Constraints

- Preserve prior dirty dev31, legacy APIs/Run receipts; no automatic commit/push/worktree switch.
- Capture current139-module dev31 SDK and actual wheel in this plan's own private workspace before product changes; never inspect sibling private workspaces.
- Local colocated SQLite native/sequence only; fail closed for remote/mixed/composite Session resources and schema2 downgrade.
- Explicit open_session/SessionRef and original command_id; no implicit model retry or dynamic binding upgrade.
- User authorized existing roadmap continuation inline; written design/plan refine its declared next stage, no repeat approval gates.

## Review Focus

- Historical command replay under moved defaults or stale Session handles returns the exact original outcome.
- Failed admissions cannot partly allocate Run/Turn/seq/route or migrate Schema, including custom adapter failures.
- Terminal cancellation with actual handler/unknown effects cannot free occupancy or bypass it via raw submit.
- Same actual namespace address and execution-store aliases cannot register multiple routes; Scope/Ref mismatches refuse.
- Old SDKs reject activated Schema before dispatch while ordinary native schema1 upgrades stay compatible.

### Task 1: Durable identity, optional store and shared acceptance

**Files:** create session_types.py/sqlite_sessions.py/session_ports.py; modify storage.py/engine.py; test test_session_admission.py.
**Interfaces:** SessionKey/SessionRef/TurnAdmission DTOs; SQLiteSessionAdmission(store) bound optional port; LocalEngine._accept_submission(run_id,payload,parent_call=None) produces the old acceptance outcome.

- [x] RED DTO/key/ref roundtrip, bool revisions/unknown fields/credential locators rejected; adapter prepare within rollback leaves schema1 and no tables; after prepare schema2 reads and rejects invalid versions.
```python
with store.transaction():
    admission.prepare()
    admission.insert(record)
    raise RuntimeError("rollback")
assert (
    store.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] == "1"
)
```
- [x] Run `.venv/bin/python -m pytest tests/test_session_admission.py -q`; expect missing DTO/factory FAIL.
- [x] Implement immutable bounded DTOs, port and indexed SQL Session/Turn CAS, feature activation and raw address guard; extract existing acceptance body without changing raw request/receipt/Manifest.
- [x] Run module plus storage/runtime/Session binding regressions, expected PASS; ledger via task-done.

### Task 2: Authority-backed Session entry and controls

**Files:** create local_sessions.py/agent_session.py; modify agent.py/agent_runtime.py/errors.py/exports; tests test_agent_sessions.py/test_session_recovery.py.
**Interfaces:** LocalSessionAuthority.open/submit/rebind/status/turns, Agent.open_session/Runtime.attach_session, AgentSession.submit/run/status/rebind/turns/aclose; AgentRun.turn.

- [x] RED sequential actual SQLite Turns retain history and seq1/2; same command returns original Turn; status/turns do not mutate command/event/model counts.
```python
session = await agent.open_session("customer", command_id="open")
one = await session.run("first", command_id="one", wait_timeout=1)
two = await session.run("second", command_id="two", wait_timeout=1)
assert [x.turn_seq for x in await session.turns()] == [1, 2]
```
- [x] RED approval/close/restart busy returns identical rejection/old RunRef and creates no extra Run; approve original then replay still rejects, new command starts next Turn; moved default replay original, new input fails, idle CAS rebind works and old handles reject.
- [x] RED terminal unknown or blocking thread holds occupancy; actual exit/reconcile releases; aliases/Scope/ref drift/raw bypass fail; unsupported remote/mixed/composite routes no acceptance; delegating admission adapter remains injectable.
- [x] Run new modules expected missing APIs/semantics FAIL; implement authority command callbacks using shared acceptance and an authority-local scoped permit, exact manifest pinning and quiescence/save gate.
- [x] Run new modules plus H2a and binding/orchestration lifecycle regressions expected PASS; ledger Task2.

### Task 3: Packaging, compatibility, documentation and final review

**Files:** docs/session-api.md; current status/checklist/design/guide/dev32 and review record.
**Interfaces:** installed explicit Session entry with truthful H2b1 capability matrix, actual old/new wheel Schema1/Schema2 compatibility.

- [x] Document native/sequence/colocated subset, Schema2 activation and older SDK refusal, original receipts, busy/rebind/reconnect and remote limitations.
- [x] Build/install actual old/current wheels, run outside checkout new Session and H2a/legacy contracts; recover old native approval unchanged and verify activated DB refuses old wheel before model/tool dispatch.
- [x] Full pytest -Werror, Ruff/format/whitespace, package byte/credential/exclusion and unchanged starters/dependency checks; expected PASS with service skips explicitly reported.
- [x] One fresh read-only reviewer; grade behavior; Important/Critical one TDD fix pass plus green full suite; no re-review.
- [x] Attest final evidence/task-done, keep source/evidence local, no paid calls or full H2b/AgentScope claim.
