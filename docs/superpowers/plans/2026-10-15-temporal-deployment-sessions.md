# Temporal deployment Session admission — next delivery plan

> **Status: not implemented; pending design review.** This is a source-grounded handoff for the work after dev120, not a dev120 acceptance claim.
>
> **For agentic workers:** implement only after the Session contract is reviewed, using the existing authorized execution workflow and TDD. Do not infer authorization to run services, models, commit, or push from this document.

**Goal:** Integrate the existing SDK Session coordinator with the original deployment Registry and business Run admission, first for ordinary execution (S1), then for the already required Coding compositions (S2).

**Architecture:** Session History retains Session binding, serial Turn admission, conversation publication, and original start intent. The deployment Registry retains shared root capacity and command acceptance; the original business Run/Parent Histories retain effects, charges, result adoption, physical closure, and retirement. A coordinator is an SDK parent and a Session authority, not another business root or scheduler.

**Tech stack:** Existing Temporal Python SDK, pure Session/deployment state, fixed Worker Activities, existing effect and Runner journals.

**Spec:** A Session deployment contract must be reviewed before implementation. Existing boundaries are documented in `architecture/specs/temporal-deployment-public-contract.md`, `architecture/specs/temporal-deployment-coding-contract.md`, and `architecture/specs/temporal-deployment-control-contract.md`.

## Current delivery checkpoint

