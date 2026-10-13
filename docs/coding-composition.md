# Local Coding 的图与父子编排

dev105 将原 Coding ToolAction 接入有限 Local Graph、Team、Dynamic 和嵌套成员。
Graph 的 Agent 节点与直接 Tool 节点支持串行和并行；Team／Dynamic 的成员仍由原
编排器提交为独立 child Run，可包含 Agent、sequence、Graph 或下一层父级。
所有原生工作继续使用原 Run、Action、attempt、审批、预算和停止日志。

资源装配沿用[显式 Coding Profile](coding-profiles.md)：选择已有的 `coding_a`、
`coding_b` 工具，以及借用它们实际资源的 `runner-a`、`runner-b` Catalog 引用。
本文不增加 Profile 字段，也不改变省略 runner 的旧 descriptor、普通 Agent／sequence
或默认数据库的行为。Profile 示例的 `offline-echo` 不会提出 Coding 调用；下列定义
展示选择与控制接口，不表示已经配置原生认证或验收真实模型业务。
固定镜像与物理前提见[环境指南](codex-coding-environment.md)，单个 Action 的授权
与回执协议见[原 Action 委托](local-coding-delegation.md)。

## Graph 的 Agent 与直接 Tool 节点

以下声明使用已经装配的两个实际 Runner。`max_concurrency=1` 使用串行 Graph；
改为 `2` 允许无依赖节点并行。节点有依赖时仍按原 Graph 的依赖关系执行。

```python
from ralf_agent import (
    AgentBindingDescriptor, AgentSpec, BindingSelection, BoundDefinition,
    GraphNode, GraphWorkflowSpec, Literal,
)

a = AgentSpec("coding-a", "Handle the approved Coding task.", tools=("coding_a",))
b = AgentSpec("coding-b", "Handle the next approved Coding task.", tools=("coding_b",))
bindings_a = AgentBindingDescriptor(runner=BindingSelection.ref("runner-a", "1"))
bindings_b = AgentBindingDescriptor(runner=BindingSelection.ref("runner-b", "1"))

agent_graph = BoundDefinition(
    GraphWorkflowSpec(
        "agent-graph",
        [GraphNode("left", agent=a), GraphNode("right", agent=b)],
        max_concurrency=2,
    ),
    {
        "graph/nodes/left": bindings_a,
        "graph/nodes/right": bindings_b,
    },
)

direct_graph = GraphWorkflowSpec(
    "direct-graph",
    [
        GraphNode("left", tool="coding_a", input=Literal({"task": "Inspect task A."})),
        GraphNode("right", tool="coding_b", input=Literal({"task": "Inspect task B."})),
    ],
    max_concurrency=2,
)
```

Agent 节点先由其原模型提出工具调用，再等待原审批。直接 Tool 节点直接构造原
ToolAction，也必须审批；参数仍只允许有限的 `{"task": "..."}`。直接 Tool 节点没有
Agent descriptor，使用该节点实际选择的注册工具及固定 Runner。Graph 可以混合
两种节点；binding 路径只指向 Agent 节点。

并行节点的执行视图投影到同一个原 Graph Run，审批仍使用该 Graph 的 Run ID。
原生请求固定原 Run 的 release／definition digest、Action 与节点索引；视图不创建
替代 Run，也不取得独立的原生授权。

两个名称引用同一个实际 Runner 时仍共享单操作所有权。并行 Graph 调度会保留冲突
节点，待原操作结束后再接纳它，不为等候节点提前追加 attempt 或启动第二个 Turn。
不同实际 Runner 可以按 Graph 并发上限同时执行。Team／Dynamic 成员的并发仍由原
编排策略控制；共享 Runner 的成员应串行安排，或选择独立 Runner，不能把不同工具
名称当作资源隔离。

## Team、Dynamic 与嵌套绑定

绑定在整个声明树的 Agent 路径上，成员接纳时只投影该成员的子树。下面复用上面的
`a`、`b`、`bindings_a` 和 `bindings_b`；`WorkflowSpec` 是顺序 sequence。

