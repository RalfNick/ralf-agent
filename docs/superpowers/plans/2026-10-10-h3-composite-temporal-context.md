# H3 advanced managed context implementation

Spec: docs/superpowers/specs/2026-10-10-h3-composite-temporal-context.md

## Task 1: Local composite authority

Produces: Schema 11 activation; original node projection journals; node-scoped context credits; Local composite tests.
Consumes: dev43 managed context and artifact journals, existing composite scheduler and parent budgets.
Completion: tests/test_composite_data_context.py and existing context suites pass.

1. Write composite context tests; run `.venv/bin/pytest -q tests/test_composite_data_context.py`.
Expected: unsupported composite context fails before implementation.
2. Implement admissions, journal projection validation and node reservations without changing pure hooks.
3. Run `.venv/bin/pytest -q tests/test_composite_data_context.py tests/test_context_preparation.py tests/test_managed_data_context.py`.
Expected: all pass.

## Task 2: Temporal History stages

Produces: opt-in managed context manifest, deterministic History stages and managed activities; recovery tests.
Consumes: Task 1 existing pure policies and artifact evidence semantics, Temporal original state/budget and worker registration.
Completion: tests/test_temporal_managed_context.py plus existing Temporal tests pass.

1. Add real staged-operation tests; run `.venv/bin/pytest -q tests/test_temporal_managed_context.py`.
Expected: managed builder admission fails.
2. Implement explicit History transitions and no-repeat artifact/summary effects, post-await component validation.
3. Run `.venv/bin/pytest -q tests/test_temporal_managed_context.py tests/test_temporal_custom_context.py tests/test_temporal_engine.py tests/test_temporal_composites.py`.
Expected: all pass.

## Task 3: Recovery, documentation and release

Produces: capability docs, recovery evidence, dev44 artifacts and local commit.
Consumes: Task 1 and 2 behavior and tests.
Completion: full suite, Ruff, format, whitespace, build and installed smoke pass; no push.

1. Add crash/cancel/drift cases and actual History replay when available.
2. Update docs with accurate scope, raw-storage and external-quality limitations.
3. Run `.venv/bin/pytest -q`, Ruff, build and installed smoke.
Expected: suite and packaging pass; service-dependent skips explicitly reported.
4. One fresh read-only final reviewer; fix Important findings with failing regression first; local commit only.

## Review Focus

Parallel frame journals against parent model Actions, colliding auxiliary reservation IDs, bound contexts and Scope drift; cancellation during artifact reads; write Activity timeout and lost acknowledgement; independent summary receipt versus adoption; old History/default release compatibility; child unknown budget/remote quiescence; source validation after artifact awaits.
