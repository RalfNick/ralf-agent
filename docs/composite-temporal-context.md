# 图、Team、动态编排与 Temporal 自动上下文（dev44）

复用 `ManagedContextPipeline`／`ManagedDataContext`，不增加 Harness、存储或执行权威。
自动链路发生在实际 Agent 决策前：原始历史 → 产物核验／历史压缩 → 固定上下文快照 → 再验证来源 → 模型。
规划策略和父级团队路由不是另一套隐式 Agent 上下文。

| 能力 | Local | Temporal |
| --- | --- | --- |
| 原生 Agent／顺序 Workflow | 原协议／Schema8、10 | 显式 temporal-2 |
| 串行／并行 Agent 图 | 原 Run；并行节点 execution 投影 | 原父子 Workflow History |
| Team、动态 Plan／DAG、嵌套 Agent | 原子父子额度、各子 Run 原上下文 | 已注册 orchestration_release；各实际 Agent 子 Run |
| 历史摘录／可选模型摘要、大工具产物投影 | 支持；可按已有 Agent context 绑定替换 | dev46 支持 context／knowledge 版本化每 Agent 绑定 |
| 确定性 Session／Facts／Knowledge 引用摘录 | 支持原引用校验 | 已有 KnowledgeContext 引用；无共享 Session／Facts 自动召回 |
| 自动长期记忆写入 | dev45 已支持高级 Local 实际 Agent | dev46 显式 temporal-3 已支持实际 Agent |

`local-basic`／`local-knowledge` 可用于 Local 高级编排；dev45 的 `managed-memory` 也支持高级 Local 实际 Agent；见[高级记忆阶段](composite-memory-stages.md)。
高级 Local 受管理上下文第一次接受启用语义 **Schema11**；dev43 及以前明确拒绝该库。
原生／顺序仍按原 Schema8／10 激活；普通默认发布身份保持不变。
自定义 Store 要显式提供 `composite_context_stage_version=1` 和同步事务内 `prepare_composite_context_stages()`，不能把原子契约当成普通读写端口。

## Local 使用与恢复

```python
from ralf_agent import (
    ManagedDataContext,
    SQLiteArtifactStore,
    GraphNode,
    GraphWorkflowSpec,
    AgentSpec,
)

artifacts = SQLiteArtifactStore("results.sqlite")  # borrowed; host closes after Engine
context = ManagedDataContext(artifacts, mode="model", provider="summary")
# LocalEngine(..., providers={"default": provider, "summary": summary_provider},
#             context_assembler=context)
flow = GraphWorkflowSpec(
    "research",
    [
        GraphNode("read", agent=AgentSpec("read", "Find evidence")),
        GraphNode("check", agent=AgentSpec("check", "Check evidence")),
    ],
    max_concurrency=2,
)
```

并行节点的原始 Actions 属于根 Run；上下文意图、响应和产物回执在各自 execution 投影。
摘要预留按节点隔离，汇入同一个根预算。`context_stages(run_id)`、`context_artifacts(run_id)`
返回节点证据并附 `workflow_node`，纯查询不读取产物、不启动模型。
根已取消／失败时，显式恢复只采纳已保存回执或保留未知预算；不重新运行摘要和工具。
Team／动态／嵌套使用原实际子 Run，按子 Run 查询证据和固定绑定。

## Temporal 显式装配

```python
from ralf_agent import ManagedDataContext, SQLiteArtifactStore, Scope, ToolRegistry
from ralf_agent.temporal import TemporalEngine, build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime

scope = Scope("workspace", "developer")
artifacts = SQLiteArtifactStore("worker-results.sqlite")
context = ManagedDataContext(artifacts, scope=scope, mode="model", provider="summary")
execution = TemporalRuntime(
    providers={"default": provider, "summary": summary_provider},
    tools=ToolRegistry(),
    context_builder=context,
)
# Providers are host-supplied; use real tools for real tasks.
release = execution.orchestration_release  # Graph / Team / Dynamic / nesting
worker = build_temporal_worker(client, task_queue="h3-v1", runtime=execution, release=release)
engine = TemporalEngine(client, task_queue="h3-v1", scope=scope, release=release)
# async with worker: submit/drive using existing APIs
# Shut down workers before closing borrowed artifacts/provider clients.
```

这是新注册发布 `kernel="temporal-2"`；普通／纯自定义上下文仍使用 temporal-1。
同一队列的每个 Worker 必须固定相同策略、Provider、Scope、后端身份和实现；滚动升级管理仍由宿主负责。
SQLite 只适合同机共享磁盘示例；跨机器必须注册一个身份稳定、提供统一 async put/get 的共享不可变产物适配器。
框架不自动复制本地文件，也不宣称已有 S3 默认适配器。

History 分别记录计划、只读查询、写派发、写后核验、摘要响应和最终快照。
写和模型摘要 `maximum_attempts=1`；纯规划／读取／采纳阶段最多三次 Activity 尝试。
写丢回执后只读核验，已派发／已核验产物消失则失败，不重写。模型摘要回执先入 History，恢复后不再次调用；非法响应使用固定回退。
摘要每次预留 **1 execution credit**；未知响应保留额度，并保留远程执行不确定性，不能宣称子 Run 已确认停止、也不能提前释放父额度。
上下文读取和准备完成后，模型、摘要和产物写必须向原 Run 的 History 请求原子派发授权；Scope、Action、请求摘要和固定 Release 均匹配才允许执行。取消先被 History 接受时，尚未获准的外部调用被拒绝，即使准备 Activity 已开始也不会继续调用模型。
授权先被接受时，该操作已属在途；晚到结果继续采集和结算，取消不能撤销已经获准的远程操作。写 Activity 超时后，即使随后读到产物或业务工具成功，也保留执行不确定性，不能提前确认远程停止或释放父额度。固定等待及 detach 语义保持不变。

`await engine.context_stages(run_id)` 与 `await engine.context_artifacts(run_id)` 读取当前 Run 的 History 证据，
支持共同 AgentRun 对应方法，不自动遍历子 Run。每次业务模型派发先核验产物，再验证原 Knowledge 引用版本。
任何实际后端／Provider 更换都不能静默确认原发布。借用资源由宿主关闭。

## 验证与限制

恢复测试覆盖原图／并行／Team／动态流程的进程退出窗口，以及真实 Temporal Worker 在摘要回执已持久、采纳尚未完成时被 kill 的五类场景；重启后完成原 Run，重放父子 History。另验证模型 Activity 产物读取等待期间取消，读取恢复后不能再向 Provider 派发。
原始工具结果仍保存于执行库／History：卸载降低模型输入，并不降低总存储。
Temporal 大消息受服务载荷／History 大小限制，尚无外部 History payload 存储默认组合或自动压缩保留策略。
引用摘录不是语义摘要；字符／token 估算不是精确模型计量。此轮不调用真实模型，不代表任务、引用或长期记忆质量已达标。
dev46 已增加 [Temporal 自动记忆与五类绑定](temporal-memory-bindings.md)。H3 还缺语义默认组合、完整质量及长期保留治理。
