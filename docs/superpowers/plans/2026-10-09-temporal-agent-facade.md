# Temporal Agent Facade Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline and test-driven-development; one fresh final reviewer.

**Goal:** Deliver H2c1 native/sequence Temporal through the shared Agent facade, preserving Local and original History contracts.
**Architecture:** Add async Runtime observation/control hooks, a private Temporal Runtime specialization and strongly-owned outbound RPC tasks. History remains the sole remote business authority.
**Tech Stack:** Python3.11+, asyncio, existing optional Temporal SDK; no dependencies added.
**Spec:** docs/superpowers/specs/2026-10-09-temporal-agent-facade.md

## Global Constraints

- Preserve all dev31/dev32 dirty changes; no automatic commit/push/worktree switch, paid model calls or unrelated private workspace reads.
- Snapshot 144-module dev32 SDK and actual old wheel in this plan's own private workspace before SDK modifications.
- Remote native/sequence only; async reference/attachment; close_policy='detach' only; borrowed Client/Workers.
- Preserve existing RunHandle, schema1/schema2, release/command IDs and Local Session/hosting semantics.
- Continue approved architecture inline without repeated approval gates; retain private evidence until explicitly integrated.

## Review Focus

- Caller cancellation during submission must not strand accepted intent or cancel the server Run; original command replay remains unique.
- Mutated input, client/namespace/Scope or moved release defaults must not silently change accepted identity or controls.
- Slow remote query timeout uses an actual prior observation and leaves business commands unchanged.
- Close timeout, body cancellation and owned close failures preserve RPC cleanup and borrowed Client/Workers.
- Unsupported definitions and malformed async responses refuse before partial acceptance/control, without Local regressions.

### Task 1: Shared async facade hooks and Temporal entry

**Files:** modify agent_runtime.py; create temporal_agent_runtime.py and rpc_supervisor.py; test test_temporal_agent_runtime.py.
**Interfaces:** Runtime.from_temporal/areference/aattach, _aobserve/_apending/_acontrol/_await_root/_check_wait_errors; internal Temporal client Runtime returns AgentRun subclasses with cached observations.

- [x] RED using a real TemporalRunState RPC fixture: factory missing; submit→waiting_approval→approve→succeeded; duplicate submit/control exact receipts; two-step sequence; same shared Agent API.
```python
runtime = Runtime.from_temporal(engine)
agent = runtime.create_agent(AgentSpec("a", "Answer"))
run = await agent.submit("q", command_id="submit")
observed = await run.wait(wait_timeout=1)
assert observed.snapshot.state == "waiting_approval"
```
- [x] RED common Local areference/aattach preserve original refs and no drive; remote wrong Scope/locator/release/closed facade and composite/session/queue/deadline reject without commands.
- [x] Implement common async hooks without changing Local validation/control/supervisor semantics; specialize remote native query validation, pinned endpoint/namespace locator and submit/resume/control RPC ownership.
- [x] Run new file plus Local facade/Session/Temporal state suites; expect PASS and record Task1 via task-done.

### Task 2: Observation deadlines and client lifecycle

**Files:** temporal_agent_runtime.py/rpc_supervisor.py, tests/test_temporal_agent_lifecycle.py.
**Interfaces:** managed RPC task set/drain; timeout returns cached validated WaitResult with original observed_at; Runtime detach flushes RPC then owned engine facade.

- [x] RED cancelled submit remains held until RPC completes; immutable input; wait cancellation/blocked query timeout makes no drive/cancel; returned snapshot mutation cannot affect cached observation.
```python
observer = asyncio.create_task(run.wait(wait_timeout=0.02))
answer = await observer
assert answer.wait_reason == "observation_timeout"
assert engine_command_count == before
```
- [x] RED close timeout/cancel wait keeps RPC task and cleanup, borrowed Client unchanged, owned close retry, wrong-loop caller leaves rightful loop cleanup, body exception primary; 100 completed requests leave no task/Run history.
- [x] Implement scoped RPC task ownership and detached validated observation cache, monotonic deadlines and detach-only closure; record finite failure counts rather than error-object history.
- [x] Run Task1/2 plus Local lifecycle/Session/binding/service tests with warnings-as-errors; expect PASS and record Task2.

### Task 3: Actual service, installed compatibility, docs and review

**Files:** tests/test_temporal_agent_service.py, docs/temporal-agent-api.md; current dev33 docs/design/checklist/review.
**Interfaces:** actual persisted Service/Worker/History proof and old/new wheel Local schema1/schema2 recovery; clear native-only remote capability matrix.

- [x] Run explicit actual Service offline-provider probe for approval/replay, observer cancellation, client detach/reconnect and History replay; record actual success or unavailable status.
- [x] Build/install actual dev33 wheel outside checkout; execute new facade and Local contracts; old dev32 Sessions/recovery retain original bindings/receipts/effect1; old SDK still supports schema2, new facade does not alter History schema.
- [x] Update guide and all current status/design/remaining docs, preserving historical snapshots and recording subset/async attachment/detach/cached-timeout limitations.
- [x] One most-capable fresh read-only reviewer against captured dev32→dev33; Important/Critical one TDD fix pass, no re-review. Final full pytest -Werror, Ruff/format/whitespace, module/package/credential exclusions, optional imports, dependencies and20 starter maps pass.
- [x] Attest frozen SDK/log/package evidence with task-done, keep local changes/evidence, no paid/parity/publication claims.
