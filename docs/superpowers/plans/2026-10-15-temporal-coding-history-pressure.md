# Selected deployment3: Parent History and control projection proposal

Status: implementation in progress, not accepted or released. Compact identity queries, invocation-local validation, control carriers and child-change notifications have implementations and focused tests. The earlier sandbox/admission failures below were resolved; all thirteen selected topology cases have since passed with actual Temporal/PostgreSQL. Trials39–40 also passed the two original Tool-worker death cases and four recovery cases. The remaining gates include the newly added actual approval-idle History/ledger window, the owned-close maintenance/late-release repair, final regression, installation and compatibility. Historical failures remain evidence rather than current blockers; see the [current acceptance record](../../../architecture/reviews/2026-10-15-temporal-coding-wake-latency.md). Implementation follows the user's existing continuous-development authorization.

## Problem and acceptance boundary

Frozen4 removed the zero-timer self-wake loop, but Trial07 still reached 70.9 MB JSON, 1321 events and 76 CONTROL Activities with 16 timers. Repeated full request/Manifest/child snapshots/physical proofs and repeated SDK proof walks remain costly. There is also a distinct original-call ledger bound: `CALL_CAPACITY=4096`; unchanged observe Activities consume that bound even if their payloads are compressed.

The proposed guarantee is that an unchanged approval/reconciliation wait produces no additional Parent Activities, timers, call records or full observation payloads as wall-clock time passes. A finite amount of legitimate business/recovery work still produces History. This is not a promise that arbitrarily many commands fit one History, and does not remove existing call/command limits.

Apply the new path only to explicit deployment publication3. Unselected, private1 and public2 retain their current paths. Keep native6/binding22/composition7/binding23 logical schemas and full callable inventories. Selected3 histories require their exact immutable matching Worker; do not upgrade an existing selected History to changed code.

## 1. Invocation-local bootstrap and exact compact validation queries

Use the audit's single exact ABI `deployment_coding_validation`, not a second competing identity query. Each original Activity/invocation first completes the existing full SDK deployment/Coding ancestry verification once. Native22 uses the deployment chain; composition23 additionally validates the original Coding edges and requires both chains to agree. An unpinned edge first completes the existing discovery/pin gate. Do not bootstrap a guessed edge.

Keep only immutable original identities in the invocation-local snapshot: fixed Scope/namespace UUID, Registry original epoch/configuration/policy, actor/ancestor SDK epochs/types/task queues/actual parent tuples, original request/Manifest/release/start(queue+timeout)/admission metadata and receipt digests, original first envelope digest, and unique immutable child-edge tuples. Do not retain a revision, held/admitted/close/stop/sealed flag, mutable state or permission. A snapshot cannot cross an Activity invocation, attempt, owner or original carrier digest. It is not a Runtime cache.

Node query request is exact `{kind:'deployment_coding_validation', scope, run_id, execution_epoch, child_call_id}`. Leaf has child_call_id=null; ancestors use the original unique call.id established by bootstrap.

Node response is exact `{version:1, scope, namespace, run_id, execution_epoch, original_execution_epoch, identity_digest, revision, state, stop_requested, sealed, edge, proof_digest}`:

- identity_digest is derived by the server from its original stored request/Manifest/release/admission/receipt/start(queue+timeout)/parent links, never from caller expected hashes.
- edge is null or exact `{call_id, child_run_id, child_execution_epoch, identity_digest, dispatch_started, owned}`. Its identity_digest covers the bootstrap's original immutable call tuple: request digest, deployment metadata digest, Coding parent-link digest, command/member/planning revision/depth/cap identity. owned means the original state contains exactly that original edge; it is never a caller claim or permission to dispatch. Duplicate call.id is refusal.
- revision/state/stop_requested/sealed/dispatch_started/owned are fresh original facts. proof_digest is the digest of the response excluding that field and provides consistency checking, not independent authority.

The selected3 SDK query handler rejects incorrect Scope/run/epoch, non-original current/first/original SDK epoch, wrong publication and ambiguous original edge before returning the pure projection. It neither emits events nor pins/adopts/cancels/restores anything. It returns no complete request, Manifest, action list or children list.

Registry query request is exact `{kind:'deployment_coding_validation', scope, admission_policy, namespace, command_id, run_id, execution_epoch, request_digest, manifest_digest}`.

Registry response is exact `{version:1, registry_id, registry_execution_epoch, configuration_version:3, policy, scope, namespace, root_identity_digest, submission_digest, held, retired, close_requested, admitted, proof_digest}`. Derive the root from the one original record plus original coding_index. held requires the same current original held-bound root/epoch; admitted equals held and not retired and not close_requested. Do not reuse an existing coding_admission admitted=!close value as proof of held ownership. A missing record/root refuses; absence cannot become retired. A retirement true value requires the existing matching positive tombstone and is usable only along the original cleanup/stop path.

