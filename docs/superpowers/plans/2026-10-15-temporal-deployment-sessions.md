# Temporal deployment Session admission — next delivery plan

> **Status: the fixed S1 ordinary Session functional subset is accepted for this batch.** S2 Coding Session, Temporal＋PostgreSQL integration and phase-three acceptance remain pending. Source and installed evidence are recorded by snapshot below.
>
> **For agentic workers:** implement only after the Session contract is reviewed, using the existing authorized execution workflow and TDD. Do not infer authorization to run services, models, commit, or push from this document.

**Goal:** Integrate the existing SDK Session coordinator with the original deployment Registry and business Run admission, first for ordinary execution (S1), then for the already required Coding compositions (S2).

**Architecture:** Session History retains Session binding, serial Turn admission, conversation publication, and original start intent. The deployment Registry retains shared root capacity and command acceptance; the original business Run/Parent Histories retain effects, charges, result adoption, physical closure, and retirement. A coordinator is an SDK parent and a Session authority, not another business root or scheduler.

**Tech stack:** Existing Temporal Python SDK, pure Session/deployment state, fixed Worker Activities, existing effect and Runner journals.

**Spec:** Keep the aligned Session interfaces and the original authorities fixed during implementation. Existing boundaries are documented in the [public contract](../../../architecture/specs/temporal-deployment-public-contract.md), [Coding contract](../../../architecture/specs/temporal-deployment-coding-contract.md), and [control contract](../../../architecture/specs/temporal-deployment-control-contract.md).

## Current delivery checkpoint

