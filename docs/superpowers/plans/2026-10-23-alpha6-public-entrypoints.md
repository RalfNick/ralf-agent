# Alpha 6 Public Entrypoints Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; one final local commit after validation. No push or external publication.

**Goal:** Make `relf_agent` and `relf` / `relf-*` the canonical Python and CLI entrypoints in a separate `relf-agent==0.1.0a6` candidate.

**Architecture:** Mechanically move the existing package and update imports, dynamic module lists, generated applications and command hints. Keep runtime algorithms, stored namespaces, `RALF_*`, `.ralf`, protocol names and schemas unchanged. Extend existing release identity declarations with explicit Python-module and CLI fields, retaining historical defaults for original a1–a5 packages.

**Tech Stack:** Existing Python/setuptools, pytest, Ruff, Twine, manual GitHub Actions and static website.

**Spec:** User request following local a5 commit `e58f7f6`: rename both Python import and CLI to relf; previous no-feature, local-commit/single-hook-bypass/no-push constraints continue.

## Global Constraints

- Distribution `relf-agent`, version `0.1.0a6`, module `relf_agent`, command `relf` and `relf-*`; no old-namespace shim or duplicate execution implementation.
- New environment and matching components for new tasks. Preserve old SDK environments/Workers and artifacts; no automatic old-Run or History migration promise.
- Do not rename environment variables, persistent directory/database/schema identifiers, RPC fields, activity names, resource prefixes or registered wire identities.
- Preserve original a5/a4 packages, manifests, workflows, checks and acceptance documents; record new evidence separately.
- Keep original311/16/two-starter node identities, dependency lock and cached Linux2CPU/2GiB/swap0/offline/serial limits.
- Use current maintenance checkout and execute without another approval round: the user explicitly selected the new public names. One final local commit with command-scoped hook bypass and `[skip ci]`; no push/CI/account/publication/deployment.

## Review Focus

- A generated starter or CLI inspection hint must execute with the new installed import/command, outside the checkout.
- Dynamic Temporal imports, embedded subprocess code and packaged JSON schemas must remain usable; no surviving old runtime import.
- Historical archive validation must still select its original module and CLI, even though a5 and a6 share the same distribution and archive prefix.
- Module/CLI identity drift and mixed old/new package trees must fail before a deliverable is exposed.
- Current tutorials must identify a6 versus the website's pinned historical a1 examples, without rewriting old packages or records.

### Task 1: Package and command migration

**Files:** `src/ralf_agent/` → `src/relf_agent/`; `pyproject.toml`; current `tests/`, `examples/`, `.github/workflows/ci.yml`; new `tests/test_alpha6_identity.py`; historical correction fixture in `tests/fixtures/release_gate_alpha2_agent_sessions.txt`.

**Interfaces:** All current public Python symbols remain available under `relf_agent`; console entrypoint values point into that one package. Existing wire identifiers keep their bytes.

- [x] Add failing real import/`python -m`/CLI-entrypoint/starter-hint tests; observe failures without collection errors.
- [x] Move package, update current imports and dynamic module references, command entrypoints, generated scripts/hints and CLI presentation. Retain runtime control logic and persistent identifiers.
- [x] Update current test/example/CI imports and commands. Keep historical release fixture data under its original namespace; run current CLI, starter, binding, Temporal configuration and protocol checks.

### Task 2: Historical-aware release identity

**Files:** `tools/release_gate.py`, `release_preflight.py`, `stage_alpha1_candidate.py`, new `check_alpha6_publication.py`, `release_gate_manifest.alpha6.json`, three `alpha6-*.yml`, `MANIFEST.in`; new release/publication/workflow tests and shared archive fixture.

**Interfaces:** Optional `python_module` defaults to `ralf_agent`; optional `cli_name` defaults to `ralf`. a6 explicitly fixes `relf_agent` and `relf`. Only these known values are accepted; a6 publication requires the new pair and a6 workflow/run.

- [x] Add real renamed-module archive/preflight and wrong-identity tests; demonstrate RED while historical a5 fixtures remain old-module inputs.
- [x] Make archive/source/installed probes and starter command selection manifest-aware. Add separate manual a6 workflows and publication validation without modifying original ones.
- [x] Run new and historical maintainer contracts, CLI/install tests and static checks; keep all failures and do not relax deadlines or frozen gate nodes.

### Task 3: Documentation, freeze and installed acceptance

**Files:** Current README/user docs and website release notices, new a6 release/status/acceptance docs; ignored `dist/alpha6-candidate/`.

**Interfaces:** Separate immutable a6 original wheel/sdist and external manifest. Source receipt distinguishes build-input snapshot from final acceptance/commit.

- [x] Update current SDK examples and commands, new/old version boundaries and Publisher fields. Preserve historical review/release/plan documents and pinned a1 website examples.
- [x] Freeze originals with exact source/product/test hashes. Run full source regression, Twine, website checks and original-wheel311/16/two starters.
- [x] Rebuild/install the sdist outside source, run migration/CLI/continuous-example contracts and two starters; use cached Linux ARM64 three-Python serial gate with unchanged limits. Leave native AMD64/remote CI/public installation pending.
- [x] Obtain one fresh read-only review, address material issues, verify protected originals, record actual results, and commit once locally with single-command hook bypass; no push or publication.
