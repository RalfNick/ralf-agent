# dev123 SDK stabilization implementation plan

> **For agentic workers:** Use superpowers:executing-plans in this session, followed by one independent review of the complete diff.

**Goal:** Stabilize the existing basic SDK's public adapter boundaries, selected recovery combinations and first-use guidance without expanding supported features.

**Architecture:** Reuse `ports.is_async_callable` in consumers that still reject native async callable objects; retain domain identities, completed-result checks, source pins and Local/Temporal execution authorities. Validate four existing business chains and the already-wired P3-4 service gates.

**Tech Stack:** Python 3.11+, pytest, Ruff, setuptools, existing optional Temporal/psycopg libraries and owned local test services.

**Spec:** User-approved next-step order; `docs/extending.md`, `docs/support-journey.md`, `docs/recovery-guide.md`, and the dev122 review fixes acceptance.

## Global constraints

- Preserve `746b6b6` as the local dev122 baseline; the dev122 artifacts and evidence are immutable.
- No new agents, backends, protocol features, storage schema, execution authority or runtime dependency.
- Function-fingerprint qualification, S2 and their historical failures remain deferred; do not run their suites or prototypes.
- No push, model calls or public release. Local commits use only an invocation-scoped hook override under the user's existing authorization.
- Reuse cached test binaries/images if available; manage only newly created test services. Do not touch old services or resources.
- Actual remote gate results and internal first-use trials do not qualify all services, old History compatibility or independent external adoption.

## Review focus

- A native async callable adapter completes actual work through every selected public entry. Async-only ports reject sync coroutine factories without entering them; Artifact retains its existing all-sync/all-async modes and rejects mixed mode.
- Corrected validation never skips approval, effect identity, resource pins, complete-result checks or shutdown ownership.
- Approval/restart, Session/context, RAG/Facts bindings and Workflow/Team retain original command and reference evidence through interruption.
- All selected real service cases must run with zero skips and show owned service shutdown; lack of local prerequisites remains an explicit evidence gap.
- First-use instructions use existing commands and explain configuration versus recovery; secrets never enter diagnostic examples or output.

## Tasks

### Task 1: Save the accepted baseline

- [x] Recheck affected dev122 tests, product bytes and artifact checksums.
- [x] Commit dev122 locally with a one-invocation hook override; retain persistent configuration and do not push. Result: `746b6b6`.

### Task 2: Align public async adapter checks

Files: `ports.py`, `tool_sources.py`, `mcp.py`, `memory_pipeline.py`, `data_context.py`, `fact_index_maintenance_tools.py`; tests for these public consumers.

- [x] Add failing behavior tests for async callable Engine operations, ToolSource/MCP requests, memory extraction, Artifact offload and existing generation-index maintenance. RED: 6 failed / 5 passed; GREEN: 11 passed.
- [x] Replace only inconsistent method-mode checks with the shared predicate. Keep vendor-specific concrete checks, streaming generator rules and function identity implementation outside this task.
- [x] Test rejection at async-only ports and Artifact mixed mode, real dispatch, deduplication and resource closure.

### Task 3: Verify four existing combinations

Files: existing Engine/Agent/Session/context, RAG/Facts, Workflow/Team tests; add a focused integration test only where shared adapter replacements lack coverage.

- [x] Run the affected existing suites for approval/restart, Session/context offload, RAG/Facts and Workflow/Team. Final source run: 379 passed.
- [x] Verify valid structural replacements within these chains, preserving business write counts and source evidence after restart.

### Task 4: Execute the selected CI service gates

Files: existing CI test modules; private temporary runner/evidence, no new service framework.

- [x] Check cached Temporal CLI and PostgreSQL image availability without downloading or querying credentials.
- [x] Run the existing scoped audit and effect-retention gates against the installed exact wheel with newly owned local Temporal/PostgreSQL; collect JUnit and actual shutdown records. Installed service run: 24 passed, zero skips; owned shutdown confirmed. No additional source service run.
- [x] Validate installation paths and the new CI step's job-local test path/copy prerequisite; exact new installed step 11 passed. No claim of a hosted GitHub Actions run.

### Task 5: Improve existing first-use and recovery guidance

Files: existing continuous walkthrough, extension guide and recovery/troubleshooting entry.

- [x] Document consistent async callable support and declared limitations; add a compact symptom/error/action table using existing commands.
- [x] Exercise the documented offline walkthrough outside checkout; keep external human adoption explicitly unverified. Installed suites: 160 passed, plus two starter cases with one business write each.

### Task 6: Verify and save the candidate

Files: version declarations, current status/release notes and `architecture/reviews/2026-10-19-dev123-sdk-stabilization.md`.

- [x] Run targeted regressions, Ruff/format/whitespace checks and independent review. Source 379 passed, installed 160 passed; independent review found no P1/P2.
- [x] Build the uniquely versioned dev123 wheel, install without network and record exact inputs and finite results. Freeze the final sdist and checksum manifest after documentation review without rebuilding the tested wheel.
- Final action after artifact verification: local commit using an invocation-scoped hook override; do not push or change deferred gates. The resulting commit is recorded by Git, without rewriting the frozen artifacts.
