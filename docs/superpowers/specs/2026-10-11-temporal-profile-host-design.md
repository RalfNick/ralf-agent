# Temporal Profile Host design

Baseline: 4186fe2/dev69. Implements the approved R04/H1/H5 configuration and original-release routing subset; R01–R26 remains active. Human requests continuous development/local commits/no push.

## Purpose and observed problem

Developers should retain the original Worker versions when switching the default Profile. A command Registry and Session Coordinator retain their first task queue in History. Starting only the new version's queue can leave updates waiting for an absent old Worker. Dev69's installed example reproduced this with a reused Scope/command and a different data path; isolated namespace acceptance passed. This batch addresses explicit multi-version hosting rather than changing command identity or creating a new authority.

## Public interfaces

- `TemporalProfileCatalog.profiles`: detached immutable tuple of registered TemporalProfiles. Existing JSON/TOML schema and Profile identity unchanged.
- `TemporalRuntimeBuilder.abuild_catalog(catalog, *, data_path=None, scope=None) -> TemporalProfileHost`: snapshot every Profile/default/base_dir, pure-preflight all declarations before any factory, construct existing assemblies with one owned-resource ledger on the creation loop. At most32 registered Profiles; refuse larger catalogs before I/O. Explicit SQLite paths can share a Session dataset; implicit data_path remains the caller's declared common data prefix.
- `TemporalProfileHost.start_workers(client, *, queue_prefix="ralf-profile", engine_options=None, worker_options=None)`: single borrowed original SDK Client; deterministic distinct queues from prefix + Scope + actual release digest. All compatible original versions remain served. The prefix and all old resolved resources must be retained across restart. No implicit SDK connect/service creation.
- `select_default(identity)`: explicitly switch to a registered, already hosted exact Profile, purely on the hosting loop. Existing handles retain their original facade/components. Mutating the supplied Catalog cannot affect the Host.
- `runtime(identity=None)`: create/track a borrowed existing `Runtime.from_temporal` facade for the selected exact version; no third scheduler. Reject until complete startup and during close/Worker fatal failure. Public Host does not expose assemblies or raw Runtime components.
- `aattach(RunRef)`: validate Scope/actual authority; describe original Workflow using server metadata without requiring its Worker, resolve its declared queue, query original diagnostics through that version, validate saved Profile and original release, then return an existing AgentRun. Unknown queue/Profile/resource refuses; never substitutes current defaults.
- `aattach_session(SessionRef)`: validate Scope and current actual namespace identity, describe original Coordinator queue, query bounded pure binding metadata (Profile identity/task_queue/binding revision/definition digest), resolve its accepted current binding, then use existing Session attachment. Stale binding is refused; no implicit rebind or data migration.
- `aclose(wait_timeout=30)`: retryable shared ownership; reject concurrent close. Stop new entry/admission across every version, retain startup and RPC work, drain every actual handler/thread and original Context/Session acknowledgment while every required Worker can still receive them, stop every SDK Worker, then close each distinct owned resource exactly once. Borrowed SDK Client remains open. SDK fatal failures reach caller after safe cleanup; incomplete shutdown retains all required ownership.

## Reuse and authority

Original TemporalEngine/Runtime facades, Workflow Histories, command Registry, Session Coordinator, RunRef/SessionRef and Context/Session end gates remain authoritative. The Host only selects original published queues and owns lifecycle. Existing unprofiled releases, native save-v1, dev69 single Assembly and DTO shapes remain exact-compatible. No wildcard Activity dispatch or one queue with mismatched Profile workers.

SDK Workflow description provides original queue/type; SDK payload conversion is not needed. Startup describes the existing scoped command Registry before Worker activation. If its original queue/type is unavailable, reject promptly rather than awaiting an unserved update. SDK namespace UUID, Client object and service endpoint are pinned across awaits. Session binding metadata is a new scoped pure query, not a transition or a new persisted index. All routing outputs must be revalidated against declared queue, saved Profile identity and original metadata.

## Resource responsibility

All owned resources across this Host share one BuildContext ledger; duplicate ownership of the same object and mode closes once, conflicting close modes refuse. All contexts are on one loop. Construction cancellation retains cooperative factory tasks and explicit bridge threads as dev69 does. Partial construction/start failure retains a cleanup handle. A single failed or closed child cannot release a shared client while another version's actual operation remains live. Undeclared private background work remains unsupported.

Workers and caller facades may be closed independently only through the Host's managed protocol. Factory ownership transfer after startup is unavailable. Root resources are released after every child has established actual stop. All original notification receivers remain alive during the global drain. Close deadlines remain per phase; custom resource close duration is unbounded and must retain retry on cancellation.

## Boundaries and acceptance

No automatic code archive/download, hot component migration, SDK deployment versioning/Continue-As-New, automatic process-loss supervision, cross-authority leases, global quotas, enterprise IAM or live quality claim. Missing historical Profiles/resources must be restored explicitly. Legacy unprofiled queues are not fabricated from new Profile declarations; use the original advanced host. Old code need not support new Host/query APIs; default old/new execution must still recover.

Required evidence: every invalid late declaration refused before factory I/O; alias mutation isolation; original queues after default switch and process restart; approval duplicate receipt and once-counted tools; persistent native and graph Sessions/rebind; unknown old Registry queue prompt refusal; shared-resource model/thread shutdown and failed/cancelled startup; default core-only configuration/no implicit network; isolated wheel installed behavior; actual old69↔new compatibility; one final read-only review, unified Important fix pass, full/package/docs gates and local commit. Scripted providers establish mechanics, not semantic quality.

## Necessary configuration closure discovered by actual write acceptance

Temporal-only `components.effect_journal` reuses the existing PostgreSQL EffectJournal, with adapter postgres/config dsn_env/backend_id/initialize/timeout. Secret DSN is only environment-resolved, never placed in declarations. All config/env validation precedes construction; factory owns async connection, optional explicit initialize, and shared Host cleanup. Default remainsNone/read-only; Local Profile schema unchanged. The original evidence/adoption and write exclusion protocol is unchanged. Physical resource restoration and migrations remain operator responsibilities. This is required to test real writes through the declared Host rather than substituting query-only tools.