**2026-10-15 收尾范围冻结：** 用户要求加快进度并停止自动扩展新功能。本计划是[第三阶段固定清单 P3-2](../../phase3-support-matrix.md#收尾范围冻结2026-10-15-用户指令)的当前必需项；仅将既有普通 Session（S1）及已选 Coding Session（S2）接入部署准入，不增加新 Session／编排类型、持久 FIFO、替代调度器、额外适配器或通用重构。沿已有协议完成最小公开链路及原定恢复／安装门槛后关闭 P3-2，转入 P3-3，不继续深化本子系统。dev120 已在 `c52d54c` 本地提交；当前 Session 源码在工作区实现中，尚未验收。以下候选 checkpoint 是历史记录，不覆盖当前冻结范围或 dev120 最终验收。

dev119 remains the published boundary; dev120 is uncommitted. Frozen v24 Trial47 passed the complete approval-idle graph case (1 passed, 0 skipped, 151.117 seconds): the 10-second idle window retained identical 220 events, 1,574,051 JSON bytes and 7 calls; subsequent business success, two adopted effects, seal, physical stop and Registry count zero were asserted. Trial46 has no JUnit result, was ended by the owner with SIGTERM after an asyncio exit timeout, and retains two unended original calls and PG evidence; its primary cause is unresolved and it is not a pass. Trial48 parallel owned-close on v25 failed (123.37 seconds): the primary error is a fixture diagnostics query against a closing Engine; a separate stop-Activity closing rejection still needs diagnosis. Its 416 product source files equal v24, and this case is not accepted. Current-candidate full regression, final installed acceptance and compatibility remain pending. None of these records implements or approves Session admission; phase3 batch2 remains open.

## Current source facts

- `temporal_session_state.py` records a durable Turn/start intent. `temporal_session_workflow.py` registers that intent and starts the single original business child with `ABANDON`, `REJECT_DUPLICATE`, and no retry policy. Its actual SDK parent is the Session coordinator.
- `temporal_session_client.py` reserves Session commands through the existing command registry and waits for the original `start_receipt`; duplicate commands retain their first receipt and original binding.
- Public deployment Session attachment is explicitly refused in `temporal_agent_runtime.py`. `temporal_deployment_registry.py` and `temporal_deployment_execution_state.py` also refuse `session_turn`, `session_observer`, and `session_lineage`.
- Empty deployment business lineage currently requires no SDK parent. Session Turn Run IDs currently use the legacy scoped command derivation, which differs from deployment `root_run_id`.
- The universal Worker guard wraps `SESSION_ACTIVITY`, but the coordinator has no deployment root proof. Removing the facade refusal alone would not integrate admission.

## Global constraints

Preserve private1, ordinary2, Coding3, native6/binding22, composition7/binding23, their complete inventories, and immutable matching Workers. Reuse the same deployment Registry address and capacity across supported profiles. Do not upgrade an existing incompatible Registry or choose another address to bypass capacity. Do not count a coordinator as a business root. Preserve all currently selected native/sequence/graph/Team/Dynamic/recursive definitions in S2. No new model-quality gate is introduced.

## Required contract decisions before implementation

The independent source review identified these three prerequisites. They are requirements for the next shared contract, not an approved wire ABI or a completed design review. Keep every implementation checkbox below open until that contract fixes exact field sets, nullability, response shapes and SDK verification/commit boundaries.

### 1. Session commands and Turn roots have distinct records under one collision authority

- [ ] Define `session_open`, `session_submit` and `session_rebind` as durable command acceptances consuming zero business-root slots. They still use the original Registry's shared `(Scope, command_id)` identity and command allowance; they must not bypass cross-kind/target/payload conflicts. Preserve duplicate-first acceptance, including after alias/rebind or retirement. Current public `_control` does not accept these kinds, so routing through it unchanged is not an implementation.
- [ ] Separate the caller's Session command/receipt from the derived Turn `run_command_id` and its single deployment root claim. Fix the exact mapping between original Session command, Turn ID/sequence, run command, deployment `root_run_id` and original start intent. Exercise a caller command colliding with another Session command, a business command, and a derived Turn command; reject conflicting identity without creating another root or Registry address.
- [ ] Keep the existing Session coordinator address and all accepted legacy Turn IDs/receipts unchanged. The current legacy Turn Run formula differs from deployment `root_run_id`; choose the new publication's derivation explicitly before intent acceptance. Do not recompute an old intent after rebind, reinterpret an existing incompatible coordinator as the new protocol, or replace its History. Test old receipt lookup and explicit incompatible-history refusal separately from a new-publication Turn.

### 2. Durable intent, deferred admission and SDK start need exact recoverable DTOs

- [ ] Specify the original intent DTO and query/update ABI before splitting pure state and transport work. Its immutable identity must include original Scope, namespace name/UUID, coordinator ID and original SDK epoch, original SessionRef/binding, Session command, Turn ID/sequence, derived run command/Run ID, and the first complete submission envelope (`request`, `manifest`, `activity_timeout`, `task_queue`). Define the digest coverage and exact fields instead of treating a caller-supplied intent digest as proof. SDK verification reads that original coordinator History; raw attestation is never accepted.
- [ ] Specify separate durable/readback DTOs for accepted intent awaiting admission, positively capacity-deferred intent, reserve/start outcome unknown, held-unbound root, and SDK-started/bound root. State exactly where the original reservation, receipt and execution epoch are absent or required, how they correlate with the first envelope, and what `start_receipt` returns or waits for in each phase. A held-unbound claim still holds capacity. An absent facade start record cannot refute an already SDK-verified bound root; a present receipt/epoch must match that original epoch. Actual SDK current/first/original epochs, parent, namespace, queue and timeout remain mandatory.
- [ ] Distinguish confirmed capacity rejection from an uncertain reserve/start reply. A duplicate Session command must look up the original intent and Registry acceptance, then wake the original coordinator to resume that phase. It must not allocate a second Turn, start a replacement Run, free an uncertain claim, or leave an accepted root detached from its original intent. Fix an explicit retry/wake input and observable deferred state: the present Workflow waits for an external wake after register failure, so implicit automatic recovery cannot be assumed. A wake is only a hint, pinned to the original coordinator epoch, followed by fresh original-intent verification.
- [ ] Cover lost reserve/start/receipt replies, Worker-bound-root before facade-record ACK, deferred retry after quota becomes available, changed alias/queue, changed SessionRef, namespace replacement and coordinator reset. `WorkflowAlreadyStarted` or a child-start exception alone cannot become a positive original start receipt.

### 3. Advancing a Turn requires positive retirement without observer self-dependency

- [ ] Define the exact positive original deployment seal/certificate and Registry retirement evidence required before publishing the Turn once, clearing `active`, or accepting the next Turn. The existing `adopt_observation`/`quiet()` checks omit deployment call-ledger closure and retirement; business terminal state, physical stop, a read/cancel receipt, or an absent held-root entry must not substitute. Unknown effects, unended calls or missing ACKs retain the original busy/held obligation.
- [ ] Keep the coordinator's mechanical observer lease outside the observed Turn's business call-ledger closure obligation. The observer may wait for original retirement but cannot itself be an outstanding call that that retirement waits to end. Define its independent ownership/end-ACK and bounded shutdown behavior; retain the original receiver while eligible queued closure/retirement and Session publication can still complete.
- [ ] Give only the exact framework-registered `SESSION_ACTIVITY` a coordinator transport path, bound to its original Runtime/client/function/source registration, actual Scope/namespace/original coordinator epoch and durable intent. Register and observe must validate that original intent before and after relevant I/O. A matching activity name, copied marker, caller flag or claimed parent is insufficient. This mechanical path creates no coordinator root and does not exempt any business Activity from its existing deployment admission gate; closing cannot admit a new Turn through it.
- [ ] Exercise a quiet-but-not-retired Run, pending end/effect ACK, a lost retirement reply, an observer waiting for retirement, duplicate observation/publication, and owned close with queued original ACKs. Assert no self-referential closure wait, no premature next Turn, and no forced retirement of unknown debt.

## S1 — ordinary Session coordinator admission

- [ ] Review an explicit new publication/Registry handshake (proposed deployment4/Registry4), selected by explicit Session enablement plus public admission. A new Registry accepts the current compatible ordinary/Coding/session publications under one policy; old incompatible Registries refuse the new publication. Host selects its maximum required Registry version before first acceptance.
- [ ] Define an original `session_origin` beside business deployment metadata: coordinator ID and first/current/original SDK epoch, Turn ID/sequence, original SessionRef and intent digests. Preserve business lineage beginning at the Turn Run; never manufacture a business Parent edge to the coordinator.
- [ ] Keep Session intent acceptance first, then verify the exact original intent from its actual coordinator History before reserving the original deployment root/envelope. Use the original SDK-owned verification/commit pattern; accept no raw caller attestation. Record original request, Manifest, queue and Activity timeout. Start only that original SDK child with deployment metadata.
- [ ] Define capacity-deferred start and duplicate-command recovery explicitly: retain one original pending intent/Turn, expose its durable state, and wake that original History on retry. Do not create a second Turn, replace an uncertain SDK start, or leave a reservation unrelated to an accepted original intent.
- [ ] Pin coordinator transport and notifications to Scope, actual namespace UUID, original SDK epochs, and original Session binding. Lookup the first receipt/envelope before current-alias validation. Idle rebind changes only future accepted Turns.
- [ ] Admit only the exact trusted coordinator control registration, with fresh original SDK proof. Keep all business Activities behind the existing Run gate. Complete original result/effect/charge adoption and physical/ACK closure before advancing the Turn; use original deployment seal/retirement evidence rather than coordinator claims to free quota. Owned close retains the receiver for allowed original observations and retirement; unknown debt remains held.

**Files:** create focused pure/SDK Session deployment helpers; modify `temporal_session_state.py`, `temporal_session_workflow.py`, `temporal_session_client.py`, `temporal_session_activities.py`; integrate the existing deployment protocol, registry, execution state/transport, submissions, Runtime facade, Host version selection, and assembly lifecycle. Keep the shared DTOs in the reviewed contract before splitting ownership.

**Acceptance:** TDD for intent/envelope/receipt identity, duplicate and lost reserve/start/observe replies, alias/rebind recovery, same-Session busy state, cross-Session shared deployment capacity, and original namespace/epoch/reset/parent/intent/queue/timeout rejection before business Activities. Actual SDK acceptance covers two consecutive ordinary Turns, required ordinary compositions, unknown/ACK retention, cold recovery, mixed Profile queues, and owned close. Preserve source/install/default compatibility evidence; a skipped service test is not acceptance.

## S2 — existing Coding scope through the same Session origin

- [ ] Extend original Coding root-parent validation to the verified Session origin. Keep native22 and composition23 request/inventory shapes; retain original business Parent ancestry and shared Registry root identity.
- [ ] Extend invocation-local bootstrap and fresh validation to the original coordinator where required; cache no permission, cancellation, epoch, or admission facts across I/O. Retain resource ownership, grants, effect/charge adoption, cold stop proof, and original retirement semantics.
- [ ] Run the existing required native/sequence/graph/Team/Dynamic/recursive acceptance through consecutive Session Turns, with reply loss, cancellation, worker death, unknown effects, physical ACK, and close/recovery boundaries. Reuse the existing structural/native/Docker gates as applicable; do not replace genuine endpoint evidence with model-quality claims.

**Files:** the S1 helpers plus the existing Coding state/composition control/compact validation bridge and their focused tests. No Codex protocol expansion, new scheduler, alternate effects authority, or independent quota counter is planned.

## Review focus before implementation

- Actual Session SDK parent must be verified separately from business ancestry, including after every relevant await and after reset/replacement.
- A capacity-deferred Turn must be observable and recoverable using its original command without accidental second acceptance.
- A read, cancellation receipt, quiet query, or missing held-root entry is not sufficient retirement proof.
- A Session alias/rebind or mixed queue must not replace the first accepted envelope or move the original coordinator/Run to another authority.
- Long-lived coordinator shutdown must not close the only receiver before original Turn publication, ACK and eligible root retirement have completed; genuine unknown debt remains recoverable.
