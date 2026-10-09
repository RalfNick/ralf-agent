# Agent Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, test-driven-development for each task.

**Goal:** Implement real, replaceable per-Agent execution caps under mandatory host restrictions.
**Architecture:** Pure limits proposal plus accepted manifest snapshot, shared Local execution enforcement and H1 bindings. No third authority or hidden I/O.
**Tech Stack:** Python3.11+, existing asyncio/SQLite/jsonschema/pytest/Ruff; no new dependency.
**Spec:** docs/superpowers/specs/2026-10-08-agent-limits.md

## Global Constraints

- Preserve all accumulated dirty changes; no commits/push/publish/worktree cleanup.
- Local-only numeric caps: decisions, context characters, adopted tool Actions. No enterprise capacity/real cost claim.
- No live model calls needed for deterministic quota validation; prior model reports remain unchanged.
- Snapshot actual dev29 SDK and wheel before production edits into this plan's private workspace.

## Review Focus

- Selected ref/disabled or looser Spec cannot relax mandatory host limits.
- Stateful/mutated policy alternates proposals between check and use: execution uses accepted caps and drift refuses before paid dispatch.
- Over-limit multi-tool batch is atomic; unknown/recovered Action counts once, sibling nodes/children cannot consume each other's quota.
- Tiny context caps are enforced at admission/graph preparation and final prepared request; policy cannot mutate a shared Spec Schema.
- Real old wheel refuses new selected limits before dispatch while original old approvals retain request/release/control receipts.

### Task 1: Pure limits proposal and snapshot

**Files:** Create src/ralf_agent/agent_limits.py and tests/test_agent_limits.py.
**Interfaces:** AgentLimitProposal(max_decisions=None,max_context_chars=None,max_tool_actions=None), AgentLimitsPolicy.propose(AgentSpec), FixedAgentLimits; limit_manifest(engine,steps,selected), apply_pinned_limits(step,manifest), tool_action_limit(step,manifest).

- [x] Write pure RED tests: integer/bool/None boundaries, proposal immutability/detachment, host+selected+Spec minimum, disabled leaves host, duplicate inputs with differing results, unsupported/lazy returns, actual identity mutation.
- [x] Run `.venv/bin/python -m pytest tests/test_agent_limits.py -q`; expected missing API FAIL.
- [x] Implement strict DTO/default and pure resolution. Snapshot caps by original effective step digest; applying stored caps never calls policies.
- [x] Run whole pure module; expected PASS.

### Task 2: Local enforcement, binding and assembly

**Files:** Modify engine.py/binding_runtime/catalog.py/workflow_runtime.py/node_execution.py/runtime_config/builder.py/exports/errors.py. Create tests/test_limit_execution.py/tests/test_limit_bindings.py.
**Interfaces:** LocalEngine(limits=None) mandatory host; limits ref/disabled optional selection; local-bindings-6; policy and fixed caps in agent_limits manifest.

- [x] Write RED behavioral tests: fewer decisions with completion retries, initial/custom-Harness context cap before dispatch, over-limit tool batch zero writes/zero proposed Actions, exact quota successful approval and restart, accepted caps used despite oscillating policy; per-path composite routing and quota isolation; Profile sync/async factories and unknown ref/selector refusal.
- [x] Run both modules and observe missing support failures.
- [x] Wire fixed snapshots into effective step, native admission and graph preparation. Check complete batch before Action proposals. Add strict registry factories and preserve legacy no-limits manifests.
- [x] Run three new modules plus binding/composite/completion suites; expected PASS. Record actual results.

### Task 3: Default tutorial, package/upgrade evidence and final review

**Files:** docs/agent-limits.md, current status/checklist/architecture contract, dev30 version/change notes.
**Interfaces:** easy FixedAgentLimits injection, custom pure policy, declarative configuration; real installed old/new evidence.

- [x] Document delivered bounds and exclusions; build wheel/sdist `--no-isolation`.
- [x] Full pytest with localhost fixture authorization, Ruff/format/Git whitespace. Expected all configured tests PASS, unconfigured service cases skipped.
- [x] Install real old/new wheels outside checkout, run new contracts; create old approvals and recover with fixed request/manifest/receipts/effects; old refuses new limits. Verify source/wheel/sdist/installed SDK bytes and private artifact exclusion.
- [x] One fresh final read-only reviewer required by executing-plans; grade actual behavior, one TDD fix pass for important findings, record minors.
- [x] Completion attests actual logs and package identity, preserves local evidence. No remote writes.
