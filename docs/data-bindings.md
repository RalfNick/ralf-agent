# 每 Agent Facts／Knowledge 范围绑定 — dev28 / Local H1d

一个共享存储客户端可以服务多个 Agent，各 Agent 使用宿主明确允许的 namespace。原生、顺序、并行图、Team、Dynamic 和嵌套成员沿用原绑定路径和执行权威；不会临时修改客户端的 namespace。

## SDK 默认组合与替换

~~~python
import asyncio
from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    FactsBindingResource,
    InMemoryMemory,
    KnowledgeBindingResource,
    LocalEngine,
    Scope,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.retrieval import (
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
)
from ralf_agent.runtime_builder import EchoProvider

scope = Scope()
facts = InMemoryMemory(backend_id="shared-facts-v1")
facts.put_fact(scope, "research", "language", "Chinese", expected_version=0)
docs = InMemoryKnowledgeStore(backend_id="shared-documents-v1")
docs.put(scope, "research", Document("guide", "pool recovery guide"), expected_version=0)
catalog = BindingCatalog(scope=scope)
catalog.register(
    "facts",
    "preferences",
    "1",
    FactsBindingResource(
        facts,
        namespaces=("research", "review"),
        default_namespace="research",
    ),
)
catalog.register(
    "knowledge",
    "guides",
    "1",
    KnowledgeBindingResource(
        KnowledgeContext(LexicalRetriever(docs)),
        namespaces=("research", "review"),
        default_namespace="research",
    ),
)
agent = AgentDefinition(
    AgentSpec("assistant", "Answer using references"),
    AgentBindingDescriptor(
        facts=BindingSelection.ref("preferences", "1", selector={"namespace": "research"}),
        knowledge=BindingSelection.ref("guides", "1", selector={"namespace": "research"}),
    ),
)
with LocalEngine(
    SQLiteStore("runs.sqlite"),
    providers={"default": EchoProvider("offline")},
    tools=ToolRegistry(),
    scope=scope,
    binding_catalog=catalog,
) as engine:
    handle = engine.submit(agent, "pool", command_id="request-001")
    result = asyncio.run(engine.drive(handle.run_id))
~~~

替换 facts 为现有 SQLiteMemory、RedisMemoryStore、PostgreSQLMemoryStore 或实现 Facts／Recall 端口的自定义对象；替换 KnowledgeContext 的 retriever 为已有 VectorRetriever、HybridRetriever 或自定义 retrieve／validate 实现。远程客户端沿用原异步生命周期和 [abuild](async-assembly.md)。基础依赖不增加厂商 SDK。

FactsBindingResource 和 KnowledgeBindingResource 默认允许 default，默认 namespace 为 default。显式 allowlist 必须包含默认值，每个值为 1–128 字符非空字符串；None 不在数据范围中表示继承。未包装的旧 Facts／Knowledge ref 保持原行为，不能额外传 namespace selector。自定义 references／validate Context 仍可直接登记；范围选择要求原生 KnowledgeContext 包装其 retriever，以免框架猜测自定义 Context 的 namespace 行为。

## 来源、预算与生命周期

Facts 视图将 Agent 名称等逻辑 namespace 映射到固定的物理 namespace。facts／recall 返回 _facts_binding，固定 Scope、backend_id、namespace 和 value_digest；validate_facts 检查来源及内容，再复用原端口校验版本／过期。另一视图的引用和游标不能混用。该元数据属于来源绑定协议，不是用于防范任意可信 Python 伪造的签名。

Facts 视图提供只读召回和校验，没有 put_fact；现有 MemoryPipeline 写入继续使用显式原后端及命名空间。本轮没有把提炼阶段自动装入 Agent。原 legacy facts 端口经已有 LegacyMemoryRecallAdapter 继续可用，并如实报告 backend_bounded=false。

分页按实际返回记录计算来源字段的字符开销；未能放入当前页面、但能放入空页面的记录，通过只包含底层游标／快照的范围游标保留，避免按 max_items 预留空间时丢掉稀疏事实。每次底层读取一个候选，所有读取和重读都计入 scan_limit；该默认桥接可能有多次远程往返，旧全量读取也仍有原效率限制。最终 used_chars 包含来源字段，不超过请求预算；自身完整记录超过预算时按 skipped 计量。

Knowledge 视图每次使用同一借用 retriever 创建独立的 KnowledgeContext 配置，保留原来源版本／摘要／过期和引用校验。真实 retriever 对象、配置和实现身份在异步调用前后复核；相同身份的新对象也不能在调用中替换它。共享原 Context 不会被改写。

视图与 Resource 不拥有底层客户端。使用宿主池或原工厂的 own／own_async 管理实际资源；选出的视图不能再次登记，也不能作为 Engine 的默认数据组件。Scope 是可信宿主提供的访问范围，namespace allowlist 不等于企业来源 ACL；既有顺序数据流／会话历史仍可能显式携带前一步结果，这与直接召回范围隔离分别定义。

## JSON／TOML 装配

Profile schema v2 的 binding_components 支持 facts-resource 和 knowledge-resource。如下片段嵌入既有 profile；原有 provider／路径／CLI 设置见[装配指南](runtime-assembly.md)。

~~~toml
[[profiles.binding_components]]
role = "facts"
component_id = "preferences"
version = "1"
[profiles.binding_components.component]
adapter = "facts-resource"
[profiles.binding_components.component.config]
namespaces = ["research", "review"]
default_namespace = "research"
[profiles.binding_components.component.config.backend]
adapter = "sqlite"

[[profiles.binding_components]]
role = "knowledge"
component_id = "guides"
version = "1"
[profiles.binding_components.component]
adapter = "knowledge-resource"
[profiles.binding_components.component.config]
namespaces = ["research", "review"]
default_namespace = "research"
[profiles.binding_components.component.config.backend]
adapter = "sqlite-lexical"
~~~

backend 使用原 session／memory／knowledge 工厂的配置；允许范围在创建客户端前校验，包装不能嵌套。同步和异步工厂类型保持，实际客户端按原 owned／borrowed 规则关闭，借用对象不被包装器关闭。namespaces／default_namespace 在 prepare 时固定，不能被随后修改的声明改写。

## 发布、恢复与支持范围

选择数据 Resource 时使用 local-bindings-4。未使用新包装器的原生／H1a／H1b／H1c Manifest 保持；同请求原回执先于当前目录解析，恢复找不到原资源时拒绝，不回退默认。已收到的模型响应先持久化，再报告身份漂移。旧 dev27 wheel 明确拒绝新 scoped-data 发布。

Session 和数据 Resource 可以混用：Session 实际地址占用由原执行权威检查，不因 kernel4 丢失；仅选择数据 Resource 时，不要求自定义 Store 增加 Session 准入端口。binding_capabilities 分别列出 session／facts／knowledge 的 namespace selector；缺 Session 准入时仅撤销 Session 能力。

本轮没有实现其他资源角色、Temporal 绑定、H2 Facade／Turn／rebind／新关闭协议、自动智能数据阶段或跨权威会话租约。默认模型答案符合 Schema，并不证明业务系统实际完成操作；本轮 DeepSeek 六次修复任务在未写入时回答 resolved，详见[真实试验](live-model-quality-dev28.md)。这些边界继续保留在[剩余清单](remaining-work.md)。
