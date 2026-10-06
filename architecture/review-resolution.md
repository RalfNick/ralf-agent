# 架构 review 合并说明

日期：2026-10-05（Asia/Shanghai）  
对应设计：文档 v0.2；产品 v0.1／v0.2 为预览，v1.0 为企业正式版目标。  
状态：设计决策，尚未实现或通过产品验收。

来源：[用户提供的架构review](https://chatgpt.com/space/page_6ac325daccd4819190f4ac1ef3fa90f2)。本文记录对 review 建议的采用方式，完整方案见[架构设计](design.md)。

2026-10-06 后续修订：用户明确了通用框架的完整能力目标，设计 v0.3 将通用 SDK／本地组合能力前置，详见[分层能力与交付验收](viewpoints/framework-capabilities.md)。本文保留此前 review 的历史取舍；当前建设顺序以 v0.3 和 G1–G6 为准，既有授权、执行权威、恢复及兼容约束继续适用。

## 1. 合并结论

采用 review 对恢复粒度、职责归属、并发边界、外部 Runner 能力与早期评测的建议。把完整企业蓝图与工程预览范围分开，用一个原生任务闭环验证核心，再逐步验证并行、外部 Runtime 和分布式执行。

保留此前确定的企业目标：SDK／CLI／自部署 API／基础控制台、单机多进程、Temporal、多工作区、OIDC、记忆与向量后端替换、工具扩展、消息与 A2A、知识库与 Oncall。review 以个人／小团队建设为假设；实际团队规模尚未确认，因此采用分期策略，不据此删除企业能力。

## 2. 逐项决策

| review 建议 | 合并决策 | 文档位置及验证要求 |
| --- | --- | --- |
| 缩小首个版本，先证明核心价值 | 采纳。v0.1 为原生 Harness、Local／SQLite、Python Tools、顺序任务和持久审批；v0.2 验证一个外部 Runner、并行和多进程。企业功能进入完整 v1.0 建设阶段 | [定位](design.md#1-项目定位与已确定决策)、[交付阶段](design.md#153-阶段)。每阶段明确退出条件及支持状态 |
| 明确 Agent／Harness／Workflow／Engine／ToolExecutor 归属 | 采纳。AgentSpec 定义行为；Harness 提案；Workflow 解释依赖；Engine 唯一提交状态和派发；ToolExecutor 执行授权请求并保存效果 | [职责表](design.md#33-核心职责)、[Action 恢复契约](specs/action-recovery-contract.md)。原生循环必须暴露模型、工具、等待和子 Run 边界 |
| Local 与 Temporal 用契约验证，不假设相同内部实现 | 采纳。v0.1 并行建立最小 Temporal 内部验证样例，正式产品化随后交付 | [引擎](design.md#9-执行引擎与状态一致性)、[Run 命令契约](specs/run-command-contract.md)。验证可靠记录与应用的区别、取消竞争、命令去重、事件续传和固定版本 |
| 外部 Runner 区分委派与受管步骤，恢复及工具拦截不能用布尔值概括 | 采纳。Codex App Server 作为第一个真实 DelegatedRunner，验证范围限定为隔离 Coding 任务；其他框架保持独立生态路线 | [Runner 分层](design.md#54-原生步骤与外部委派)、[能力契约](specs/runner-capability-contract.md)。session_continue、checkpoint_recovery、node_restart、工具拦截、停止证据及用量界限分别验收 |
| 原子预算、审批指纹、计划修改／派发串行化、有状态资源租约 | 采纳。预算在共享账户原子预留；未知消费不全额释放；审批绑定操作内容；同一 Engine 裁定计划和派发；Workspace／浏览器默认独占 | [计划与资源](design.md#5-agentharness-与工作流)、[HITL](design.md#102-hitl)、[预算](design.md#112-budget-与-usageledger)。并发及崩溃窗口进入契约测试 |
| AI 质量评测从 M1 开始 | 采纳。先建立原生单 Agent 基线，评估任务完成、工具／参数、停止、事实保留、人工介入、成本和延迟 | [评测](design.md#134-评测与发布门禁)、[M1 验收](design.md#166-m1-闭环与质量基线)。动态／多 Agent／外部 Runner 使用相同场景对照，不预先宣称优势 |

## 3. 需要保留的细节

- 取消是不要求客户端预期状态版本的停止意图；胜负按 Engine 应用取消与提交终态的顺序决定。可靠记录取消不等于运行已取消。
- 已采纳模型响应与稳定 Action 清单一并提交，之后才能调度工具。历史重放复用该决策；显式重规划产生可审计的新计划。
- 审批随工具版本、参数或目标等操作内容变化失效，无关分支的 PlanRevision 变化不使所有审批失效。
- 业务重试由 Engine 统一拥有；传输重试和交接重投递只取得原回执或重复投递原命令。外部 Runtime 内部行为单独声明，未知效果不允许整任务盲目重启。
- Temporal History、PostgreSQL 控制与效果记录分别拥有各自事实，使用稳定 ID／Outbox／核验衔接，不宣称跨库原子提交。
- 取消、超时、财务预算释放和执行槽释放分别判断。不能因超时认定外部调用未消费预算或旧执行已停止。
- 多 Worker 调度与工具沙箱隔离独立建设；单进程可调用隔离工具，多个进程不自动满足安全隔离。
- 框架和存储扩展只有在具体版本／环境下通过契约测试后才称为支持；接口预留可供开发扩展，不能代替兼容验收。

## 4. 第一条可验证闭环

读取工单 → 形成方案 → 持久审批 → 测试业务 API → 结果核验。无需生产权限即可验证原生 Agent 和执行可靠性。

在等待审批、模型响应采纳后、工具 dispatch 前、业务 API 已接受而结果未提交时分别终止进程，再恢复。核对原等待对象、审批指纹、Action 身份、预算和效果。可核验工具利用稳定下游身份恢复；不可核验写保留未知效果并交给人工。

闭环同时报告 AI 质量及运行可靠性。最小 Temporal 样例复用对应契约场景，提前发现 Local 设计中不能迁移的隐含假设；它仍是内部验证，不能作为生产后端支持声明。

## 5. 三份实现前规格

| 规格 | 实现时回答的问题 |
| --- | --- |
| [Run 命令与状态契约](specs/run-command-contract.md) | submit／approve／cancel 的返回保证是什么？谁提交状态？取消与成功、计划与派发如何裁定？事件如何续传？ |
| [Action 恢复契约](specs/action-recovery-contract.md) | 模型决策何时采纳？什么内容可重放？崩溃在哪些窗口会出现未知效果？预算与独占资源如何处理？ |
| [Runner 能力契约](specs/runner-capability-contract.md) | 外部 Session、检查点和节点重启有什么区别？工具拦截覆盖哪些路径？取消与用量的证据是否满足场景要求？ |

下一步实施先使用上述规格形成同一套运行契约测试与小任务样例，再扩展后端。本文的合并完成只表示设计已补充，所有产品能力仍需实施与验收。
