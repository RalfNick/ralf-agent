# 每 Agent 能力绑定 — Local 基础与 Temporal 当前范围

在同一个 LocalEngine 中，原生 Agent、顺序／图 Workflow、Team、Dynamic 及嵌套成员可以选择不同的模型、
纯 DecisionPolicy、上下文、长期事实、知识库和工具子集。每个 Run 固定实际组件及身份；
无需修改原 AgentSpec，也不为每个 Agent 新建执行权威。

H1a、Local H1b、Session H1c 和 Facts／Knowledge 范围 H1d 已实现。Session 后端与宿主允许的 namespace 选择见[Session 教程](session-bindings.md)。
当前 Temporal 已提供版本化 provider/context/knowledge/tool_set/stage_policy/facts 六类绑定，含高级 Agent-node 编排；
Knowledge selector、共享 Session 和其他角色等其余组合仍未实现，详见[Temporal 执行范围](temporal-execution.md)。
统一 Agent/Runtime Facade 和 Local 耐久 Session 已交付明确子集，见[Agent API](agent-api.md)；
跨后端完整会话路由、其余能力及关闭／移交语义继续按[目标契约](../architecture/specs/agent-facade-session-contract.md)逐项验收。
本页最小用法以 Local 为主，底层 submit/drive/close 与 Facade 的托管生命周期应分别使用各自契约。

## 1. 最小用法

下面示例使用离线 Provider 验证选择与执行链路，不调用真实模型：

~~~python
import asyncio
from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    RuntimeBuilder,
    RuntimeProfile,
)

profile = RuntimeProfile(
    "app",
    "1",
    {"default": {"adapter": "offline-echo"}},
    binding_components=[
        {
            "role": "provider",
            "component_id": "research-model",
            "version": "1",
            "component": {
                "adapter": "offline-echo",
                "config": {"label": "research"},
            },
        }
    ],
)
agent = AgentDefinition(
    AgentSpec("research", "Answer the question"),
    AgentBindingDescriptor(
        provider=BindingSelection.ref("research-model", "1"),
    ),
)
with RuntimeBuilder().build(profile, "bindings.sqlite") as runtime:
    handle = runtime.submit(agent, "pool timeout", command_id="query-001")
    result = asyncio.run(runtime.drive(handle.run_id))
    print(result.result)  # {"echo": "pool timeout", "label": "research"}
~~~

模型适配使用同一已注册 Provider 工厂，例如 chat-completions、deepseek-chat、
anthropic-messages、gemini-content、openai-responses。服务、账号和任务质量仍需分别验证。
配置只保存环境变量/secret 引用；密钥不能放进绑定声明、组件 identity 或事件。
真实模型配置见[模型适配](model-adapters.md)。

## 2. 当前角色与默认行为

| 角色 | inherit | ref | disabled |
| --- | --- | --- | --- |
| provider | 原 spec.provider 对应宿主 Provider | BindingCatalog 中的 Provider | 拒绝，属于必需角色 |
| decision_policy | 宿主 Harness/NativeHarness | 同步纯 prepare/propose 策略 | 拒绝，属于必需角色 |
| context | 宿主 ContextBuilder | 同步、版本化上下文构建器 | 拒绝，属于必需角色 |
| facts | 宿主长期记忆后端 | sync/async facts 后端，保留 backend_id 与来源核验 | 不读取长期事实 |
| knowledge | 宿主 KnowledgeContext 或关闭默认 | async references/validate，固定知识范围 | 不检索知识 |
| tool_set | 原 AgentSpec 工具集合 | 注册工具名称子集 | 有效工具集为空 |
| session | 宿主原 Session 后端 | 注册 SessionStore／AsyncSessionStore；宿主 allowlist 下的 namespace | stateless，不读取/保存会话消息 |
| verifier | 未配置时仅强制 Schema 校验；已配置时继承宿主验证器 | 纯同步 CompletionVerifier，固定身份与回执证据 | 关闭额外规则，Schema 仍强制 |
| limits | 原 Spec 与宿主强制上限 | 纯同步策略，与宿主／Spec 取最小值 | 只关闭额外 Agent 策略，宿主限制仍生效 |
| stage_policy | 原生／顺序：默认关闭或宿主自动规则记忆 | 关闭自动阶段 | 宿主注册的 ManagedMemoryPolicy |
| artifacts/workspace/sandbox/skills | 原宿主行为；不激活新阶段 | 首期拒绝 | 首期拒绝 |

