# Temporal Profile Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL superpowers:executing-plans inline; no implementation agents. Exactly one final fresh-context read-only whole-batch reviewer. Human authorized continuous architecture-aligned implementation/local commits/no push; do not repeat approval menus.

**Goal:** Build versioned Temporal components from explicit JSON/TOML declarations and retain actual Worker/resource close responsibility.
**Architecture:** Reuse RuntimeProfile/ComponentRegistry/BuildContext, original TemporalRuntime and History authorities; mechanical actual-call ownership only, no LocalEngine or new business scheduler.
**Tech Stack:** existing Python JSON/TOML/asyncio/thread tracker and Temporal SDK.
**Spec:** docs/superpowers/specs/2026-10-11-temporal-profile-assembly-design.md.

## Global Constraints

- R01–R26 remains active; only local commits/no push/no secret output.
- New Temporal catalogs kind temporal-profiles/schema_version1; existing Local v1/v2 unchanged.
- Strict execution flags enable_sessions/session_writes/composite_sessions/context_reads; all defaults False.
- Context/Session actual end proofs remain original History responsibility; mechanical Worker owner is not business authority.
- Owned factory resources close only after actual calls/threads and original notifications; injected SDK clients remain borrowed.
- Unknown/Local-only declarations fail before construction I/O; no fake executionStore/lease.

## Review Focus

1. Cancellation during async construction or cleanup retains owned clients/tasks and a retry handle; never silently closes live delegated work.
2. Raw runtime/Worker borrowing cannot bypass actual-handler close responsibility, including summary/write and post-observer-cancel threads.
3. Profile/default/path/Scope changes do not reinterpret original Release or receipt; exact same version conflicting content refuses.
4. Activity decorator/context wrapping retains actual SDK UUID/attempt/namespace and does not reschedule business calls or discharge original Context/Session end gates.
5. Existing Local catalogs/default Temporal manifests remain exact-compatible; unsupported new configuration is refused before I/O, not dropped.

### Task 1: pure immutable Temporal Profile and Catalog

**Files:** create src/ralf_agent/temporal_profile.py, tests/test_temporal_profiles.py; export pure objects in __init__ only after tests.
**Interfaces:** TemporalProfile(name,version,providers,components=None,binding_components=None,execution=None).identity/to_dict/providers/components/binding_components/execution; TemporalProfileCatalog(base_dir=None).register/set_default/resolve/default_profile/from_file; pure bounded JSON/TOML parsing and atomic in-memory registrations.

- [x] Write missing-module RED tests for immutable full identity, component/flags/paths, duplicate JSON keys/versions/unknown fields/bounds, explicit kind and Local rejection, core-only noSDK import.
- [x] Implement pure declarations using existing RuntimeProfile validations; no factories constructed.
- [x] Run new Profile plus original runtime_config/assembly contracts GREEN. Expected complete defaults and new declarations are retained exactly.

### Task 2: assembly factories and mechanical Worker close ownership

**Files:** create src/ralf_agent/temporal_builder.py and temporal_assembly_lifecycle.py; modify temporal_activities.py/temporal.py for explicit profile and managed Activity hook; tests/test_temporal_assembly.py and test_temporal_assembly_lifetime.py.
**Consumes:** Task1 profiles. **Produces:** TemporalRuntimeBuilder.abuild(profile,*,data_path=None,scope=None)→TemporalRuntimeAssembly; profile/scope/release/capabilities/start_worker/create_engine/aclose/detach_components, failure cleanup handle. DefaultFalse/raw legacy runtime unchanged.

- [x] Tests missing builder RED: defaults, alias/config cloning, all supported components/ten binding roles, source paths, pre-I/O invalid declarations and old profile identities.
- [x] Build with existing ComponentRegistry and BuildContext(None,...); explicit owned/borrowed resources; original Runtime runtime_profile argument, defaultNone exact compatibility.
- [x] Actual thread/async/cancel/close and borrowed-runtime cases RED. Track SDK activity task/thread lifetime separately; retain Worker on incomplete close so original end Updates remain reachable. Enforce pre-start explicit detach_components ownership transfer; no implicit raw runtime exposure or early cleanup.
- [x] Failure/cancel cleanup/retry, strict flags/timeouts/close reentry and lifetime tests GREEN; no hidden Engine/store/lease construction.

### Task 3: real SDK composition, install, docs and local acceptance

- [x] Real separateWorker/Service native+sequence+graph+Team+DAG+nested from Profile, original approval/restart/History replay, task/model/save counts; thread/model/summary/write shutdown windows and original gate proofs.
- [x] Real Redis/PG declared factories and per-Agent selectors; no configured skip claimed as evidence.
- [x] Add installed offline-first Temporal configuration example, guide/capability/acceptance records; core-only Profile/factories and explicit optionalSDK refusal.
- [x] One final fresh-context Astra readonly review with five Focus and ledger rulings, one important fix pass RED→GREEN; full regression/build/installed/core/module/Metadata/old68compat; owned services stopped/waited; local commit and continue full capabilities.
