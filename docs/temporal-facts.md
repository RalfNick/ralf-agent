# Temporal Facts 绑定与有界召回（dev58）

`TemporalRuntime` 可显式接入 Facts 后端，并复用 `FactsBindingResource`、
`BindingCatalog`、`MemoryRecallPolicy` 和纯 `RecallPlanner`。
默认不启用；启用后采用有界召回，沿原 Context Activity／Temporal History 采纳，
没有新增执行权威。原生 Agent、顺序、图、Team、动态 flat/DAG 和嵌套中的实际 Agent 使用相同协议。

## 默认组合与替换

```python
from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    FactsBindingResource,
    MemoryRecallPolicy,
    RecallQuery,
    Scope,
    SQLiteMemory,
    TaskRecallPlanner,
    ToolRegistry,
)
from relf_agent.temporal_activities import TemporalRuntime

scope = Scope("workspace", "developer")
facts = SQLiteMemory("facts.sqlite")
facts.put_fact(scope, "personal", "language", "中文", expected_version=0)
catalog = BindingCatalog(scope=scope)
catalog.register(
    "facts",
    "preferences",
    "1",
    FactsBindingResource(
        facts,
        namespaces=("personal",),
        default_namespace="personal",
    ),
)
execution = TemporalRuntime(
    providers={"default": provider},  # 宿主注册的 Provider
    tools=ToolRegistry(),
    binding_catalog=catalog,
    recall_planner=TaskRecallPlanner(
        MemoryRecallPolicy(
            facts=RecallQuery(max_items=16, max_chars=6000, scan_limit=128),
        )
    ),
)
definition = AgentDefinition(
    AgentSpec("assistant", "Use evidence to answer the task"),
    AgentBindingDescriptor(
        facts=BindingSelection.ref(
            "preferences",
            "1",
            selector={"namespace": "personal"},
        )
    ),
)
release = execution.orchestration_release
# 将原 release、definition、scope 传给 TemporalEngine／已注册 Worker。
# Worker 停止并确认所有 Activity 退出后，由拥有者关闭 facts。
```

未指定 planner／policy 时使用 `MemoryRecallPolicy()`：最多 32 条、8000 个 canonical JSON
字符、256 个候选、1 页。此默认是有界事实读取，不是语义召回。
`recall_policy` 与 `recall_planner` 互斥；TaskRecallPlanner 将任务文本用于过滤／检索。
当前显式 shared session_id 会在接受前拒绝；planner 以稳定 Run ID 标识隐式会话。
接口保留 session_id 语义，不提供共享 Session 持久化。

`facts=original_backend` 可配置全局默认，物理 namespace 沿用 AgentSpec.name；
每路径 `inherit/ref/disabled` 可继承、替换、关闭。显式宿主资源才能选择允许的 namespace，
不能从输入扩大 Scope／allowlist。全局参数不接受已选视图或资源 wrapper。

替换为原生异步 `RedisMemory`／`PostgresMemory` 或 `IndexedMemoryStore` 不需要改 Workflow。
Facts 后端沿 `recall(scope, namespace, RecallQuery) -> RecallPage` 和
`validate_facts(scope, namespace, records) -> None`；原 facts-only 后端使用明确的 legacy 桥接，
其底层全量读取不具有 backend-bounded 保证。索引写后重建仍是显式宿主操作。
Worker 使用现有显式 SDK 工厂装配；本轮没有把 Local RuntimeProfile 自动变成 Temporal 工厂。
绑定投影覆盖定义中的已声明 Agent；内部 Planner 仍由宿主 Planner 注册独立配置。

## 有界页面与固定身份

多页预先分配总 item／字符／candidate 额度，之后保持每页查询不变，只推进 cursor。
源 snapshot 必须一致；重复记录、循环 cursor、超额或惰性返回均拒绝。
预分配可能降低稀疏数据的额度利用率，不能以页数重复消费总额度。
回执保存原 query、page query、snapshot、扫描统计、continuation 和已采纳事实摘要。
若后端召回含 Embedding，Context 接收前的读取重试仍可能重复调用；记录扫描额度不等于费用。
分页终止不代表扫描了整个语料库；IndexedMemoryStore 的 top256 候选边界仍适用。

注册固定对象、方法、声明身份和原生 SQLite 连接／路径；原生 Redis client、pool、prefix 和
地址／DB，PostgreSQL connection 和地址／数据库也固定。公开发布信息不包含密码。
自定义或代理客户端应以 backend_id／公开 identity 声明物理资源，宿主仍负责其正确性。
所有 Facts、Provider 和客户端为 borrowed；不能在 Activity await 中替换或先行关闭。

## 采纳、取消与恢复

Knowledge references、Facts records、召回回执分别保存，ContextBuilder 收到两者合并的证据。
普通 Context 采纳校验来源分类、摘要和额度；受管理 finalize 必须保持原 prepare 的三项 Facts 证据。
Knowledge 的校验器只收到 Knowledge 引用；Facts 的校验器复核原 Scope、namespace、版本、值和 TTL。
新业务模型调用前复核原事实，最后一次 Facts await 在 History dispatch admission 之前，
期间取消会阻止模型派发。模型摘要只处理历史 groups，不另读本轮 Facts。

已完成模型响应和业务结果作为原 History 证据保留，不因 Facts 后续更新重新执行。
安全的未完成 Context 读取按原读取重试契约恢复；未知模型响应保留未知状态，不能作为无效果自动重试。
本轮实际 Worker kill 矩阵验证读取恢复、已完成成员和原子树选择；单机 SQLite 示例要求共享同一磁盘。
跨机器使用远程事实库，并承担各自服务一致性、权限和运维要求。

真实服务、安装包与验收详见 [dev58 记录](../architecture/reviews/2026-10-11-temporal-facts.md)。
dev59 补齐 [Temporal Knowledge namespace 视图](temporal-knowledge-bindings.md)。仍未完成：其他绑定角色、共享 Session／续接、
全库索引自动生命周期、真实语义质量和完整 H1/H3/M1。
