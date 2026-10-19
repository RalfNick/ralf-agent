# dev121 basic delivery plan

> **For agentic workers:** Use superpowers:executing-plans; implement in this session and request one final independent review.

**Goal:** Give the current basic SDK one unambiguous installable version, a continuous support-ticket example and clear extension guidance.

**Architecture:** Reuse existing Provider, Python tools, Runtime/Session, SQLite Knowledge/Facts and sequential Workflow. Add application examples and documentation only; no execution, protocol or adapter changes.

**Tech Stack:** Python 3.11+, setuptools/build, pytest, Ruff.

**Spec:** User-approved review follow-up; `docs/basic-capabilities.md`, `docs/releasing.md`, `docs/extending.md`.

## Constraints and review focus

- New package version `0.1.0.dev121`; never replace historical dev120 artifacts or their evidence.
- Recommend the new candidate for the explicitly tested Local basic scope only.
- Fingerprint qualification, S2 and History compatibility qualification remain deferred. No new support/quality claims.
- Keep the existing documentation organization; no new starter API, backend or deployment dependency.
- Example defaults offline; live models require explicit selection/model/credentials and are not called by acceptance tests.
- Validate duplicate receipts, cross-process Session/Facts, cited local knowledge, Workflow, and installed imports outside the checkout.
- Local commit with a one-invocation hook skip; no push.

## Tasks

- [x] Write failing subprocess tests for one support-ticket script, then implement the five existing capability stages.
- [x] Update package/runtime version together and current installation entry points; retain historical records.
- [x] Add the continuous walkthrough and structural-port / inheritance / unsupported extension table.
- [x] Run affected offline tests and checks; independently review the diff.
- [x] Build a fresh wheel/sdist in `dist/basic-sdk-dev121/`, install outside checkout without network, and verify metadata, CLI, approval/restart and all example stages.
- [x] Record exact source inputs, artifact SHA and finite verification scope; prepare the authorized local commit. Actual commit outcome is recorded in Git.

## Verification outcome

Final affected source: 290 passed; installed final wheel: 82 passed; original installed starter: two separate scenarios, each one business write. No failures/errors/skips. The 442 runtime files match source. Independent review and Ruff/format/whitespace checks pass. See `architecture/reviews/2026-10-19-dev121-basic-delivery.md`; deferred gates remain unchanged.
