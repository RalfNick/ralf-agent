# dev15 DAG、嵌套、交接与独立分布式权威审查

2026-10-07（Asia/Shanghai）。范围：用户授权继续实现动态 DAG、嵌套编排、MQ/A2A、分布式执行和真实模型规划质量。保留工作区已有 dev12–14 增量；未提交、推送或发布。

## 交付与权威边界

- Local DAG：不可变提案、复用静态依赖/绑定/条件校验，保存接收与采纳阶段、节点绑定和已确认结果。显式 CAS patch 仅改变 pending 节点，沿用 scoped command 去重；规则/受管理模型 Planner 默认实现和目录工厂可替换。
- 嵌套：Team/Dynamic 成员可为原生 Agent、sequence、static graph、team 或 dynamic。独立子 Run/Session、固定祖先 Release、递归 escrow 结算、有限大小/深度。后代真实线程未完成时保留根 Session。
- 交接：MessageBus、同步/异步 Inbox/Outbox、CommandAdapter 和 A2AClientPort 是结构化端口；内存/SQLite 为本地默认，Redis Streams 为真实服务适配。耐久接收、原执行回执、耐久完成、ack 分阶段；Broker/HTTP 不拥有 Run、不隐式执行。
- A2A：固定0.3 JSON-RPC polling 子集，宿主认证返回可信 Scope、固定服务定义；远程工具按 queryable_write/批准/稳定message key/只读核验接入。原生 ASGI 服务使用本地同步控制，与 MQ AsyncCommandAdapter 的 Temporal 组合分别声明。
- Temporal：独立 Workflow/History 权威，注册 Activity 执行模型/工具；不包装 LocalEngine、不将 ExecutionStore 当分布式锁。PostgresEffectJournal 仅保存 dispatch intent/效果证据/未知写守卫；History 采纳后才确认清除。
- 质量：冻结20个不同语义任务，真实 ModelDAGPlanner 的受管理 child 路径，参数/依赖/条件/输出/拒绝/停止评分。只测提案，不执行业务 worker。默认不调用模型；离线fixture model_quality 保持 null。

支持边界见 [DAG/nesting](../../docs/dynamic-dag.md)、[MQ/A2A](../../docs/remote-handoff.md)、[Temporal](../../docs/temporal-execution.md)和[评测](../../docs/planning-evaluation.md)。

## 一次独立只读审查与修复

使用 requesting-code-review 技能安排新审查者，不继承实施上下文。确认三处问题，均在同一次审查内 RED→GREEN，并由原审查者复核；无第二轮审查。

1. **P1，Temporal 取消终态重开**：跨 Run 未知写 guard 将 Action 阻塞，cancel 后 drive 的 retry_blocked 将其改 ready/running。增加 TERMINAL 保护，已取消 Run 保持状态，晚到证据仍可安全确认。纯状态覆盖三种终态；真实服务在清除原 guard 后再次 drive，仍只有原业务写一次。
2. **P2，A2A 根 endpoint**：无 path 的 URL 对应 ASGI `/`，原匹配返回404。空 path 规范为 `/`，Card/client 保持一致；裸 origin、尾斜线、带端口地址 discover/send/get 回归通过。
3. **P2，自定义 EffectJournal 虚假完成**：忽略 received/ack 的非 None 或内层 coroutine，可能确认未持久证据。强制已完成 None、关闭 lazy 而不执行；begin 校验有限 typed/bool/互斥证据，observation 仅 EffectObservation/None。实际 incomplete received 保留 outcome_unknown/额度，不确认 journal。

独立审查验证：DAG/配置/评测70项、flat/team/真实退出恢复62项、稳定修复后的 Temporal/A2A/MQ/handoff73项通过。审查者实际 HTTP/Redis 运行受 sandbox socket 限制；本线程实际服务验证单独记录，不把受限运行算通过。

## 实际服务与故障证据

服务版本：Redis8.8.0/client8.1.0、PostgreSQL16.2/psycopg3.3.6、Qdrant1.19.2；Temporal Python SDK1.34.0、CLI1.9.1、Server1.32.0。Temporal 使用真实持久本地 Service 和独立 Worker 进程，没有 time-skipping server。

