# Relf-Agent branding implementation plan

> **For agentic workers:** Use superpowers:executing-plans for this single integrated task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved Relf-Agent brand to current project entry points and the existing bilingual website, then review the result.

**Architecture:** Change presentation and explanatory copy only. Centralize website brand strings; retain current SDK names, source URLs, installation commands and durable identities. Preserve historical release and architecture evidence.

**Tech Stack:** Markdown, Astro 7, TypeScript, existing SVG assets and static-site checks.

**Spec:** User-approved name `Relf-Agent`; full meaning `Reliable and Extensible Lifecycle Framework for Intelligent Agents`; Chinese meaning `可靠、可扩展的智能体全生命周期框架。`; tagline `灵活构建智能体，可靠运行智能应用。`.

## Global constraints

- Keep `ralf-agent`, `ralf_agent`, `ralf`, environment variables, database/Temporal identifiers, Python SDK sources and exact published a2 artifacts unchanged.
- Repository URLs remain the actual `https://github.com/RalfNick/ralf-agent`; no remote rename, push, publication or website deployment in this task.
- Work in the existing checkout because the user explicitly includes its untracked website. Save the pre-change inputs before editing; preserve earlier website plans/reviews.
- Retain the website's published a1 tutorial baseline and clearly distinguish it from the latest public a2 release and the new presentation brand.
- Preserve original copyright/NOTICE and historical review/release records. Explain the old technical names in both languages.

## Review focus

1. New branding must not produce nonexistent install commands, import paths or repository URLs.
2. Both locales, accessibility labels, metadata, navigation and social images must use the new brand.
3. New copy must not claim full M1, model quality or production readiness.
4. All existing guide links, search, demo and mobile navigation must still work.
5. The untracked website must retain its existing tutorials and source provenance; update reviewed source hashes only after checking the affected translations.

## Task 1: Integrated brand update and review

**Files:** Current root/community/introductory Markdown; `website/src/lib/site.ts`, shared Astro components/layouts/pages, affected bilingual guide copy, SVG/social assets, website README and reviewed source lock. Record final checks in `website/reviews/2026-10-22-relf-brand.md`.

**Interfaces:** Add shared website brand metadata; retain public SDK APIs, CLI entry points, repository helpers and guide URLs. No runtime feature or public Python API is added.

- [x] Save current inputs and baseline check results; make presentation-only edits and add clear technical-name compatibility notes.
- [x] Review affected bilingual sources; record their updated snapshot; run site tests, Astro checks, fresh static build/link checks and the existing offline tutorial verification.
- [x] Inspect desktop/mobile pages, metadata, sharing assets and search in a browser; obtain one independent final review and address actionable findings.
- [x] Verify Python/product inputs and prior artifact checksums unchanged; record actual results and leave changes local for the user.

## Execution decisions

The user has approved the naming and explicitly requested implementation and review, so no additional plan approval is required. This is a reversible presentation change: reuse existing checks instead of adding tests that merely mirror replacement strings. No commit or remote action is requested in this turn.
