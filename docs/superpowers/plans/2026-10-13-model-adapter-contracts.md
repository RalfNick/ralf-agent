# ModelProvider replacement implementation plan

> For agentic workers: use explicit parallel author lanes with exclusive files;
> root integrates shared protocols and runs one fresh whole-batch review. The
> user's continuous implementation and parallel authorization remains active.

**Goal:** Installed configurable ModelProvider replacement and a verified editable
Agent/RAG/Plan/Team business application, with original recovery.

**Architecture:** Add one role to the existing immutable suite/catalog runner.
Supplier fixtures configure actual providers beneath original Local authority;
application factories use original ComponentRegistry/BuildContext/ProfiledEngine.

**Tech Stack:** Python 3.11–3.13, existing SDK, sqlite3, pytest and Ruff. No added
runtime dependency or mandatory service/model.

**Spec:** [design](../specs/2026-10-13-model-adapter-contract-design.md).

## Global constraints

P01–P10 core and P01–P16 tools all required. Generic JSON output, optional extension
ports and lost-response uncertainty preserved. Existing K/S/Facts/model-check
metadata/reports/defaults and native identities remain unchanged. Owned/borrowed
resources, original Local/Temporal sole authority and actual process evidence
remain explicit. Preserve explicit resume/new-Attempt cost behavior and old unknown
holds. No remote push, implicit credentials/model, fallback or provider-hidden retry.

## Review focus

- Valid generic JSON/null Schema and unknown usage must keep original semantics.
- Deep/nonfinite/lazy completed output must retain known completion and drain.
- Supplier mutation and identity/method/source drift across await must be rejected.
- Historical or shared mutable audit counts must not fabricate lifecycle verdicts.
- Lost-response inspection must not redispatch; explicit resume preserves the
  original unknown hold and reserves its new Attempt separately.

## Task 1 — immutable catalog (parallel catalog author)

Files: `src/ralf_agent/adapter_contract_catalog.py`,
`tests/test_model_adapter_catalog.py` only.

Consumes: exact role/profile/P IDs, labels and observations in the spec.
Produces: additive MODEL_CONTRACT_CASES and core/tools catalogs through existing
`catalog_for`/`catalog_for_case`; no other published selection changes.

- [x] RED exact catalogs/digests, invalid selectors, immutability and literal
  old K/S/Facts report/catalog bytes.
- [x] Add only ModelProvider metadata and dispatch map entries.
- [x] GREEN catalog tests; report exact commands/exit codes and old byte anchors.
- [x] Hand off frozen metadata to root; no worker commit.

## Task 2 — actual provider cases (parallel cases author)

Files: `src/ralf_agent/model_adapter_contract.py`,
`tests/test_model_adapter_contract.py`, `tests/test_model_adapter_recovery.py`,
`tests/model_adapter_recovery_worker.py`. A reproduced known-completion evidence
defect may justify focused `model_evidence.py`/`test_model_evidence.py` changes;
coordinate with root before changing those existing files.

Consumes: catalog and spec fixture signatures. Produces ModelAdapterFixture,
ModelContractSession/Resource/Pause and `run_model_case(case_id, fixture, workspace)`
returning original AdapterContractCaseResult, with existing cleanup retention.

- [x] RED actual core/tools provider and original Run/effect/recovery cases;
  missing hooks, redaction, input mutation, real pause/cancellation/audit baselines.
- [x] Implement real checks through original Local Agent/Action/approval/budget.
  Tools business effect uses actual local durable receipt; fixture has no verdict.
- [x] Reproduce and repair any completed-evidence encoding issue through original
  Run before broadening consumer behavior; preserve unknown call semantics.
- [x] GREEN focused core/tools, lifecycle and original recovery tests, including
  actual waited/reaped child processes. Send raw evidence and owner closure.

## Task 3 — independent editable application (parallel reference author)

Files: `src/ralf_agent/model_adapter_contract_reference.py`,
`src/ralf_agent/model_adapter_contract_starter.py`,
`tests/test_model_adapter_reference.py`, `tests/test_model_adapter_starter.py`,
`docs/model-adapter-contracts.md` only. Use private test worker if Task 2 owns
the public worker. Coordinate fixture controls directly with cases author.

Produces `offline_model_fixture()`, lazy provider component registration and
`model_contract_files()`, full editable adapter and original engine factory.

- [x] RED direct independent provider/source, lazy config, owned/borrowed and
  SDK/JSON/TOML; original Run response-recorded and lost-response windows.
- [x] Implement actual supplier audit beneath provider, read real messages/tools;
  no SDK fake provider/test delegation or call deduplication.
- [x] Generate one app using existing Agent/current-source RAG/RulePlanner Plan/
  Supervisor Team; actual business sources/receipts and bounded verification.
- [x] GREEN same-app modes and configurations, explicit idempotent seed, read-only
  diagnostics, actual process recovery and cancellation/resource cleanup.
- [x] Write honest guide; report exact evidence, no source fallback/quality claim.

## Task 4 — integration and delivery (root)

Files: `adapter_contracts.py`, `adapter_contract_cli.py`, `__init__.py`, `cli.py`,
`starter.py`, version/docs/CI, new role/CLI tests. Leave authors' files exclusive.

- [x] RED runner/CLI/no-config zero-I/O/canonical old reports/public exports.
- [x] Add additive dispatch, explicit offline fixture and editable starter selector.
- [x] Review combined changes; one fresh whole-batch reviewer; repair actual findings.
- [x] Freeze source/tests; final full regression and appropriate static checks.
- [x] Build local wheel/sdist, independent core/SDK installations, original dev96
  native/default/model-check/K/S/Facts/Run recovery compatibility and actual
  application process evidence. Preserve previous installations immutably.
- [x] Synchronize accepted subset/open gates, check byte/document provenance and
  exact local commit/clean receipt; do not push. Standing goal stays active.

## Self-review

Every spec boundary has a task and exclusive owner. The cases and reference share
fixture signatures before implementation, while root owns existing integrations.
Current offline wiring does not prove real model quality or enterprise deployment.
Original response and effect evidence decides recovery, not source audit counts.
Root ruling: original recovery-guide.md:54 and Action contract T2 allow explicit
new model Attempts. Preserve this behavior rather than adding a blanket guard;
an incorrect ruling would silently change historical recovery semantics.


Delivery statistics and actual evidence are in the [acceptance record](../../../architecture/reviews/2026-10-13-model-adapter-contracts.md). Checklist marks record the accepted subset; local commit is verified by the separate exact Git receipt, not this checklist. Whole R01–R26 remains active.
