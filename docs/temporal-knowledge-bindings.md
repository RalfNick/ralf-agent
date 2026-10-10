# Temporal 每 Agent 知识库绑定（dev59）

Temporal 的 `KnowledgeBindingResource` 复用 Local 的宿主范围视图和原
`BindingCatalog`，允许同一 Workflow 的不同 Agent 选择独立 namespace。
Context Activity 负责读取，原 Temporal History 负责采纳和执行；没有新的状态机。
原生 Agent、顺序、图、Team、动态 flat/DAG、嵌套中的实际 Agent 使用同一协议。

## 最小 SDK 装配

```python
from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    Document,
    KnowledgeBindingResource,
    KnowledgeContext,
    LexicalRetriever,
    Scope,
    SQLiteKnowledgeStore,
    ToolRegistry,
)
from ralf_agent.temporal_activities import TemporalRuntime

scope = Scope("workspace", "developer")
store = SQLiteKnowledgeStore("knowledge.sqlite")
store.put(scope, "guides", Document("guide", "pool troubleshooting"), expected_version=0)
catalog = BindingCatalog(scope=scope)
catalog.register(
    "knowledge",
    "docs",
    "1",
    KnowledgeBindingResource(
        KnowledgeContext(LexicalRetriever(store)),
        namespaces=("guides", "policies"),
        default_namespace="guides",
    ),
)
execution = TemporalRuntime(
    providers={"default": provider},  # 宿主已注册 Provider
    tools=ToolRegistry(),
    binding_catalog=catalog,
)
definition = AgentDefinition(
    AgentSpec("answer", "Answer from the supplied evidence"),
    AgentBindingDescriptor(
        knowledge=BindingSelection.ref("docs", "1", selector={"namespace": "guides"}),
    ),
)
release = execution.orchestration_release
# 将 definition、原 release 和 scope 传给 TemporalEngine 与已注册 Worker。
# Worker 停止并确认 Activity 退出之后，由宿主关闭 store。
```

`BoundDefinition` 按现有规范路径绑定组合成员；无需修改编排定义。
`inherit/ref/disabled` 分别继承、替换和关闭。省略 selector 使用资源默认 namespace；
只能选择宿主 allowlist 中的 namespace，输入不能扩大 Scope 或数据权限。
原始 Knowledge port 的 ref 仍拒绝 selector，可继续使用其构造器固定的 namespace。

## 默认、替换与固定发布

默认不启用 Knowledge，原 global/raw 发布不增加 scoped 协议字段。
显式资源启用 `temporal-3` 的 `knowledge_protocol=1`；旧版本不能执行新协议。
具体选择的 namespace、原上下文身份与检索资源写入 effective manifest。
SDK/工厂装配交付；Local RuntimeProfile 尚不能自动生成 Temporal Worker。

`KnowledgeContext` 默认最多 5 条、8000 个 canonical JSON 字符。
原生 SQLite／内存 Lexical 是离线默认；PostgreSQL 使用原生异步知识库端口。
Vector、Hybrid、QueryTransformRetriever 可按原 SPI 组合，Embedding／Reranker／
ModelQueryTransform 必须显式注册。Hash 是词项基线，不是语义质量保证。

注册固定已知原生组合的对象、方法和公开身份：Lexical 的来源、Vector 的来源／
索引／Embedding、Hybrid 的分支／Fusion／Reranker、Query 的 transform／Provider。
SQLite 实际路径及 Store 身份、连接固定；PostgreSQL 地址／数据库及连接固定。
原生 HTTP 与 Qdrant 客户端实例固定；允许原生 owned Embedding／Reranker 第一次惰性初始化，
初始化后不能替换。HTTP 模型固定 public client，并固定其客户端管理方法。
公开身份不含密码或 API key。自定义端口必须以公开 identity 声明自己的内部资源；
框架不递归扫描任意对象内部字段。

SQLite 组合要求 Worker 使用相同磁盘位置，显式 backend_id 不能绕过物理地址。
跨机器使用远程数据服务并提供固定资源身份；本轮单机恢复不代替跨机部署验收。
组件均为 borrowed，多个 Worker 的拥有者负责池、客户端和连接生命周期。

## 来源、取消与恢复

History 采纳具体 Scope、namespace、document/chunk ID、版本和文本摘要，
受管理 finalize 保持 prepare 的原始来源分类。Knowledge 与 Facts 同时启用时
各自保存证据，校验器只接收自己的原来源；Builder 接收合并引用。
新模型派发前复核原始来源是否存在、版本是否一致及 TTL。
最后一次 Knowledge await 在 History dispatch admission 之前；期间取消会阻止新模型。

已完成模型／成员保留原 History 结果，不因后续知识库更新重新执行。
安全的未完成 Context 读取遵循原重试契约；模型未知响应保持未知，不能借检索重试重复派发。
Embedding、query 模型和 HTTP 重排在 Context 采纳前可能重复调用，当前记录／预算不保证真实费用上限。

真实 Worker 退出、重启及 replay、源码／安装／兼容证据分别见
[dev59 验收](../architecture/reviews/2026-10-11-temporal-knowledge.md)。
共享 Session／输入续接、其他绑定角色、自动索引生命周期、企业 ACL、真实语义质量
及完整 H1/H3/M1 仍需后续开发和验收。
