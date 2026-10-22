# Website documentation closure implementation plan

> **For agentic workers:** Use executing-plans for the integrated implementation and dispatching-parallel-agents for the two independent bilingual content packages. Complete one fresh full-site review at the end.

**Goal:** Resolve all six findings in the approved full-site audit and give Chinese and English users complete tutorial, reference and testing paths.

**Architecture:** Keep the existing Astro static site. Centralize a published repository commit and transform `repo:` Markdown links at build time; validate their paths against that Git tree. Retain the ten current topics and add four bilingual guides: durable input, a continuous application tutorial, API/CLI reference, and testing/evaluation.

**Tech Stack:** Astro 7.4.1, Node 24, Markdown, Pagefind; Python 3.11+ SDK examples.

**Spec:** `website/reviews/2026-10-21-full-site-docs-audit.md`, explicitly approved for P1/P2/P3 implementation by the user on 2026-10-21.

## Global constraints

- Keep Ralf-Agent naming, Astro, the current visual style and Cloudflare static hosting configuration; do not deploy.
- Preserve unrelated in-progress SDK/Temporal edits; implementation stays in website and its existing CI workflow, apart from this plan.
- Both locales offer the same executable tasks. Mark untranslated optional repository material explicitly.
- Use the remotely published `0b9b6c9682c40285d91994cd831aa93d7e814bf1` (SDK `0.1.0a1`) as documentation/installation baseline, after checking required paths and examples.
- No online model calls, credential reads or paid/service integration tests. Explain their explicit opt-in boundaries.
- Keep code and reference examples truthful about identity, receipts, Session occupancy, borrowed resources and execution authority.
- Work in the existing feature checkout: website sources are untracked and would not be carried into a new worktree. Do not commit or push unrelated work.

## Review focus

1. Repository links must resolve to published files, including optional sources; unpublished Edit links must not be emitted. Task 1 checks Git paths and rejects stale refs.
2. A user following model → structured output → Session steps must not encounter wrong object types or command-ID conflicts. Task 2 runs actual examples sequentially offline.
3. Replying to an old input question must retain its original Run and not create a Session Turn. Task 3 checks the starter's wait/reply/resume sequence and duplicate answer.
4. English users must not need Chinese-only instructions to finish core tasks. Task 4 compares both paths and marks optional foreign-language references.
5. More documentation must not silently break Pagefind completeness, mobile navigation or locale switching. Task 5 builds and exercises these paths.

## Task 1: Published repository links and source baseline

Files: create `website/repository.json`, `website/src/lib/repository.mjs`, `website/scripts/check-repository-links.mjs`, `website/tests/repository.test.ts`; modify Astro Markdown config, site exports, documentation template, footer and guide links.

Interfaces: `repositoryUrl(path, kind)` constructs pinned blob/tree links; `remarkRepositoryLinks` expands `repo:path#anchor`; validator reads built HTML and uses `git cat-file` for every repository path, with an explicit remote baseline check command.

- [x] Capture failing evidence for main links and unpublished edit targets; add meaningful URL/Markdown resolution and invalid-path tests.
- [x] Implement central immutable ref, repository link transformation, source/date labels and removal of unpublished editing entry.
- [x] Check every target against the published Git tree and verify remote publication; integrate offline checks into build/CI.

## Task 2: Correct model and Session tutorials

Files: both `models-tools.md`, both `sessions-memory.md`, tutorial smoke checks under `website/scripts/`.

Interfaces: examples use `spec` for AgentSpec and `agent` for Agent; Session example includes complete async entry and owned lifetime. Structured output uses a new command ID.

- [x] Retain the audit's reproducible failures as the acceptance cases.
- [x] Correct both examples, add save/run instructions and expected results; include explicit new-command guidance for definition changes.
- [x] Execute both locales' complete examples against an offline provider and the published SDK baseline, preserving persistent identity checks.

## Task 3: Durable input and continuous application paths

Files: create bilingual `user-input.md` and `app-tutorial.md`; parent updates capability overview, recovery state tables, sidebar metadata and related links.

Interfaces: exact installed `user-input` starter commands; one source-file application advances through agent/session/rag/memory/workflow with independent stage databases. References use `repo:` links.

- [x] Write both language pairs from existing source contracts with commands, expected results, restart and failure next steps.
- [x] Run input wait → inspect → reply → resume → duplicate replay without model services.
- [x] Run all continuous application stages and cross-process Session continuation; retain output evidence.

## Task 4: API, tests/evaluation and English self-service

Files: create bilingual `api-reference.md` and `testing.md`; expand existing model/session/operations topics and overview links.

Interfaces: curated common signatures/returns/defaults, SDK vs CLI driving semantics, errors, model compatibility probe, offline business/task evaluation commands; optional Chinese repository links visibly labeled.

- [x] Verify exact APIs against source and write both pairs with executable query/testing entry points.
- [x] Add bilingual semantic/hybrid recipe and route all critical tasks to site-local guidance.
- [x] Run an example application test and existing offline compatibility/business/task checks; distinguish regression from live quality.

## Task 5: Integrate, validate and review all pages

Files: site metadata, build checks, README, CI, source lock and final implementation/review log.

- [x] Integrate fourteen bilingual topics into grouped navigation and capability paths; update counts and source snapshot after content review.
- [x] Run site tests, Astro check, source check, fresh build, repository target checks, and Cloudflare dry run.
- [x] Browser-check desktop/mobile long pages, new-topic searches, locale switching, navigation, demo and 404 behavior.
- [x] Dispatch fresh independent full-site content/API and usability review; resolve actionable findings and rerun affected checks.
- [x] Record each audit item's closure, actual results and verification limits; leave the local preview available.

## Execution record

Ruling: The approved audit is the specification and authorizes implementation; no additional planning approval is needed. The two new content packages have separate files and can be written in parallel while repository integration is implemented centrally.

Task 1–5: complete. Final evidence and independent review: `website/reviews/2026-10-21-docs-closure.md`.

Ruling: Astro 7 uses native Sätteri, so repo links use its immutable-node plugin API rather than legacy remark. Expanded docs produce two Pagefind chunks per locale; the exact-match Pagefind 1.5.2 rethrow guard replaces the old single-chunk restriction, with unit tests and browser failure/retry evidence. No deployment or commit was performed.
