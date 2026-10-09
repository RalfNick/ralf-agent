# Local Composite Session Turns Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline with test-driven-development and one fresh final reviewer. Track steps in this plan and its own ledger.

**Goal:** H2b2 colocated Local composite conversations with durable Turns and safe occupancy.
**Architecture:** Extend existing admission/publication and original graph/orchestration final-success transactions. A private module holds composite publication and final-save rules; no new execution state machine.
**Tech Stack:** Python3.11+, existing SQLite/asyncio; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-09-local-composite-session-turns.md

## Global Constraints

- Base is the user's explicit dev34 local commit5626c17; no auto push or dev35 commit.
- Own private workspace only; capture actual dev34 wheel/SDK before SDK changes.
- Native/schema1/schema2 and original raw Session behavior remain compatible; new composite routes opt in Schema3 atomically and monotonically.
- Root conversation requires actual colocated plain SQLiteMemory/namespaceNone; members retain their own bindings. No implicit input rewriting.
- Completed port values only; existing authority transaction and stable result ID; no SQLiteMemory construction within transactions.
- Continue approved architecture/spec/plan inline without repeated permission gates, preserve local evidence.

## Review Focus

1. A terminal parent with active/unknown descendants or graph-frame effects must stay busy across restart.
2. Final save and success must share a real transaction; lazy append/port, store commit failure or changed release cannot claim success.
3. Moved defaults and rebind cannot alter original Turn/child release or free another storage address; duplicate rejection receipts remain stable.
4. Old SDKs must refuse Schema3, new preparation must never downgrade it, failed open/rebind must not upgrade it.
5. Observation and shared Runtime close must preserve existing cancellation/ownership contracts; user-configured member Session isolation remains real.

### Task 1: Composite admission and atomic root result

**Files:** create src/ralf_agent/session_composites.py; modify local_sessions.py, session_ports.py, sqlite_sessions.py, storage.py, agent_runtime.py, workflow_runtime.py, workflow_parallel.py, orchestration.py; tests/test_composite_sessions.py.
**Interfaces:** optional prepare_composites()->None and session_admission_version=2; private composite_manifest(engine,definition), save_composite_turn_result(engine,run,result); same AgentSession and TurnAdmission DTOs.

- [x] RED with real SQLite/memory for graph/parallel/team/plan/DAG/nested ordered Turns and stable final content/IDs:
```python
session = await runtime.create_agent(definition).open_session("customer", command_id="open")
first = await session.submit("first", command_id="one", budget=64)
assert (await first.wait(wait_timeout=2)).snapshot.state == "succeeded"
assert not (await session.status()).busy
second = await session.submit("second", command_id="two", budget=64)
assert second.turn.turn_seq == 2
```
- [x] Implement existing manifest selection, optional extension/resource gating, Schema3 activation and atomic final save at all three composite-success boundaries. Verify actual persisted final message before success.
- [x] RED append failure/lazy return and outer transaction failure retain child/tool facts while final save/success roll back. Existing native/open/namespace rejection remains before partial acceptance.
- [x] Run new tests plus Session/graph/orchestration suites with -Werror; Expected: pass; task-done records result.

### Task 2: Descendant occupancy, recovery and rebind

**Files:** private session_composites.py/local_sessions.py/run_supervisor.py; tests/test_composite_session_recovery.py.
**Interfaces:** pure bounded descendant/frame blocker checks; atomic idle rebind uses optional composite preparation.

- [x] RED approval/busy replay, root cancel while real async/thread handler active, unknown descendant after restart, parallel-frame unknown tools and malformed ownership.
- [x] RED original manifest/receipt recovery after alias changes, native↔composite rebind, same-route enforcement, malformed/lazy optional port and monotonic/rolled-back Schema3 preparation.
```python
with pytest.raises(SessionBusy) as blocked:
    await session.submit("next", command_id="next")
assert blocked.value.run_ref == original.ref
# Cancel/timeout of an observer never applies a business control.
```
- [x] Implement bounded pure occupancy against existing authority records and true handlers; validate required root save before eligibility; preserve explicit original-root control routing.
- [x] Run new and native Session/facade/binding/lifecycle suites; Expected: pass; task-done records result.

### Task 3: Installed compatibility, docs and final review

**Files:** version dev35; docs/session-api.md and current status/design/checklist; architecture/reviews/2026-10-09-local-composite-session-turns.md.
**Interfaces:** actual old/new wheel schema1/2/3 recovery/refusal and honest capability subset.

- [x] Build/install outside checkout; old dev34 actual wheel recovers original1/2 and refuses3; new wheel restores3 original Turns/approval/effects. No dependency/export/starter drift or private artifacts in packages.
- [x] Document root/member conversation behavior, extension and transaction contract, busy semantics and Schema3 migration/refusal. Record all evidence/rulings and remaining full H2/H3.
- [x] One fresh most-capable read-only reviewer against5626c17 and own plan/spec/ledger; Important/Critical one RED→GREEN fix pass, no re-review.
- [x] Final full pytest -Werror, installed contracts, Ruff/format/whitespace and package/docs checks; Expected: pass. Task-done attests evidence; preserve local dev35 work without auto commit/push.
