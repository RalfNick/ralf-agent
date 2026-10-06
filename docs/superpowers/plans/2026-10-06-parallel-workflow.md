# Bounded Parallel Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute independent static graph nodes concurrently under one durable Run and shared governance.

**Architecture:** A pure scheduler proposes eligible nodes; isolated node frames reuse native execution via a transactional store view. One supervisor plus explicit worker/real-thread ownership protects the parent Coordinator.

**Tech Stack:** Python >=3.11, asyncio, existing ExecutionStore/jsonschema; no new dependency.

**Spec:** [parallel-workflow-design.md](../specs/2026-10-06-parallel-workflow-design.md)

## Global Constraints

Package 0.1.0.dev12. max_concurrency is an integer 1..32; default 1 omits the field and retains legacy v1/v2 identities. Explicit parallel plans use v3. No new SQLite/ExecutionStore Schema. Capacity is per Run. Sessions isolate by parent Session/node ID. Preserve received evidence and unknown effects; do not perform automatic migrations.

## Review Focus

- A blocked/failing/cancelled branch must not overwrite sibling progress or free ownership early.
- Approval/reconciliation during another branch's await must reach the correct frame and messages.
- Concurrent Session appends must not lose messages or create implicit cross-branch context.
- Old persisted serial receipts/manifests must remain exact after upgrade.
- Custom scheduler can reorder ready nodes but cannot invent binding values, skip required work or exceed capacity.

### Task 1: Isolated bounded graph execution

**Files:** create `src/ralf_agent/workflow_scheduler.py`, `src/ralf_agent/workflow_parallel.py`, `src/ralf_agent/node_execution.py`; modify workflow/runtime/engine/profile assembly/CLI facade. Add `tests/test_workflow_scheduler.py`, `tests/test_parallel_workflow.py`, crash fixture and installed starter tests; docs and version.

**Interfaces:** constructors/pure scheduler in the spec; internal node view forwards authority operations and maps only branch data. Existing model/tool receiving/adoption and Action identity remain authoritative.

- [ ] Write plan/scheduler regressions; run `.venv/bin/python -m pytest -q tests/test_workflow_scheduler.py`, expected missing public API/parallel field failures.
- [ ] Implement canonical v3 plans and validated pure batch scheduler; run the same file and existing Workflow unit tests, expected pass.
- [ ] Write barrier-based engine/governance/ownership/crash regressions before execution code; run `tests/test_parallel_workflow.py`, expected serial singleton/unsupported runtime failures.
- [ ] Implement transactional node frames, controls and bounded supervisor; run related Agent/Tool/Workflow/lifecycle suites, expected no lost sibling progress, shared credits and evidence preservation.
- [ ] Write adoption/starter/config tests; deliver default factory/CLI inspection/packaged parallel starter and guide. Update dev12 support matrix without broader claims.
- [ ] Full `.venv/bin/python -m pytest -q -W error`, Ruff/format/whitespace/docs checks; build/install outside checkout and actual dev11-to-dev12 receipt/manifest replay, expected pass.
- [ ] Commit, dispatch one fresh read-only reviewer, fix material findings with RED→GREEN and full suite, record evidence and scoped rulings; keep local branch.
