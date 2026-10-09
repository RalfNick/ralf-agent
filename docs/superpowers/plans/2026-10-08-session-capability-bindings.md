# H1c Local Session Capability Bindings Implementation Plan

> Execute inline using executing-plans, TDD and verification-before-completion. The user authorized continued implementation of the approved H1 architecture. Preserve all changes and evidence locally; no commit, push, cleanup or live-model calls.

**Goal:** Select existing sync/async Session backends per Agent with host-authorized namespace views and durable canonical resource admission, including Local graph/team/dynamic/nesting.
**Architecture:** BindingCatalog fixes Session resources; an immutable view projects logical IDs to actual storage keys. ExecutionStore optionally provides session_resource_owner inside the existing acceptance transaction; SQLite derives legacy claims and persists new resource claims without a new state machine or SQL schema. Parent/child/node release checks remain authoritative.
**Spec:** architecture/specs/agent-capability-binding-contract.md; architecture/specs/agent-facade-session-contract.md (H1 resource identity only; H2 APIs deferred).
**Tech Stack:** Existing Python/SQLite/sync+async Session ports; no new runtime dependencies.

## Global Constraints

- Preserve original native local-4 and H1a/H1b identities and requests when Session refs are absent. Session refs use local-bindings-3; old runtimes must refuse them before dispatch.
- Namespace selectors only for the Session role and only within a host-registered allowlist. Other selectors/roles, Temporal bindings and H2 Facade/Turn/rebind/close semantics remain refused/deferred.
- Canonical ownership uses trusted Scope, raw backend_id and actual storage key, not catalog ID or logical Session label. Aliases, inherited default access and direct physical-key access cannot bypass an active owner.
- Persist full potential serial/parallel leaf Session claims, retain approval/unknown/quiescent ownership and preserve legacy session_ids with physical aliases for conservative old-reader protection.
- New refs require a synchronous execution-authority session_resource_owner capability. Legacy stores without it keep legacy behavior and refuse refs before Run creation.
- Session views are borrowed; builder factories register ownership on actual clients. No global current-agent state or hidden model I/O. Pagination/CAS/message dedup/cursor isolation remain backend-owned.
- Continue in the existing dirty checkout to preserve authorized increments; no Git mutations or worktree creation.

## Review Focus

- Two catalog aliases/default bindings/direct physical Session IDs targeting the same storage address must share admission across restart; unrelated resources should remain independent.
- New canonical claims must cover mixed inherit/ref/disabled sequential and parallel leaves, preserve real-thread quiescence, and remain safe for old-reader refusal.
- Namespace views must freeze scope/selection, validate host allowlists before I/O, preserve page cursors and refuse backend drift before and after awaits.
- Composite parent/member/node releases must retain Session selections, isolated child IDs, budgets/cancellation and original approval/evidence recovery.
- Existing accepted native/H1a/H1b releases, including large native schemas, must recover from actual dev26 wheel; unsupported custom stores/Temporal must refuse before dispatch.

### Task 1: Session resources and scoped views

**Files:** new src/ralf_agent/binding_sessions.py; binding_catalog.py; tests/test_session_binding_resources.py.
**Interfaces:** SessionBindingResource(backend, *, namespaces=(None,), default_namespace=None), immutable namespace/scoped view with read/append/read_page and resource identity; catalog Session ref returns view plus fixed resource record.

- [x] Write Session ref/default/allowlist/invalid-selector/Scope/alias/page-CAS/drift tests against real memory/SQLite ports; missing role/module expected RED.
- [x] Implement strict pure selection and guarded sync/async view, preserving underlying cursor and physical key binding. Run resource tests GREEN.

### Task 2: Durable Session resource admission and Local routing

**Files:** new src/ralf_agent/session_resources.py; storage.py; ports.py; binding_runtime.py; binding_manifests.py; engine.py; orchestration.py; tests/test_session_binding_execution.py.
**Interfaces:** optional session_resource_owner(scope, resource)->run_id|None, atomic under command transaction; canonical resources from recorded manifests; admit_sessions(engine, manifest, logical_ids, plan=None) returns persisted claims/legacy aliases only for new refs, unchanged legacy DTO otherwise.

- [x] Write alias/default/physical-ID busy tests with restart/approval, separate backend/namespace tests, serial/parallel/nested/team/dynamic routing, replay/removal, drift evidence and unsupported-store refusal. Expected RED at unsupported ref/admission.
- [x] Implement actual-address claims, original legacy inference, pure node/resource projection, Session role routing and kernel3 release. Run new execution and original binding/workflow/crash tests GREEN.

### Task 3: Configuration, remote conformance and installed compatibility

**Files:** runtime_builder.py; __init__.py; pyproject.toml; tests/test_session_binding_configuration.py; tests/test_session_binding_remote.py; SDK/docs support records.
**Interfaces:** session maps to existing session_store factories; session-resource adapter wraps a prepared nested session_store with allowlist/default namespace, keeping original sync/async factory and owned-client cleanup. Public SessionBindingResource export.

- [x] Write JSON/TOML sync/async assembly and owned/borrowed cleanup tests; expected RED without factory/export. Implement optional wrapper preparation, no new base dependencies.
- [x] Verify actual localhost Redis Session view/CAS/restart and configured-only PostgreSQL cases; unavailable services are explicit skips. No external paid model calls.
- [x] Build wheel/sdist, installed Session and original binding contracts; actual dev26 wheel recovery of native/H1a/H1b and refusal of new Session release; version dev27 with accurate docs/remaining-work updates.
- [x] Run full pytest, Ruff/format/Git whitespace; perform exactly one fresh-context final review and one test-driven fix pass for important findings. Record actual results and deferred H1/H2 scope.
