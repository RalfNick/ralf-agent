# Alpha 4 Candidate Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Freeze 0.1.0a4 with the accepted contract and Coding fixture fixes, verify its original wheel/sdist locally, and make one local commit without pushing or publishing.

**Architecture:** Reuse the installed-artifact gate, dependency lock, preflight and publication protocol. Give a4 its own manifest and manual workflows; retain a2/a3 artifacts, manifests, workflows and all historical failures. Keep product changes relative to 672d0cf limited to the package version.

**Tech Stack:** Python 3.11+, setuptools/build, pytest, Twine, existing GitHub Actions/OIDC templates.

**Spec:** User request 2026-10-23; `docs/release-gate.md`, `docs/pypi-publishing.md`, and `architecture/reviews/2026-10-22-coding-regression-fixture-readiness.md`.

## Global Constraints

- Brand Relf-Agent; distribution `ralf-agent`, import `ralf_agent`, CLI `ralf`, repository `RalfNick/relf-agent`.
- No new SDK capability, dependency, Schema, execution authority, Run/Worker identity or deadline change.
- Original 311 basic / 16 recovery / two starter gate; Linux 2 CPU / 2 GiB / swap0 / offline / serial constraints remain.
- a4 has independent original bytes and evidence. Historical S2/fingerprint/model evidence does not qualify the new package.
- No push, remote CI dispatch, credentials/account configuration, upload, Tag or public Release. Pending external validation is reported explicitly.
- One final local commit, `[skip ci]`, command-scoped `core.hooksPath=/dev/null`; no permanent hook configuration change.

## Review Focus

- a4 publication must refuse a3 or foreign/incomplete runs, altered bytes, missing Python rows, skipped checks and incomplete cleanup.
- Frozen source/test inputs must contain the recent fixes, including the shared Coding fixture helper; wheel/sdist/installed product bytes must agree.
- Build-input and external manifests avoid a self-referential artifact hash; post-build evidence updates must not modify original packages.
- Public a2 remains the public installation recommendation. a4 local success cannot imply Linux, remote CI, PyPI or complete S2 qualification.
- Old artifacts and historical records must remain intact, including failed attempts.

### Task 1: Version, frozen gate and local release contracts

**Files:** `pyproject.toml`, `src/ralf_agent/__init__.py`, `MANIFEST.in`, `tools/release_gate_manifest.alpha4.json`, `tools/stage_alpha1_candidate.py`, `tools/check_alpha4_publication.py`, release tests, `.github/workflows/alpha4-*.yml`.

- [x] Add a4 metadata, staging and publication coverage; observe rejection before adding a4 support.
- [x] Reuse the a3 protocol in separate a4 templates; preserve historical a2/a3 workflows and default manifest.
- [x] Run all affected release tests, YAML/embedded script checks and Ruff/format checks.

### Task 2: Release documentation and original artifact freeze

**Files:** `README.md`, `CHANGELOG.md`, current capability/release docs, new `docs/releases/0.1.0a4.md`, `docs/alpha4-validation-status.md`, website installation status and source lock.

- [x] Distinguish a4 local candidate from original a3 and publicly available a2; document current fixes and compatibility boundaries.
- [x] Verify protected historical checksums; freeze explicit source inputs, build original wheel/sdist, and record final external hashes.
- [x] Verify exact product equivalence to 672d0cf except version and include the accepted test fixes in sdist.

### Task 3: Local acceptance, independent review and local commit

**Files:** new acceptance record, archived local candidate/evidence (ignored), final status docs.

- [x] Twine strict check both originals; execute unchanged macOS ARM64/Python3.12 installed gate and two starters offline, outside checkout.
- [x] Rebuild/install sdist independently, run release and recent-fix contracts plus continuous five-stage example; distinguish this scope from the original gate and historical full source regression.
- [x] Check website/tests/links and final source/test hashes; preserve any failures and all original a2/a3 checksums.
- [x] Obtain one independent final review; resolve material findings, record actual counts and pending remote/account steps.
- Final commit step: make one local commit with a single-command hook bypass, then verify clean worktree and unchanged permanent hooks. Actual SHA is recorded by Git and the local delivery receipt after the commit; do not make a second commit to embed its own SHA.

## Execution record

- Final originals:442 products /975 test inputs /2046 source files; SDK only version differs from672d0cf.
- Source release scope:200 passed. Final macOS installed gate:311 /16 /two starters. Separate sdist installation:292 passed /two starters; rebuilt wheel SHA matches original. Scopes overlap and are not summed; no new full-source or Linux/service qualification.
- Independent fresh-context review:zero P1/P2 or minor findings. Original a2/a3 and historical failures retained. Final result docs are maintained outside immutable packages.
- One final local commit is authorized; no push, remoteCI, account access or publication.
