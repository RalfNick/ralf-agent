# Temporal 自动记忆与每 Agent 绑定（dev46；Facts dev58）

显式 `temporal-3` 发布复用 `AgentDefinition`、`BoundDefinition`、`AgentBindingDescriptor` 和宿主授权的 `BindingCatalog`。原 `temporal-1`／`temporal-2` 发布身份与执行流程保持；旧 Worker 拒绝新协议。History 是唯一执行权威，记忆数据库只保存事实和可核验版本。

## 能力范围

| 角色／链路 | 当前支持 | 边界 |
| --- | --- | --- |
| provider | 每声明路径 inherit／版本 ref | 固定 Provider 与实际方法，选择不增加宿主权限 |
| context | 每路径 inherit／ref；纯 builder 或受管理压缩／产物卸载 | required，不能 disabled；产物仍须共享后端 |
| knowledge | inherit／ref／disabled | 原 references／validate 端口；无 namespace selector |
| tool_set | inherit／ref／disabled | 只能缩小 AgentSpec 已声明工具集合 |
| stage_policy | inherit／ref／disabled | 规则／模型字段选择、每 Agent 写后端／namespace |
| Agent／顺序／图／Team／动态 flat/DAG／嵌套 | 各实际 Agent 支持以上选择 | 高级编排使用 orchestration_release，子请求只带原声明子树 |
| facts | inherit／ref／disabled，有界召回与宿主 namespace selector | [Facts 契约](temporal-facts.md)；来源／额度／客户端固定 |
| Session、custom Harness／Verifier／limits 与环境角色 | 未支持 Temporal 绑定 | 非 inherit 的未支持选择在接受前拒绝 |

字段选择的写阶段是长期记忆来源观察链路，不是自动信念修订。Facts 召回需显式注册读后端／绑定；dev58 的读链路与写阶段独立选择，不因授权写入扩大召回范围。模型只选允许的字段，值来自已通过最终输出校验的结果。

## 显式装配

```python
from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    ManagedMemoryPolicy,
    MemoryAdmissionPolicy,
    Scope,
    SQLiteMemory,
    ToolRegistry,
)
from ralf_agent.temporal import TemporalEngine, build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime

scope = Scope("workspace", "developer")
facts = SQLiteMemory("facts.sqlite")  # borrowed；同机共享磁盘示例
catalog = BindingCatalog(scope=scope)
catalog.register(
    "stage_policy",
    "observations",
    "1",
    ManagedMemoryPolicy(
        facts,
        scope=scope,
        namespace="observations",
        admission=MemoryAdmissionPolicy({"result": ("result",)}),
    ),
)
# provider 和 client 由宿主提供；不会隐式下载模型或配置凭据。
execution = TemporalRuntime(
    providers={"default": provider},
    tools=ToolRegistry(),
    binding_catalog=catalog,
)
release = execution.orchestration_release
worker = build_temporal_worker(
    client, task_queue="h3-memory-v1", runtime=execution, release=release
)
engine = TemporalEngine(client, task_queue="h3-memory-v1", scope=scope, release=release)
spec = AgentDefinition(
    AgentSpec("assistant", "Answer the request"),
    AgentBindingDescriptor(
        stage_policy=BindingSelection.ref("observations", "1"),
    ),
)
# async with worker:
#     handle = await engine.submit(spec, "task", command_id="first", budget=8)
#     result = await engine.drive(handle.run_id)
#     evidence = await engine.memory_stages(handle.run_id)
# Worker 停止后再关闭借用的 facts／Provider／client。
```

使用 `stage_policy=ManagedMemoryPolicy(...)` 可为 Runtime 设置 opt-in 默认；成员可显式 disabled。
`ManagedModelMemoryPolicy(..., provider="selector")` 使用独立注册的选择模型；必须显式配置该 alias。每次字段选择与每次 CAS 各占一个 execution credit；额度不是货币计费上限。
`Runtime.from_temporal(engine)` 支持同一绑定定义及共同 AgentRun 查询／resume／detach。JSON／TOML 的 Local Profile 工厂不直接创建 Temporal Worker。

