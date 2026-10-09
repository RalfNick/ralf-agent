# H2a: Local Agent entry, hosting and observation

Approved architecture: [Facade contract](../../../architecture/specs/agent-facade-session-contract.md).
Deliver the Local stateless entry/hosting/closing subset first. Existing nine Local
bindings are sufficient; environment and stage roles need H3/H4, and Temporal
bindings need their own backend gates. This does not complete H1 or H2.

## Objects and invariants

- AgentHarness freezes an existing native/bound Agent/Workflow/Graph/Team/Dynamic
  declaration and exposes detached definitions. It composes declarations; existing
  Harness remains a pure DecisionPolicy. No extra Run state machine or hidden I/O.
- Runtime hosts one LocalEngine or Local RuntimeInstance in one event loop.
  Injected engines default borrowed; from_profile and standalone Agent own their
  created resources. Factories and legacy engine behavior remain unchanged.
- Agent is an async application entry. runtime.create_agent borrows Runtime;
  standalone Agent(model=..., tools=..., db_path=...) creates an owned Runtime.
  command_id is required; no implicit retry with a different command identity.
- AgentRun is the online handle; preserve existing RunHandle DTO/import.
  RunRef fixes authority_locator, Scope, run_id, release_digest and schema_version=1.
  authority_locator is a non-secret digest of the stable store backend identity,
  or a trusted explicit bounded opaque identifier for custom stores.
- attach validates Scope/authority/release but only observes; resume and controls
  explicitly wake the owned supervisor. Existing command receipts remain exact.
- submit calls the durable authority then schedules a strongly owned drive task
  before yielding. Restart recovery is explicit resume of existing queued intent.
  No business progress is inferred from task bookkeeping.
- wait polls only committed status; default returns terminal/human waiting states.
  wait_timeout is observation-only; cancellation never cancels hosted drive.
  terminal_only waits through human pauses. Host failure is explicit, preserving
  the original business state and reference; absent hosting requires timeout or
  explicit resume. No automatic drive from status/attach/wait.
- close defaults drain, timeout30s; it blocks new accepts, retains controls, waits
  hosted tasks plus actual framework-managed threads, then closes only owned
  resources. Human pauses are parked and reported as RunRefs. Borrowed Agent
  close does not close Runtime or business work. Closed live handles refuse access.
- close_timeout/cancelled close waits never cancel the cleanup task. CloseIncomplete
  retains refs and a retryable quiescing runtime. Explicit cancel policy submits
  stable cancellation commands and waits actual exit. Unsupported handoff refused.
  Body exceptions remain primary with closing failure chained or noted.
- No completed-history task/lock retention: only active/paused/failed-host refs
  remain managed. Completed handles live in the application, not Runtime history.

## Explicit boundaries

Shared session_id, Turn queue/rebind, business deadline and Temporal/custom async
authority are refused before acceptance. Per-Run legacy Session storage remains
unchanged; this is not a durable Session facade. No H3 automatic stages, sandbox,
global capacity, UI or monetary ceiling is claimed. Capabilities report these facts.

## Verification

Real LocalEngine/SQLite tests: waiter timeout/cancel leaves work running; explicit
cancel/approval/reconcile wakes original Run; duplicate submits start one task;
parked approval and unknown effects survive owned close and reattach; borrowed
Agent/Engine remain usable; closing timeout/cancel/storage failure preserves
resources and retry; missing release causes no paid call; wrong Scope/authority
refused; graph/team/dynamic/bound definitions route unchanged; hundreds of terminal
tasks leave no retained history. Install actual dev30/dev31 wheels, recover old
approved actions with original receipts and one business effect. Full suite,
Ruff/format/whitespace, one independent final review, package/source byte checks.
