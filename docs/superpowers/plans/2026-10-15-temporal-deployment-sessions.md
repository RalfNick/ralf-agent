# Temporal deployment Session admission — next delivery plan

> **Status: S1 ordinary Session publication4 is connected as an explicit preview; delivery remains in progress.** The committed product baseline is dev120 (`c52d54c`). The current installed S1 matrix passes; this does not close every S1 fault/recovery gate or the unimplemented S2 scope.
>
> **For agentic workers:** implement only after the Session contract is reviewed, using the existing authorized execution workflow and TDD. Do not infer authorization to run services, models, commit, or push from this document.

**Goal:** Integrate the existing SDK Session coordinator with the original deployment Registry and business Run admission, first for ordinary execution (S1), then for the already required Coding compositions (S2).

**Architecture:** Session History retains Session binding, serial Turn admission, conversation publication, and original start intent. The deployment Registry retains shared root capacity and command acceptance; the original business Run/Parent Histories retain effects, charges, result adoption, physical closure, and retirement. A coordinator is an SDK parent and a Session authority, not another business root or scheduler.

**Tech stack:** Existing Temporal Python SDK, pure Session/deployment state, fixed Worker Activities, existing effect and Runner journals.

**Spec:** Keep the aligned Session interfaces and the original authorities fixed during implementation. Existing boundaries are documented in the [public contract](../../../architecture/specs/temporal-deployment-public-contract.md), [Coding contract](../../../architecture/specs/temporal-deployment-coding-contract.md), and [control contract](../../../architecture/specs/temporal-deployment-control-contract.md).

## Current delivery checkpoint

