# Alpha 5 Distribution Rename Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; one final local commit after validation, no intermediate commits or remote operations.

**Goal:** Freeze `relf-agent==0.1.0a5`, retain `ralf_agent` imports and `ralf` commands, and verify a separate local candidate without publishing.

**Architecture:** Reuse the existing gate/preflight and manual staging/publication protocol. Add an explicit distribution identity with historical `ralf-agent` defaults; a5 publication requires `relf-agent`. Preserve a4 original bytes, manifests, workflows and actual platform records.

**Tech Stack:** Existing Python/setuptools, pytest, Twine, manual GitHub Actions and static documentation.

**Spec:** User request 2026-10-23; `docs/project-naming.md`, `docs/release-gate.md`, `docs/pypi-publishing.md`, and `architecture/reviews/2026-10-23-alpha4-linux-validation.md`.

## Global Constraints

- Distribution `relf-agent`, version `0.1.0a5`; import `ralf_agent`, CLI `ralf`, schemas, dependencies and execution identities unchanged.
- Only install guidance in SDK starters/errors changes alongside version; retain protocol client names and stored identities.
- Original 311 basic /16 recovery /two starter node identities, dependency lock and 2CPU/2GiB/swap0/offline/serial Linux constraints remain.
- No new capabilities, remote CI, account configuration, upload or public release; a4 reports do not qualify a5.
- Reuse this maintenance checkout to retain the completed pending a4 documentation. Snapshot existing changes and include those records; do not overwrite other work.
- User has approved the concrete scope and requested execution. Execute without another design/plan approval. One final local commit uses command-scoped `core.hooksPath=/dev/null` and `[skip ci]`.

## Review Focus

- Renamed archive/dist-info metadata must use `relf-agent`, while package contents and executable entry remain `ralf_agent`/`ralf`.
- Manifest/name/version/source mismatch, old a4 runs and wrong staging prefixes must be refused before deliverable exposure.
- Legacy manifests and frozen a4 artifacts remain verifiable; no rewritten historical hashes or borrowed platform qualifications.
- No current install guidance silently recommends the old distribution; historical a2/a4 commands remain explicitly historical.
- New package build input snapshot and final external manifest avoid self-reference; installed wheel and rebuilt sdist contain identical product files.

### Task 1: Packaging identity and publication contracts

**Files:** `tools/release_gate.py`, `tools/release_preflight.py`, `tools/stage_alpha1_candidate.py`, new `tools/check_alpha5_publication.py`, new `tests/test_alpha5_*.py`, shared fixture and existing current-metadata assertions, three new `.github/workflows/alpha5-*.yml`, `pyproject.toml`, `MANIFEST.in`, version/install guidance in `src/ralf_agent`.

**Interfaces:** Manifest optional `distribution_name` defaults to `ralf-agent`; a5 fixes it to `relf-agent`. Archive prefix is `relf_agent-0.1.0a5`, while Python contents stay `ralf_agent/`.

- [x] Write and run renamed real archive/preflight, wrong distribution, historical fallback, old-run rejection and workflow tests before implementation. Expected: failures on missing a5 support, not collection errors.
- [x] Add the minimum name-aware checks and separate a5 publication/workflows; update metadata/version/install guidance. Keep legacy APIs/defaults and old manifests/workflows.
- [x] Run affected release, staging, starter and optional-install tests plus Ruff/format. Expected: all scoped tests pass; complete failure logs retained.

### Task 2: Documentation and immutable candidate

**Files:** current README/release/naming/installation docs, new a5 release/status/acceptance docs, bilingual website status/source lock; new ignored `dist/alpha5-candidate/`.

**Interfaces:** Task1's explicit a5 manifest, original renamed wheel/sdist and exact source/product/test hashes; no changes to frozen a4 records.

- [x] Document distribution migration and no co-installation of old/new distributions sharing the same import tree; public a2 remains the verified historical installation until a5 publication is accepted.
- [x] Freeze the source-worktree receipt and build-input manifest, build both original archives, then write final external hashes without rebuilding or overwriting old artifacts. Expected: wheel/sdist/source product trees agree; fixed gate nodes unchanged.
- [x] Run the project offline suite and preserve named failures/skips, relevant website/document checks and Twine strict metadata checks. Do not repair unrelated engineering failures or claim skipped service/model tests passed.

### Task 3: Installed acceptance, review and one local commit

**Files:** a5 acceptance/status docs, ignored evidence archive and commit receipt.

- [x] Install final original wheel outside checkout using locked dependencies; run original311/16/two-starter gate. Expected: `relf-agent` metadata, unchanged import/CLI, all selected checks pass.
- [x] Independently rebuild/install final sdist; verify products, metadata and licenses, two starters and continuous example. Expected: same product bytes and working CLI; no historical package metadata contamination.
- [x] Obtain one fresh read-only final review, address material findings with reproducing tests; update actual results and pending Linux/native-CI/account/public-install steps. Verify all761 protected artifact checks and protected a4 records.
- [x] Commit once locally with authorized one-command hook bypass and `[skip ci]`; verify intended scope, clean state and permanent hook unchanged. Do not push; report remote gates needed for a5.
