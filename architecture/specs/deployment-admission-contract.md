# Deployment root admission contract

Phase-three batch 2 adds deployment admission to the original execution authority. Local implementation is first; Temporal's independent History admission remains a required continuation, not a delivered capability. No new business scheduler or effect authority is introduced.

## Public policy and default

`DeploymentAdmissionPolicy(deployment_id, version="1", max_active_root_runs=32, max_active_root_runs_per_scope=None)` is an immutable portable policy value. Identity kind is `deployment-admission-policy`; IDs/version are nonempty text. Both limits are exact positive integers up to 10000 (no bool), and a selected Scope limit cannot exceed the deployment limit.

SDK `LocalEngine(admission_policy=policy)` and Local Profile `components.admission_policy={adapter:"bounded",config:{deployment_id:..., ...}}` select it. ExecutionPolicy identities do not change. Builder `build/abuild(..., admission_policy=policy)` provide a separate host declaration for legacy original Profiles; selecting both host and Profile sources is rejected before resource I/O. Legacy recovery uses the unchanged original Profile plus this host policy. Custom sync/async ComponentRegistry factories must return the exact policy value; invalid/lazy results fail and owned assembly rolls back. First Local delivery explicitly refuses Temporal admission configuration before component I/O; the subsequent Temporal delivery must implement original History admission.

Omission on an unconfigured Store preserves default Profile, Manifest, requests and Schema 1. A physical SQLite execution authority is one deployment; its stored deployment ID and complete policy cannot be moved by changing aliases, current Profile, principal or policy omission. Distinct SQLite databases do not share capacity. No queue/fairness/TTL eviction is claimed.

## Optional completed Store contract

Mandatory ExecutionStore v1 remains unchanged. Optional `LocalAdmissionExecutionStore` advertises `local_admission_version=1` and these completed synchronous operations, with no external business I/O:

- `local_capacity_policy() -> dict | None`: detached exact policy identity or None before activation.
- `prepare_local_capacity(policy: dict) -> None`: in the original execution transaction, atomically fix deployment policy, activate Schema 16, preserve Session/native publication tables, and seed legacy occupied roots. Existing identical policy is idempotent; a different ID/version/limit refuses. Initial legacy occupancy may exceed selected limits; original recovery is allowed and new admission denied.
- `local_capacity_acquire(scope: Scope, root_run_id: str) -> None`: in the original submit transaction, validate stored policy and atomically reserve one root claim under deployment and Scope limits; repeated held claim for the same identity is idempotent. Typed `CapacityExceeded` is transient refusal, no accepted Run/command is created; an accepted duplicate command still returns its original receipt before fresh admission.
- `local_capacity_release(scope: Scope, root_run_id: str) -> bool`: in the original transaction, release exactly one held root only if original durable tree is terminal/quiet and has no pending reservation (including amount zero), unknown effect or auxiliary/stop obligation. False retains occupancy; True means already released or released now. Host also proves actual handlers/drive owners have ended before invoking it. No TTL/terminal shortcut.
- `local_capacity_holders(scope: Scope) -> tuple[str, ...]`: detached unique held root locators for only this Scope, at most 10000; no foreign owner IDs in diagnostics/errors.

Original Store/backend/method bindings and policy object/identity are fixed. Lazy operations/results and malformed values refuse. Scope/ownership/topology mismatches refuse. An adapter remains responsible for atomicity and truthful completed operations, without SQL reflection by Engine.

## Activation, acceptance and bypass prevention

Explicit policy assembly acquires the original Coordinator, then activates policy and seeds legacy claims in a separate original Store transaction before serving submissions. A full legacy deployment does not roll policy activation back with a later rejected submit. Constructor failure keeps existing ownership cleanup rules; failed activation cannot be represented as installed.

On an already configured Store a capable Engine requires the exact policy; omission/mismatch refuses before accepting work. The SQLite `insert_run` mandatory write boundary also validates the original claim/protocol, preventing a new-version proxy that hides the optional port from bypassing an activated deployment. Old dev115 Reader refuses Schema 16. No new authority is created by this last insertion guard.

New roots atomically acquire a claim with original command/Run/budget/events. New Run metadata `local_admission={version:1,root_run_id:...}` plus its digest references the original root. Manifest selects `local_admission_protocol=1` and `admission_policy` identity. New children inherit the original root without consuming another root quota, and require the same Scope, validated original parent chain and held root claim. Original parent budgets and per-Run concurrency bounds remain independent.

Legacy Runs retain original Manifest and release digest: deployment activation never rewrites old accepted releases or adds a new quota on recovery. Legacy children resolve to their original root. Original Scope recovery may settle/remove that held legacy claim; exceeding a newly installed limit does not cancel old accepted work.

## Occupancy, evidence and lifecycle

Capacity claims are durable original authority facts, held until safe release. All accepted nonterminal roots, approval/input pauses and terminal roots with obligations remain occupied. Children share the root; original child links, settled escrow and tree closure are checked.

A shared pure `capacity_obligations(run) -> bool` conservatively reads original records/parallel frames: nonterminal state, nonquiet graph/team, model/tool pending/executing/unknown/received evidence, unfinished memory/context/artifact/remote Session/native-history writes, and delegated stop obligations. Known ended model verifier stages retire through the original ParentCompletion journal. Schema-16 governed retirement preserves a received but unadopted proposal in the existing closed stage; plain ungoverned old records do not gain this variant. Unknown or actual work stays pending, and terminal recovery covers the persisted pre-retirement window. Store additionally checks EXISTS reserved/unknown reservations across the tree, not just summed held credits. Business ready/approval proposals with no dispatched/unknown attempts on terminal work do not require a new execution. Prepared but undispatched auxiliary writes on terminal failed/cancelled work can be safely retired only along existing semantics; malformed evidence cannot make occupancy disappear.

Engine try-release also checks original `_active`, `_drive_users`, `_inflight`, parallel tasks and real thread trackers for every original descendant. A cancelled asyncio Task cannot prove a thread ended. Coding uses its original physical stop evidence. Cold Coordinator acquisition does not clear unknown durable facts. Waiting timeout, business deadline, caller cancellation and close do not independently free quota.

Releasing a claim is idempotent original control/cleanup, not re-opening business. Cleanup after actual drive/thread completion and refresh before fresh submission allow progress; direct cancel/reconcile and safe close also attempt release. Normal paused close retains the claim for original recovery. No force-release API is provided. Terminal obligations stay diagnosable and recoverable with matching original components; incomplete evidence is not waived for capacity.

## Delivery gates

Local gates: SDK/JSON/TOML/factory replacement and no-port safety; defaults/legacy release compatibility; Schema 15→16, rollback and immutable old Reader refusal; concurrent atomic Store claims; cross-Scope limits without foreign locators; duplicate accepted requests while full; nested/graph/Team/Dynamic shared root; deadline/approval/unknown/amount-zero reservations; actual sync thread ownership; process crash and original recovery; source/fixed installed wheel and owned process cleanup.

Temporal remains batch-2-required: a deployment-addressed extension of original CommandRegistry History, scoped command identity, receipt-bound original Run acceptance/epoch, no release on uncertain SDK startup, and original Run/Parent terminal+actual stop evidence. Its shared policy/identity must be fixed without moving registry identity when limits/task queues change. EffectJournal stores evidence, not another admission execution authority. Actual multi-client/Scope/service/History replay/installation evidence must precede batch-2 closure.