## 2. Fresh verification before and after control/native I/O

Each fresh validation phase performs:

1. Read the actual namespace resource UUID before the phase.
2. Concurrently query each fixed original node projection, describe each node through an unbound SDK handle to detect current-epoch replacement, query the one Registry projection and describe that Registry. Await/drain every sibling even when a read fails; no validation read may outlive the actual-call owner ACK.
3. Read and compare the actual namespace resource UUID after all reads finish.

For depth d (d ancestor edges, d+1 nodes), this is 2d+6 RPCs in three dependent rounds, excluding the bootstrap and actual native/control I/O. This is a design count, not a measured latency claim.

Every description must bind ID/type/namespace/task queue/actual parent tuple, be RUNNING, and have current run_id == raw first_run_id == expected original epoch. The original query must also bind original_execution_epoch. The Registry must be RUNNING with first=current=original pinned epoch and configuration3. Termination is not reset proof, no-start or physical closure.

Compare projected immutable identity/edge/root/envelope digests to the full bootstrap snapshot; reject parent/descendant replacement, changed pin/intent, Scope/UUID/queue/timeout/request/Manifest/release drift. Compare fresh cancellation/stop/seal/Root held-close-retirement facts before business I/O and freshly again afterward. Do not carry a pre-I/O result across that boundary. Runtime release validation, actual SDK Activity identity and fixed callback/Runner/PG callable-resource pins still run at every required before/after check.

The existing native ABI matters: TemporalCodingAuthority._call validation returns None and _update has no fresh-result parameter. Therefore selected3 validate and grant_allowed each perform their own compact fresh set; retain the dedicated immediate pre-grant check and original grant Update followed by a fresh set. For a child with one ancestor edge this can be 8 before + 8 dedicated grant check + 1 native Update + 8 after = 25 RPCs; a standalone root with no ancestor uses 6 per set, or 19 RPCs. These are design counts, not measured latency. Removing the dedicated set requires an explicitly reviewed single-call result handoff with no intervening await; it is not part of the minimum implementation. Never hide lastAllowed in callbacks/Runtime.

Only the original Run-owned native Update grants phase permission. Compact validation is not a new permission authority. A close/cancel can race after the final fresh read and before a grant; the original grant authority and stop intent must still converge that race. Already issued native grants retain exact stop responsibilities and are not retried merely because a post-read fails. Do not claim an atomic Registry+Run transaction.

Full mutable native/physical/effect evidence is still fetched for dirty observations, child stop adoption, sealing/release and cold fencing. Original action_stops, Runner/owner identity, exact effect ACKs, unknown credit, store resources and child tree checks remain. Cleanup/query/adopt paths may validate original identities after admission closes; new business/grants require fresh held and no close/stop/seal. No compact boolean replaces physical closure.

## 3. Child wake replaces unchanged polling

Add exact `deployment_child_wake` Signal `{version:1, scope, parent_run_id, parent_execution_epoch, child_run_id, child_execution_epoch, token}`. The child sends it to the actual SDK original parent tuple. The Parent accepts only its recorded original child/epoch/Scope; the signal is merely a dirty hint. A token/hash/caller counter must never grant admission or advance a trusted observation watermark.

Each started/pinned child is initially dirty. Observe only dirty children, plus those explicitly selected by cancel/recovery obligations. Capture a Parent-local dirty generation before awaiting CONTROL. Clear it after validated adoption only if that generation has not changed; an approval/end/stop signal arriving during the await remains pending. Do not overwrite the pre-await business wake revision afterward.

The child emits a deterministic token after observably relevant original facts change: business revision, physical/native owner stop, effect/context/session/tool obligations, and first actual-call end/fence relevant to closure. Revision alone is insufficient because deployment call-end changes the ledger without `_emit`. Repeated identical ACKs do not notify. A Parent's own observe begin/end does not create a child notification feedback loop.

Persist the child's notified token only after SDK signal delivery completes. Send before entering indefinite waits and after relevant accepted Update/Activity results. A cold replay/continuation must finish any pending notification and perform an initial observation opportunity; no volatile-only notification task or timer can be the recovery guarantee.

Approval/reconciliation changes notify the original parent; Parent cancel/stop acts immediately on its own command, then waits for original child proof. Drive marks all still-unsettled children dirty and retains original recovery semantics. Late owner/end/effect ACKs notify even during retirement verification. With no dirty children or runnable work, wait on real commands/child hints, without the .5s timer.

