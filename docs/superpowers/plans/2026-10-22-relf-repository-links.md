# Relf-Agent repository link synchronization plan

> **For agentic workers:** Use superpowers:executing-plans for this integrated maintenance task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize active project and website repository links to `https://github.com/RalfNick/relf-agent`, verify the same repository and original artifacts, then commit and push as RalfNick.

**Architecture:** Update current documentation and the website's central repository URL, retaining pinned commits, SDK names and release asset identities. Correct clone-directory commands and compatibility prose together with the links. Preserve historical evidence.

**Tech Stack:** Markdown, existing Astro/TypeScript checks, Git and GitHub API readback.

**Spec:** User explicitly requested README, documentation and website links be synchronized while preserving historical records and original artifacts, followed by checks, commit and push.

## Global constraints

- Repository is the same public repository ID1405169929, now `RalfNick/relf-agent`; origin is already updated.
- Keep `ralf-agent` distribution, `ralf_agent` imports, `ralf` CLI, SDK sources, runtime identities and pyproject metadata unchanged.
- Keep website baseline `0b9b6c9682c40285d91994cd831aa93d7e814bf1` / SDK0.1.0a1 and all release asset names, versions, SHA256 and Tag commits unchanged.
- Leave `docs/archive/`, existing `docs/superpowers/`, `docs/releases/`, `architecture/` and existing `website/reviews/` records unchanged. In mixed current/history pages, edit current sections only.
- No rebuild of Alpha artifacts, external model/service tests, remote CI dispatch, release mutation or deployment. Preserve `[skip ci]`, one-shot hook bypass and global hook configuration for the authorized commit/push.

## Review focus

1. New clone URLs must be paired with `cd relf-agent`; no accidental changes to install/import/CLI names.
2. Current bilingual instructions must no longer claim the repository address is unchanged.
3. Generated source links must use the new repository and original immutable commit; old historical references remain auditable.
4. Anonymous new release URLs must yield the exact original assets; no same-version rebuild or Tag movement.
5. Content snapshots must be recorded only after reviewing both translations; push must target the verified RalfNick account and actual current branch.

## Task 1: Synchronize, verify and publish source changes

**Files:** README/CONTRIBUTING; active root documentation (current sections only); `website/repository.json`, Home clone command, affected bilingual guides, repository URL assertions, `website/scripts/check-repository-links.mjs` and reviewed source lock. Add a dated verification record; do not rewrite earlier records.

**Interfaces:** No new API. `repositoryUrl()` and `checkRepositoryTargets()` keep their signatures and fixed-commit validation; central repository URL changes only.

- [x] Capture original inputs; update existing expected repository URLs before configuration, observe failure, then update active links, clone paths and compatibility explanations.
- [x] Review bilingual diffs, refresh source snapshot, and run website tests, Astro, docs, build and original offline tutorial checks; verify new remote source targets and anonymous artifact hashes.
- [x] Obtain one fresh read-only review; verify historical trees, SDK inputs and prior artifact checksums unchanged; record the actual scope and results.
- [x] Commit only this task's files with one-shot hook bypass and `[skip ci]`; verify RalfNick, fast-forward push and remote commit readback without deployment.

## Execution decision

Implementation, checks, commit and push are already explicitly authorized; no additional planning approval is required. Reuse existing assertions and checks for this reversible link/configuration maintenance; do not introduce new features.

Observed during verification: Astro retained old transformed repository URLs in20 cached Markdown pages, and the original validator ignored the old host. Add one regression for rejecting cached prior-repository links, make the existing validator fail on that exact legacy repository, and use the documented `astro sync --force` before rebuilding. This repairs verification of the requested link migration; SDK/runtime behavior stays unchanged.
