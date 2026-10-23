# 每 Agent Session 绑定 — dev27 / Local H1c

原生 Agent／顺序／图／Team／Dynamic／嵌套成员可以选择独立的短期会话后端。复用 SessionStore／AsyncSessionStore：SQLite、内存、Redis、PostgreSQL 和自定义实现；事实记忆、知识库和执行事实仍各自独立。

## 最小替换

~~~python
import asyncio
from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    InMemoryMemory,
    LocalEngine,
    Scope,
    SQLiteStore,
    ToolRegistry,
)
from relf_agent.runtime_builder import EchoProvider

scope = Scope()
history = InMemoryMemory(backend_id="private-session-v1")
catalog = BindingCatalog(scope=scope)
catalog.register("session", "history", "1", history)
agent = AgentDefinition(
    AgentSpec("assistant", "Answer"),
    AgentBindingDescriptor(session=BindingSelection.ref("history", "1")),
)
with LocalEngine(
    SQLiteStore("runs.sqlite"),
    providers={"default": EchoProvider("offline")},
    tools=ToolRegistry(),
    scope=scope,
    binding_catalog=catalog,
) as engine:
    handle = engine.submit(agent, "hello", command_id="turn-001", session_id="conversation")
    result = asyncio.run(engine.drive(handle.run_id))
~~~

原 Session 的 CAS、message_id 去重及分页保持；每个完成的 Agent 结果仍保存一条包含 task/result 的会话记录。借用的客户端不会被 Engine 关闭；使用工厂 own/own_async 登记自己创建的客户端。

## 共享客户端与允许的 namespace

~~~python
from relf_agent import SessionBindingResource

resource = SessionBindingResource(
    history,
    namespaces=("research", "review"),
    default_namespace="research",
)
catalog.register("session", "shared-history", "1", resource)
selection = BindingSelection.ref(
    "shared-history",
    "1",
    selector={"namespace": "review"},
)
~~~

namespace 由可信宿主登记，用户只能选择允许值。None 表示沿用原存储键；显式 namespace 为 1–128 字符。作用域固定为目录的 Scope。其他 selector 字段和其他角色的 selector 仍拒绝。视图不会临时修改共享客户端；物理键采用版本化完整 JSON 编码，原会话不会自动迁移。

目录登记原始后端或 SessionBindingResource。select() 返回的 SessionView 只用于该 Scope 下的直接操作，不能再次注册到目录，也不能作为 LocalEngine 的 session_store 默认后端；这些配置在接受 Run 前明确拒绝，避免丢失实际键投影和占用信息。

## JSON／TOML 与真实后端

已有 schema v2 的 binding_components 支持 role=session。普通 backend adapter 可直接使用；需要范围选择时使用 session-resource 包装。下面是可以离线运行的 TOML：

~~~toml
schema_version = 2
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[[profiles.binding_components]]
role = "session"
component_id = "history"
version = "1"
[profiles.binding_components.component]
adapter = "session-resource"
[profiles.binding_components.component.config]
namespaces = ["research", "review"]
default_namespace = "research"
[profiles.binding_components.component.config.backend]
adapter = "sqlite"
~~~

绑定 Agent 保存为 agent.to_dict() JSON，通过既有 CLI --config/--spec/--session-id 运行、恢复和检查。SQLite 可指定 path，默认复用执行 Store 的会话表。远程后端声明沿用 redis/postgres 适配器的环境引用及 backend_id，使用 await RuntimeBuilder.abuild(...)。外部客户端有自己的创建事件循环与所有权；同步 CLI/ProfiledEngine 仍不装配异步工厂。session-resource 用于绑定目录，不是宿主 session_store 的默认端口实现。见[远程数据](remote-data.md)与[异步装配](async-assembly.md)。

## 占用、发布与恢复

同一执行权威内，占用按 Scope、实际后端身份和实际存储键匹配，不使用目录名称作为锁。目录别名、默认后端和直接使用物理键不能绕过活动 Run；不同资源的相同逻辑 Session 名称可以独立使用。顺序步骤一次固定全部可能使用的资源；并行图节点使用原隔离会话，图／团队协调会话仍由宿主固定。

SQLite 在既有接受事务内推导旧 Run 的资源并记录新 Session ref 的 session_resources；不用新表或第二套调度器。真实线程／后代尚未静止时保留原占用。新任务也保存实际键别名供旧 reader 保守阻断。旧 ThreadedMemoryAdapter 的 threaded: 后端前缀按可能的存储别名保守匹配；部署身份需稳定且如实描述存储。此检查只覆盖同一 ExecutionStore／Coordinator；共享 Redis/PG 会话存储不会产生跨独立执行权威的分布式租约。

自定义执行 Store 要实现同步 SessionResourceAdmission.session_resource_owner(scope, resource)，在同一事务中检查旧／新任务，并保留审批／未知效果／quiescent 占用；缺失时 Session ref 在提交前拒绝，旧不绑定接口仍可使用。binding_capabilities 报告实际 Store 支持与允许的 Session selector 角色。

Session ref 使用 local-bindings-3；同时选择[H1d 数据 Resource](data-bindings.md)时使用 local-bindings-4，Session 实际地址准入保持。原生／顺序 H1a 与图／团队 H1b 在未选择新 Resource 时保持原发布字节。原回执先于目录查找，组件缺失不能回退默认；模型响应收到后先持久化，再拒绝身份漂移。

H1c 没有实现 H2 Agent/Runtime Facade、SessionKey/Turn 队列、CAS rebind、仅观察等待或新关闭协议；也没有交付 Temporal 绑定、企业资源 ACL、其他角色的 selector 和跨执行权威共享 Session。完整 H1、默认 AgentHarness 与企业验收继续沿[剩余清单](remaining-work.md)推进。

## 默认精确核验（dev64）

内存/SQLite 默认支持精确消息回执，与 Redis/PG 的 native async 契约一致；独立 Local Session 可复用远程 admission。内存不是跨重启耐久存储，同库 SQLite 保持原路由。使用与替换见[回执指南](session-receipts.md)；Temporal 外置数据尚未交付。