多个 Agent 的选择用 `BoundDefinition(flow, {path: descriptor})`：顺序 `sequence/steps/0`，图 `graph/nodes/research`，Team `team/members/research`，嵌套可继续 `/sequence/steps/0` 或 `/team/members/check`，动态 `dynamic/members/research`。以声明路径固定，重名 Agent 不会混用目标。默认别名或新发布变化不会改变已接受 Run 的版本，重复 caller command 返回原回执。

同一队列的所有 Worker 必须装配相同非秘密注册信息、实现和稳定后端身份。组件全部借用，catalog 注册不授予额外身份权限。自定义同步/异步 Memory 需提供 CAS、验证及 `fact_inspection_version=1` 的准确查询；仅 bounded recall 的旧目标明确拒绝。SQLite／内存不能当作跨机器默认存储，分布式 Worker 须使用共享的持久后端，如已有 Redis／PostgreSQL Memory 端口。

## 阶段与恢复

History 在推进下一步／确认业务完成前，分别记录来源、规则准备或模型选择请求、选择响应、字段采纳、事实初读、CAS 派发和准确核验。纯准备／采纳／读取 Activity 最多三次尝试，包括 temporal-3 的只读 Knowledge／上下文准备；自定义 references／validate 必须可安全重复读取，不能在这些端口写业务效果或隐式调用模型。选择模型与 CAS 仅一次。CAS 使用 `expected_version=0`，键由原 Run／node／字段确定；同键冲突不会覆盖。

选择响应先进入 History，再由纯采纳阶段校验。模型不能新增字段、工具或自行合成值；无效输入/响应、已过期事实或不足的可选额度不撤销已完成业务结果。未知选择成本和写效果保留原独立额度。

模型、摘要、字段选择与记忆写入在对外派发前，向原 Workflow 请求匹配 Scope／Action／请求摘要／Release 的一次授权。取消先被接受时拒绝新外部调用；授权先被接受的在途操作仍可返回证据。各 await 后重新验证原组件及其实际方法；同 backend_id 的实例更换也不能静默确认原发布。上下文快照身份包含原节点及其绑定；历史产物证据保存原阶段策略，后续切换上下文不改变它。

`engine.memory_stages(run_id)`／`AgentRun.memory_stages()` 是纯 History 查询，不读事实库，也不自动遍历子 Run。显式 `drive`／根 `resume` 才会恢复原未知事实：沿原已接受子 Run 控制递归查询核验，不能重新派发选择模型或 CAS。未知事实找不到、版本/内容冲突或后端改变时不释放额度。

超时写 Activity 即使后来查到完全匹配的事实，也只证明效果。它不能证明执行线程／远程请求已停止，因此原子额度可结算，但远程停止仍未知，父 Run 继续持有子额度。没有强行清理未知效果或自动重试写的接口。多事实不是跨库原子事务，期限与服务载荷限制仍存在。

## 验证与下一阶段

确定性测试使用真实 JSON 编码／解码，验证固定来源、额度、取消、目标漂移、无效响应及终态只读恢复。实际 localhost Temporal Service 使用独立 Worker 进程和 SQLite 审计，覆盖选择响应后／CAS 后退出、根子恢复、读取取消与父子 History replay；最终统计见[验收记录](../architecture/reviews/2026-10-10-temporal-memory-bindings.md)。没有调用真实模型，也没有重测远程数据库部署。

剩余：Temporal 其他绑定角色／Knowledge selector／共享 Session、语义质量与冲突修订／撤回／遗忘、真实模型质量、远程产物默认组合、History payload 卸载／Continue-As-New、长期容量和保留治理。完整 H1／H3／M1 仍未验收。
