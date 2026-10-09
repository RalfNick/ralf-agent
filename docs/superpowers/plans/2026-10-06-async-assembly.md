# Async assembly implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the current session.

**Goal:** Provide managed async component construction and cleanup without weakening local execution authority.
**Architecture:** Keep Store/Engine factories synchronous. Move resource ownership to a focused lifecycle module and expose additive async methods through the same registry and runtime facade.
**Tech Stack:** Python asyncio, existing SQLite/HTTP clients and pytest; no new dependency.
**Spec:** [async assembly design](../specs/2026-10-06-async-assembly-design.md).

## Global Constraints

- Python >=3.11; no new runtime dependencies.
- Package 0.1.0.dev13; preserve local-4, SQLite/ExecutionStore v1 and legal request identities.
- Preserve prior working-tree fixes and original seven starter dictionaries.
- Native implementation in this session; one independent read-only review after the complete increment. No remote publication.

## Review Focus

- A cancelled outer aclose must retain the real cleanup Task and consume late failures.
- A cached submit/drive method cannot accept new work once async shutdown starts.
- Wrong event loop must fail before engine closure; partial cleanup stays retriable.
- Cancelled construction must clean owned clients or return a usable cleanup handle.
- Synchronous ProfiledEngine/CLI must refuse async construction before allocating authority.

## Task 1: Managed resource lifetime and async assembly

**Files:** create src/ralf_agent/runtime_lifecycle.py and tests/test_async_runtime.py; modify ports.py, runtime_builder.py and __init__.py.
**Interfaces:** AsyncLifecycle.aclose; BuildContext.own_async; RuntimeInstance.aclose and async context; ComponentRegistry.register_async; RuntimeBuilder.abuild.

- [x] Write lifecycle, authority, cancellation, affinity and factory boundary tests; run and confirm expected failure.
- [x] Extract existing synchronous facade with unchanged public imports; implement additive managed async cleanup and loop checks.
- [x] Add explicit async registry and abuild with shared profile validation; keep sync Store/Engine contracts and default identity.
- [x] Run new tests plus builder/router/shutdown and extension suites; correct failures using RED→GREEN.

## Task 2: Installed first-use path and release evidence

**Files:** create async_starter.py and tests/test_async_starter.py; modify starter.py, CLI help, docs, README, CHANGELOG and version fields.
**Interfaces:** create_starter(directory, template=\"async\") yields agent_app with an async create_runtime; use load_catalog/profile and the public SDK.

- [x] Write real generated-project execution/replay/cleanup tests and confirm failure.
- [x] Add offline managed async client factory and editable JSON/TOML configuration guide; don't alter old starter content.
- [x] Run one independent review and fix concrete findings; then complete the full test and quality gates.
- [x] Build/install outside checkout; verify default dev12 continuation, async starter and public imports; record actual evidence and limits.
