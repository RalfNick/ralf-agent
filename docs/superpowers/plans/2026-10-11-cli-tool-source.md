# CLI ToolSource Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL superpowers:executing-plans INLINE. No implementation agents. One final fresh-context read-only review. Continuous human authorization overrides repeated spec/plan/finish approval menus; local commits only, no push.

**Goal:** Enable fixed-command JSON CLI tools through original ToolSource effects and lifecycle contracts.
**Architecture:** Pure descriptor/configuration plus one bounded POSIX process handler; original ThreadExecutionTracker, registry, Engine/History and ownership ledger retain responsibility.
**Tech Stack:** stdlib subprocess/selectors/threading, existing jsonschema and pytest.
**Spec:** docs/superpowers/specs/2026-10-11-cli-tool-source-design.md.

## Global Constraints

- Base d260724/dev71; no default manifest or old DTO/protocol changes, no new authority/dependency.
- One descriptor/source; argv fixed absolute executable; default env empty, cwd fixed absolute, timeout(0,300], byte limits[1,16777216] default1048576.
- Canonical JSON stdin, one finite UTF-8 JSON stdout, exit0 and optional Schema; typed sanitized errors, stderr discarded.
- POSIX process group and root wait; actual ambient AND source ownership after asyncio cancellation; escaped descendants not sandboxed.
- tools/cli-json async configuration and owned cleanup, installed starter, true effect-key approval/recovery; no model calls/push.

## Review Focus

1. Cancelled/closed event loops, queued bridge work and source shutdown cannot release actual process ownership or start withdrawn calls.
2. Frozen descriptor/argv/env/cwd identities and JSON stdin cannot become runtime command selection, implicit parent environment or shell interpolation.
3. Pipe partial writes, huge/invalid JSON, nonzero exit and parent exit with remaining group members must not deadlock or become silent success.
4. Configuration failure or partial construction must stop and drain already-owned sources; shared owned close remains once-only and borrowed sources remain borrowed.
5. Local/Temporal approval, effect-key replay, unknown writes and installed default71 releases keep original authority and identity; this adapter cannot claim detached-process containment or external Runner recovery.

### Task 1: fixed process ToolSource

**Files:** create src/ralf_agent/cli_tools.py, src/ralf_agent/cli_process.py; export in __init__.py; tests/cli_tool_fixture.py and tests/test_cli_tools.py.
**Produces:** CLIToolSource(descriptor, command, *, version, cwd=None, env=None, timeout=30, max_input_bytes=1048576, max_output_bytes=1048576); async list_tools/call_tool/wait_for_calls/aclose. Pure construction/discovery; descriptor match before process; original ambient+source actual-thread ownership.

- [ ] Write missing-export and actual protocol/environment/error/bounds tests; run RED.
- [ ] Implement minimal fixed process invocation and tracked stop/drain; run new tests and original MCP/ToolSource/thread contracts GREEN.
- [ ] Add real cancellation/source-close/ambient ownership and immutable-config regressions; prove RED→GREEN for failures, record task evidence.
Expected: real processes reaped; no ambient threads remain after drain; no program/credential data in public errors.

### Task 2: declarations, starter and delivery

**Files:** create src/ralf_agent/cli_tool_factories.py and src/ralf_agent/cli_starter.py; wire registry/starter; tests/test_cli_tool_configuration.py, tests/test_cli_starter.py, tests/test_cli_temporal_service.py; docs/cli-tools.md, capabilities/CI/acceptance/version.
**Consumes:** Task1 source. **Produces:** async tools/cli-json factory and installed cli starter using original explicit policies, owned cleanup, Local/Temporal execution evidence.

- [ ] RED strict pure configuration errors/sync refusal/owned partial cleanup; implement factory and register.
- [ ] RED installed-compatible starter approval/restart/repeated control/once effect; implement starter and Temporal service probe with original History.
- [ ] Sync capability docs to actual boundaries; exactly one final reviewer/fix pass; frozen full/build/install/actual71 compatibility/services stopped; local commit then task-done. Goal remains active.
Expected: core starter succeeds with one business write; async declarations work on original Local and Temporal builders; no hidden execution authority or sandbox claim.