Worker disappearance or no new notification is not evidence of closure. An unchanged unknown remains held until genuine proof or an explicit recovery drive. This preserves safety while eliminating no-progress History growth.

## 4. Compact selected3 CONTROL operation and observation DTOs

New selected3 CONTROL request is exact `{version:1, mode, scope, parent_run_id, parent_execution_epoch, child_run_id, child_execution_epoch, parent_request_digest, manifest_digest, child_intent_digest}`. Mode is one of the existing register/observe/cancel/recover values. Child epoch may be null only on original discovery/start uncertainty; use the existing full original intent and SDK-parent discovery/pin procedure, not latest-epoch control. Other cases require the original pinned child epoch. No caller queue, request body, Manifest, complete child record, old snapshot or permission is included. Queue/timeout come from the accepted original start binding.

`child_intent_digest` is computed over an explicit immutable identity tuple `{id, call_id, member, input_digest, command_id, run_id, request_digest, cap, depth, planning_revision, deployment_metadata_digest}`. Mutable snapshot/settlement/epoch/stop fields are excluded and separately read fresh. The query must project its own recorded intent; it does not echo the digest from the Activity request.

The exact compact request becomes this selected3 control Activity's original logical handler body. Its existing carrier/actual-call SHA is computed over that body before scheduling and checked consistently at the SDK handler boundary; no late header injection or reconstructed request may change that SHA. Original Tool/native/model/session/context business request bodies and hashes remain unchanged. This is an explicit source-pinned selected3 internal control operation revision; it is not an automatic replay upgrade of old selected Histories.

Observe reply is exact `{version:1, binding, observation, physical_proof}`:

- `binding` is exact `{scope, namespace, parent_run_id, parent_execution_epoch, child_run_id, child_execution_epoch, manifest_digest, request_digest, child_intent_digest}` from the verified original endpoints.
- `observation` retains the full original snapshot and budget, release_digest and the five resource flags `{quiescent, remote_stop_confirmed, unknown_remote_execution, evidence_ack_pending, reconciliation_pending}`. Preserve the existing protocol-selected input journals/planning_input_sources and native history fields needed by `observed_journal`/`observed_bundle`; leaf episodes and Parent bundles keep their existing respective semantics. No complete workflow.children, DAG, old observed_flow or diagnostic stage list is sent merely for Parent bookkeeping. Full public diagnostics queries remain unchanged.
- `physical_proof` retains the original mutable native/composition7 proof evidence, including state/revision/physical_stopped/action_stops/proof_digest. Only its immutable Manifest/request fields may use explicit references to the Parent's already held exact accepted Manifest and original child request. Before calling the unchanged original pin/adopt validator, restore those two exact objects and verify the original full proof_digest. A missing/mismatched reference refuses; never rebuild an unknown request from its digest. Initial discovery without a known exact original child request keeps the full proof path.

The selected3 adapter reconstructs the original validator input using its held exact Manifest/request and the new observation fields. `state.observe` currently consumes these five workflow resource flags at observation_version2; its fingerprint deliberately excludes a child's private DAG/children/planning bookkeeping. This must be covered by equivalence tests for native Agent/sequence and Parent graph/Team/dynamic/recursive results, input requests and native history. Do not remove snapshot/action/native evidence required by those consumers. Public diagnostics/native6/composition7 logical proof shapes remain intact.

No generic compression codec is implemented in this batch. If retained snapshots still dominate after event-driven scheduling and projections, a separate reviewed deterministic reference/compression encoding may reduce those bytes, preserving exact decoder output and original logical SHA. Generic shared-client PayloadCodec is not the minimal solution: installed SDK serialization context has no publication identity and warns that activity_type/task_queue may be unavailable. It can alter default/shared-client histories.

Compression alone is relief, not a bounded-wait fix. Long-poll within the existing fixed Activity timeout also repeats Activity/ledger records forever; increasing timeout is excluded. Continue-as-new replaces the execution epoch and violates this batch's original-History authority, so it is outside this proposal.

## Exact freshness and recovery matrix