工具子集不能增加 AgentSpec 未声明的工具；HostPolicy、审批、效果分类和执行器始终由宿主控制。
目录绑定不授予企业资源权限。facts 使用当前 Agent 名称作为既有 namespace；knowledge
使用构造器固定的 namespace。Session、Facts 和 Knowledge Resource 的 namespace selector 受宿主 allowlist 约束；数据范围配置见[H1d 教程](data-bindings.md)。原始数据组件 ref 和其他角色仍拒绝 selector，不能跨 Scope。
原 Session 后端继承时沿用当前 Session 保护，不代表已经实现 H2 的规范 SessionKey/Turn 队列。
disabled Session 与显式 session_id 组合在接受前拒绝。Run/Action 事实仍然持久保存。

## 3. Python 组件注入和所有权

~~~python
import asyncio
from ralf_agent import (
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
from ralf_agent.runtime_builder import EchoProvider

scope = Scope("workspace", "owner")
catalog = BindingCatalog(scope=scope)
catalog.register("provider", "model", "1", EchoProvider("selected"))
facts = InMemoryMemory(backend_id="workspace-facts-v1")
catalog.register("facts", "facts", "1", facts)

with LocalEngine(
    SQLiteStore("custom.sqlite"),
    providers={"default": EchoProvider("host")},
    tools=ToolRegistry(),
    scope=scope,
    binding_catalog=catalog,
) as engine:
    agent = AgentDefinition(
        AgentSpec("assistant", "Answer"),
        AgentBindingDescriptor(
            provider=BindingSelection.ref("model", "1"),
            facts=BindingSelection.ref("facts", "1"),
        ),
    )
    handle = engine.submit(agent, "hello", command_id="custom-001")
    result = asyncio.run(engine.drive(handle.run_id))
~~~

BindingCatalog 中的对象默认 borrowed，Engine 不关闭它们。自定义工厂用
BuildContext.own/own_async 显式登记自己创建的资源，沿用 RuntimeBuilder 的逆序关闭、
失败重试和异步取消收尾。异步工厂用 await RuntimeBuilder.abuild(...)，保持创建事件循环。
详见[异步装配](async-assembly.md)。全局 current_agent 或切换 Engine 字段不是绑定实现方式。

## 4. 顺序 Workflow

~~~python
from ralf_agent import BoundDefinition, WorkflowSpec

workflow = BoundDefinition(
    WorkflowSpec(
        "pipeline",
        [
            AgentSpec("researcher", "Research"),
            AgentSpec("reviewer", "Review the previous result"),
        ],
    ),
    agent_bindings={
        "sequence/steps/0": AgentBindingDescriptor(
            provider=BindingSelection.ref("research-model", "1"),
        ),
        "sequence/steps/1": AgentBindingDescriptor(),
    },
)
~~~

路径必须指向已声明步骤；未指定步骤继承宿主组件。每一步单独保存 manifest，所以多个
步骤都用逻辑槽位 default 也可以解析到不同模型。工具执行仍采用同一执行权威。
dev26 将相同六类选择扩展到本地图、团队、动态规划和嵌套声明；原来未绑定的高级编排继续使用原接口。

### 图、团队与嵌套路径

~~~python
from ralf_agent import GraphNode, GraphWorkflowSpec, TeamSpec

research = GraphWorkflowSpec(
    "research",
    [GraphNode("read", agent=AgentSpec("researcher", "Research the task"))],
    max_concurrency=2,
)
team = BoundDefinition(
    TeamSpec("review", {"research": research, "reviewer": AgentSpec("reviewer", "Review")}),
    {
        "team/members/research/graph/nodes/read": AgentBindingDescriptor(
            provider=BindingSelection.ref("research-model", "1"),
        ),
        "team/members/reviewer": AgentBindingDescriptor(),
    },
)
# 使用第1节的 profile；research-model 为显式注册的离线 Provider。
with RuntimeBuilder().build(profile, "team-bindings.sqlite") as runtime:
    handle = runtime.submit(team, "查询并审阅", command_id="team-001")
    result = asyncio.run(runtime.drive(handle.run_id))
    print(result.state)
~~~

| 原定义 | Agent 绑定路径 |
| --- | --- |
| 顺序 | sequence/steps/0 |
| 图 | graph/nodes/read |
| 团队 | team/members/reviewer |
| 动态 | dynamic/members/worker |
| 嵌套 | team/members/research/graph/nodes/read；逐层追加原声明路径 |

只允许指向原生 Agent 叶子；不能绑定容器、Tool/Transform 节点或宿主规划器 @planner。
动态节点 ID 与成员绑定分开：计划只能引用首次接受时已经固定的 member。
父发布固定全部成员，包括 Router 未选中的成员；子 Run 继承对应子树声明、宿主 Scope、
审批／预算／取消契约。绑定不扩大工具授权。

串行 Graph 的 inherit Session 保留原共享会话行为；并行图继续使用原隔离节点 Session。
需要关闭消息读写时显式选择 session=disabled。原生／顺序／图带 disabled 叶子的显式
session_id 请求仍拒绝；Team/Dynamic 的 session_id 只标识父协调会话，子会话独立。
含 stateless 叶子的受管理子定义省略框架生成的显式 Session 请求，仍保留耐久 parent/call 身份。
dev27 开放独立 Session 后端及 namespace；跨执行权威共享 Session、H2 Turn 准入及新关闭语义仍未实现。

## 5. JSON/TOML 与能力声明

新增目录字段要求顶层 schema_version=2；schema_version=1 拒绝 binding_components。
原 v1 Profile 的 identity 不增加缺省字段。v2 可以保留不含绑定字段的原 v1 Profile。
支持的 Agent/Workflow/Graph/Team/Dynamic 包装可以保存成 to_dict() 的 JSON，通过 load_spec 加载，不能保存 Python 客户端。JSON/TOML 继续使用现有 schema v2 注册工厂及资源生命周期。

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
role = "provider"
component_id = "research-model"
version = "1"

[profiles.binding_components.component]
adapter = "offline-echo"

[profiles.binding_components.component.config]
label = "research"
~~~

LocalEngine.binding_capabilities 报告支持的定义、角色、Session 模式与阶段。
TemporalEngine.binding_capabilities 当前列出空的定义/角色集合，提交包装时在传输前拒绝。
Session ref 要求执行 Store 的可选同步 session_resource_owner 能力；能力声明按实际 Store 更新。不支持的 Store 在提交前拒绝。其他后端需要单独通过相同契约验收。

## 6. 发布、恢复和排障

同 command_id、同声明与输入先返回原提交回执，目录项移除或默认变化不影响查回。
改变绑定声明会发生 idempotency_conflict；这不是运行迁移。

显式 role/id/version 不可替换为另一对象或新 identity。新的组件应使用新版本；旧 Run
恢复需要原 Profile、目录及对象身份。缺失时报 definition_mismatch，不回退新默认。
模型返回后先保存完整响应，再检查绑定漂移；禁止因组件变化丢失已收到的证据。
CLI inspect 和文本 status/run/resume 按逐步骤发布展示绑定；审批及未知效果按原Action的node读取工具描述。

原生包装保留历史 AgentSpec 准入范围，不对它新增复合树的 1 MiB 限制；顺序／复合声明继续遵守原 Codec 的树大小和层级限制。

原生／顺序包装保持 local-bindings-1；高级编排包装在无 Session ref 时使用 local-bindings-2；Session ref 使用 local-bindings-3；选择 Facts／Knowledge Resource 时使用 local-bindings-4。复合发布保存稳定叶子路径、图节点索引和编排／成员身份；原未绑定 Run 保持 local-4。旧版本不能用旧内核推进新复合绑定发布；恢复需要支持该发布且能取得原组件的版本。
共享客户端的数据范围、原父子预算、审批和未知业务效果阻断仍有效。迁移、企业 IAM、
自动安装插件和跨后端绑定可移植性未交付。

设计依据：[能力绑定契约](../architecture/specs/agent-capability-binding-contract.md)、
[AgentHarness 架构](../architecture/viewpoints/harness-runtime.md)、
[当前实现清单](implementation-status.md)。

纯完成 verifier 的配置、耐久反馈和恢复见[H1e 教程](completion-verification.md)。

决策／上下文／工具动作 caps 与默认配置见[H1f 教程](agent-limits.md)。

自动记忆 stage_policy 的支持范围、写授权和独立恢复证据见[受管理记忆阶段](managed-memory-stages.md)。高级编排和 Temporal 自动阶段仍未交付。

Temporal dev58 的 Facts allowlist namespace、可替换有界召回与恢复边界见[专项指南](temporal-facts.md)。Knowledge selector／其他角色／共享 Session 尚未交付。