```python
from ralf_agent import BoundDefinition, DynamicWorkflowSpec, TeamSpec, WorkflowSpec

team = BoundDefinition(
    TeamSpec("coding-team", {"first": a, "second": b}, child_budget=8),
    {
        "team/members/first": bindings_a,
        "team/members/second": bindings_b,
    },
)

dynamic = BoundDefinition(
    DynamicWorkflowSpec(
        "coding-plan",
        {"worker": a, "pipeline": WorkflowSpec("pipeline", (a, b))},
        child_budget=8,
    ),
    {
        "dynamic/members/worker": bindings_a,
        "dynamic/members/pipeline/sequence/steps/0": bindings_a,
        "dynamic/members/pipeline/sequence/steps/1": bindings_b,
    },
)

nested = BoundDefinition(
    TeamSpec(
        "outer",
        {"inner": TeamSpec("inner", {"work": a}, child_budget=8)},
        child_budget=16,
        max_depth=8,
    ),
    {"team/members/inner/team/members/work": bindings_a},
)
```

`ref` 必须是该 Agent 获授 Coding 工具的同一个实际 Runner 对象；仅有相同 JSON
身份的替代对象不够。`inherit` 从实际获授工具中选择唯一 Runner；`disabled` 与获授
Coding 工具同时出现会拒绝。工具子集移除 Coding 后不获得委托协议，宿主注册了
未选择的 Coding 工具也不会扩大成员权限。Planner Agent 仍须 tool-free；本批不把
Coding 授予 planner 或父级 verifier。

声明与原 parent 链保留既有深度限制。全局最多八个编排父级；第八个父级可提交最终
非编排叶子，其 Run 深度为九。不能在该叶子位置继续增加第九个编排父级。声明树从
根深度零计算，深度最多八，并继续受 256 个组件／1 MiB 限制；各父级显式
`max_depth` 可进一步限制原祖先链。Graph 的节点不是独立 child Run 层级。

## 审批使用实际 Action 所在的 Run ID

在已 `abuild` 的 Local Runtime 中，先提交所选定义，保存根 Run ID，再驱动：

```python
handle = runtime.submit(team, "Review the declared tasks.", command_id="submit-team-1")
root_run_id = handle.run_id
snapshot = await runtime.drive(root_run_id)
```

Team／Dynamic 父级可以是 `waiting_approval`，而其自己的 `pending` 为空；真正待审
Action 在已记录的 child Run 中。`runtime.diagnostics(parent_id).workflow["children"]`
提供原 child Run ID 与快照。以下只读取已接纳的记录，列出工具审批目标，不自动批准：

```python
def approval_targets(runtime, root_run_id):
    targets = {}
    seen = set()
    pending_runs = [root_run_id]
    while pending_runs:
        run_id = pending_runs.pop()
        if run_id in seen:
            continue
        seen.add(run_id)
        snapshot = runtime.status(run_id)
        for item in snapshot.pending:
            if item.get("kind") == "input":
                continue
            owner_run_id = item.get("run_id", snapshot.run_id)
            targets[(owner_run_id, item["action_id"])] = {
                "run_id": owner_run_id,
                **item,
            }
        details = runtime.diagnostics(run_id).workflow
        if details is not None:
            pending_runs.extend(call["run_id"] for call in details.get("children", ()))
    return tuple(targets.values())


targets = approval_targets(runtime, root_run_id)
```

调用方展示并审核具体目标的 `tool`、`arguments`、`run_id`、`action_id` 和 `digest`。
审核通过后，将审核界面选定的三个原身份传给原接口；不能把 child Action 改用根 ID
批准，也不能根据父级状态自动批准所有子级：

```python
# owner_run_id、action_id、action_digest 来自调用方已审核的一个目标。
runtime.approve(
    owner_run_id, action_id, action_digest,
    command_id="approve-reviewed-action-1",
)
snapshot = await runtime.drive(root_run_id)
```

每条不同审批使用自己的稳定 command ID；原幂等命令重试保留原负载。再次驱动后
重新读取目标，成员可能在后续模型决定中提出新的 Action。普通暂停、输入请求与
`outcome_unknown` 按各自原接口处理，不能由“没有待审条目”推断执行已成功。