**2026-10-15 收尾范围冻结：** 用户要求加快进度并停止自动扩展新功能。本计划是[第三阶段固定清单 P3-2](../../phase3-support-matrix.md#收尾范围冻结2026-10-15-用户指令)的当前必需项；仅将既有普通 Session（S1）及已选 Coding Session（S2）接入部署准入，不增加新 Session／编排类型、持久 FIFO、替代调度器、额外适配器、模型、平台集成或通用重构。所选部署固定为可信单宿主上的既有 Local＋SQLite、Temporal＋PostgreSQL。OIDC、跨宿主、HA、Kubernetes 及新增外部集成留在阶段之后；优先手动、有界治理和原身份恢复，不另建后台调度。完整 R01–R26 路线图保留，不自动扩大本轮验收维度。

dev120 已在 `c52d54c` 本地提交；所选 Coding 部署准入的最终证据见[验收记录](../../../architecture/reviews/2026-10-15-temporal-deployment-coding.md)。该基线未交付部署 Session。当前工作区已实现并接通 S1 的显式 deployment4／Registry4、公共 Session 入口与 Worker 路径：沿原 intent／SDK 身份共享 Registry 容量，保留重复及延迟重试、独立 observer／ACK、正退休后推进与 owned-close 的原 receiver。当前 pub4 普通 Session 作为显式 preview 已接通，产品代码和接口保持冻结。最终 durable 候选的安装实际 SDK 矩阵已通过：专用 3 秒超时复现 1 passed，公共默认 60 秒的 9 种普通编排 9 passed，均无 skip／failed／error；最终 v4 安装的最小两项链路亦通过（2 passed／39.63 秒），覆盖两次 Turn、审批期间 Worker 重启和完成回复丢失后的原回执恢复。这些结果不代表 S1 全部故障／恢复门槛完成。S2 既有 Coding Session 尚未实现，仍为必需后续；P3-2、批次 2 和第三阶段均保持进行中，未标验收完成。

此前 S1 最小实际验证（历史候选）：源码 1 passed／23.16 秒、wheel 安装 1 passed／26.13 秒。两次普通 Agent Turn 各有原 Registry 正向退休、容量归零和重复回执证据，关闭后 Worker 停止、owned Provider 仅关闭一次；安装检查的 314 个已加载模块均来自安装目录。源码、wheel 和安装的 424 个产品文件一致。dev120 默认完整发布等值、原 History 重放／续接和新增 Provider 调用为零亦已验证。首轮关闭入口缺失的失败保留，修复后复验通过；这些是最小正向链路证据，不代替本计划剩余恢复／编排、最终全量及 S2 门槛。

S1 原 observer 超时恢复补充：既有内部 `session_deployment_call_end` Update 增加完整原 `body_result`，与既有 digest／stopped／identity 一并校验后才记录；ACK DTO 保持不变。结果受既有 submission allowance 的 8 倍字节上限约束。原 Session History 仅保留成功 register／正向 Advance，全部原调用 end 债务关闭后通过既有 adopt 路径消费一次；超时后优先消费该结果，未结束调用不触发替代 observer，null／error 不自动唤醒循环。保持 3 秒 start-to-close／14 秒总界限，不把 observer 纳入业务 root ledger。针对性开发检查已通过，最终安装候选的专用 3 秒实际 SDK 复现已通过。此前原 3 秒场景中 Run 已退休而 Session 仍 busy 的失败保留；它与修复后的通过结果来自不同运行，不能合并为一次通过。

回归证据分开登记：最终受影响检查为 3167 passed／567 skipped；此前基线全量为 12083 passed／805 skipped。后者不是 durable late-body 修复后的同一全量运行，skip 也不计作实际 SDK 验收。

## Committed dev120 source baseline

These facts describe the committed baseline, rather than acceptance of the current working-tree integration.

- `temporal_session_state.py` records a durable Turn/start intent. `temporal_session_workflow.py` registers that intent and starts the single original business child with `ABANDON`, `REJECT_DUPLICATE`, and no retry policy. Its actual SDK parent is the Session coordinator.
- `temporal_session_client.py` reserves Session commands through the existing command registry and waits for the original `start_receipt`; duplicate commands retain their first receipt and original binding.
- Public deployment Session attachment is explicitly refused in `temporal_agent_runtime.py`. `temporal_deployment_registry.py` and `temporal_deployment_execution_state.py` also refuse `session_turn`, `session_observer`, and `session_lineage`.
- Empty deployment business lineage currently requires no SDK parent. Session Turn Run IDs currently use the legacy scoped command derivation, which differs from deployment `root_run_id`.
- The universal Worker guard wraps `SESSION_ACTIVITY`, but the coordinator has no deployment root proof. Removing the facade refusal alone would not integrate admission.

## Global constraints

Preserve private1, ordinary2, Coding3, native6/binding22, composition7/binding23, their complete inventories, and immutable matching Workers. Reuse the same deployment Registry address and capacity across supported profiles. Do not upgrade an existing incompatible Registry or choose another address to bypass capacity. Do not count a coordinator as a business root. Preserve all currently selected native/sequence/graph/Team/Dynamic/recursive definitions in S2. No new model-quality gate is introduced.

## Frozen contract and acceptance requirements

The independent source review established these three required boundaries. The current implementation has aligned field sets and SDK prepare/verify/commit interfaces; freeze those interfaces and complete their integration. The checkboxes remain open until their required evidence is recorded. Pure validation or a passing simulated SDK test does not establish SDK attestation or close a runtime acceptance gate.

### Finite remaining work and completion conditions

1. Complete S1 along the existing public client → original Session → original Registry → original Run path. Verify two consecutive ordinary Turns and the already selected ordinary compositions with actual SDK evidence, original identity/receipt recovery, shared capacity and permission rejection.
2. Complete S2 for the existing required native/sequence/graph/Team/Dynamic/recursive Coding subset. Retain the original reply-loss, cancellation, Worker death, unknown-effect, physical stop/ACK and owned-close gates below; do not add topologies, adapters or model-quality gates.
3. Freeze the integrated candidate, finish the affected checks, required actual lifecycle matrix, installed acceptance and agreed default/History compatibility. Record failures, skips and missing evidence separately; retain original recovery resources for unresolved obligations.
4. Close P3-2 only when S1 and S2 satisfy those gates, then proceed to the remaining fixed phase-three batches. Complete their original service-control, permission/audit/retention and backup/restore requirements and final phase acceptance; freeze phase three once all fixed gates pass. Do not reopen this subsystem to pursue optional optimizations or the full R01–R26 roadmap.

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

- [ ] Complete the explicit deployment4/Registry4 handshake, selected by explicit Session deployment enablement plus public admission. A new Registry accepts the current compatible ordinary/Coding/session publications under one policy; old incompatible Registries refuse the new publication. Host selects its maximum required Registry version before first acceptance.
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

## Review focus for delivery closure

- Actual Session SDK parent must be verified separately from business ancestry, including after every relevant await and after reset/replacement.
- A capacity-deferred Turn must be observable and recoverable using its original command without accidental second acceptance.
- A read, cancellation receipt, quiet query, or missing held-root entry is not sufficient retirement proof.
- A Session alias/rebind or mixed queue must not replace the first accepted envelope or move the original coordinator/Run to another authority.
- Long-lived coordinator shutdown must not close the only receiver before original Turn publication, ACK and eligible root retirement have completed; genuine unknown debt remains recoverable.
