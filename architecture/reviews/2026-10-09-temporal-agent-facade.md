# dev33 — Temporal native Agent facade / H2c1

日期：2026-10-09；Git 基线 da55f97。实施范围为本轮开始时捕获的实际 dev32 SDK（144模块）→未提交 dev33（146模块），保留所有既有 dev31/dev32 改动。完整 H2／理想 Harness／AgentScope 对齐与企业验收均未完成。

## 实际交付与边界

Runtime.from_temporal 复用现有 Agent/AgentHarness/AgentRun/RunRef/WaitResult，支持原生 AgentSpec／顺序 WorkflowSpec；Local 新增异步 areference/aattach，原同步 API 与 Session 保持。共同异步观察／控制钩子复用已有执行端口，TemporalClientRuntime 是私有客户端责任实现。未新建执行状态机、History 格式或基础依赖。

- 服务端 Workflow/History 独占 Run/Action／审批／预算；客户端只托管在途 submit/resume/control RPC。接受与控制本身唤醒原 Workflow，仅显式 resume 发送 drive。
- 每次调用使用固定 Client/namespace/Scope/release 的配置视图，默认方法跨内部 await 不切换最终资源。原始 Engine 配置漂移会报告；已提交至原资源的控制不能撤销，也不会重定向到替换资源。自定义 override 必须遵守视图，不能借捕获的可变原 dispatcher 绕过。
- opaque locator 根据真实 endpoint/namespace 与可选 alias seed 生成，queue/default release 移动不改变原权威；async aattach 先查原事实并验证 Scope／locator／发布／native backend。
- wait/status/events/diagnostics/pending/attach 为查询。等待超时包含慢查询，返回最近成功观察的快照与真实 observed_at；查询自身错误继续传播，不伪装成正常观察超时。返回值与内部缓存分离。
- RPC Task 强引用与 shield 不依赖 caller；close 先停止新提交、等待在途 RPC 完成。唯一关闭策略 detach，owned 只关闭 Engine facade；Client 与 Workers 借用，服务端业务继续。超时／取消关闭等待保留清理，失败可重试。
- 不保留历史 Run 或完成 Task。hosting_status.running 统计客户端 RPC，不表示服务端活动；parked 为空，调用方保存 RunRef 与原 command_id。
- 接受前拒绝 bound 定义、Graph/Team/Dynamic/nesting facade、shared Session、queue/deadline/input/handoff。原 raw Temporal 复合编排继续可用。H1 其余绑定、远程／复合 Session 与 H3 自动智能链路按既有规划推进。

## 验证证据

- Task1：11个 missing-API RED → 11 GREEN；相关133 passed8.58s。
- Task2：8个新 RED + 惰性 close1 RED，新增29项全部通过；相关198 passed7.92s。
- 单次独立审查的三项 Important：8 failed +1未处置 coroutine 的 teardown error RED → 新增37项 GREEN1.16s；一次修复，无再审查。
- 修复后全量：**2317 passed／47 skipped，337.65s，-W error**。47项为配置服务依赖，包含本轮3项显式 Temporal 探针；跳过不计为真实服务通过。
- 实际 dev33 wheel 在 /private/tmp：**206 passed8.25s**；包含 Local／Session／绑定／旧 Temporal 与本轮新契约。
- 明确启动实际持久 Temporal Service／Worker，使用离线 Provider：源码**3 passed7.45s**；实际安装包相同场景**3 passed6.27s**。覆盖原生／顺序审批、重复控制、队列／默认移动后的原发布恢复、真实 read-only lookup 审计单次调用、观察超时／取消、客户端 detach 后 Worker 完成以及真实 History 重放。不使用 time-skipping、内存模拟服务或收费模型。
- 实际 dev32→dev33 和 dev33→dev32 wheel 各11类 Local 原审批恢复：原生、大 Schema、顺序、绑定、并行图、团队、动态、DAG、嵌套，以及 schema2 原生／顺序 Session。原 submit/control 回执和 Manifest 保持，每项实际业务效果一次；Session 顺序／占用确认保持。
- 实际旧 wheel144模块与捕获基线相同；源码／wheel／sdist／实际安装结果146模块逐字节一致，原 Temporal History/Workflow 模块未改变。基础依赖／extras／脚本不变。
- 屏蔽 redis/psycopg/qdrant_client/temporalio 后实际包294个导出可用；20个旧 starter 生成文件摘要保持；Ruff、339文件格式、Git 空白、文档链接及包私有文件／凭据排除通过。

