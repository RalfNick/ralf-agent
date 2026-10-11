# Temporal Startup Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL superpowers:executing-plans inline. No implementation agents; exactly one final fresh-context read-only review. Human explicitly authorizes continuous architecture/capability completion and local commits, no push or repeated permission menus.

**Goal:** Refuse invalid basic Host startup configuration before service I/O while preserving original execution and lifetime contracts.
**Architecture:** Pure validators reuse existing Engine and installed SDK constructor declarations; original Host applies them before retained startup. No new authority or dependency.
**Tech Stack:** Python asyncio/inspect, original Temporal SDK and pytest.
**Spec:** docs/superpowers/specs/2026-10-11-temporal-startup-preflight-design.md.

## Global Constraints

- Baseef711f4/dev70; defaults/release/DTO/queue identities unchanged; local commits/no push.
- Engine only activity_timeout/drive_timeout, finite non-bool numeric seconds in (0,86400]; defaults60/120 unchanged.
- Worker names depend on actual installed SDK signature; protected original roles cannot be overridden.
- No constructor/callback/executor/network execution during validation. Rich SDK object semantics remain delegated.
- Every version's build_id validated before first RPC; corrected pure refusal can retry.

## Review Focus

1. Scalar subclasses, lazy values, bool/None/nonfinite numbers cannot bypass primitive validation or execute user code during pure preflight.
2. Older SDK optional signatures/newer fields and reserved activity/workflow registrations refuse coherently before Client state or I/O.
3. Cross-field cache/polls/slot/tuner and per-version build IDs cannot validate only the default Profile while another later version fails after I/O.
4. Caller cancellation, failed pure retry and mutated option dictionaries cannot change the retained actual startup, queue or original cleanup responsibility.
5. Original direct Engine/default manifest and hosted ordinary RPC/Session/global close behavior remain compatible; no independent scheduler or global capacity claim.

### Task 1: reusable pure option contracts

**Files:** create src/ralf_agent/temporal_startup_options.py and tests/test_temporal_startup_options.py; modify temporal.py only to reuse original timeout validation.
**Produces:** validate_engine_options(options) and validate_worker_options(options, *, releases) returning detached option dictionaries or raising typed refusal. Installed Worker parameter names read lazily after basic checks; no construction.

- [x] RED unknown/reserved names; original timeout boundaries and bool/NaN/inf; primitive nullable/int/bool/rate/timedelta cases; tuner/cache conflicts; all release build IDs; SDK signature absence/newer fields; no caller callback invocation.
- [x] Implement smallest pure shared validators, using installed official SDK signature and documented primitive contract; keep rich values borrowed and unexecuted.
- [x] Original direct Engine tests plus new validators GREEN; no default timeout/Manifest change.

### Task 2: before-I/O Host integration and delivery

**Files:** modify temporal_profile_host.py startup; create tests/test_temporal_host_preflight.py; update guide/capability/acceptance/CI/version only after behavior evidence.
**Consumes:** Task1 validators. **Produces:** pure refusal before Client/_route/_start_task/Engines/Workers; corrected retry uses original startup lifetime.

- [x] RED namespace/Worker/client-state counters for unknown/invalid/later-release options and primitive cross-field conflicts; prove no RPC and retry allowed.
- [x] Apply validators before _sdk/client-binding/start task; keep original task shielding/Worker owner behavior.
- [x] Original Host/routing/lifecycle/Session tests GREEN; minimal installed and explicit SDK path; real service smoke with original receipt/restart where affected.
- [x] Exactly one final fresh read-only review with fiveFocus; one unified Important/Critical RED→GREEN pass; final full/build/install/default70 compatibility/docs/owned-service stop; local commit. GoalR01–R26 remains active.
