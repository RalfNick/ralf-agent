# 自动记忆阶段（dev40／H3a）

dev45 将原协议扩展到 Local 图／并行／Team／动态／嵌套的实际 Agent，推荐默认组合也可使用；见[高级记忆阶段](composite-memory-stages.md)。下面保留原生／顺序的原契约，Temporal 自动记忆写入仍待实现。

Local 原生 Agent 和顺序 Workflow 可在每步输出通过 Schema／完成验证、必需
Session 保存后，自动提炼宿主允许的结果字段。默认关闭；原 Engine 负责额度、
来源、提案、写入意图、回执和恢复，没有额外执行权威或后台任务。

```python
from ralf_agent import (
    AgentSpec,
    LocalEngine,
    ManagedMemoryPolicy,
    MemoryAdmissionPolicy,
    SQLiteStore,
    ToolRegistry,
)

store = SQLiteStore("runs.sqlite")
stage = ManagedMemoryPolicy(
    store.create_memory(),
    admission=MemoryAdmissionPolicy({"language": ("result", "language")}),
    namespace="observations",
    timeout=5,
)
# provider 是应用装配的 async ModelProvider。
with LocalEngine(
    store, providers={"default": provider}, tools=ToolRegistry(), stage_policy=stage
) as engine:
    run = engine.submit(
        AgentSpec(
            "assistant",
            "Return language as JSON",
            output_schema={
                "type": "object",
                "required": ["language"],
                "properties": {"language": {"type": "string"}},
            },
        ),
        "request",
        command_id="request-1",
        budget=4,
    )
    result = await engine.drive(run.run_id)
    receipts = engine.memory_stages(run.run_id)
```

每个提议事实占一个 execution credit，先原子预留，再执行 expected_version=0
的 CAS。额度不足、字段不存在或提案不合规属于辅助失败，业务结果仍可成功。
写入结果未知会保留额度；`drive`／Facade 的显式 `resume` 仅查询未知写入的精确
内容、版本、有效期和来源，再采纳回执。已持久化并验证的回执直接结算，不受
之后的 TTL 过期、事实修订或后端暂时离线影响。已完成的模型、工具、事实不会重复执行。
未知且查不到的写入保持未知，不盲目补写；当前没有操作员撤销未知额度的接口。
终态恢复不改变业务终态，也不开始新的记忆写入。

`AgentRun.memory_stages()` 返回脱离内部状态的来源／策略／事实回执；`pending()`
以 `kind=auxiliary, source=memory` 表示可显式查询的辅助阶段，与业务效果核验分开。
`wait()` 观察业务状态；若需观察恢复完成，应检查这些回执和 Runtime 托管状态。

来源是已采纳且通过验证的 **completed-result-observation**。自动记忆发生在最终
Run 提交之前，取消或之后的本地提交失败可能留下观察，不能把它当作业务成功、
授权或外部事实证明。既有 [MemoryPipeline](managed-memory.md) 仍要求已成功的
权威 Run，是独立的显式提炼接口；其规则／模型选择行为没有改变。

每 Agent `stage_policy` 支持 inherit/ref/disabled；注册在 scoped BindingCatalog
中的 `ManagedMemoryPolicy` 是宿主对写入目标的明确授权。Facts 绑定只是只读视图，
不能作为写入目标，读取 namespace 也不会自动获得写权限。可实现同步纯 `propose`
返回具体 FactProposal 列表，所有值仍必须通过固定的基础字段 allowlist 验证。
借用后端不会由 Engine 自动关闭；使用装配工厂的 owned 客户端按已有生命周期关闭。

自动提炼不自动扩大读取权限。若后续对话需要召回观察，显式配置既有
MemoryRecallPolicy／Facts 绑定，选择对应 backend 和 namespace；默认 Facts
读取仍是 `default`。策略提炼的是观察，召回这些观察也不能替代业务核验。

配置默认使用同权威 SQLite backend，写入独立 namespace：

```toml
[profiles.components.stage_policy]
adapter = "sourced-memory"
[profiles.components.stage_policy.config]
namespace = "observations"
timeout = 5
max_facts = 4
[profiles.components.stage_policy.config.fields]
language = ["result", "language"]
```

可在 `config.memory` 显式声明既有 memory_store 适配器，例如 sqlite/in-memory。
Redis／PostgreSQL 等原生异步后端用 `sourced-memory-async` 和 `Runtime.afrom_profile`
或 `RuntimeBuilder.abuild`。工厂声明不包含密钥；凭证仍通过现有宿主配置接入。
同步端口必须及时返回；timeout 约束可挂起的异步 I/O，不能抢占同步 Python。
ThreadedMemoryAdapter 复用 Engine 真实线程跟踪，线程退出前不会释放 Coordinator。

首次接受启用阶段的 Run，在同一事务中启用 semantic schema7；自定义 ExecutionStore
须显式实现 `managed_stage_version=1`、同步 `prepare_managed_stages()->None`
与 `managed_stage_reservation(run_id, reservation_id)` 独立额度查询，在自己的
执行事务内使旧读者拒绝新语义。未启用的提交保留原有 Schema／Manifest。

dev45 高级自动阶段明确准入；规则／模型选择在原实际 Agent 执行权威中运行。
Temporal、自由合成模型记忆、背景记忆 Job、语义修订／撤回、多事实全局事务仍待交付。

内置内存／SQLite／Redis／PostgreSQL 提供可选 `fact_inspection_version=1` 的
`inspect_fact(scope, namespace, key)` 精确查询。自定义后端可实现该端口，或沿用
分页 recall：每次最多 32 页，进度留在原 Run 中，下次显式恢复续读。若 namespace
变化导致快照失效，保守重置游标后等待下一次恢复。持续变化的超大 legacy
namespace 应实现精确查询，不能依赖有限快照扫描保证及时确认。恢复和只读回执
均核对合法阶段状态、提案／回执对应关系与独立预算记录；缺失额度不会重建为写入授权。
