# Temporal Team／动态规划 Coding

dev110 的显式组合在原父 History 内支持静态 Agent 图、Team 与 Dynamic。
当前 native 发布为 version 3／binding 16，组合为 version 4／binding 17。
旧选定 Run 必须续用匹配的 Worker；不修改原 History 或伪改元数据版本。

## 选择默认组合

沿用[模型连接配置](codex-model-connection.md)中的 Temporal Profile：选择
`tools/codex-coding-connected-postgres`，提供固定工作根目录、Docker 端点、
`effect_journal/postgres` 和非敏感模型连接声明。保持
`execution={"coding_execution": True, "coding_composition": True}`。
凭证只通过可信宿主中的声明环境变量延迟解析。

```python
from ralf_agent import AgentSpec, DynamicWorkflowSpec, TeamSpec

coder = AgentSpec(
    "coder", "Use the approved coding tool and report the verified result.",
    tools=("coding",),
)

team = TeamSpec("coding-team", {"implementation": coder}, strategy="sequential")
plan = DynamicWorkflowSpec(
    "coding-plan", {"implementation": coder}, plan_mode="dag", max_concurrency=2,
)

# assembly 来自已配置的 TemporalRuntimeBuilder().abuild(profile)。
# Worker 必须使用同一固定发布，并在执行与关闭期间保持可接收原 History 更新。
# engine = assembly.create_engine(client, task_queue="coding-v4")
# handle = await engine.submit(plan, "Implement the bounded task", command_id="task-001", budget=24)
# status = await engine.drive(handle.run_id, wait_seconds=10)
# 审批使用 status.pending 中实际子 Run 的 run_id、action_id 和 digest。
```

默认 Team 策略仍为 `sequential`、`router`、`supervisor`；默认动态 Planner
为 `rule`／`dag-rule`。这些规则组合提供可运行调度，不代表模型自动制定计划。
已注册的 model Planner 和业务 verifier 沿原选择 Activity／受管理 Agent 阶段替换，
隐藏 planner／verifier 的有效授权必须不包含 Coding；它们的子 Run 仍纳入根关闭。

## 固定成员与绑定

成员必须直接声明 `AgentSpec`。本批不接受 sequence、嵌套 Team／Dynamic／图成员
或直接 Tool 图节点。静态图路径为 `graph/nodes/<node_id>`；Team 和 Dynamic 的
路径分别为 `team/members/<member>` 和 `dynamic/members/<member>`。动态 DAG 节点 ID 可以与成员名不同，
实际授权和 Runner 选择始终按声明成员投影，规划占位 Agent 不获得工具权限。

同一 Agent 的多个 Coding 工具名称若引用同一个 Runner，共用一个资源槽。
同根下不同 Runner 可并行；共享 Runner 的候选等待原子 Run 正常结算并取得实际
owner 的物理停止证明。仅财务结算、内容核验或容器探测均不能单独释放容量。
Team 队列保留未获准候选，其他独立资源可继续调度；未准入候选不预占子预算。
跨独立父 Run 的全局容量治理仍未交付。

## 计划修订与恢复

每个已接受 child intent 固定原规划 revision、request、cap、SDK epoch 和父级
release；replan 保存此前所有 child 及其停止义务。旧 revision 的晚到证据可以
完善原账本，但不得覆盖新计划的结果、节点或推进阶段。

Dynamic DAG patch 只修改 pending 节点；已调度或已结算节点不能改变成员、输入
或依赖。取消／关闭后不接受新计划或 patch。静态图 patch 仍明确拒绝。

等待超时只停止观察。显式取消／owned 关闭先持久停止根准入，再逐个停止原实际
子 Run；原 Worker 保持接收直到停止证据采纳完成。失败保留责任并可重试，未知
效果／费用不会因物理结束而清空。原 namespace UUID、父子 request／release 和
SDK epoch 均须匹配；不通过最新同名 Workflow 取代已有 epoch。

本批恢复测试使用真实 Temporal／PostgreSQL 与结构化 native peer；真实模型
Coding 基线仍是[dev109 的三个有限任务](../evals/results/deepseek-coding-dev109.json)。
这两类证据分别记录，不将机械恢复验证描述成真实模型规划质量。
验收进度见[本批记录](../architecture/reviews/2026-10-14-temporal-coding-orchestration.md)。
