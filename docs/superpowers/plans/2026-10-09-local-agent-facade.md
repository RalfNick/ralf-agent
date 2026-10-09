# Local Agent Facade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans inline, test-driven-development.

**Goal:** Deliver H2a Local application entry with independent hosting, pure observation and recoverable closing.
**Architecture:** AgentHarness freezes declarations; Runtime/Supervisor host existing Local authority; AgentRun/RunRef observe/control its committed facts. No extra business state machine.
**Tech Stack:** Python3.11+, asyncio, existing SQLite/ports/factories; no dependencies.
**Spec:** docs/superpowers/specs/2026-10-09-local-agent-facade.md

## Global Constraints

- Preserve legacy public Harness/RunHandle/Engine signatures and release/request identities.
- Local stateless scope only; session/deadline/queue/handoff unsupported before acceptance.
- User approved existing ideal architecture and continued implementation; no repeated approval gates, commit/push or worktree switching.
- Own private workspace only; capture dev30 SDK and wheel before production edits.
- No paid model calls for deterministic hosting; preserve historical quality reports.

## Review Focus

- Cancelled/timeout observers cannot propagate to real drive, its tools or shutdown task.
- Actual threads and late evidence retain ownership even after outer task cancellation.
- Scope/authority/release mismatch refuses before observation/control/paid dispatch.
- Shared Agent closes only its entry; resource close failures remain retryable and body exceptions visible.
- Existing native large Schema/bound/nested encodings and original receipts survive wrapping and installed upgrade.

### Task 1: Immutable composition and locator

**Files:** Create agent_harness.py, agent_run.py, tests/test_agent_harness.py; exports/errors additive.
**Interfaces:** AgentHarness(definition).definition/.identity; RunRef(authority_locator,workspace,principal,run_id,release_digest).to_dict/from_dict; WaitResult(ref,snapshot,wait_reason,observed_at).

- [x] RED: `api()` asserts new public APIs exist; mutate original Schema and returned definition, then assert Harness original is fixed. Parametrize native/sequence/graph/team/dynamic/bound and 1.1MiB native Schema. Ref round-trip; bool schema_version/invalid digests/unknown keys refused.
- [x] Run `.venv/bin/python -m pytest tests/test_agent_harness.py -q`; expect missing APIs FAIL.
- [x] Freeze submission declaration via existing codecs; preserve native/sequence reconstruction without new size restriction; implement strict locators/results and exports.
- [x] Re-run whole module, expect PASS; ledger Task1 result.

### Task 2: Hosted Runtime and application API

**Files:** Create run_supervisor.py, agent_runtime.py, agent.py; tests/test_agent_runtime.py/test_agent_lifecycle.py; extend errors/exports.
**Interfaces:** Runtime(engine,owned=False,authority_locator=None,close_timeout=30,close_policy='drain'); Runtime.from_profile/afrom_profile; create_agent/attach/resume/aclose. Agent(runtime=...,definition=...) or standalone model/tools/db_path; async submit/run/aclose. AgentRun.status/wait/approve/cancel/reconcile/events/resume.

- [x] RED with actual SQLite: delayed Provider signals started, timeout/cancel wait, release it, expect succeeded/no run_cancelled; duplicate submit only one model call; unsupported session/deadline before no Run.
- [x] RED: approval park/close/new Runtime attach/status no model call, then approve/resume succeeds with one write; scoped/mismatched locator refusal; graph/team/dynamic/bound preserve results.
- [x] RED: threading.Event tool waits, close_timeout raises CloseIncomplete and new Coordinator refused; release thread then retry closes. Cancel close waiter preserves cleanup; borrowed Agent/Engine usable; owned close failure retry and original body error preserved; 100 terminal tasks leave no managed history.
- [x] Run both modules, expect missing API/behavior FAIL. Implement Supervisor task ownership/exception observation and lifecycle helpers, then facade forwarding with strict preflight and detach/drain semantics.
- [x] Run new modules plus legacy runtime/service/lifecycle/binding tests; expect PASS and ledger result.

### Task 3: Installed chain, docs and final evidence

**Files:** docs/agent-api.md; current architecture/status/checklist/version dev31; review record.
**Interfaces:** standalone Basic and shared Runtime examples; existing specs are usable with explicit H2a capability refusal.

- [x] Document exact implemented subset and next H2b durable Session/Turn; fix review's stale README/baseline labels.
- [x] Build/install actual wheel outside checkout. Run facade/legacy contracts there and upgrade actual old approval through new Runtime with receipt/effect identity assertions.
- [x] Full pytest, Ruff, format, whitespace and source/wheel/sdist/installed byte/secret exclusions; expect configured checks pass, service-dependent tests explicitly skipped.
- [x] One fresh read-only final reviewer; Important findings one TDD fix pass plus green suite; record remaining Minor/Declined items.
- [x] Final evidence attestation/task-done, preserve local records; no remote writes or full-H2/AgentScope claim.
