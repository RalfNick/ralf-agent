# Facts Adapter Contracts Implementation Plan

> **For agentic workers:** Use the user's explicitly authorized parallel method,
> with isolated contexts and exclusive files. Root integrates shared protocols
> and one fresh final review; no worker commits or pushes independently.

**Goal:** Make Facts replacements checkable and usable through configured defaults,
original pipeline/managed execution and real save recovery.

**Architecture:** Extend the existing immutable role/profile catalogs and original
runner. Facts core and managed ports are distinct; Local/Temporal retain authority.

**Tech Stack:** Python >=3.11, stdlib/sqlite3, existing SDK; no new runtime dependency.

**Spec:** [design](../specs/2026-10-13-facts-adapter-contract-design.md).

## Global constraints

- dev96, baseline a147fde/dev95; local commit only, no push/model credentials.
- facts-store/v1 core=F01–F10; managed=F01–F16, all selected cases required.
- K/S catalogs, canonical bytes and published native methods/defaults retained.
- No fixture = zero testing I/O/not_run; missing hook = not_verified.
- Current Facts, exact inspection, scanner/index and vector authority stay distinct.
- Original tasks/resources/loops/Run/stage/budget survive cancellation and recovery.
- Full R01–R26 and actual service/model/adoption gates remain open.

## Review focus

1. Eight Scope/namespace partitions must expose omission of either Scope dimension.
2. Raw CAS retry conflict must not be misrepresented as message dedupe or exact-once.
3. Cancellation during prepare/seed/fault must drain only original work, no later I/O.
4. Malformed completed facts/expiry/ACK and lazy validation must fail at adoption.
5. Partial/unknown memory stays separate from business result and original settlement.

## Task 1 — Facts catalog and compatibility (catalog worker)

**Files:** modify adapter_contract_catalog.py only; new
tests/test_facts_adapter_catalog.py.
**Interfaces:** same catalog_for/catalog_for_case; exact cases/labels/observations
from design, core/managed catalogs, managed case-owner superset.

- [x] Record RED for literal K/S bytes/digests and new immutable Facts selection.
- [x] Implement fixed core/managed metadata, no fixture or I/O dependencies.
- [x] GREEN completeness/mixed catalogs/unknown selections/immutable keys; freeze.

## Task 2 — Cases and consumer adoption (case worker)

**Files:** new facts_adapter_contract.py, facts_store_values.py;
private engine.py full-facts adoption only; new test_facts_adapter_contract.py and
test_facts_store_values.py. No native memory/binding/pipeline/managed edits without
root agreement and a concrete failing reproduction.
**Interfaces:** concrete fixture DTOs and run_facts_case(case_id,fixture,workspace)
from design; AdapterContractCaseResult/shared cleanup transfer.

- [x] RED real malformed values, F01–F16, missing hooks and cancellation windows.
- [x] Implement black-box checks, original MemoryPipeline/ManagedMemoryPolicy and
Local Run/reservation recovery with actual evidence, no alternative authority.
- [x] Validate/detach private full-read adoption; retain native fingerprints.
- [x] GREEN targeted cases and existing Facts/binding/pipeline/managed anchors;
failed cleanup retry on original loop and actual handler drain; freeze.

## Task 3 — Independent default, configuration and recovery (reference worker)

**Files:** new facts_adapter_contract_reference.py,
facts_adapter_contract_starter.py, tests/test_facts_adapter_reference.py,
test_facts_adapter_starter.py, test_facts_adapter_recovery.py,
facts_adapter_recovery_worker.py, docs/facts-adapter-contracts.md.
**Interfaces:** exact public names/factories/generator and fixture management hooks
from design. Full sqlite3 implementation copied into editable agent_app/adapter.py.

- [x] RED actual source CAS/TTL/detachment/receipt/currentness and isolation.
- [x] Implement core/managed sync/async, pinned dataset/file, scoped bounded ports.
- [x] Test lazy SDK/JSON/TOML, sync/async owned/borrowed and all three modes in one app.
- [x] Two actual original process crash windows, wait/reap, unchanged Run/stage/
commands/budget/model count/accepted fact count; no seed on recovery; freeze.

## Task 4 — Root integration and acceptance

**Files:** runner/CLI/SDK exports/starter registration/version/CI and capability
status/remaining/architecture/continuous docs; new test_facts_adapter_roles.py,
test_facts_adapter_cli.py. Keep authors' exclusive files separate.

- [x] RED shared role/profile/no-config/CLI/canonical K/S/report behavior.
- [x] Integrate dispatch, exports, explicit offline and starter paths.
- [x] One fresh whole-batch review and same-reviewer repair closure.
- [x] Freeze source/tests; full regression, isolated installations/generated app,
original dev95 defaults and Run/stage compatibility, actual required recovery.
- [ ] Source/wheel/sdist/installed/static/documentation provenance; synchronize
accepted subset/open gates, exact local commit/clean receipt, no push.

## Self-review

This is one complete configured Facts replacement chain, not a count of adapter
interfaces. Current read values preserve extension provenance; inspection remains
current state. Recovery uses original reservation/action evidence. Fixed observers
do not prove intelligence or semantic quality. Additional indexing/service/quality
work and all remaining capabilities stay in the standing goal.
