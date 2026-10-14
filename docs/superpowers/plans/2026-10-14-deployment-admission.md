# Deployment admission implementation plan

> **For agentic workers:** Use the already authorized parallel execution method; root owns shared Engine integration. Storage and disjoint tests are delegated, followed by independent review.

**Goal:** Deliver durable Local root admission with default/replacement/configuration and actual recovery evidence; retain Temporal deployment admission as required next delivery.

**Architecture:** Original SQLite command/Run authority owns root claims. A portable immutable DeploymentAdmissionPolicy is separate from per-Run ExecutionPolicy. No new business state machine, queues or TTL release.

**Tech Stack:** Existing Python 3.12 SDK, SQLite transactions, original Coordinator/handler trackers, pytest process fixtures.

**Spec:** `architecture/specs/deployment-admission-contract.md`.

## Global constraints and review focus

Default omitted bytes/Schema 1 stay unchanged. Opt-in Schema 16 rejects old readers. Policy activation commits before a full-deployment submit refusal. Legacy roots count without modifying releases. Roots retain unknown/zero-credit/child/auxiliary/real-handler obligations; new-version connection-hidden proxies cannot bypass original insertion admission. No remote push, credentials, fake model quality or batch-2 closure without Temporal.

## Storage deliverable

Files: `src/ralf_agent/sqlite_capacity.py`, `src/ralf_agent/capacity_rules.py`, `storage.py`, `sqlite_sessions.py`, `ports.py`; tests `tests/test_local_admission_storage.py`.

- [x] Write/run RED for Schema16/default/15 preservation, transaction rollback, deployment/Scope atomic limits, exact repeated root, legacy seeding/unknown/zero-reservation retention and hidden-port insert refusal.
- [x] Implement the five optional completed methods from the spec and shared `capacity_obligations(run)->bool`; policy identity consumed from governance value, all durable closure checked under original transaction.
- [x] Run storage cases, preserve original dev115 Reader probe, give root exact port names and pure-rule semantics; no Engine or policy edits by storage worker.

## Shared integration deliverable

Files: `governance.py`, `errors.py`, `__init__.py`, `local_admission.py`, `admission_factories.py`, `runtime_config.py`, `runtime_builder.py`, `temporal_builder.py`, `engine.py`, `orchestration.py`; tests `tests/test_local_admission.py`.

- [x] Write/run RED policy validation and root SDK occupancy/duplicates/recovery/legacy/actual-thread cases before production changes.
- [x] Add portable immutable policy and bounded factory, exact type/lazy/preflight guard, Local role; Temporal explicit preflight refusal until History delivery.
- [x] Register/pin completed Store methods; activate policy after original Coordinator inside constructor rollback boundary, preserve default omitted bytes.
- [x] Root/child acceptance select original metadata/Manifest and same-transaction acquisition; legacy release reconstruction omits new markers. Validate Scope/root and original claim at dispatch.
- [x] Try-release only after durable closure and actual root/descendant owner checks, on actual cleanup/direct controls/safe close and before fresh submit. Store release False retains obligations.
- [x] Run orchestration/parallel/deadline/unknown regression; independently review hidden adapter bypass, zero-cost reservations and abandoned child evidence.

## Configuration and process deliverable

Files: tests `test_local_admission_profiles.py`, `test_local_admission_process.py`, fixture `local_admission_worker.py`; worker owns only these files.

- [x] Write/run RED SDK/JSON/TOML/sync+async factory/no-port/malformed return/owned rollback/default compatibility; build/abuild host policy must preserve legacy original Profile, rejecting dual sources before I/O.
- [x] Prove actual pending approval owner crash retains occupancy and original receipt; recover with original policy/Scope, reject new root while occupied, then settle original once and admit next. Verify actual PIDs and installed imports.
- [x] Cover different Scope original ownership and terminal unknown persistence without model/network calls.

## Acceptance and commit

- [x] Independent targeted review/RED fixes, final affected source and matching wheel installed tests, immutable dev115 default/legacy/Reader comparison and product byte provenance; cleanup owned process handles.
- [x] Document current delivery, support matrix and pending Temporal capacity; no reuse of old full regression as current full pass. Update version/CI, complete plan boxes from evidence, local commit only.
