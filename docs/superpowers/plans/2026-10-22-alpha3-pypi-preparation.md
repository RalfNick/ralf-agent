# Alpha 3 PyPI Preparation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for implementation and superpowers:requesting-code-review for one final independent review. Follow the user's already authorized scope without another planning approval.

**Goal:** Prepare a separately versioned 0.1.0a3 Local SDK Alpha and its manual PyPI delivery path, with local tests and installation evidence, without pushing or publishing.

**Architecture:** Reuse the existing immutable wheel/sdist checks, offline installed-artifact gate and resource-limited Linux wrapper. Keep a2's original artifacts, manifests, workflows and historical evidence intact. Add a separate a3 manifest and manual validation/publishing workflows; publishing consumes validated frozen bytes rather than rebuilding them.

**Tech Stack:** Python 3.11+, setuptools, pytest, Twine, GitHub Actions / PyPI OIDC.

**Spec:** User request dated 2026-10-22; `docs/project-naming.md`; `docs/releases/0.1.0a2.md`; existing `tools/release_gate.py` and `tools/release_preflight.py` contracts.

## Global Constraints

- Distribution `ralf-agent`, import `ralf_agent`, CLI `ralf`; display brand `Relf-Agent` and repository `RalfNick/relf-agent`.
- Version `0.1.0a3`; no runtime feature, dependency, storage schema or execution-identity change.
- Preserve a2 original files and historical failures. New packages have separate filenames, hashes and evidence.
- Keep the existing 311 basic / 16 recovery / two starter gate and Linux 2 CPU / 2 GiB / swap0 / offline / serial requirements.
- No push, remote CI execution, account changes, TestPyPI upload, PyPI upload, Tag or Release creation in this task.
- Final local commit uses a command-scoped hook bypass and `[skip ci]`.

## Review Focus

- A candidate altered after qualification must fail hash/product/metadata validation before upload.
- A workflow must never rebuild files during publication, accept an arbitrary unqualified artifact, or publish from push/PR events.
- PyPI rendering must not depend on repository-relative Markdown links or claim a3 is already public.
- a2's passing reports cannot qualify the new a3 package; local and pending remote qualifications remain distinct.
- PyPI/TestPyPI identity must match the distribution metadata and renamed repository; OIDC permission is limited to publication.

### Task 1: Version and package presentation

**Files:** `pyproject.toml`, `src/ralf_agent/__init__.py`, `README.md`, `CHANGELOG.md`, new `tests/test_alpha3_release.py`.

**Interfaces:** Produces a3 version, new-brand metadata and PyPI-renderable long description while retaining technical identifiers.

- [x] Add failing assertions for synchronized version, repository metadata, Alpha/Python classifiers, preserved identifiers and absolute README document links.
- [x] Update only version and release presentation; run the affected tests.

### Task 2: Frozen a3 gate and explicit manifest selection

**Files:** existing release tools and their tests, new `tools/release_gate_manifest.alpha3.json`, `MANIFEST.in`.

**Interfaces:** Optional `--manifest PATH` selects a frozen gate; omitted selection retains a2 behavior. a3 tools consume the new exact hashes and original test identities.

- [x] Add failing coverage for explicit manifest selection and preservation of historical defaults.
- [x] Implement manifest selection without changing gate limits, subprocess deadlines or original a2 manifests.
- [x] Freeze a3 input snapshot, build the wheel/sdist once, and write the external manifest with final hashes.

### Task 3: Manual validation and trusted publication

**Files:** new `.github/workflows/alpha3-release-gate.yml`, `.github/workflows/pypi-publish.yml`, release validation helper and tests as needed.

**Interfaces:** Manual gate retains evidence and the exact validated candidate. Manual TestPyPI/PyPI publishing verifies the matching successful gate and frozen hashes, then uploads only those two files with OIDC.

- [x] Add failing tests for manual-only events, source-run verification, fixed candidate hashes, read-only gate permissions, OIDC/environment isolation and no rebuild.
- [x] Implement workflows and minimum offline validation support; validate YAML and shell/Python blocks locally.
- [x] Record required PyPI account / pending publisher / environment configuration, without claiming it is configured.

### Task 4: Local acceptance and documentation

**Files:** new `docs/releases/0.1.0a3.md`, `docs/alpha3-validation-status.md`, acceptance record; current installation, releasing, naming, capability and website entry points where needed.

**Interfaces:** Public a2 remains recommended for public installation; a3 is explicitly local/unpublished. Frozen a3 reports and hashes identify the new candidate.

- [x] Run release-tool/workflow tests, Ruff/format/whitespace checks and relevant documentation/website checks.
- [x] Check both archives with `twine check --strict`, run the existing macOS installed gate and separate sdist rebuild/install validation outside the checkout, including approval/recovery starters and the continuous journey.
- [x] Confirm the runtime product differs from a2 only by version, and all protected a2 checksum inputs remain unchanged.
- [x] Record actual local results and pending native remote CI / account / upload / public-install steps; do not promote historical qualifications.
- [x] Obtain an independent review; resolve material findings, then make one local commit with a command-scoped hook bypass. Do not push.

## Execution record

- Final local candidate and exact hashes are recorded in `architecture/reviews/2026-10-22-alpha3-pypi-preparation.md`. One earlier unqualified source archive was rejected by final Ruff; preserve it and its results, then freeze/retest the corrected final pair rather than claiming a single successful first attempt.
- Independent static review found no P1/P2. Its receipt-state and CLI-composition observations were covered before final freeze; five integration cases and the complete 159-check maintainer scope pass.
- Final local Mac installed gate: 311 basic / 16 recovery / two starters. Separate sdist rebuilt installation:155 checks / two starters. These are distinct overlapping scopes, not a full-project regression or remote qualification.
- Final local commit uses a command-scoped hook bypass; no push, CI dispatch, account configuration, upload, Tag or Release is performed.
