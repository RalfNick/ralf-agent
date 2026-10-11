# Temporal Context Read Lifetime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans inline. No implementation delegation; exactly one fresh-context read-only whole-batch reviewer at the end. User authorized continuous development/local commits/no push; do not repeat start/plan-approval prompts.

**Goal:** Own native/private Context read handlers through timeout/cancellation and prove termination to the original History before model advancement or Session release.
**Architecture:** ContextExecutionOwner reuses ThreadExecutionTracker. Original Native History owns fixed read intents/admission/response/end facts; original Parent/Coordinator propagate quiescence. No other business authority, no shifted async-client loop.
**Tech Stack:** existing Python asyncio/ContextVar/ThreadedMemoryAdapter, original Temporal SDK/Histories and portable pure rules.
**Spec:** docs/superpowers/specs/2026-10-11-temporal-context-read-lifetime-design.md; existing Harness/Session/data contracts remain binding.

## Global Constraints

- FullR01–R26 remainsactive; no narrow subset becomes overall success.
- Explicit context_reads=True →kernel3/binding_protocol2/readprotocol1; defaultFalse/native-v1 unchanged, old67 refuses before I/O.
- Context/plan/read/verify/finalize only; summary/write retain original effects. No generic allWorker-stop claim.
- Actual Task+tracked threads+end notification, not observation cancellation, proves stop.
- Scope/original Workflow epoch/Action/phase/complete request fixed; readonly budget0, no model/tool repeat.
- Source-once and existing catalog/root/member/data namespace identities unchanged.
- Registered resources borrowed; own handlers drain first. Local commit/no push/no live secret.

## Files and Responsibilities

- Create temporal_context_execution.py: replaceable default actual handler+thread/end owner.
- Create temporal_context_read_protocol.py: pure protocol/schema/pinned metadata, no SDK.
- Create temporal_context_read_state.py: pure original Action envelope/admission/response/end helpers.
- Modify temporal_state.py, temporal_managed_context.py: original Native read evidence/advancement and phase admission, preserve legacy wire.
- Modify temporal_activities.py, temporal_control_activities.py, temporal_workflow.py: constructor/fixed view/actual Worker lifetime, exact SDK guards/end Updates/singleattempt.
- Add focused pure/actual worker/service/remote/installed tests; guides/capability/acceptance. Existing thread_tracker and data SPI stay default-compatible.

## Review Focus

1. All-loop cancellation leaves a real delegated reader: no Turn release or borrowed close before thread+notification completes.
2. Duplicate denied reads/capacity refusal/old end notices cannot clear another actual reader.
3. Scope/epoch/selected sources change across awaits: refuse before disclosure and never deliver proof to another original execution.
4. Response/end ordering and schema rejection: never advance early, lose the response, or roll cancellation back.
5. Managed read/verify/finalize and cached-source metadata are real I/O; do not certify only initial read_page.

### Task 1: actual owner and pure versioned protocol

**Interfaces:** ContextExecutionOwner(max_calls=8).identity/active_count/execute(operation,*,proof,on_end=None)/wait(*,wait_timeout=30)/aclose(*,wait_timeout=30). execute returns the actual awaited operation value; wait strictbool. Proof5 fields scope/action_id/release_digest/request_digest/execution_epoch. Fixed helpers produce context_read_protocol1 +binding_protocol2; validate exact phases and owner/method identity. Defaults unchanged.

- [x] Write tests actual threaded+async operation and mixed await, observer/all-loop cancellation, thread group drain, notification retry, duplicate/capacity, invalid timeout/lazy operation/contract, proof detached identity. Run missing module RED.
- [x] Implement owner using existing tracker/context groups; hold delivered notifications until ACK and retain entries after closed/cancelled loop. Expose no business/state scheduler.
- [x] Test protocol explicit marker and exact/malformed types/config; binding1/newmarker refused, binding2/incomplete refused; no stored clients/futures. Run missing marker RED.
- [x] Implement pure protocol registration with actual method/config pins; run owner/protocol and existing tools/Memory/thread/Session suites GREEN.

### Task 2: original Native Action read authority

**Consumes:** Task1 proof/marker. **Produces:** envelope(state,action,request,phase)→detachedrequest; admission(state,payload); observe/end helpers on original action/read record. Required original epoch and full digest. End Update idempotent; no extra reservations.

- [x] Write native/plain+managed phase tests for admitted timeout/cancel, no-grant fence, duplicate/forged proof, both end/response orders, malformed snapshot, restored states, budget0 and model not scheduled before completed gate. Expect existing Actor premature-quiescence RED.
- [x] Integrate exact read envelope and original record, compatible binding2 validate_manifest; preserve every legacy request/event and old retry semantics when flag absent.
- [x] Route prepare/read/verify/finalize response adoption through original receiver with mandatory validation; persist original failure/late evidence and keep nonquiescence until end. Models/tools never rescheduled by read recovery.
- [x] Run Context/managed/Session/binding/limits/parent/memory/default suites GREEN; stateless/native/sequence accepted, original data identities and source-once unchanged.

### Task 3: Runtime/Worker and composition integration

**Consumes:** owner+original read authority. **Produces:** context_reads constructor/fixed host owner, actual guarded readonly phase calls/Update, singleattempts, pure read diagnostics, wait_context_executions/close_context_execution. Source view inherits host owner.

- [x] Write Runtime actual thread tests reproducing current native read_page and metadata/fact/RAG/artifact waits after cancellation, with original busy proof and borrowed close refusal; run missing constructor/ownership RED.
- [x] Implement selected runtime wrappers/host pinning and SDK actual workflow_id/run UUID/namespace checks before/after await. End callback stays original pinned client/epoch. Default releases retain old path.
- [x] Register context_execution_ended Update, protect original plain/managed requests, singleattempt SDK only new-read phases, no synthetic Run/model/source. Duplicate/capacity truth checks cannot discharge an existing entry.
- [x] Write/run original graph/team/flatPlan/DAG/nested/member/native/sequence combinations, ordinary/managed twoTurns, cache/source-once, late responses and actual end proof; expect GREEN.

### Task 4: complete real evidence and local delivery

- [x] Actual Temporal Service/separateWorker thread/async native/sequence/private compositions, timeout/cancel/allstop proof and Worker kill/wait/restart; replay every root/child History; verify model/tool/read/save counts and IDs.
- [x] Real Redis/PG and mixed Context/RAG/Artifact/stage binding replacement; metadata/cached paths; no skips as proof.
- [x] One final fresh Astra read-only whole-batch review with all five Focus items and ledger rulings. Regrade, one important fix pass RED→GREEN, no re-review; minors ledger.
- [x] Freeze source; full regression/build/installed/core/modules/METADATA/guide; actual old67↔new default/native-v1 History and oldWorker binding2 refusal before I/O.
- [x] Sync capability documents/default entry and limitations; actual owned services stopped/waited; local commit/no push, then continue R04/Profile and remaining full abilities.
