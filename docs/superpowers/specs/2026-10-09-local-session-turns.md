# H2b1 — Local durable Session/Turn

User authorized continuing the approved ideal Harness roadmap after H2a. Implement
this tranche inline without repeated approval, automatic commits, remote writes,
new base dependencies or paid-model calls. Preserve all existing dev31 changes.
This delivers the safe colocated SQLite native/sequence Session subset, not full H2b.

## Authority and supported composition

SessionAdmission belongs to the existing Local execution transaction; a Facade
holds no durable occupancy or second Run state machine. Extract the unchanged
first-acceptance body of LocalEngine.submit into _accept_submission(run_id,payload,
parent_call=None), so raw submit and Turn acceptance share identical governance.
The new session_submit command atomically commits original request receipt,
Turn/seq/binding, Run intent and occupancy. No nested synthetic submit command.

SessionKey includes trusted Scope, canonical resource digest, namespace and ID.
Only actual SQLiteMemory using the execution Store's connection is supported,
optionally via host-authorized SessionView; all native/sequence steps must share
one actual address. No remote/database-alias promise; reject other resources,
Graph/Team/Dynamic Sessions, queue/deadline/input/handoff and Temporal facade.
Their existing stateless entry remains usable. Raw session_id shortcut stays
unsupported; use explicit Agent.open_session and portable SessionRef.

Use an optional SessionAdmissionStore port with prepare/load/load_address/insert/
save/insert_turn/turns/confirmed_result/route_owner/legacy_owner, synchronous within the same
execution Store transaction. Default SQLiteSessionAdmission is replaceable via
create_session_admission factory; verify transaction_owner and backend identity.
Mutation methods return exactly None; confirmation returns bool; reads return
concrete finite JSON records, lists or owner IDs. Reject lazy or invalid results
without entering them. Coordination also pins the original Runtime locator;
open/reconnect cannot silently substitute an alias.
Keep v1 ExecutionStore unchanged. The default Store reserves registered physical
Session addresses even while idle; only the authority's scoped synchronous Turn
acceptance permit may use the address. Raw submit cannot bypass pinned routes.

## SQLite feature activation and compatibility

Opening the first valid Session atomically enables execution schema2 and creates
indexed Session/Turn tables; ordinary new stores/raw runs keep schema1. New Store
and Readers support both. Old SDKs reject schema2 before Coordinator/dispatch,
preventing old raw admission from bypassing the new route rules. There is no
silent downgrade. Activation rolls back with failed first acceptance. Actual
coordinator/file identity still governs the canonical database; namespace aliases
with the same actual storage key cannot register two routes.

## Public API

Agent.open_session(session_id,command_id) -> AgentSession with immutable SessionRef
and original receipt. Runtime.open_session/attach_session use the same host Scope.
SessionRef holds SessionKey, coordination digest, binding_revision and declaration
digest, no clients/secrets. Observing an older ref is allowed; submitting new input
on it after rebind yields a durable session_binding_mismatch rejection.

AgentSession.submit/run -> AgentRun with TurnAdmission and original command receipt.
status is pure; turns(after=0,limit=100) is a bounded durable page. Session/Agent entry
close never owns Runtime. Approve/cancel/reconcile remain controls of original Run.
SessionBusy includes stable rejected receipt and original RunRef; replay stays
rejected after the blocker finishes. Retry requires a new command_id. Definition
mismatch/stale revision are also durably rejected; invalid configuration stays
explicit and never dispatches. No failed attempt increments Turn seq.

Session bindings retain declaration plus accepted manifest per revision. Original
command lookup precedes current model/default resolution. New Turns must match
current original pinned components; missing/moved defaults refuse, not silently
upgrade. Rebind(new_definition,expected_binding_revision,command_id) is a durable
CAS while idle, preserving historical definitions/receipts and existing Runs.
It cannot change Session resource/namespace; branching is an explicit new Session.

## Release and recovery

Approval/unknown writes/real thread or in-flight operation keep Session occupied
through pause/close/restart. Terminal Run alone is insufficient. Release requires
actual local quiescence, no unknown tool effect, and (for succeeded native/sequence)
confirmed existing final Session result with stable message ID and matching result.
Failed before result-write intent need not invent a successful message. Pure status
reports eligibility from committed evidence and current real execution; next explicit
admission/rebind atomically advances the stored owner. No TTL, observation writes,
facade-memory lock or implicit recovery. Unmanaged original queued intent is resumed
explicitly; closed handle behavior remains H2a.

## Verification

Real SQLite tests: key/ref validation, transaction rollback/schema guard/alias scope,
serial seq/history, durable busy/idempotency across close/restart, drift and CAS,
unknown reconciliation, cancellation while a real handler runs, raw bypass refusal,
unsupported remote/mixed resources before acceptance and adapter replacement.
Pure Session status/turns must not create commands/events/model calls. Actual dev31
wheel -> new SDK ordinary approval recovery; new schema1 -> dev31 recovery remains
possible; actual dev31 refuses activated schema2 unchanged. Full pytest/-Werror,
installed new/legacy contracts, wheel/sdist/source byte evidence and one fresh
read-only final review, one TDD Important fix pass. No AgentScope or quality claim.