| Operation / race | Required original facts before I/O | Fresh facts after I/O / recovery behavior |
| --- | --- | --- |
| register/start | SDK original/first/current actor epoch; UUID; exact first root/start binding; all ancestor states/admission open; original unique intent and cap/depth; no stop intent | Reread identity/admission/stop vector after registration before child scheduling; original native grants still validate on the child; cancellation does not manufacture no-start |
| observe | Original actor/target SDK epochs, exact parent tuple and intent; root/Scope/UUID/start binding; closed admission permits only the existing evidence-read path | Reread epoch/UUID/current ancestry/stop facts before adoption; retain unknown unless complete original observation/physical evidence verifies; dirty generation arriving during await remains pending |
| cancel | Original unique target, pinned epoch, original root and ancestry; original stop authority | Actual original command receipt and fresh child state/proof; stale/split root or reset refuses; no latest-epoch redirect |
| recover/drive | Same original identities and admission/cleanup classification; actual original recovery request, not caller permission | Fresh close/stop facts after I/O; existing drive marks unsettled targets dirty, no inferred ended handler |
| terminal owner/end/effect ACK | Exact original accepted receipt/owner/call identity | First material ACK changes notification token and wakes pending retirement even during its await; identical duplicate is no-op |
| Worker crash before child signal delivery | The original notification token remains pending in History replay | Send unfinished notification again; Parent does not advance trusted watermarks from caller token; one initial dirty observation exists |
| child start uncertain / no epoch pin | Existing complete original intent; SDK original actual parent and first/current epoch discovery | Existing original pin operation only, then projection fast path; no empty query/no Worker/no process inference |
| root closes/resets during awaits | Preflight did not supply durable permission beyond original native authority | Fresh Registry epoch/held root and ancestor cancellation vector must match; stale context is discarded; cleanup/unknown remains held |

## Work split and sequencing

1. Pure projection owner: exact projection DTOs, original invocation bootstrap, one-edge/Registry binding derivation and strict validators; tests malformed Scope/UUID/epoch/intents/digests and absence of mutable/full inventory transfer. Keep initial full proof validators available.
2. Workflow owner: selected3 query gates, child notification persistence and Parent dirty generations; RED await-race/default/public2 tests before transport changes.
3. Control/transport owner: compact operation DTO, invocation-local immutable proof sharing, fresh before/after I/O checks and observation adapter. Keep native permission and physical/effect closure validators unchanged.
4. Root integration/review: add fixed helper to deployment3 inventory without replacing native callable inventories; freeze source, immutable replay checks, default/public2 canonical gates, actual long approval/cancel/recovery and History/span measurements. No codec, timeout or cap change in this split.

Risks requiring review: input/model-history observation equivalence; notifications for ledger-only end/fence changes; crash-safe sending with no volatile-only tasks; malicious wake tokens must not suppress valid later wakes; initial uncertain start must retain full proof fallback; returned projection digests must come from original accepted objects, not caller expectations; per-invocation proof sharing must never cross its fresh I/O boundary. Signal delivery alone has no authority and cannot settle physical or monetary obligations.

## Minimal files and focused gates

New pure `temporal_deployment_control_projection.py` and selected3 observation adapter; selected3 branches in temporal_workflow.py, temporal_parent_workflow.py, temporal_deployment_execution.py, temporal_deployment_coding_bridge.py, temporal_coding_composition_control.py, temporal_control_activities.py and Registry pure/view handling; extend only deployment3 source inventory. Keep original full physical proof/state/Runtime DTO helpers unchanged.

Required RED/GREEN and actual gates:

1. Cold replay/continue at initial start, after changed child evidence but before signal send, and while signal delivery/observe is pending.
2. Approve/cancel/drive/child stop/end ACK during observe await and retirement await; no lost wake or self-loop. Identical receipts/ACKs do not create repeated notifications.
3. Wrong Scope/namespace UUID/SDK parent/first epoch/request/Manifest/release/child-intent digest and one-edge pin mismatch reject before business. Reset/close after preflight rejects post-I/O adoption. Forged signal never grants permission, settles cost or seals.
4. Compact projections omit full Manifest/request/all children but bind the same accepted logical identity; fresh original root close/admission changes are visible with no cross-call cache. A failed parallel read with another blocked read must drain all siblings before owner end; multiple invocations/attempts cannot share a permission or snapshot.
5. Compact control/observation round-trip preserves the original native physical DTO and business body/digest; unknown immutable references refuse. Default/public2 payload bytes and immutable selected replay remain compatible. No codec is implemented.
6. Actual graph long approval: compare History events/bytes/call-ledger count before and after an idle window; they remain unchanged. Then approve and cancel/reconcile another case, demonstrating full original effect/physical/store closure and one root release. Count SDK spans to demonstrate reduced repeated payload/query walks, including the retained dedicated grant checks; do not claim a time bound from compression ratios alone.

Every normal native grant creates `pending_stop` cleanup debt; it is not a cancellation request. Keep its strict boolean validation and require it to be false for physical closure. Fresh permission is denied by actual cancellation, `stop_needed`/`stop_active`, ancestor stop/terminal state or a seal, independently of that debt.

This proposal does not change scheduling authority, charge facts, stop authority, native physical closure, or Registry root ownership. It changes when Parent asks for fresh evidence and how fixed identity/evidence bytes travel.
