# Runtime capability and component validation repair

> **For agentic workers:** Use superpowers:executing-plans to implement these tasks in order.

**Goal:** Fix optional Session capability discovery and share component validation without adding features.

**Architecture:** Keep Local and Temporal as separate execution authorities. Put common identity/callable validation in the existing ports module; retain existing backend entry signatures.

**Tech Stack:** Python 3.11+, pytest, Ruff.

**Spec:** User-approved review follow-up; `docs/extending.md`, `docs/agent-api.md`, `src/ralf_agent/ports.py`.

## Global constraints

- Function-fingerprint validation and S2 remain deferred; no changes to their implementation or acceptance gates.
- Preserve documentation organized in `56e0535`; make only related corrections.
- Run affected offline tests; no model/service calls or remote push.
- Finish with one local commit. No persistent Git hook configuration changes.

## Review focus

- A basic ExecutionStore without optional Session properties must remain queryable.
- A version property without a Session factory must not advertise durable Sessions.
- Missing/invalid extension versions must not imply advanced Session support.
- Sync/async callable shape and finite identity rejection must agree across backends.
- Identity snapshots must be detached; validation must not invoke component methods.

## Task 1: Optional capability discovery

- [x] Add failing public Runtime capability tests with the existing port-only StoreAdapter and SQLite variants.
- [x] Safely read the optional version once; gate Session descriptions on the synchronous factory.
- [x] Run capability, Agent and Session tests, including existing SQLite behavior.

## Task 2: Shared component validation and documentation

- [x] Add cross-backend tests for method shapes, identity failures and detached snapshots.
- [x] Introduce `validate_component_identity(component, methods, *, synchronous=False, label="Component")` in `ports.py`.
- [x] Delegate existing Engine/Temporal validators and component consumers to that rule; retain compatibility entry signatures.
- [x] Update only related extension, capability and model documentation; record verification in the current status summary.
- [x] Run affected offline tests and Ruff/format/whitespace checks, then request an independent final review.
- [x] Inspect the complete diff and prepare the authorized local commit; do not push. The resulting commit is recorded in Git, outside this self-contained plan.

## Verification

- Capability regression before the fix: 10 failed / 9 passed; shared validation before the fix: 5 failed / 18 passed.
- Final affected source selection: 25 modules, 428 passed, no failures/errors/skips (`-W error`); includes direct, synchronous and asynchronous assembly plus Session and managed-context recovery.
- Ruff over src/tests, formatting of the ten changed Python files and Git whitespace checks passed; changed-guide relative file links resolve.
- Dedicated fingerprint/S2/History compatibility checks, builds and live services/models were not run. No new compatibility or performance acceptance is claimed.

- Independent review found a remaining Local Context entry check; six public-construction regressions failed before the fix. Constructor and manifest now use the shared synchronous rule; all nine Context regression cases pass. Final read-only re-review found no remaining P1/P2.
