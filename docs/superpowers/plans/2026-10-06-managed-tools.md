# Managed Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver replaceable MCP tool sources and managed async/sync graph Tool nodes, retaining durable governance.

**Architecture:** Sources feed fixed descriptors into ToolRegistry. Tool nodes reuse existing Actions, executor receiving/adoption and effect ownership. Default stdio owns/reaps a per-operation process group under the actual worker tracker.

**Tech Stack:** Python >=3.11, existing jsonschema/httpx, POSIX subprocess/selectors; no new runtime dependency.

**Spec:** [managed-tools-design.md](../specs/2026-10-06-managed-tools-design.md)

## Global Constraints

Package 0.1.0.dev11; old local-4/ExecutionStore v1 and plan v1 identities unchanged. Tool plans use v2. Maximum 256 tools/32 pages, 1 MiB/message, 100 unsolicited messages/response, timeout 0 < value <= 300. Pure transforms retain the existing contract. No implicit credentials or shell invocation.

## Review Focus

- Cancelled event loop must not free execution authority while MCP child/worker is alive.
- Tool discovery name collision or late invalid policy must not partially register tools.
- Reserved idempotency keys must not be user-controlled or omitted from remote writes.
- Remote Schema/identity changes must not silently execute an old approval.
- Existing installed dev10 Graph/native records must keep exact receipt/manifest identity.

### Task 1: Managed remote tool path

**Files:** create `src/ralf_agent/tool_sources.py`, `src/ralf_agent/mcp.py`, `src/ralf_agent/mcp_stdio.py`; modify tools, workflow, workflow_runtime, engine and public facade. Create `tests/test_tool_sources.py`, `tests/test_mcp.py`, `tests/mcp_fixture.py`, `tests/test_workflow_tools.py`; add installed example and guides.

**Interfaces:** exact public constructors/async methods in the spec. Shared Action builder keeps model-generated and explicit Tool proposals identical. The existing _tool method remains execution authority.

- [x] Write source registration/policy tests; run `.venv/bin/python -m pytest -q tests/test_tool_sources.py`, expected missing public interfaces assertions.
- [x] Implement descriptor/policy/source and atomic registry registration; run source tests, expected passing selected registration, immutable snapshots, reserved key, custom source and source drift cases.
- [x] Write real MCP subprocess tests; run `tests/test_mcp.py`, expected absent transport/source assertions.
- [x] Implement replaceable MCP normalization and bounded one-shot stdio; run source/MCP suites, expected real protocol/error/timeout/reaping/worker-ownership cases pass.
- [x] Write direct Tool-node integration tests; run `tests/test_workflow_tools.py`, expected unsupported tool argument/plan assertions.
- [x] Implement v2 plan/Tool-node execution via shared Action builder; run related Workflow/executor/runtime suites, expected approval/recovery/cancel/budget/output and v1 compatibility pass.
- [x] Deliver package-contained example/guide and dev11; full `.venv/bin/python -m pytest -q -W error`, Ruff lint/format, Git whitespace and documentation checks pass.
- [x] Build/install outside checkout; run example with no Provider and actual dev10-to-dev11 native/Graph identity replay. Commit, obtain a fresh independent review, fix material findings with RED→GREEN and full suite, record evidence and scope decisions.
