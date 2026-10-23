# Temporal Team／动态规划 Coding

显式组合在原父 History 内支持静态 Agent 图、Team 与 Dynamic。
dev113 新发布为 native version 6／binding 22、组合 version 7／binding 23，
增加顺序与递归成员；源码／安装各六个实际恢复场景已验收，范围以[支持矩阵](phase2-support-matrix.md)为准。
旧20／21使用 immutable dev112 Worker，18／19使用 dev111，16／17使用 dev110。
旧选定 Run 必须续用匹配的 Worker；不修改原 History 或伪改元数据版本。

## 选择默认组合

沿用[模型连接配置](codex-model-connection.md)中的 Temporal Profile：选择
`tools/codex-coding-connected-postgres`，提供固定工作根目录、Docker 端点、
`effect_journal/postgres` 和非敏感模型连接声明。保持
`execution={"coding_execution": True, "coding_composition": True}`。
凭证只通过可信宿主中的声明环境变量延迟解析。

```python
from relf_agent import AgentSpec, DynamicWorkflowSpec, TeamSpec, WorkflowSpec

coder = AgentSpec(
    "coder", "Use the approved coding tool and report the verified result.",
    tools=("coding",),
)

team = TeamSpec("coding-team", {"implementation": coder}, strategy="sequential")
plan = DynamicWorkflowSpec(
    "coding-plan", {"implementation": coder}, plan_mode="dag", max_concurrency=2,
)

# 顺序成员在一个原子 Run 中执行；递归组合保留每层的原 History。
implementation = WorkflowSpec(
    "implementation", [coder, AgentSpec("report", "Summarize the result", tools=())],
)
nested = TeamSpec("nested", {"implementation": implementation})
team_with_plan = TeamSpec(
    "reviewed-team", {"implementation": DynamicWorkflowSpec("plan", {"team": nested})},
)

# assembly 来自已配置的 TemporalRuntimeBuilder().abuild(profile)。
# Worker 必须使用同一固定发布，并在执行与关闭期间保持可接收原 History 更新。
# engine = assembly.create_engine(client, task_queue="coding-v7")
# handle = await engine.submit(plan, "Implement the bounded task", command_id="task-001", budget=24)
# status = await engine.drive(handle.run_id, wait_seconds=10)
# 审批使用 status.pending 中实际子 Run 的 run_id、action_id 和 digest。
```

默认 Team 策略仍为 `sequential`、`router`、`supervisor`；默认动态 Planner
为 `rule`／`dag-rule`。这些规则组合提供可运行调度，不代表模型自动制定计划。
已注册的 model Planner 和业务 verifier 沿原选择 Activity／受管理 Agent 阶段替换，
隐藏 planner／verifier 的有效授权必须不包含 Coding；它们的子 Run 仍纳入根关闭。

## 固定成员与绑定

Team／Dynamic 成员可声明 Agent、sequence、静态 Agent 图、Team 或 Dynamic；
固定的 execution policy 限制递归深度、子数量与并发，原父预算继续约束各层。
静态图保持 Agent 节点，直接 Tool／transform／复合 GraphNode 在业务 I/O 前拒绝。
静态图路径为 `graph/nodes/<node_id>`；Team 和 Dynamic 的
路径分别为 `team/members/<member>` 和 `dynamic/members/<member>`。动态 DAG 节点 ID 可以与成员名不同，
实际授权和 Runner 选择始终按声明成员投影，规划占位 Agent 不获得工具权限。

同一 Agent 的多个 Coding 工具名称若引用同一个 Runner，共用一个资源槽。
同根下不同 Runner 可并行；共享 Runner 的候选等待原子 Run 正常结算并取得实际
owner 的物理停止证明。仅财务结算、内容核验或容器探测均不能单独释放容量。
Team 队列保留未获准候选，其他独立资源可继续调度；未准入候选不预占子预算。
跨独立父 Run 的同物理根容量已由 dev111／112 原 RootCapacity 保护；
持久公平队列、跨宿主容量和企业全局配额仍未交付。

## 计划修订与恢复

每个已接受 child intent 固定原规划 revision、request、cap、SDK epoch 和父级
release；replan 保存此前所有 child 及其停止义务。旧 revision 的晚到证据可以
完善原账本，但不得覆盖新计划的结果、节点或推进阶段。

Dynamic DAG patch 只修改 pending 节点；已调度或已结算节点不能改变成员、输入
或依赖。取消／关闭后不接受新计划或 patch。静态图 patch 仍明确拒绝。

等待超时只停止观察。显式取消／owned 关闭先持久停止根准入，再逐个停止原实际
子 Run；递归树先排空原后代，再逐层采纳直接 child 的停止证明，
不能将一个叶停止当作整个 subtree 已结束。原 Worker 保持接收直到停止证据采纳完成。失败保留责任并可重试，未知
效果／费用不会因物理结束而清空。原 namespace UUID、父子 request／release 和
SDK epoch 均须匹配；不通过最新同名 Workflow 取代已有 epoch。

本批恢复测试使用真实 Temporal／PostgreSQL 与结构化 native peer；真实模型
Coding 基线仍是[dev109 的三个有限任务](../evals/results/deepseek-coding-dev109.json)。
这两类证据分别记录，不将机械恢复验证描述成真实模型规划质量。
递归约束见[新契约](../architecture/specs/temporal-coding-nested-contract.md)，
上一轮直接 Agent 范围见[dev110验收](../architecture/reviews/2026-10-14-temporal-coding-orchestration.md)。