**2026-10-15 收尾范围冻结：** 用户要求加快进度并停止自动扩展新功能。本计划是[第三阶段固定清单 P3-2](../../phase3-support-matrix.md#收尾范围冻结2026-10-15-用户指令)的当前必需项；仅将既有普通 Session（S1）及已选 Coding Session（S2）接入部署准入，不增加新 Session／编排类型、持久 FIFO、替代调度器、额外适配器、模型、平台集成或通用重构。所选部署固定为可信单宿主上的既有 Local＋SQLite、Temporal＋PostgreSQL。OIDC、跨宿主、HA、Kubernetes 及新增外部集成留在阶段之后；优先手动、有界治理和原身份恢复，不另建后台调度。完整 R01–R26 路线图保留，不自动扩大本轮验收维度。

dev120 的 `c52d54c` 未交付部署 Session；其 Coding 部署准入证据见[验收记录](../../../architecture/reviews/2026-10-15-temporal-deployment-coding.md)。本地 `4fdd5ae` 已记录 S1 显式 preview，当前 v6 候选继续沿原 public client → Session → Registry → Run 路径，固定 intent／SDK 身份、独立 observer／ACK、共享容量与正退休后推进，不增加协议范围。

当前 v6 修复两项实际阻塞：关闭时仅为 exact factory 原 evidence ACK 保留维护路径，固定 Runtime／client／函数与请求 Scope，完整原 SDK／Registry held／call-end 校验保持；每次机械 release 使用新的 SDK Update ID，避免同 ID 永久重放已完成的失败，原 root／certificate payload 和 Registry 唯一退休语义不变。首轮 closing ACK 拒绝、后续全局 1 秒期限打断机械 verify，以及固定失败 ID 阻止原证书重试的失败证据分别保留。最终债务夹具显式使用 3 秒故障期限，仍断言 unknown 时原物理处理器未结束；不改变产品期限、公共默认 60 秒或旧接受信封。

实际 SDK 证据分开登记：

- v4 安装：9 种普通编排 9 passed；原 3 秒 observer 超时恢复 1 passed；两 Profile／队列／Scope 的共享 max1、deferred 原 intent 重试及命令／权限拒绝 1 passed。它们保留各自原运行证据。
- v6 安装：最小两项链路 2 passed／40.67 秒，覆盖两次 Turn、审批 Worker 重启与已完成回执丢失；冷 Runtime／client 恢复及已完成退休回复丢失 1 passed／27.23 秒，保持原 intent／信封／epoch／回执及一次 conversation publication。
- v6 effect-ack／call-end-ack 债务两节点一次通过：2 passed／84.06 秒，零 failed／error／skip，424 个产品文件与 316 个已加载安装模块核验通过。每节点两次 Turn／两次物理写：unknown 且原处理器未结束时保持 busy／root1，原 stop＋ACK 后才退休／发布／root0；第二 Turn 的 owned close 先为 `CloseIncomplete`、原 receiver 存活且 Provider 关闭数为 0，依原关闭契约重试排空后才停止 receiver、Provider 关闭一次。cleanup 不替代门槛断言。**S1 普通 Session 功能子集在本批验收关闭。**

v6 源码／sdist／wheel／安装的 424 个产品文件一致；完整默认 publication 和原／continued History 离线重放通过，live continuation 沿用 v4 的独立原证据。回归分别为 v5 Temporal 3175 passed／571 skipped、v6 24 个受影响模块 438 passed／90 skipped；历史全量 12083 passed／805 skipped 属于旧快照，不合并为当前全量，skip 不计实际 SDK 验收。

原 observer 修复继续有效：既有 `session_deployment_call_end` 携带完整原 `body_result`，与 digest／stopped／identity 校验后记录；ACK DTO 不变。History 只保留成功 register／正向 Advance，原调用全部结束后消费一次；null／error 不自动唤醒，不将 observer 纳入业务 root ledger。专用 3 秒／14 秒原超时场景的失败与修复后通过来自不同运行，分别保留。

S2 既有 Coding Session、Temporal＋PostgreSQL 集成以及 P3-2／批次 2／第三阶段整体验收继续待定。以下涉及普通与 Coding 的共享条目不能因 S1 的普通证据全部勾选；不从本批普通通过推导整个支持矩阵完成。

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

**本批普通功能子集已验收关闭。** 首条兼容普通／Coding／Session 的共享 Registry 条目仍保留后续 Coding 集成范围；其余 S1 普通条目已由本批单测及实际 SDK 证据满足，不能据此关闭 S2／PG 或整个阶段。

- [ ] Complete the explicit deployment4/Registry4 handshake, selected by explicit Session deployment enablement plus public admission. A new Registry accepts the current compatible ordinary/Coding/session publications under one policy; old incompatible Registries refuse the new publication. Host selects its maximum required Registry version before first acceptance.
- [x] Define an original `session_origin` beside business deployment metadata: coordinator ID and first/current/original SDK epoch, Turn ID/sequence, original SessionRef and intent digests. Preserve business lineage beginning at the Turn Run; never manufacture a business Parent edge to the coordinator.
- [x] Keep Session intent acceptance first, then verify the exact original intent from its actual coordinator History before reserving the original deployment root/envelope. Use the original SDK-owned verification/commit pattern; accept no raw caller attestation. Record original request, Manifest, queue and Activity timeout. Start only that original SDK child with deployment metadata.
- [x] Define capacity-deferred start and duplicate-command recovery explicitly: retain one original pending intent/Turn, expose its durable state, and wake that original History on retry. Do not create a second Turn, replace an uncertain SDK start, or leave a reservation unrelated to an accepted original intent.
- [x] Pin coordinator transport and notifications to Scope, actual namespace UUID, original SDK epochs, and original Session binding. Lookup the first receipt/envelope before current-alias validation. Idle rebind changes only future accepted Turns.
- [x] Admit only the exact trusted coordinator control registration, with fresh original SDK proof. Keep all business Activities behind the existing Run gate. Complete original result/effect/charge adoption and physical/ACK closure before advancing the Turn; use original deployment seal/retirement evidence rather than coordinator claims to free quota. Owned close retains the receiver for allowed original observations and retirement; unknown debt remains held.

**Files:** create focused pure/SDK Session deployment helpers; modify `temporal_session_state.py`, `temporal_session_workflow.py`, `temporal_session_client.py`, `temporal_session_activities.py`; integrate the existing deployment protocol, registry, execution state/transport, submissions, Runtime facade, Host version selection, and assembly lifecycle. Keep the shared DTOs in the reviewed contract before splitting ownership.

**Acceptance:** TDD for intent/envelope/receipt identity, duplicate and lost reserve/start/observe replies, alias/rebind recovery, same-Session busy state, cross-Session shared deployment capacity, and original namespace/epoch/reset/parent/intent/queue/timeout rejection before business Activities. Actual SDK acceptance covers two consecutive ordinary Turns, required ordinary compositions, unknown/ACK retention, cold recovery, mixed Profile queues, and owned close. Preserve source/install/default compatibility evidence; a skipped service test is not acceptance.

## S2 — existing Coding scope through the same Session origin

v21正常原图首项已终态1 failed／455.001秒，零错误／跳过；424产品／854测试运行前后同。原整体360秒取消第二轮，第二approve180未到期；前三Tool成功且candidate已接受，第四实际开始后21.029423秒definition_mismatch、无candidate。首seal→正Advance Completed ACK19.594258秒；两root一条退休，3 adopted＋1 dispatched，原close未成功、schema保留，不能以Worker退出替代。其余十二项正常组合及五故障不解锁，S2／P3-2继续开放。本轮只登记实际结果，不再相同产品复跑或追加尾部小修补。下一批复用函数级CPU证据审查工具阶段与交接的完整验证成本；候选须先证明原字段／身份／source／错误检测契约及完整链路收益，不引入第二验证权威、跨请求缓存或期限放宽。预计一个有界结构审查／必要源码检查批次，只有新候选证据充分后才运行约8分钟的原首项；当前不足以估计整阶段结束时间。

v21窄批次已实现并完成最终23模块368 passed／58.66秒（-Werror），零失败／错误／跳过；1278产品／测试前后同，独立审查及格式检查通过。仅将正证书／退休后的后代集合复用既有独立reader：原结果与非Session Counter相同，三后代Session组15→1，独立raw七事实与完整出口保持。独立安装四模块73 passed／20.65秒、默认完整canonical及保存History离线兼容通过，424产品／854测试无漂移，Provider0／服务0。随后实际首项失败，见上方；只有固定原图通过后再展开原其余十二项及五故障，不改原期限、不增加功能，S2／P3-2继续开放。

当前定位checkpoint：v20 CPU-only实际1 failed／453.198秒，零错误／跳过；原整体360秒取消第二Turn。前三Tool成功且有candidate（48.107700／42.299957／44.522015秒），第四Tool20.742248秒为definition_mismatch、无candidate；首seal至正Advance Completed ACK21.705067秒。accepted2／retired1／held1，首次CloseIncomplete、最终RPCError；原root／Session关闭证据与unadopted write未清，schema保留。正常428.761秒与SDK／RAISE314.926秒仍分记，不比较为优化收益；其余十二项正常组合和五项故障未运行，S2／P3-2开放。

全Worker含关闭窗口370.689625 CPU秒／416.570039墙钟秒；`_current_manifest` 6062次110.207923 CPU秒，`validate_release` 6147次inclusive 128.445344 CPU秒，嵌套不能相加或等同业务关键窗口。faults0／incomplete0；projection未覆盖为null，不称零CPU。纯Unicode／ASCII分支ABBA完整Runtime仅2–5%已放弃；广义raw live-pins缺等价证明不实施。随后窄descendant候选的实现／检查见上方v21，不改native逐请求fresh、期限或权限边界，实际首门槛仍待。

本批最小诊断实现：仅tests的独立helper，以显式env／marker启用sys.monitoring固定同步代码CPU聚合，原产品函数和source pins不替换。PY_START／RETURN只作用于固定code，异常unwind仅过滤目标code；有界线程／栈，退出恢复自有槽位，固定脱敏数字聚合仅退出写入，故障不改变业务结果。现有Worker plugin负责生命周期，默认不启用；先验证返回／异常／foreign工具／嵌套与关闭清理，再冻结夹具。下一次实际诊断仅测量，不解锁其余矩阵；直到有函数级证据才实施产品修复。424个产品文件及既有安装／默认／History证据按原范围复用，不重跑未受影响全量。该测试夹具已完成，独立审查无P1／P2，五模块95 passed／4.43秒（-Werror），1277产品／测试前后无漂移；CPU-only实际结果已在上方记录。仅覆盖固定host code对象，沙箱副本不在覆盖内；exclusive只扣除选中目标之间嵌套。本次未同时开SDK计时或RAISE，仍不作为正常验收。


历史诊断checkpoint为 `d9bae41`（产品仍为v19）：一次原图1 failed／482.320秒，整体360秒取消；首Turn与前三Tool成功，第四Tool为definition_mismatch且无结果候选。首次close由原task返回CloseIncomplete，不是外层wait_timeout。未知leaf原handler／call-end ACK完整，但无业务结果，effects仍3 adopted＋1 dispatched，1／2 root未退休、schema保留。关闭拒绝有依据，独立关闭缺陷未证明；并行Task堆栈不能作为它的等待因果。不继续复跑同产品或为不同关闭窗口叠加修复。

此前v20批次限定为一个原CONTROL只读采样边界设计／实现批次（现已完成源码／安装检查，实际未通过）：借鉴既有sealed-tree内部读取与完整身份关联，不复用sealed-only证书walk，也不改默认 `_proof`。先明确exact Coding4／actual CONTROL／固定child及祖先身份／全程拒写的封闭集合，保留原完整Activity入口和末独立raw七事实出口；中间只作不可采纳proposal。对齐当前仍要求每组七事实的契约，审查reset／namespace／epoch／Scope／source漂移、原Registry／Start替换及错误／取消清理后再实施。未pin、ordinary、旧3、其他mode、所有native／permission入口保持原行为。原360秒门槛不变，实际RPC／延迟需最终固定版本验证。预计一批设计、受影响检查和必要修复；首次实际复验仍约8分钟，修复总时长无充分证据估计。


### v20候选的最小实现边界（已实现，最终验收待定）

- 从 `temporal_session_deployment_verification._SessionTreeReading._node` 提取既有私有读序列：原 `_read_admission` → `_start_record` → 完整canonical intent／origin相等 → `_start_record_binding`。默认 `_proof` 不变；新入口只产生封闭集合内不可采纳的node proposal。CONTROL Parent可能是后代，固定共同业务root／原Registry epoch；不照搬sealed-tree的空lineage约束，不把Session coordinator算作业务root。
- 将 CodingValidation bootstrap 前段leaf／ancestry／ancestor读取提为私有固定方法；基类仍执行原full proof路径，只有 exact私有observation类使用上述collector。后面的composition／Start／current describe／Registry配置与完整envelope／node／held关联保留，不能用外层假validate或类型标志代替原证据。
- transport仅在原完整 `validate_activity` 后、actual CONTROL＋Coding4＋非空fixed child epoch和完整child_execution匹配时打开collector；register／cancel／recover／ordinary／旧3／未pin和native路径不变。该完整入口可能进行原ancestry pin，不能被归入随后只读集合或跳过。
- 私有observation的Session identity检查只关联同一完整固定identity；末parent node使用同一内部读序列，保留当前child描述／epoch／namespace及纯关联。所有Run、Registry、Start与compact读仍真实读取，代理全程拒绝Update／start／discover／pin；若需要写入直接拒绝，不能先写再补终验。不得缓存SDK响应或把采样结果跨请求共享。
- 全部body读取结束、任何pack／return前，新建独立raw `SessionControlValidation(..., _coordinator_activity=False)` 读完整七事实，与固定identity相等，再完成原Activity、source／endpoint／request／Runtime等出口。try/finally清除全部proposal／snapshot；独立verifier、helper、类／方法和transport闭包纳入既有source pins。调用中延后发现reset／identity漂移是明确的采样语义变化，须窄范围修订当前契约，不承诺逐读立即撤销。
- 首要RED已确认所有非Session SDK读取及原结果相同，仅Session完整组原6不等于2失败；然后验证缺ancestor pin拒写、中段完整Registry intent替换、末current／first／original epoch或namespace漂移、source／端口替换、假outer validate、错误／取消不返回proposal，以及默认／native原fresh对照。通过源码审阅和受影响检查、固定安装与约定兼容后，才复验一次原图；调用计数不能换算成性能或验收通过。

v20实现更新：已提取原节点读取序列，sealed-tree仍保留原入口／出口；只有transport原完整入口后的exact CONTROL分支打开私有集合，所有group读取由独立固定只读端口逐await检查，完整canonical身份为不可变str，不缓存SDK回包。最后独立new raw SCV完整7和原出口通过才pack；transport finally在正常、错误和取消后清全部私有snapshot／proposal，原captured discard不能被晚到替换。新增真实后代node/ancestor纯关联及原端口实例替换拒绝，缺原pin无Update。最终135模块受影响回归1986 passed／289 skipped／106.38秒（-Werror），1274产品／测试前后相同；独立审阅无P1／P2，Ruff／格式／空白检查通过。安装11模块173 passed／43.01秒，默认完整canonical及原／continued保存History离线兼容通过；424产品与850测试副本前后相同，全部导入来自安装。源码已本地提交 `49d26d8`。一次真实首项已结束：1 failed／428.761秒，整体360秒取消，前三Tool成功，第四业务子Workflow已创建但Tool未调度；第一Turn正Completed ACK已取得，第二Turn末observe缺end ACK。三效果已adopted且两业务root已退休，Session关闭仍未确认、schema保留。其余十二项／五项故障未运行，S2未关闭。下一批仅用既有有界SDK／Worker计时诊断定位实际开销，区分诊断与正常验收；不再从夹具6→2推导实际分支命中或速度，不放宽原期限，不追加功能。

v19当前源码候选已完成本轮离线定位及必要最小修复：一次真实原控制链／SDK形状observe调用完整Runtime端口76次，pre-body46次中bootstrap31次；不是把约33秒交接当作一个RPC。仅已全验证、固定child且actual CONTROL Activity的Coding4只读observe使用专用私有类，保留全部SDK和六组Session七事实，full76→37；其自身固定Manifest真实Runtime入／出口、逐await pins、取消清snapshot和拒permission保持。其余入口沿原实现。新增15项与同次132模块回归1956 passed／289 skipped／93.30秒通过；跳过不代服务验收。独立审阅、冻结安装八模块143项、默认完整canonical及保存History离线兼容通过；随后一次原图仍1失败／466.580秒，原360秒取消，关闭未排空。前三Tool成功，第四Tool已启动但最终unknown，无结果候选。仅1／2 root退休，schema保留；其余十二项正常组合和五项故障未运行。不把调用次数换算为实际速度结论。

本批已补同一原关闭任务的有界诊断：v19两次 `_bounded_task` 超时均在 `_coding_stop_task`，尚未执行Session close或Worker shutdown；现有Task顶层帧无法区分native stop Update、后置fresh与Parent adoption。在原fixture的首次close异常边界、退出Worker前保存原任务最多16层静态await帧，优先纳入32项快照；不读locals／任务名称／载荷，不推进或取消await，不新增SDK查询，不改变任何期限、重试或证据要求。根据实际等待点再做必要最小修复；现证据不支持继续盲目Runtime微优化或全图重跑。该诊断改进本身不证明集成通过。 定向37 passed／61配置依赖跳过，产品424文件与v19冻结源码相同；该一次诊断现已结束，结果以上方当前checkpoint为准；不继续同产品重跑。单次原链路加原关闭预算约8分钟；根因与修复时长尚无足够证据估计。

历史实际checkpoint为2026-10-16 v18／本地 `85dce98`：安装七模块128 passed／22.33秒，默认完整canonical及原／continued保存History离线重放通过；实际原图仍1失败／390.395秒。首Turn成功发布，第二Turn第三Tool完成、第四child注册与整体360秒取消交错，未成功启动第四Tool。owned关闭成功，accepted2／retired2／retained0，Session清理证据成立，schema安全删除。仍须解决原期限内完整两Turn；其余十二项正常组合及五项故障未运行，S2未关闭。只对原执行／交接的剩余耗时继续定位，不新增功能、通用重构、额外模型或期限；单次结果不证明性能改善。以下v17及更早失败记录不覆盖该checkpoint。

2026-10-16 v18收尾源码已实现并经独立审查：仅 `_observe` 的Coding4封闭树入口归并独立Session读取，通用 `_proof`／`_tree` 与ordinary双轮完整校验保持；每个Run／Registry／Start仍实际读取，末轮独立raw SDK七事实与全部pins／Runtime正验证后才返回证书。真实三子状态／SDK形状主用例验证原13组→新1组、读取Counter与证书相同，定向19项通过。关闭侧仅明确的纯physical pending可延至原末轮resource／ancestor adoption后，以fresh完整原树与原资源正证据消解；新增18项涵盖合法零资源、真实资源producer、硬错误／缺ACK／unknown／子／资源消失及旧3对照。同次131模块受影响回归1941 passed／289 skipped／88.74秒（-Werror），1270个产品／测试前后相同。未启动模型或新服务，不作为实际恢复验收；下一步只做冻结、安装兼容和一次原图复验。

最新checkpoint为本地 `a4cfc38`／v17，metadata保持dev120。相关回归959 passed／193 skipped／55.06秒，独立安装五模块91 passed／11.39秒，默认与保存History离线兼容通过。原图实际首项1失败／432.08秒：第一Turn成功发布；第二Turn第四child已启动、尚未批准即被整体360秒取消，第四Tool未运行；不是内部180秒TimeoutError。两root正退休、held0；第二Session尾调用缺end ACK，physical close先CloseIncomplete，Worker退出后重试RPCError，schema保留。其余十二项正常组合及五项故障未运行。各候选历史不覆盖此checkpoint。

本批原只读group和固定child observe重复检查已本地提交／安装／实际复验。最终证明、原生逐请求fresh及原80／60／180／360期限保持。首root start→seal191.984926秒、Tool交接33.603793秒、seal→Session ACK24.222412秒；与v16的差异是两个单次样本，不作性能归因或稳定SLO结论。SDK History不记录Query返回和分支marker，实际carrier／最终pin与直读条件相符，但没有直接实际branch计数。当前微调仍不足以满足整体期限。

下一批固定为重复Session proof的封闭只读收集边界和上游physical close责任核对。每个原Run／Registry身份关联仍须读取，组出口由原raw SDK上的独立verifier验证全部七项Session事实后才可返回；不允许凭wrapper标志跳过通用proof验证、缓存permission或借用假的外层validate。先完成针对性设计审查与必要最小实现／恢复测试，再做受影响回归、安装兼容及一次原图复验；单次服务检查本轮约7分钟，总修复时长未确定。不扩展功能范围、不调高期限；首项完整通过后才运行相同候选的其余十二项和五项故障。

两项独立定位按同一批集成：只读树的身份收集必须封闭、默认通用proof行为保持；关闭侧先TDD验证早期pending能否在同次末轮全部原fresh资源／祖先正闭合后消解。不得用retired／held0、较晚PG快照或单个parent physical标志覆盖错误；身份／源码／SDK错误、真实未停、未知效果及缺ACK仍必须保留。v17外层report丢失了composition内部细节，当前只能确认候选危险结构，不能宣称实际唯一根因。

2026-10-15 本次有限收尾：先修复v13恢复路径的2MiB载荷拒绝，完成Coding4有界无损编码及State／Workflow两端接线，保留原semantic digest、Update ID、ACK、8MiB语义限制和逐请求fresh。相关八模块同次191项通过，含两处wire、冷恢复、Scope拒绝和sandbox激活；仅为源码证据，安装／真实服务复验待做。180秒主流程超时独立未解，其余十二项正常组合和五项故障未运行。该次未启动新的服务矩阵；后续v14复验结果以上方checkpoint为准，S2仍开放。

源码已接通并完成交叉审阅，实际安装验收仍待通过。首轮全受影响 Temporal 回归 3226 passed／584 skipped；两个正常 Agent 安装候选分别命中沙箱激活与原生握手期限，另一次计时诊断复现握手问题，失败及原恢复资源均保留。后续分流及 Advance 修复后，v5 首个实际安装 Agent 两 Turn 通过，其余矩阵两个首项分别因顺序工具超时和动态子调用旧 metadata 校验失败，后续十项未运行。已补齐完整 Session origin 校验；仅 Coding4 的首批四项独立读取并发，保留全部七项 fresh 事实与最终校验。v6 首个Agent通过，但矩阵首两项仍失败；隔离计时显示一次原Runner60秒预算耗尽。v7仅减少三个同步方法的重复完整intent复制，安装相关155项通过，原失败sequence两Turn／四次业务写通过（306.23秒），其余十二项并行验收。全部修复保持原超时、原事实读取及执行权威；不得因源码／模拟验证通过勾选下方交付门槛。参见[验收记录](../../../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。

- [ ] Extend original Coding root-parent validation to the verified Session origin. Keep native22 and composition23 request/inventory shapes; retain original business Parent ancestry and shared Registry root identity.
- [ ] Extend invocation-local bootstrap and fresh validation to the original coordinator where required; cache no permission, cancellation, epoch, or admission facts across I/O. Retain resource ownership, grants, effect/charge adoption, cold stop proof, and original retirement semantics.
- [ ] Run the existing required native/sequence/graph/Team/Dynamic/recursive acceptance through consecutive Session Turns, with reply loss, cancellation, worker death, unknown effects, physical ACK, and close/recovery boundaries. Reuse the existing structural/native/Docker gates as applicable; do not replace genuine endpoint evidence with model-quality claims.

**Files:** the S1 helpers plus the existing Coding state/composition control/compact validation bridge and their focused tests. No Codex protocol expansion, new scheduler, alternate effects authority, or independent quota counter is planned.

历史v12已提交预览为 `22af163`，metadata 保持未发布 `0.1.0.dev120`。既往 Agent／sequence 两 Turn 有通过证据；v12 图首门槛仍1失败／268.17秒，两个Tool在原80秒内完成，但180秒审批辅助等待在第二child收尾阶段失败，owned关闭与最终清理也未通过。其余十二项与五项故障未运行，不能关闭S2。v13仅合并exact Coding4只读启动证明的重复首轮Session读取，保留末轮完整事实及固定身份，ordinary Session4保持原两轮；本地回归、审查、安装及离线兼容通过，但实际图仍1失败／343.10秒，180秒等待仍在第二child收尾阶段超时。随后Session原History确认2MiB载荷硬拒绝，晚于Root取消／退休，不作为先前超时根因；大证据传输与主流程等待须分别收尾，逐原生请求fresh契约保持。继续保持原期限、不新增协议；各候选证据及剩余项以[验收记录](../../../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)为准。

## Review focus for delivery closure

- Actual Session SDK parent must be verified separately from business ancestry, including after every relevant await and after reset/replacement.
- A capacity-deferred Turn must be observable and recoverable using its original command without accidental second acceptance.
- A read, cancellation receipt, quiet query, or missing held-root entry is not sufficient retirement proof.
- A Session alias/rebind or mixed queue must not replace the first accepted envelope or move the original coordinator/Run to another authority.
- Long-lived coordinator shutdown must not close the only receiver before original Turn publication, ACK and eligible root retirement have completed; genuine unknown debt remains recoverable.