这些证明声明的运行与恢复契约，不证明生产 failover、网络分区恢复、任意外部写恰好一次、真实模型质量或 AgentScope/LangGraph 对等优势。无远端提交／发布／收费调用。

## 一次独立审查与永久修复

fresh-context reviewer 发现三项 Important，无 Critical/Minor，按实际影响保留分级。

1. 原控制内部等待后仍读取可变 Engine.client，可能先取消同 ID 的另一服务 Run，再由 Facade 报错。现在操作配置视图固定真实 Client／Scope／namespace／release，缓存 Registry 从该 Client 获取。`test_managed_dispatch_never_follows_changed_client_after_internal_await` 在 cancel/resume/submit 三条路径中证明替换服务未收到业务命令。
2. 捕获 TimeoutError 混淆等待计时器与查询自身失败，甚至无期限 wait 也吞掉网络错误。使用独立 asyncio.timeout 对象并核验 expired；无期限路径直接传播查询错误。`test_query_timeout_error_propagates_instead_of_becoming_observation_timeout` 覆盖 None／10秒。
3. resume 忽略 drive 返回值，None／嵌套 coroutine／其他 Run 快照都可能被当作成功。公共采纳检查实际 authoritative RunSnapshot、目标、合法状态／修订及有限 JSON；惰性值拒绝并处置。`test_resume_refuses_invalid_completed_drive_response_without_claiming_dispatch` 覆盖三类。

8项永久复现观察到 RED→GREEN；既有29项共同通过；最终2317 passed／47 skipped。无 deferred Minor。

## 全部取舍与成本

以下按 ledger 顺序公开全部 Ruling，包括 reviewer declined judgments。

1. 沿用户认可路线 inline，保留 dirty／私有证据，不重复批准或自动提交／切换 worktree。成本：源快照标识增量，尚未形成新 commit。
2. 共同异步钩子与私有 Temporal Runtime 特化，避免整体后端重写／另一公开 RemoteAgent。成本：原生／顺序子集，完整 H2 未完成。
3. 远程 detach 只关 owned Engine，Client/Workers 借用；超时用真实旧快照时间。成本：调用方保留 refs/原ID，不能从 close/timeout 推断服务端停止／新状态。
4. 既有服务端 submit/control 唤醒，只 resume 发 drive。成本：没有客户端业务循环或完整复合唤醒协议。
5. locator 采用规范真实 endpoint/namespace/seed，不依赖 queue/release。成本：endpoint alias/failover 要维持宿主配置，未发现集群身份或迁移。
6. 异步端口要求完成态目标回执／快照与 close None，拒绝惰性值。成本：自定义组件需适配验收。
7. Reviewer declined 实际 Service/Worker/History：实施者使用持久服务、离线 Provider 和 lookup 审计验证。成本：未证明生产拓扑、长负载和 failover。
8. Reviewer declined 安装／包：实施者验证实际旧新 wheel 与固定模块。成本：源码 review 不能替代安装验收。
9. Reviewer declined 全量 Local/Session：最终全量与安装旧契约另执行。成本：配置服务跳过保留为未测范围。
10. Reviewer declined 可选导入／依赖／starter／凭据／release：实际包核对，未发布。成本：公开 release、企业验收仍独立。
11. Reviewer declined 真实网络／进程丢失／外部效果／付费模型：RPC 保留测试通过，进程丢失依原ID恢复；无收费调用。成本：未认证网络分区、跨服务 failover 或质量优势。
12. Reviewer declined 穷举 malformed／组合：共用完成态校验与不支持组合拒绝。成本：任意 override 仍需 conformance，完整 H2 未完成。
13. 固定默认 dispatcher 的调用视图并保留自定义 override 注入。成本：可信 override 若故意调用捕获的可变原对象，仍可能违反端口契约；不能从返回值证明任意代码诚实。
14. 本轮私有兼容探针修正 effect_key 的审计读取：pending DTO不含该字段，使用原所属动作诊断；handler/Provider 身份未变。成本：探针修正后重跑并核对真实 SQL 效果，不能把失败的仪表读取算产品失败或成功。
15. task-done 核对实际全量／安装／服务／升级日志与冻结 SDK／重建包，不重复运行未变化的绿色全量。成本：任何 SDK 变化需新测试，摘要不符会拒绝收尾。
16. 保留未提交代码与本轮私有数据，停止自己启动的测试服务，未自动整合／发布／清理文件。成本：后续 commit/release 为独立行动。

见[使用指南](../../docs/temporal-agent-api.md)、[实施计划](../../docs/superpowers/plans/2026-10-09-temporal-agent-facade.md)和[剩余能力](../../docs/remaining-work.md)。
