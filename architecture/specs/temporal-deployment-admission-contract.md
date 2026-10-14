# Temporal deployment admission: original History contract

This is the required Temporal continuation of [deployment admission](deployment-admission-contract.md), not an alternative to the full phase-three batch-2 gate. The first implementation slice establishes atomic History admission and immutable SDK root binding. Public Engine/Profile activation stays rejected until original Run/Parent dispatch, descendants, physical closure and release are implemented and validated.

## One authority and stable addressing

Extend the existing `ralf.temporal.commands.v1` Workflow with an explicit deployment mode; do not create an EffectJournal or service scheduler. Default scoped initialization and all existing responses remain byte-compatible. Deployment initialization has exactly `deployment_admission={version:1,policy:<full DeploymentAdmissionPolicy identity>,namespace:{name,id}}`. Namespace ID is a canonical UUID. The Workflow verifies its actual namespace name and Workflow ID before installing the mode; SDK namespace-ID retrieval belongs to the later public assembly path.

`registry_id(deployment_id)` is `ralf-temporal-deployment-` plus digest of the deployment ID. It excludes policy version, limits, queue and Scope. Temporal namespace independently addresses the Workflow. A selected deployment's original root ID is `ralf-temporal-` plus digest of `[deployment_id, scope, command_id]`, avoiding collisions with default roots and other selected deployments. A registry cannot be moved by modifying a current release. First accepted complete policy and namespace are immutable.

The deterministic state is attached to `TemporalCommandRegistryState`, held in its original History. Its internal module is not exported as a user-facing execution backend. It does not accept Run outcomes, budgets or external-effect receipts.

## Atomic reservation

Deployment `reserve` requires the exact fields `scope`, `command_id`, `kind`, `target`, `payload_digest`, `admission_policy`, `namespace`; submit additionally requires `root_admission={version:1,manifest_digest:<sha256>}`. Scope has exactly nonempty workspace/principal fields. All digests are SHA256. Policy/namespace mismatches refuse before mutation. Commands are keyed by digest of `[scope, command_id]`; no cross-Scope collision or locator disclosure.

An accepted duplicate returns the original detached reservation, even when full or when a new manifest alias resolves differently. Different kind/target/request under the same scoped command is an idempotency conflict. A fresh submit validates its derived root ID and atomically records request identity, first manifest and one held root under total and optional Scope limits. `CapacityExceeded` creates no command or root. The existing cumulative command-record limit (4096 by default) remains a separate bound. Fresh control commands refer only to an original root owned by the same Scope, consume no root quota and remain usable while the root limit is full. This initial slice does not accept separately submitted children or composition metadata; descendants inherit original root in the following integration.

The returned reservation remains `record_state=durably_recorded`, `apply_state=not_applied`: it is not a Run submission receipt. Root metadata additionally pins protocol, registry, Scope, original request and manifest digests and namespace in a `proof_digest`. State transitions are only held-unbound to held-bound in this slice. There is no TTL, reaper, forced release, inferred absence or terminal-state shortcut.

## Original SDK binding and observation

Registry Update `bind_deployment_root` requires exactly Scope, full policy, namespace, command ID, root Run ID, original request/manifest digests, reservation proof and a nonempty SDK execution epoch of at most 1024 characters. It binds only the originally accepted root. Exact retries are idempotent; foreign Scope, another root, forged proof, changed namespace/manifest/request/epoch refuse without mutation. This is a necessary identity gate, not proof of dispatch or completion; future integration must obtain the epoch from the original SDK execution before business Activities run.

Registry query `view` in deployment mode accepts exact kind `deployment_admission` plus Scope, policy and namespace. It returns policy, own held-root records and aggregate counts without foreign command/Run/principal locators. Unknown/malformed queries return a sanitized typed error. Caller mutation cannot change History records. Existing default-mode queries and Coding-composition updates are untouched; deployment mode explicitly refuses those composition updates until integration supports them.

## Required remaining full delivery

The first slice has no public Engine/Profile opt-in and no release operation. Uncertain SDK startup keeps its accepted reservation held. Subsequent delivery must bind accepted Run/Parent/child identities, gate all business dispatch, integrate original Coding/session ownership, preserve duplicate receipts, and release only after original tree, unknown effects, zero-cost reservations, auxiliary writes and actual handlers/stop proofs are closed. Original History is the source of closure evidence; arbitrary host terminal booleans are insufficient. Release failure retains quota and exposes a recovery path. Legacy scoped deployments cannot silently join an uncounted selected deployment.

Actual multi-client/Scope/queue concurrency, Worker absence/restart, History replay, independent installation and default compatibility prove the first slice only. Complete batch-2 acceptance additionally requires Agent/sequence/graph/Team/Dynamic/nested dispatch and recovery, approvals/deadlines, uncertain start, unknown effects, physical handler completion and controlled release. Matching old experimental Worker/source publication remains necessary; no old release is rewritten.
