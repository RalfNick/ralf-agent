# Alpha 2 public release completion plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the immutable a2 artifacts on native AMD64, close the optional Temporal fingerprint test, publish the verified Alpha through GitHub Release, and verify its public installation and recovery.

**Architecture:** Reuse the existing draft-to-artifact transport, immutable checkout, installed-artifact gate and starter recovery checks. SDK files and the original a2 artifacts remain fixed; release tooling and public status are recorded separately. PyPI publication requires actual project control and usable authentication, and is not inferred from GitHub ownership.

**Tech Stack:** Python 3.11–3.13, Docker cgroup v2, GitHub Actions/API, existing locked gate dependencies, matching optional Temporal SDK.

**Spec:** `docs/alpha2-validation-status.md`, `docs/releases/0.1.0a2.md`, `docs/release-gate.md`, and the user's explicit request to complete the remaining validation and public delivery.

## Global Constraints

- Preserve a2 wheel SHA `dfac0e38b2a879d8eb0c23dd5889774a0d64860c9ffe1945f9ef945629f95a46` and sdist SHA `8a6be717541117ce8cecf4135ba5442936b3192b9d1967d5c79ca90511a35cc8`.
- Preserve gate revision 2, 311/16 exact node identities, two starters, all original failures and limits.
- Native AMD64: 2 CPU, 2 GiB, swap0, pids256, offline test containers, Python 3.11 → 3.12 → 3.13 serial.
- Authenticate GitHub as RalfNick before mutations. Never print or persist credentials.
- No SDK features, broad CI, forced push, unrelated website changes or inferred general compatibility.
- User now authorizes staging, necessary pushes/manual fixed CI, public Alpha release and public installation; previous stop-before-publication applies only to earlier tasks.

## Review Focus

- An unrelated account, existing conflicting tag/release or different asset SHA must prevent publication.
- Draft staging must reject public/foreign/extra/changed assets before exposing a candidate.
- A workflow must pin immutable accepted tools and verify real native architecture and resource limits.
- Missing optional SDK or a skipped test is not a passing fingerprint inventory test.
- Anonymous public download must match the original two artifact hashes; fresh installation must prove approval, duplicate request and recovery.

### Task 1: Prepare exact transport and optional fingerprint evidence

**Files:** `tools/stage_alpha1_candidate.py`, `tests/test_stage_alpha1_candidate.py`; external evidence under `dist/alpha2-public-release-20261022/`.

**Interfaces:** Existing `stage(release_id, output, spec, fetch_json, fetch_blob)` remains unchanged; select the private staging prefix by the fixed supported Alpha version.

- [x] Add and run RED tests for a2 exact draft acceptance, version/prefix mismatch and unsupported version rejection.
- [x] Make the minimal staging change, retaining a1 behavior; run affected maintenance tests and static checks.
- [x] Run the original missing fingerprint inventory node using the immutable a2 wheel in a matching Temporal SDK environment; record exact SDK versions, artifact/node identities and result.
- [x] Commit the transport tool locally with one-shot hook bypass and `[skip ci]`; record immutable tool SHA for Task 2.

### Task 2: Native AMD64 fixed gate

**Files:** `.github/workflows/alpha2-stage-candidate.yml`, `.github/workflows/alpha2-release-gate.yml`, focused workflow contract tests.

**Interfaces:** New a2 workflow names, a2 asset names, private draft prefix and Actions artifact name; both workflows pin Task 1's immutable tools commit. a1 workflows remain unchanged.

- [x] Add and run RED tests for manual-only triggers, exact checkout, existing action SHAs, resource/native gate command and a1 preservation.
- [x] Derive a2 workflows from the already accepted a1 workflows; run affected tests and static/YAML validation.
- [x] Push only necessary reviewed commits as RalfNick; create an unpublished staging draft with the two original assets, dispatch staging, verify resulting hashes and dispatch fixed native gate.
- [x] Download real reports and inspect all three JUnits, platform/config/serial timestamps, cleanup and artifact identities. Retain any failures and diagnose before proceeding.

### Task 3: Public Alpha delivery and installed recovery

**Files:** Current release/install/status docs and a new acceptance record; no SDK/artifact rebuild.

**Interfaces:** Public GitHub prerelease `v0.1.0a2`, exact original wheel/sdist and artifact-only checksums; anonymous download URL. PyPI is a separate target requiring actual verified control.

- [x] Verify repository publication permission, absent/conflict-free tag, fixed source tree, all gate results, license and release notes; prepare exact release assets and source/tag identity.
- [x] Publish the verified prerelease, preserving all historic artifacts and evidence. Remove only this session's unused staging draft after proof is retained; do not delete unknown resources.
- [x] Download publicly without credentials, verify SHA, install into a fresh external environment, and run version, starter approval/duplicate/recovery and continuous example checks.
- [x] Update status/docs to actual results and boundaries, perform final independent review and checks, and commit/push the release evidence docs with `[skip ci]`.

## Execution rulings and ledger

User already explicitly requested continuous completion of these tasks, including public delivery, so no repeated plan approval is required. Execute sequentially in the current checkout, preserving unrelated website work. Evidence records, original failures and all actual remote identifiers are the completion authority.