- 五类 Temporal 场景各20次：scoped 提交/控制/History replay、审批后 kill/restart、外部已提交而 Activity 回执丢失后的原key核验/跨Run守卫、取消竞争/晚到证据、Worker版本漂移拒绝。
- 首次长批次因测试 fixture 在运行期间修改造成指纹变化，57个完成用例后中止。它是独立保留的部分结果，不计作完整80/100通过。冻结fixture后的分批证据完成上述20次要求；终态修复后强化 blocked→cancel→drive 又20/20通过。
- Temporal 最终模块组合42项通过，包括37个单元契约和实际五场景；实际不完整Journal观察不会消费未知额度或发确认。
- DAG/嵌套12个真实进程退出窗口验证 received/adopted/dispatched/completed/result 的恢复，模型与Planner计数不重复，原子子 Run 树保留；既有 flat 五窗口一起17项通过。
- 交接104项focused覆盖真实Redis、HTTP和第三方组合，A2A修复后的45项相关回归通过。测试工作进程仅传必要环境，不继承宿主模型凭据。

最终全套 **1376 passed in227.68s**，warnings-as-errors，实际服务、无skip。之后仅对Planner公共返回类型注解对齐，相关34项通过。

仓库外最终wheel契约 **351 passed in56.13s**，覆盖所有本轮新增能力、实际数据服务/Temporal/HTTP和SDK来源检查。首次外部测试未复制源码专用eval fixture/wrapper，造成5项材料缺失/346项通过；补齐独立测试材料后33个评测/来源测试及最终351项全部通过。没有把examples放入wheel或回退使用仓库SDK。

基础包强制阻断redis/psycopg/temporalio/uvicorn：189个公共导入通过；基础能力组合121项通过、1个确需TemporalSDK的Worker注册测试按预期skip。完整实际服务suite没有skip。

源码/wheel/sdist/仓库外安装副本 **65个SDK模块逐字节一致**，依赖metadata仅httpx/jsonschema为必需，6种extras明确。Ruff lint/format、Git空白和pip check通过；文档69份、361个本地链接、35个Python/43个shell/2个TOML片段校验通过，CI YAML用本机Ruby解析。Python环境无PyYAML，不据此宣称使用PyYAML验证。CI实际Temporal服务helper本机启动/停止通过，GitHub作业及Python3.11/3.13尚未本机运行。

wheel/sdist、SDK公共导入、dag/nested starter和原dev14升级验证通过；测试临时服务在验收后关闭。上述证据证明声明的预览契约，不代表整体企业部署验收。

## 兼容与采用限制

实际 dev14 wheel 创建的 native/v3、Team/flat Plan 任务/回执在 dev15 下保留原记录并恢复；原十种starter字典保持一致。新DAG/nested任务需dev15。实际dev14对新记录停在派发前且不改记录，但嵌套定义可能触发其旧reader的KeyError；不保证旧代码有typed downgrade错误，不支持降级继续这些Run。

Temporal 当前只有原生 Agent/sequence、默认 Harness/History Context；共享Session、RAG/Memory、Graph/DAG/Team/nesting、自定义Harness/Context和目录路由都明确拒绝。业务终态 Workflow 为回执和晚到证据保持打开；registry容量4096，History compaction/Continue-As-New/retention/global quota/deadline/部署版本治理尚未提供。

MQ保留去重及pending证据，满容量拒绝；没有自动清理/压缩和Broker failover认证。A2A不声明完整规范支持；SQLite Inbox/Outbox也不作为跨主机共享数据库。Redis/PG/Qdrant适配和EffectJournal不构成企业身份权限、沙箱或任意效果 exactly-once。

真实模型运行的模型/调用预算配置尚未确定。本轮默认 report=not_run；离线3/3只验证评测路径，model_quality=null，没有实际模型任务成绩或竞品对等benchmark。严格货币上限无法保证时评测拒绝发起调用。完整M1、企业可用和全面AgentScope/LangChain/LangGraph对齐仍按独立验收门槛判断。
