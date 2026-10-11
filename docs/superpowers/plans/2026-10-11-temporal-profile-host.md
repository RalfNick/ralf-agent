# Temporal Profile Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL superpowers:executing-plans inline. No implementation agents; exactly one final fresh-context read-only whole-batch review. Human explicitly authorizes continuous approved-architecture implementation, local commits and no push; do not repeat approval menus.

**Goal:** Retain original Temporal Profile queues and shared resources when defaults change and old Runs/Sessions reconnect.
**Architecture:** A managed Host selects original immutable assemblies/facades and server queue metadata; existing History/Registry/Coordinator remain the only execution authorities.
**Tech Stack:** existing Python asyncio, ComponentRegistry/BuildContext, Temporal SDK and portable DTOs.
**Spec:** docs/superpowers/specs/2026-10-11-temporal-profile-host-design.md.

## Global Constraints

- Baseline4186fe2/dev69; R01–R26 active; local commits/no push/no secret output.
- Existing catalogs/Profile/default manifests and RunRef/SessionRef unchanged.
- Maximum32 explicit Profiles before any factory I/O; one original Client/Scope/creation loop.
- Distinct deterministic queues retain original prefix/resources; unknown historical queues refuse, not fallback.
- Shared resources close only after ALL actual tasks/threads and original end notifications, then every SDK Worker; injected Client borrowed.
- No Local Store, new business index/state machine, hot migration or live-quality claim.

## Review Focus

1. A later invalid declaration, cancelled factory/start/close or fatal SDK child must retain shared resources and actual work; a successful sibling cannot be silently released.
2. Actual namespace/Client/endpoint/default changes across awaits cannot redirect History, broaden Scope or replace an accepted release.
3. Original Registry/Coordinator queues must remain served through default switch/restart; absent versions refuse promptly before business dispatch.
4. Shared object ownership, reentrant/concurrent cleanup and partial global drain cannot close another version's live resource or lose original end acknowledgment responsibility.
5. Unprofiled/native save-v1 and dev69 single-assembly startup/close remain exact-compatible; unsupported configuration refuses before I/O and no third authority appears.

### Task 1: catalog snapshot, global pure preflight and shared factory ownership

**Files:** modify temporal_profile.py, temporal_builder.py/runtime_lifecycle.py only as required; create temporal_profile_host.py lifecycle skeleton, tests/test_temporal_catalog_assembly.py and tests/test_temporal_catalog_lifetime.py.
**Produces:** immutable profiles tuple; abuild_catalog/capped snapshot; all original ten-role preflight; one loop-bound owned-resource ledger; retryable partial-construction cleanup, dev69 unchanged.

- [ ] Missing API/module RED: detached Catalog/default mutation, limit32, invalid last Profile before first factory, shared object close once/conflicting close modes, actual constructor thread cancellation and cleanup retries.
- [ ] Implement pure preparation reuse and global ownership without LocalEngine/store; isolate lifecycle module as needed rather than expanding builder into a scheduler.
- [ ] Run new catalog assembly/lifetime plus original Profile/assembly/async-runtime/owned-resource contracts GREEN. Verify exact defaults/metadata and missing optional SDK behavior.

### Task 2: hosted versions, original queue routing and complete close

**Files:** implement temporal_profile_host.py and focused temporal_host_routing.py/temporal_host_lifecycle.py if needed; extend temporal_session_state.py pure binding query; tests/test_temporal_profile_host.py, tests/test_temporal_host_routing.py, tests/test_temporal_host_lifetime.py.
**Consumes:** Task1 assemblies/resource ledger. **Produces:** start_workers/runtime/select_default/aattach/aattach_session/aclose with retained original queues, SDK metadata and shared stop responsibility.

- [ ] RED real-metadata-shaped unit tests: existing Registry queue/type unavailable; default changes during await; caller cancelled startup; SDK fatal sibling; exact original queue/profile/resource in Run/Session attach; stale/unknown refs; borrowed Client; global concurrent close and actual blocked thread/resource cleanup.
- [ ] Start distinct original assemblies with one client; pin namespace UUID/endpoint; retain startup task and failed cleanup handle. Resolve scoped server metadata before querying/dispatching; add bounded pure binding query and reuse existing DTO/facades.
- [ ] Globally stop admission and drain all versions while all end receivers remain alive, stop every SDK Worker, then shared owned resources. No child independent resource cleanup.
- [ ] New routing/lifetime plus original Session/facade/SDK registration contracts GREEN; no default payload/authority change.

### Task 3: actual restart/alias/shared shutdown, installed example and final acceptance

**Files:** tests/temporal_profile_host_worker.py and tests/test_temporal_profile_host_service.py; installed example/guide and capability/architecture/acceptance records.

- [ ] Actual separate Worker process: version1 approval→version2 default→restart all hosted versions→original receipt/effect/History replay; new task usesversion2; repeated original command returns old receipt.
- [ ] Actual native and graph persistent Sessions, default change without implicit rebind; explicit idle CAS rebind; old Registry missing queue refusal; unknown original refs refusal without model/tool I/O.
- [ ] Actual async/thread sibling shutdown: global close incomplete keeps every shared resource/end receiver; release→original proof→SDK stop→one resource close. Failed startup and cancellation retain retry.
- [ ] Offline installed Catalog example and explicit SDK path; core-only/no-implicit-connection; docs show all open R04/H1/H5 boundaries.
- [ ] One final fresh read-only reviewer with five Focus; one Important fix pass RED→GREEN; final full/build/source/installed/actual/default old69 compatibility/module/metadata/docs; owned services stop+wait; local commit and continue capability goal.
