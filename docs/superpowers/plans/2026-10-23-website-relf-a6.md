# Website Relf a6 Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify website branding and bilingual executable documentation with the a6 `relf_agent` / `relf` entrypoints.

**Architecture:** Keep the Astro site and its pinned Git-source documentation model. Move the fixed tutorial snapshot to the existing public a6 source commit, verify the actual installation and tutorial loops, and retain genuine SDK compatibility identifiers and historical release evidence.

**Tech Stack:** Astro 7, Node 24, Pagefind, Python 3.12, the existing website verification scripts.

**Spec:** The user requirements recorded in the Scope section of this plan.

## Scope

The user requested replacing Ralf in website documentation and selected: “统一到 a6，并验证中英文教程”. Other SDK CI failures remain deferred; do not change SDK runtime implementation or weaken its tests.

## Global Constraints

- Pin `ba1c81fca67e15e70c1d51d0f4ecbbbcbbb37239`, SDK `0.1.0a6`, verification date `2026-10-23`; the commit is already on remote main.
- a6 is a source candidate, not a newly published PyPI/GitHub package. Use source installation and describe release qualifications separately.
- Preserve actual `RalfError`, `.ralf` database defaults, `RalfNick` account URLs, historical release artifacts and the Cloudflare Worker name `ralf-agent-website`.
- Update Chinese and English together, review their repository sources, and record the matching source/translation lock.
- Keep the current Cloudflare deployment and search architecture; only adapt naming, tutorial baseline and verification.

## Review Focus

- Wrong CLI/import against the fixed source: execute with an installed a6 SDK, not a stale global `ralf` command.
- Cross-version recovery: preserve separate environments and old SDK/Run evidence; no automatic migration claim.
- False release claims: candidate source availability does not imply a public a6 package or full SDK CI qualification.
- Partial language migration: both locales must use the same commit, names, examples and source sets.
- Broken source/search links: fixed URLs must exist remotely and built Pagefind assets must pass the production gate.

### Task 1: Brand, metadata and bilingual content

**Files:** `website/repository.json`, `website/docs-source-lock.json`, `website/src/content/guides/{zh,en}/*.md`, `website/src/components/{Home,HeroArt}.astro`, `website/src/lib/demo.ts`, `website/src/pages/[locale]/docs/[slug].astro`, `website/{README,PLAN}.md`, `website/tests/{site,repository}.test.ts`.

**Interfaces:** Preserve `repositoryInfo` shape and demo state-machine behavior; output a6 CLI/import examples and coherent candidate-version copy.

- [x] Replace display branding, illustrative Run IDs and user-defined environment/example directory names.
- [x] Pin a6 source metadata; replace tutorial imports and commands, update candidate/install/version copy, and remove the obsolete a1 banner.
- [x] Run the existing website tests to expose the old hard-coded repository expectation; update that expectation and confirm the tests pass.
- [x] Review both locales and their pinned sources; record and check all 14 documentation pairs.

### Task 2: Execute the migrated tutorials

**Files:** `website/scripts/check-tutorials.py`; temporary installation/probe artifacts outside the repository.

**Interfaces:** Keep the offline verifier's CLI entrypoint; use the pinned a6 source and its actual `relf_agent` imports. `PYTHON_BIN` selects an isolated installed SDK environment for verification.

- [x] Adapt the offline verifier fixture imports and run it against an isolated a6 installation.
- [x] Execute both locales' quickstart: install/version, init, inspect, approve, resume, inspect and repeat the original Run.
- [x] Execute the bilingual application, durable-input, model/schema, Session, hybrid and offline evaluation examples; record identities/results without live model calls.

### Task 3: Final verification and delivery

**Files:** Updated website files; concise acceptance evidence under `website/reviews/` if needed.

**Interfaces:** `npm run verify:production` remains the shared production gate; no SDK CI pass claim follows from website-only checks.

- [x] Run `PUBLIC_SITE_URL=https://relfagent.com PYTHON_BIN=<a6-python> npm run verify:production` and read the complete result.
- [ ] Inspect built pages for stale display names, verify retained technical identifiers, and check bilingual search results.
- [x] Obtain one independent read-only review; resolve actionable findings and repeat only affected checks.
- [ ] Commit the coherent website update, then use the existing automatic deployment and verify the resulting website build if pushed.

## Execution rulings

- Continue in the current checkout used by this ongoing website task; it was clean at task start and all changes are scoped to this migration.
- Use one coherent final website commit so deployment never receives a partially migrated documentation baseline.
- A source tutorial verification does not publish or qualify the a6 SDK release, and does not close the deferred SDK CI findings.