## 原 child authority、冷恢复与取消

父级为每个实际 call 保留原 child Run ID、call ID 和 child budget reservation；
child 的 definition／release 固定原 `parent_call`。父级预留是 child 的预算托管，
不替代 child ToolAction 自己的原 attempt reservation。原生授权使用 Action 所在的
原 Run ID；子级不能借父级 reservation 另开执行。

冷恢复保留相同执行数据库、Scope、固定 Profile、实际工具及 RunnerJournal，重新
装配后驱动保存的根 Run ID。只恢复已记录的原 child 与原 Action，不重新 `submit`
业务来替换原 Run。Thread／Turn 回执丢失、已持久化但未采纳或效果未知时，核对
原 container ID／generation 和原日志；不得发送替代 `thread/start`、`turn/start`
或为恢复追加 attempt。绑定、parent/call 关系或原 release 被替换会在业务 I/O 前拒绝。

取消从保存的根 ID 发起，驱动同一根 ID 完成原子级的停止处理：

```python
runtime.cancel(root_run_id, command_id="cancel-team-1")
snapshot = await runtime.drive(root_run_id)
```

原 Coding 子级尚未实际停止并 fenced 时，父级保持 `cancelling`。冷暂停父级、兄弟
失败或嵌套链也按已记录 child ID 检查；Python Task 完成、空闲父级或 RPC interrupt
回执不足以证明停止。停止失败时保留原 Run、日志与资源，修复原依赖后重试原驱动。

物理停止、业务效果分类和预算结算是独立事实。原容器已经停止后，child 仍可保留
unknown effect；取消终态不证明效果未发生，也不把未知预算托管释放掉。原 unknown
案件继续保护相同工具／参数，须按原效果核验接口显式处理，不能以新 Run 重试代替。

## Owned Runtime 的关闭

内置 Coding Profile 使用 `await RuntimeBuilder().abuild(...)` 和
`await runtime.aclose()`，或 `async with`。关闭先隔离 Engine，再通过公共
`delegated_pending(scope)` 找到原 Run，核对其完整祖先与原 release，停止并采纳
所选原资源证据；这些步骤在首次 owned Runner／journal 关闭前完成。
最后按原资源账本关闭拥有的资源和 Engine。引用注册不增加所有者，借用 Runner
不由 Engine 关闭。

关闭失败或调用方取消时保留同一个 Runtime handle、SQLite、Coordinator 与待清理
账本；修复原资源后在创建它的同一事件循环中重试 `await runtime.aclose()`。一旦
进入关闭，只能重试清理，不能通过旧 Engine 引用重新提交、驱动或获得原生阶段授权。

## 发布身份与当前边界

实际选择 Coding 或显式 runner 的复杂 Local 发布使用
`delegated_composition_protocol=1`：普通发布为 `local-11`，binding 发布为
`local-bindings-19`。实际 Coding grant 另保留 `delegated_execution_protocol=1`；
显式 Runner 角色保留 `runner_binding_protocol=1`。只有显式 disabled／无 Coding
的复杂声明也使用新 composition 身份，但不会因此激活原生委托或数据库升级。
首次实际 Coding 接纳仍在原事务中准备 Schema 14。

根级 Agent／sequence 沿用 `local-10`／`local-bindings-18`，省略 Runner 的旧
descriptor v1／v2 与 Runtime Profile schema 1／2 保持。新身份使既有发布读取方
在调度前拒绝它不能重算的复杂发布，而不是将新能力保存成旧发布身份。

本批覆盖有限 Local composition 与原资源停止闭合。Temporal Coding／显式 Runner
descriptor 仍拒绝；不声明 Temporal History、专用原生认证或真实模型质量已通过。
当前原生 Runner 仍记录 `credentials=unavailable`。跨宿主恢复、完整产物发布、
完整工具隔离与硬费用上限继续按[委托契约](../architecture/specs/delegated-coding-action-contract.md)
验收。
