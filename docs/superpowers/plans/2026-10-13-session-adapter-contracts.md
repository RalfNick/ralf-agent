# Session Adapter Contracts Implementation Plan

> **For agentic workers:** Execute the user's explicitly authorized parallel
> method with exclusive files after contract freeze. Root integrates shared files;
> TDD, original operation ownership and one fresh final review apply.

**Goal:** Validate installed SessionStore replacements and demonstrate original
Session save recovery with an editable independent adapter.

**Architecture:** Immutable role/profile catalogs extend the existing suite,
retaining Knowledge v1 bytes. Fixed Session cases use original memory_call,
BuildContext and Local execution; a separate SQLite adapter provides actual data.

**Tech Stack:** Python >=3.11, stdlib/sqlite3, existing SDK. No new runtime dependency.

**Spec:** [design](../specs/2026-10-13-session-adapter-contract-design.md).

## Global constraints

- dev95; local commit only, no remote push or credential/model discovery.
- session-store/version1 core=S01–S10; receipts=S01–S14, all required.
- Knowledge v1 aliases, digest and report serialization remain exact.
- No fixture -> zero I/O/not_run; missing hooks -> not_verified.
- Typed-valid input domain; malformed completed results refused at adoption.
- Original public Store method fingerprints/default manifests retained.
- Same owner and original loop retain actual calls/resources through failed cleanup.
- Quality/service/adoption/full R25/H3/M1/R01–R26 remain separately open.

## Review focus

1. Fake/omitted hooks or mixed catalogs must not turn incomplete evidence into pass; Scope isolation includes both workspace and principal.
2. Lost ACK, stale retries and duplicate IDs preserve original revision/content.
3. Repeated cancellation/release/close failure must not close active resources or start later case I/O after an original operation drains.
4. Malformed output including bool/float ACK and NaN history cannot succeed.
5. Independent replacement must not delegate to SDK memory or create new Run/Turn.

## Task 1: Frozen catalog (catalog worker)

**Files:** new src/ralf_agent/adapter_contract_catalog.py and
 tests/test_adapter_contract_catalog.py.
**Interfaces:** catalog_for(role, contract_version, profile), catalog_for_case(id);
immutable catalog role/version/profile/cases/case_ids/labels/observation_keys/
boolean_observations/count_observations/suite_digest. K constants stay existing
aliases in adapter_contract_types. Shared stable status-code table unchanged.

- [x] Write and run RED literal Knowledge digest/catalog compatibility tests.
- [x] Implement immutable core/receipts catalogs and exact-type validation.
- [x] Run focused GREEN malformed ID/role/profile and immutable catalog tests.

## Task 2: Session cases and original consumer (Session worker)

**Files:** new src/ralf_agent/session_adapter_contract.py,
 src/ralf_agent/session_store_values.py; modify only private engine.py adoption;
 tests/test_session_adapter_contract.py and test_session_store_values.py.
**Interfaces:** run_session_case(case_id,fixture,workspace); concrete fixture DTOs
specified in design; shared AdapterContractCaseResult and cleanup transfer.
Root exports these after author freeze. Session audit fields: read_calls,
append_calls, inspection_calls, message_count, revision, close_calls,
backend_switches, consumer_runs, model_calls, save_count, receipt_checks,
reopen_calls, rejection_checks, scope_checks, address_checks; boolean fields
runtime_closed, borrowed_closed, handler_finished, cancelled, cleanup_complete,
ports_valid, identity_valid. No fixture verdict or source text in report.

- [x] Record RED for S01–S14, missing hooks and real malformed consumer outputs.
- [x] Implement typed-domain black-box cases using actual adapter readbacks and
 original BuildContext/Local Run/Turn. Preserve pending actual I/O cleanup.
- [x] Add private completed read and append validation: exact tuple[int>=0,
 list[finite exactdict]], detached; ACK exact int in 1..observed_revision+1,
 permitting original lower duplicate revision. No public Store method changes.
- [x] Run focused GREEN and original Session/native compatibility anchors.

## Task 3: Independent reference and starter (reference worker)

**Files:** new src/ralf_agent/session_adapter_contract_reference.py,
 session_adapter_contract_starter.py; tests/test_session_adapter_reference.py,
 test_session_adapter_starter.py, test_session_adapter_recovery.py and
 tests/session_adapter_recovery_worker.py; docs/session-adapter-contracts.md.
**Interfaces:** offline_session_fixture(); copied editable SQLite Store/receipt
 facade and fixture; starter generator matches existing template generator seam.
 Fixture prepare returns SessionContractSession with actual isolated addresses.

- [x] Record RED for independent actual read/CAS/dedupe/receipt/persistence.
- [x] Implement explicit/lazy independent sqlite3 adapter, physical dataset pin,
 scoped exact receipts and safe cleanup; full implementation copied into starter.
- [x] Validate SDK/JSON/TOML sync/async owned/borrowed factories and actual consumer.
- [x] Verify two original process save windows with exit/wait/reap, same original
 Run/Turn/commands/budget and no duplicate model/save/reseed; preserve failures.

## Task 4: Shared integration and acceptance (root)

**Files:** adapter_contract_types.py, adapter_contracts.py, adapter_contract_cli.py,
 __init__.py, starter/CLI/pyproject/CI, capability/status/architecture/docs.
**Interfaces:** Suite keyword-only profile='core'; Report keyword-only role/profile
 defaults Knowledge/core, K dictionary unchanged, S dictionary includes profile.
 _run_case retains 3 parameters and selects by fixed case ID owner.

- [x] Record RED public suite/report/no-config/CLI/completeness compatibility tests.
- [x] Integrate selected catalogs/role dispatch, SDK exports and explicit offline CLI.
- [x] One fresh whole-batch review; same reviewer closure after required repairs.
- [x] Freeze source; full regression, installed SDK/CLI/generated app and old/new
 original compatibility; wheel/sdist/module provenance and static/doc checks.
- [x] Synchronize accepted subset/open gates and prepare exact reviewed local delivery.
 Git and the private delivery receipt record the resulting local commit/clean
 worktree; no push, and the full goal remains active.

## Self-review

Every S case has a real port evidence owner; receipts are selected explicitly.
Core does not acquire admission/pagination requirements. Product file ownership
is disjoint except root integrations. Failed cleanup and process windows retain
original evidence. No suite result certifies model/service/adoption quality.
