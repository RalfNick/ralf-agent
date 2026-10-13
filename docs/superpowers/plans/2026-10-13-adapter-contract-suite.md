# Adapter Contract Suite Implementation Plan

> **For agentic workers:** Execute independent tasks in parallel under the user's
> continuing authorization; freeze shared contracts first and perform one fresh
> whole-batch review. TDD and verification-before-completion apply.

**Goal:** Make installed external KnowledgeRetriever replacements verifiable.

**Architecture:** A pure entry/report layer dispatches frozen black-box role
cases; actual KnowledgeContext/BuildContext/Local execution retain authority.
An independent SQLite adapter provides explicit offline examples and recovery.

**Tech Stack:** Python >=3.11, stdlib, existing SDK/JSON Schema/SQLite; no new
required dependency or pytest dependency for SDK execution.

**Spec:** [design](../specs/2026-10-13-adapter-contract-suite-design.md).

## Global constraints

- Version dev94; no remote push or credential/model discovery.
- Fixed knowledge-retriever contract/suite version1, K01–K12 required cases.
- No fixture -> not_run/zero I/O; missing hooks -> not_verified, never pass.
- Public reports contain bounded finite counts, stable codes/digests and safe refs.
- Model/semantic quality null; real-service/recovery/adoption claims need evidence.
- Original Run/default/recommended/Temporal identities and unique authorities remain.
- Owned/borrowed and actual task/thread cleanup follow original Runtime contracts.
- Root integrates shared files and records test/build/process handles.

## Review focus

1. A fixture that lies, omits hooks or returns malformed/deferred values cannot
   supply a passed verdict or hide a required case.
2. Exceptions/identity/config text and crafted evidence paths cannot leak into
   public reports; cancellation cannot leave a resource released while calls run.
3. Source version/metadata/expiry/Scope and same-identity backend/method drift
   fail before original source disclosure or business tools.
4. Installation and actual external replacement do not depend on repo tests or
   delegate the purported external adapter to an internal Retriever/Store.
5. True process recovery preserves received responses/snapshots/budget and does
   not reseed deleted sources, repeat model/tool work or claim Temporal coverage.

## Task 1: Runner and detached reports (runner worker)

**Files:** new adapter_contracts.py, adapter_contract_types.py and focused tests.
**Interfaces:** AdapterContractSuite(role="knowledge-retriever", contract_version="1");
async run(fixture=None, *, evidence_dir=None) -> AdapterContractReport; immutable
AdapterContractCaseResult(case_id,status,code,observations,evidence), report.to_dict().
Role function `run_knowledge_case(case_id, fixture, workspace)` returns a case result.

- [x] Write missing-feature runner/report/zero-I/O/partial/malformed/cancel/evidence tests; record valid RED.
- [x] Implement fixed case dispatch, bounded truthful reports and optional evidence ownership.
- [x] Run focused tests and report GREEN plus original error/cleanup responsibility.

## Task 2: Knowledge role and original context boundary (knowledge worker)

**Files:** new knowledge_adapter_contract.py and tests; retrieval.py method pinning
only, plus relevant regression tests. Own KnowledgeAdapterFixture and concrete
KnowledgeContractSession types; notify reference worker immediately after signatures freeze.
**Interfaces:** run_knowledge_case(case_id, fixture, workspace), shared case result;
prepare(case_id,workspace), actual source/fault/audit hooks and original BuildContext.

- [x] Write RED K01–K12 valid/invalid/missing-hook cases and method-drift regressions.
- [x] Implement black-box cases, original-source/binding/consumer boundaries and actual cleanup.
- [x] Run role/context/data-binding anchors; preserve defaults and honest unverified cases.

## Task 3: Independent adapter, installed reference and process recovery (reference worker)

**Files:** new adapter_contract_reference.py, adapter_contract_starter.py,
focused integration tests/process fixture and docs/adapter-contracts.md.
**Interfaces:** explicit offline_knowledge_fixture(); external structural SQLite
Retriever, same fixture session hooks; public example generation and installed
SDK entry. Original ComponentRegistry/RuntimeBuilder/KnowledgeContext only.

- [x] Write RED actual independent adapter/JSON/TOML/sync/async/lifetime and consumer tests.
- [x] Implement independent source and truthful offline fixture, four consumers and docs.
- [x] Validate actual independent original response windows with source deletion,
  wait/reap and no reseeding/retrieval/model/effect repeat; report handles.

## Task 4: Public integration, acceptance and local commit (root)

**Files:** __init__.py, CLI/pyproject/CI as needed, capability/architecture/review
records, README/CHANGELOG/version and cross-layer public tests.

- [x] Add installed SDK exports/CLI explicit offline/no-config behavior with RED/GREEN.
- [x] Obtain one fresh full-batch review; repair substantive findings and impacted regressions.
- [x] Freeze/run complete source and installed actual suite/examples/recovery; compare
  old defaults/original records and source/wheel/sdist provenance, actual process cleanup.
- [x] Synchronize accepted subsets/open goals; complete static/docs/credential checks.

Local delivery follows these checks: create the exact reviewed local commit and
verify a clean worktree, without a push. Its outcome is recorded by the Git
receipt and the final delivery report; the complete R01–R26 goal remains open.

## Self-review

Each required case maps to role tests and the independent fixture. Runner cannot
accept fixture verdicts; management is separated from the production port.
Shared declarations and packaging have one integration owner. Recovery and
quality evidence remain separate, retaining the full original capability goal.
