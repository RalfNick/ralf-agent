# Website Automatic Deployment and Search Startup Implementation Plan

> **For agentic workers:** Implement in this session, task by task, with failing regression tests before search behavior changes.

**Goal:** Automatically check, build and publish relevant main-branch changes to the existing Cloudflare Worker, and improve first-use search reliability.

**Architecture:** Reuse Cloudflare Workers Builds and the existing GitHub installation, production Worker and domain. Share one fail-fast validation entry between GitHub Actions and Cloudflare. Search starts warming on idle/intent, coalesces concurrent initialization, uses a longer bounded startup budget and keeps the existing bounded query/retry UX.

**Tech Stack:** Astro 7.4.1, Pagefind 1.5.2, Node 24, Python 3.12, Cloudflare Workers Builds, GitHub Actions.

**Spec:** User request in this conversation dated 2026-10-23: configure automatic build/check/deploy on website-related updates and optimize initial search timeout.

## Global Constraints

- Production: main branch, https://relfagent.com, Worker ralf-agent-website; preserve current DNS and www rule.
- Relevant inputs: website/**, docs/**, src/ralf_agent/**, pyproject.toml, README.md and .github/workflows/website.yml.
- Checks must fail before deployment; PRs and other branches must not publish production.
- Keep Node dependencies locked; validate tutorials offline using the pinned SDK baseline.
- Never print/store deployment tokens in source or logs. Confirm any new persistent security permissions at the action that grants them.
- Preserve concurrent documentation edits in the shared checkout; the managed worktree was created but filesystem writes there were denied, so implementation falls back to the primary workspace.

## Review Focus

- Failed checks stop the pipeline; production origin cannot be silently omitted.
- A slow initialization can finish beyond the old 12-second budget, while queries remain bounded.
- Hover/idle and dialog open share one initialization; failed/late candidates cannot replace a later successful instance.
- Prewarming failures stay silent until the user opens search; manual retry creates a fresh instance.
- Main-only deployment and watch paths are verified in Cloudflare, not only documented locally.

## Tasks

- [x] Search: write failing lifecycle/timeout tests, implement a shared bootstrap helper, wire intent/idle warming and separate startup/query budgets, run tests and browser checks.
- [x] Pipeline: add a shared fail-fast verification command and Cloudflare dependency bootstrap; update GitHub checks and document production root/runtime/env/watch-path configuration; test failure propagation.
- [ ] Integration: commit only this task's files, make the verified changes available on main without mixing concurrent edits, grant the required repository/deployment permissions with action-time confirmation if needed, connect Workers Builds and run a real automatic production build.
- [ ] Acceptance: verify deployed commit/assets, bilingual search (including retry), HTTPS/www redirects and failure-gate evidence; record results.

## Decisions and Evidence

- Existing Cloudflare GitHub connection currently lists only yx-auto. No connection to that unrelated repository was saved.
- Local Wrangler is unauthenticated; use native Workers Builds integration instead of copying credentials into the repository.
- New isolated worktree exists at /Users/bytedance/.codex/worktrees/website-autodeploy-search/ralf-agent, but remains unchanged after write denial.
- Full production verification passed: 21 tests, no Astro diagnostics, bilingual offline tutorials, 32 pages, 28 indexed documents, 1,925 local links, 48 published repository targets and Wrangler dry run.
- Browser checks passed with the first Pagefind module deliberately delayed 13 seconds; a failed fragment request exposed retry, and retry recovered with the original Chinese query preserved.
- Independent read-only review found no actionable correctness issues in search lifecycle or the fail-fast pipeline.
- Cloudflare watch paths use its simple wildcard syntax (`website/*`, `docs/*`, `src/ralf_agent/*`), while GitHub Actions uses globstar patterns.
