# Main Branch and Open Source Entry Synchronization

**Goal:** Establish `main` from `b545aba`, make it the default branch, synchronize the live website entry/configuration and release status, then make and push one checked local commit as RalfNick.

**Architecture:** Reuse the accepted Alpha source and original frozen artifacts. Repository settings and maintained documentation change; SDK, package metadata, version, gate manifests and historical qualification remain fixed.

**Scope:** User authorization dated2026-10-23. Preserve `feat/m1-local-runtime` and original a2/a3/a4 artifacts. No new features, refactor, CI dispatch, website deployment, package upload, Tag or Release. Final commit alone uses `core.hooksPath=/dev/null` and retains `[skip ci]`.

## Tasks

1. Verify default GitHub credentials resolve to RalfNick; snapshot repository state, existing website changes and protected artifact checksums. Create remote/local `main` at exact `b545aba`, set repository default and homepage; verify original branch stays at its accepted commit.
2. Add the official website to maintained README/docs, use `main` for current README source links, retain frozen package links and pinned a1 website tutorials. Review/include the existing three website configuration/documentation changes. Append actual a4 push/main/website state without replacing historical evidence or claiming publication.
3. Run relevant README/package presentation checks, website tests/checks, production-origin build/link/metadata checks and local Wrangler dry run; verify source/artifact invariants. Review the final diff, commit once with the authorized bypass and `[skip ci]`, then push only main with verified RalfNick credentials. Confirm remote default/head/homepage, old branch, Tags/Releases, Actions and local state.

## Review Focus

- No code or frozen package/manifest changes; no deletion or rewrite of the original branch, Tags or historical records.
- The initial remote `main` points exactly at `b545aba`; later maintenance commits descend from it.
- Current source visibility, website availability, GitHub Alpha assets and PyPI publication are distinct states.
- Existing a4 package URLs keep working through the retained development branch; website tutorials remain pinned to their accepted source.
- Local checks never dispatch CI or deploy to Cloudflare/PyPI; temporary authentication never prints or persists tokens.

## Evidence

Actual results are recorded in `architecture/reviews/2026-10-23-main-open-source-entry.md` and the private operation receipt. No second commit is needed to embed the final commit's own SHA.

The initial `main` and repository settings have been verified. All nine local check steps passed, the original a4 package preflight passed without publication qualification, and all 544 protected file checks matched. The original website launch build and records are preserved separately from the new local build. Independent review found no P1/P2; final commit and push receipts accompany the local evidence archive.
