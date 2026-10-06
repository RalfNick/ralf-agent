# Static Workflow Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, followed by one fresh whole-change review. User authorized implementation of the written framework scope.

**Goal:** Deliver extensible, durable local static graphs with a usable installed starter.

**Architecture:** Versioned pure compiler/validator/interpreter and binding DTOs surround the existing Agent execution loop. Graph plans and node snapshots persist in Run JSON; graph-only Manifest entries pin the actual execution components. Default legacy Agent/sequence remains on its compatibility bridge.

**Tech Stack:** Python >=3.11, dataclasses/JSON, existing jsonschema and SQLite. No new runtime dependency.

**Spec:** [Static Workflow design](../specs/2026-10-06-static-workflow-design.md).

## Global Constraints

- Preserve local-4, ExecutionStore v1, legacy request/Manifest and existing starter dictionaries.
- Serial graphs only; no parallel, dynamic Plan, ChildRun or external-I/O transform claim.
- Maximum 256 nodes, 32 reference path segments and 1 MiB serialized IR.
- Finite JSON, explicit missing/null/skip handling, no eval/implicit imports or inherited credentials.
- Existing approval, cancellation, budget, thread ownership and independent receiving/adoption remain authoritative.

## Review Focus

- Custom compiler/interpreter/transform callbacks mutate inputs, change identity or return lazy values: refuse unsound execution.
- Branch joins observe skipped nodes, false/null/missing and bool/int differences: explicit defaults and Schema, no silent result substitution.
- Session append or node completion commits before process death: resume must not rerun a completed business effect.
- Configuration aliases move between submit/restart: original receipts and pinned plan/component identities survive or reject clearly.
- Terminal/cancelled graph receives late evidence: no scheduling, node reopening or coordinator release before real calls finish.

### Task 1: Deliver the complete static-graph increment

**Files:**
- Create `src/ralf_agent/workflow.py` (values, IR, validation, compiler, interpreter, transform contracts).
- Create `src/ralf_agent/workflow_runtime.py` (graph acceptance/selection/transition integration helpers).
- Modify `engine.py`, `types.py`, `runtime_config.py`, `runtime_builder.py`, `cli.py`, `cli_views.py`, `starter.py`, `__init__.py`.
- Tests: `test_workflow.py`, `test_engine_workflow.py`, `test_workflow_adoption.py`; existing complete suite.
- Guides/status/architecture/version/progress updates with truthful feature scope.

**Interfaces:** public binding/graph/plan/component signatures exactly as the spec; LocalEngine keyword arguments `workflow_compiler`, `workflow_interpreter`, `workflow_transforms`. Compiler/interpreter validation is pure and default implementations are independently usable.

- [ ] Write behavioral unit tests before public implementation; missing feature asserts fail. Run `pytest -q tests/test_workflow.py`, expected failing assertions for absent public API.
- [ ] Implement validated values/IR and pure defaults; run the same file, expected all pass.
- [ ] Write engine recovery/approval/cancellation/component-boundary regressions before integration; run `pytest -q tests/test_engine_workflow.py`, expected unsupported Graph/keywords failures.
- [ ] Integrate graphs through a focused runtime helper, retaining native model/tool boundaries. Run unit/integration and related engine/component suites, expected all pass.
- [ ] Write load/config/CLI/starter tests before adoption implementation. Run `pytest -q tests/test_workflow_adoption.py`, expected unknown graph/template/component failures.
- [ ] Deliver strict declarations, versioned assembly, inspect and packaged graph starter. Update guides and package dev10. Run the three new files and full `pytest -q -W error`, expected all pass; Ruff lint/format and Git checks clean.
- [ ] Build/install outside checkout; verify graph branches/resume/custom components and actual dev9→dev10 receipt/Manifest/queued run continuity. Syntax/link checks pass; no live-model claim.
- [ ] Commit feature and evidence, run final fresh review and address material findings with RED→GREEN and a clean full suite. Record findings, rulings and actual verification in implementation progress.

## Pre-flight

Single connected deliverable: IR validation produces persisted plan accepted by engine; all declaration loaders normalize the same IR and inspect reads the same node snapshots. Legacy bridge is intentionally separate until explicit migration. No conflicting interfaces identified.
