# 有界并行 Workflow

版本：0.1.0.dev12；日期：2026-10-06。静态图可以显式开启单个 Run 内的并发，Agent、受管理 Tool 和纯 Transform 节点共用原有审批、预算、取消与效果恢复协议。默认继续串行。依赖、条件和绑定见[静态图指南](static-workflows.md)。

## 开箱即用

```sh
ralf init my-parallel --template parallel
cd my-parallel
python -m agent_app --input task --command-id first
python -m agent_app --input queued --command-id second --submit-only
ralf --config runtime.toml resume RUN_ID
ralf --config runtime.toml --format text inspect RUN_ID
```

用提交返回的 ID 替换 `RUN_ID`。模板有两个独立 Agent 和一个显式合并节点，离线 Provider 立即回显。它验证执行链路；真实异步模型、HTTP/MCP 工具或同步工具线程可以重叠等待外部调用。模板不证明模型任务质量，也不是性能 benchmark。

## 定义并行图

```python
import asyncio
from ralf_agent import (
    AgentSpec, GraphNode, GraphWorkflowSpec, InputMap,
    RuntimeBuilder, RuntimeProfile, ValueRef,
)

flow = GraphWorkflowSpec(
    "report",
    [
        GraphNode("research", agent=AgentSpec("research", "Research the task.")),
        GraphNode("verify", agent=AgentSpec("verify", "Verify the task.")),
        GraphNode(
            "join", transform="identity", depends_on=("research", "verify"),
            input=InputMap({"research": ValueRef("research"), "verify": ValueRef("verify")}),
        ),
    ],
    max_concurrency=2,
    output=ValueRef("join"),
)
profile = RuntimeProfile("parallel", "1", {"default": {"adapter": "offline-echo"}})
with RuntimeBuilder().build(profile, ".ralf/parallel.sqlite") as engine:
    handle = engine.submit(flow, "task", command_id="report-001")
    print(asyncio.run(engine.drive(handle.run_id)))
```

`max_concurrency` 是 1..32 的整数。1 不进入声明或计划，保留原串行请求身份；2..32 使用计划 v3。JSON／TOML graph 声明也支持此字段。它限制一个 Run 同时活动的节点，不能限制多个 Run 的总量、租户配额或模型费用。纯 Transform 是同步计算，不会提供 CPU 并行；需要 I/O 时使用 Tool。

同一个 Provider、ToolExecutor、工具或记忆适配器可能被多个节点并发调用。适配器应支持并发使用，或者在自身实现中串行化必要的资源。自定义后台线程仍由应用负责；框架追踪它通过受管理接口启动的真实工具／核验／记忆线程和 MCP worker。

## 上下文、审批与恢复

每个节点保存自己的已绑定输入、消息、决策计数、接收证据和结果。Agent 的会话 ID 为 `<parent-session>:node:<node-id>`，提交时一并预留。父会话不隐式加入分支历史；不同分支通过 `ValueRef`／`InputMap` 分享结果。长期事实仍按 Agent 名称作用域召回；相同 Agent 名称可以看到相同事实。诊断显示节点输入、状态、结果、会话 ID 和错误，不公开内部执行帧。

所有分支属于同一个 Run、信用预算、命令日志和事件序列。一个分支等待审批或效果核验时，它的后继等待，其他独立就绪分支可以继续。活动分支全部暂停后，父状态优先报告 `waiting_reconciliation`，其次 `waiting_approval`。检查所有节点和待审批操作，逐项审批后恢复原 Run；重复命令返回原回执。

恢复时每个未完成帧每次 drive 至多尝试一次，防止一个未知操作忙循环。审批或人工核验在另一个分支等待期间受理后，可能需要再次 `drive`／`resume` 继续刚刚退出的帧；父状态此时可为 `running`，不代表已有后台服务自动推进。

失败停止新节点，等待已经启动的调用结束并保存效果证据。已完成节点结果保留；取消也停止后续调度，不会撤销业务写入。调用者取消 drive 时，监督任务继续追踪已启动工作；只要节点 Task 或真实受管理线程仍活跃，不能释放 Coordinator 或重启同一 Run。整个事件循环取消后，同步线程仍可能运行，需等待真实线程退出再关闭。

恢复复用已落盘的模型响应和工具观察；尚未接收落盘的模型调用可能重试并留下未知信用预留。外部写是否可重试仍由效果分类决定：下游幂等键、核验接口或人工确认不可省略。未知写即使 Run 已失败／取消也保留。框架不承诺任意外部操作恰好执行一次。

## 扩展调度策略

`WorkflowScheduler` 是纯同步端口，带非空 JSON `identity`，实现 `select(plan, input, states, limit) -> WorkflowBatch`。默认 `StaticWorkflowScheduler` 按声明顺序选择就绪节点。状态为脱离存储的 JSON 副本，不含内部帧；limit 是当前剩余槽位。自定义策略可选择就绪节点的顺序及非空子集，不能改输入绑定、跳过集合、依赖或完成语义，也不能超过槽位。

```python
from ralf_agent import StaticWorkflowScheduler, WorkflowBatch

class ReverseReady(StaticWorkflowScheduler):
    identity = {"kind": "reverse-ready", "version": "1"}

    def select(self, plan, input, states, limit):
        batch = super().select(plan, input, states, limit)
        return WorkflowBatch(tuple(reversed(batch.selections)), batch.skipped, batch.done, batch.result)

# LocalEngine(..., workflow_scheduler=ReverseReady())
# registry.register("workflow_scheduler", "reverse", lambda config, context: ReverseReady())
```

版本化 Profile 的 `components.workflow_scheduler` 默认 adapter 为 `static-ready`，接受空配置。调度身份仅进入 v3 图 Manifest；旧 Agent、sequence、v1/v2 图的默认身份保持不变。单节点帧内部固定使用默认串行编译器／解释器处理已接受节点；父级调度器是并行选择权威。执行恢复不会重新编译原图。

v3 图需要 dev12 及原版本组件，dev11 无法继续。SQLite Schema 仍为 v1；ExecutionStore 实现需在 `session_owner` 中识别 Run 的可选 `session_ids` 预留列表，并保持原有事务、事件、预算和独占租约契约。当前没有多进程执行池、分布式调度、ChildRun、Planner、团队消息或数据流引擎。
