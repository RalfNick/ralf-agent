# RALF AgentHarness 目标架构

版本：1.8；日期：2026-10-10；维护者：RALF maintainers。
状态：根据用户认可的理想架构形成的目标设计；实现基线为0.1.0.dev43（H1a–H1f、Local stateless H2a、同库原生／顺序 H2b1／复合 Session H2b2／授权根 namespace H2b3／远程原生顺序 H2b4a／复合根 H2b4b、Temporal 原生入口 H2c1／高级编排入口 H2c2）。
读者：框架维护者、Agent应用开发者、适配器作者与企业部署团队。
除明确标为 H1a–H1f、dev31 Local stateless H2a 、dev32 同库原生／顺序 Session H2b1 与 dev33 Temporal 原生／顺序入口 H2c1 、dev34 高级编排入口 H2c2 与 dev35 同库复合会话 H2b2、dev36 授权根 namespace H2b3 与 dev38 远程原生／顺序 H2b4a 与 dev39 远程复合根 H2b4b 的子集外，本文中的接口和示例仍为目标设计。AgentHarness 当前固定声明并复用 Local 权威，dev40–42 已实现原生／顺序 Local 的规则记忆、受管理历史摘要和模型选择记忆；dev43 增加版本化 Local 推荐组合、确定性引用压缩和产物投影；完整 H3 及高级／Temporal 自动阶段仍待补齐。
[绑定使用教程](../../docs/agent-bindings.md)与 [Local Agent API](../../docs/agent-api.md)记录实际支持与拒绝；dev32 同库原生／顺序 Session/Turn 子集已交付；dev33 Temporal 原生／顺序入口已交付；dev34 已注册高级入口已交付；dev35同库复合会话与dev36授权根namespace已交付；dev38–39 远程原生／顺序及复合根会话已交付；Temporal 绑定与完整 H2 尚未交付。
已交付范围始终以[实现状态](../../docs/implementation-status.md)为准。
历史文件名harness-runtime.md保留以保护已有审查/链接；目标组件名称统一为AgentHarness。

## 1. 目标与术语

目标是让个人开发者配置模型和业务工具即可运行Agent，同时能按Agent替换模型、
上下文、记忆、知识、执行环境和策略；Workflow与Team共用执行、作用域和恢复契约。
默认单进程与本地存储；企业按需独立部署数据、Workers、Sandbox和Service。
逻辑分层不要求每层成为服务，不要求用户先理解全部内部对象。

广义Harness是Agent运行系统，包含Core执行循环和配套能力。RALF采用以下术语：

| 名称 | 目标含义 | 与现有代码关系 |
| --- | --- | --- |
| Agent | 应用入口，发起/观察/控制Run | 新Facade目标，不新增另一种Agent本体 |
| AgentHarness | 每Agent的循环策略、能力组合与受管理阶段 | 新增组合层，复用执行后端，不产生第三个调度权威 |
| Runtime | 共享组件装配、资源生命周期与执行任务托管 | 复用RuntimeBuilder/RuntimeInstance；不更名现有TemporalRuntime |
| RuntimeKernel | 公共执行协议、纯校验与确定性推进规则 | 从现有Engine逐步提取规则；自身不持有独立状态存储 |
| DecisionPolicy | 准备模型请求、解释响应并提出决策的纯策略 | 现有Harness/NativeHarness继续保持公开名称和prepare/propose兼容 |
| ExecutionAuthority | 一个Run的命令、Action、预算、审批和终态的唯一权威 | LocalEngine/SQLite与Temporal Workflow/History分别实现 |
| CapabilityBindings | 某个Agent选择的组件、资源、策略与限制声明 | 新增，解决现有Engine级全局注入的组合限制 |
| Agent/Session Facade | 简单应用入口、交互连续性、控制和展示 | 新增；Session连续性不等于Run恢复日志 |
| Service | 可选的身份、托管、容量和跨Agent服务边界 | 不成为另一个Run状态权威 |

AgentHarness不命名为HarnessAgent；后者容易与公共Agent类型重叠。
AgentHarness不命名为HarnessRuntime；Runtime保留为宿主/资源责任。
现有Harness不是完整AgentHarness。扩大产品概念时保留现有纯策略契约，
不能把它直接改成隐藏数据库访问、模型摘要或工具执行的异步万能对象。

## 2. 组件与依赖

~~~mermaid
flowchart TB
    U["SDK / CLI / HTTP / UI"] --> A
    S["可选 Service：身份、托管、容量、通信"] --> A
    S --> R["Runtime：资源所有权 / 本地任务托管"]

    subgraph H["AgentHarness"]
        A["Agent / Session Facade"]
        B["版本化能力装配与准入"]
        K["RuntimeKernel 公共执行协议"]
        P["DecisionPolicy / Planner / Workflow / TeamStrategy"]
        C["受管理 Context / Memory / RAG / Artifact 阶段"]
        A --> B --> K
        K <--> P
        K <--> C
    end

    R -.-> B
    R -.-> K
    K <--> X["ExecutionAuthority：Local / Temporal"]
    K <--> M["ModelProvider"]
    K --> T["ToolExecutor / AgentCaller / RunnerAdapter"]
    T --> E["Python / MCP / CLI / Sandbox / 业务系统"]
    C <--> D["Session / Facts / Knowledge / Vector / Artifact 适配器"]
    K --> O["持久事件 / 展示事件 / Trace / Eval"]
~~~

图中的Kernel为逻辑协议；实现时状态转换在选定ExecutionAuthority中提交。
Local/Temporal各自推进、生成稳定动作身份和写入权威记录，共用纯验证和案例。
不能在Facade、Binder、ContextPipeline或消息消费者中再维护一套执行状态机。

依赖方向：应用→Facade/Definition→领域契约；运行装配→注册工厂和执行后端；
适配器→领域端口；核心纯规则不导入数据库、Broker或厂商SDK。
存储和执行环境通过接口交互，不要求Harness进程与沙箱或数据库同址。

## 3. 组件职责、默认行为与替换

| 组件 | 输入/输出与责任 | 推荐默认 | 独立替换和依赖 |
| --- | --- | --- | --- |
| Agent Facade | 接受输入、返回结果/等待结果，代理控制和事件 | 原生Agent与Local；等待取消只停止观察 | 业务封装与CLI/HTTP使用相同协议 |
| Runtime/RunTaskSupervisor | 资源装配、真实drive Task托管、drain/关闭 | 自建owned与显式borrowed分开 | 共享池/远程客户端；Task索引不是Run权威 |
| Session Facade/Admission | 规范身份、绑定修订、Turn顺序与耐久占用 | 首期reject_if_busy；明确续接原Run | 显式分支；后续queue需独立能力验收 |
| CapabilityResolver | 声明→经过准入的固定组件身份和能力描述 | 显式注册工厂、继承宿主默认 | 外部组件注册，不在恢复时自动下载/升级插件 |
| DecisionPolicy | ModelRequest/ModelResponse→DecisionProposal | 现有NativeHarness/ReAct | 纯prepare/propose，不调用外部模型或业务工具 |
| Planner/Workflow/Team | 计划、修订、节点选择与委派提案 | 顺序、图、现有有限Plan/Team | 模型规划经受管理Action；流式编排单独声明 |
| ExecutionAuthority | 固定Release和请求→动作/回执/结果/事件 | 单进程LocalEngine+SQLite | Temporal History独立权威；执行后端需完整conformance |
| ContextPipeline | 来源读取/选择/可选变换→固定请求证据 | 近期完整轮次、字符预算、显式词法知识 | 纯选择器、精确token计量、受管理摘要与卸载 |
| Session/Facts/Knowledge | 按角色保存会话/事实/来源及版本 | SQLite/内存 | Redis/PG等，角色契约独立；不能泛化成万能Storage |
| Embedding/Vector/Rerank | 派生索引与检索提案 | 无外部依赖的词法路径；显式离线基线 | HTTP或本地语义模型、Qdrant/pgvector；有独立费用与重建身份 |
| ToolRegistry/ToolSource | 发现并固定工具Schema/效果/版本 | typed Python、显式目录 | MCP/CLI/HTTP；发现与授权分开 |
| ToolExecutor/Sandbox | 执行一个已准入Attempt，返回可核验观察 | 可信Python；需要隔离时显式开启Sandbox | 进程/容器/远程沙箱，声明文件/网络/取消/恢复能力 |
| Workspace/Skill | 访问受限工作文件，选择说明制品 | 首期不隐式访问文件；Workspace启用后受限目录 | 文件系统/对象存储/远程Workspace；Skill不能授予工具权限 |
| AgentCaller/MessageBus/A2A | 受管理子调用与可靠交接 | 同权威子Run、独立Session | MQ/A2A传输；命令去重和执行权威保持分离 |
| Verifier | 任务与证据→有依据的验收结果 | Schema/运行契约验证，明确验证级别 | 业务规则、人审、受管理模型评审；不能默认保证业务正确 |
| Events/Middleware/Eval | 观察执行、展示进度、度量质量 | 持久Run事件、有限观察hooks和日志 | OTel/UI/评测；观察失败不得抹掉已收到的业务证据 |

默认组件必须组成可运行链路，并有独立替换示例。每个新增接口至少解决一种
实际替换或组合需求；不为每个内部函数建立公开Protocol。
适配器兼容以角色/版本/能力/拒绝案例证明，不承诺所有数据库的笛卡尔积。

## 4. 每Agent能力绑定

Agent的目标、指令和输入输出契约，与宿主的组件实例/凭据/执行权限分开。
一个运行环境可包含研究、操作和审核Agent，分别选择知识库、上下文、工具与策略。
普通Team不为这些差异创建多个互不协调的Engine。

绑定包括provider、decision_policy、context、session、facts、knowledge、artifacts、
tool_set、workspace、sandbox、skills、verifier和相应允许的阶段策略。
缺省为继承、显式ref为覆盖、disabled为关闭；不能用含混的null同时表示三者。
详细输入身份、父子传播及兼容规则见[能力绑定契约](../specs/agent-capability-binding-contract.md)。

宿主始终决定可信身份、政策上限、凭据访问和执行后端。Agent可以缩小权限和预算，
不能覆盖宿主强制政策；选择组件也不能自动取得资源权限。
租户WorkspaceScope与文件系统WorkspacePort是不同概念，不能混用。

准入时将声明固定成ResolvedBindingSet及ReleaseManifest：组件版本/实现身份、
有效配置、后端身份、资源选择器、授权范围与能力要求。保存引用，不序列化客户端、
闭包或密钥值。凭据由宿主提供者按已授权范围解析，轮换不将密钥写入模型上下文。

同command_id/同调用方请求先找回原回执；不会因默认别名变化重新解析原Release。
运行恢复使用原绑定与原请求快照。找不到历史组件时明确失败，不改用当前默认。
运行中的选择只能在固定Release已允许的能力集合内进行；激活Skill或工具子集
有明确证据，不允许通过临时发现的新版本绕过原审批/权限。

## 5. 受管理生命周期

~~~mermaid
flowchart TD
    A["接受请求：幂等、身份、定义、能力准入"] --> B["固定Release / Bindings / Run"]
    B --> C["上下文阶段：读取、召回、预算、可选摘要与产物"]
    C --> D["固定请求快照 / 预检 / 额度预留"]
    D --> E["模型调用 / 收到响应证据"]
    E --> F["公共采纳校验"]
    F --> G{"回答还是动作"}
    G -->|动作| H["权限 / 审批 / 持久派发意图"]
    H --> I["工具 / 子Run / 委派"]
    I --> J["效果回执先接收，再采纳结果"]
    J --> C
    G -->|回答| K["Verifier / 必需保存"]
    K --> L["完成、暂停、失败或等待核验"]
~~~

ContextPipeline提供受管理阶段编排，纯ContextBuilder/Counter/Budgeter只变换数据。
检索、摘要、Embedding、记忆提炼、产物写入和来源验证属于明确I/O步骤：
声明身份、输入、超时、额度、取消、接收证据和失败策略。模型型步骤使用已有
受管理Agent/Action或新增有版本阶段契约，不能藏在prepare或观察hook中。

恢复以保存的Action请求和接收证据为准，不重复执行已确认业务操作。
来源版本在每个新Action读取时确定；旧Action重试保留快照并复核有效性，
不会偷偷换文档、重新摘要或改变已批准参数。组件身份固定不等于全部业务数据永久不变。

## 6. 上下文、记忆与RAG默认链路

1. 加载必需系统/任务与当前Run的完整工具证据。
2. 按绑定与Scope读取近期Session、长期事实、知识来源；设置分页/候选/字节上限。
3. 按来源、有效期、版本和授权验证候选，保留完整近期轮次和可引用来源。
4. 计量预算；先丢弃可选低优先级内容，再按显式策略执行摘要或产物卸载。
5. 交给DecisionPolicy准备请求，内核复核实际请求预算和固定身份后保存快照。
6. 任务结束时根据声明执行记忆候选提炼和来源约束采纳，独立记录结果。

存储权威必须分开：ExecutionStore/History负责执行；Session负责交互；
Facts负责已采纳记忆；Knowledge负责文档来源；Vector是派生索引；Artifact保存产物。
不能靠Redis Session、向量库或Trace恢复审批和未知写效果。

自动长期记忆和付费摘要缺省关闭。启用后包含来源、namespace、冲突/CAS、
大小/调用额度和用途限制；模型文本不能提升为系统权限或已确认业务写入。
语义检索显式配置Embedding/维度/索引版本；默认词法有用，Hash向量不冒充语义质量。
摄入确认与向量索引就绪分开，删除/撤权后不能继续依赖旧索引绕过来源回读。

每个辅助阶段声明required或best_effort。必需会话/结果保存完成后才能成功提交。
可选记忆失败记录为辅助结果，不能令已确认业务写重新执行；未知效果和额度证据
仍须保留。首个自动链路阶段按Run内有界阶段实现，不隐式启动后台工作。
非阻塞后台提炼若后续启用，必须提前接受独立AuxiliaryRun/Job，有独立预算、
版本、幂等身份和观察入口，不在已关闭Run上偷偷追加付费调用。

大产物引用有摘要、Scope、保留与有界读取；摘要不能替代效果回执或审批对象。
上下文裁剪、自动记忆提炼、存储压缩/保留清理是三种不同能力。

## 7. 工具、工作环境与外部完整Harness

工具调用路径统一为提案→准入→审批/预留→意图持久化→派发→接收→结果采纳。
Python、MCP、CLI和远程API都声明Schema、效果分类、版本与核验能力。
写效果未知时保留原Action/effect_key，并核验原操作；不靠模型重新规划绕过重复阻断。

Sandbox/Workspace独立于Harness控制进程。任意Python仍是可信宿主代码；
子进程不是安全沙箱。容器/远程执行器需要文件、网络、身份、配额、停止和恢复契约。
关闭必须等待真实handler/进程退出，不能只看到await Task取消就释放执行归属。
凭据控制面与生成代码环境分离；业务工具所需凭据最小范围注入，不暴露宿主管理密钥。

Skill为版本化说明/资源制品。加载后可影响上下文与策略，但不能扩大工具权限。
插件显式注册/校验/激活，拥有与借用资源分别关闭；缺失历史组件不能自动安装最新版本。

Codex/Claude SDK等完整外部Harness通过RunnerAdapter委派。它们自带内部循环时，
RALF只在可观察协议范围内承诺审批/取消/恢复；不可拦截的内部写操作不能宣称
逐动作治理。能力不足在准入前拒绝，遵循[Runner契约](../specs/runner-capability-contract.md)。

## 8. Workflow、Team与执行模式

Agent、静态顺序/图、动态Plan、Team按统一Run/Action/子调用协议执行。
Planner/TeamStrategy提出方案，解释器校验依赖/条件/绑定，执行权威接受并调度。
模型规划、模型验证和委派是受管理步骤，不能在纯计划解释器中隐藏I/O。

流式展示是delta/事件订阅；流式Workflow是有背压、序号、关闭和失败传播的数据流。
二者分别声明能力。任意循环需要最大迭代、预算和停止条件。
动态DAG修订固定基准版本，不能改写已经接受/执行的节点效果。

本地默认单进程、一个Coordinator；多进程Worker只改变执行位置，不共享争夺Run权威。
Temporal使用Workflow/History，PostgreSQL journal/查询投影不接管调度。
后端支持矩阵在提交前验证；同定义切换只有在所需能力全部被声明/验收后成立。

同权威子任务使用受管理子Run/Child Workflow、独立Session、预算和取消传播；
委派目标与资源/工具上界固定在父发布中，独立绑定不意味着任意提权。
MQ投递/ack不是执行确认；Inbox/Outbox、command_id与业务回执承担交接/去重。
远程A2A Agent可以拥有自己的权威，父Run记录交接与关联回执，
不假设跨系统数据库事务、全局恰好一次或取消即远端停机。

## 9. 统一入口、会话和关闭契约

完整规范见[Agent Facade/Session契约](../specs/agent-facade-session-contract.md)，
该规范补齐等待、跨Run会话占用及退出责任，是H2实现的前置门槛。dev31 H2a 已实现 Local stateless 入口、独立托管、纯观察、原根控制唤醒与可重试关闭；dev32 H2b1 通过显式 SessionRef 支持同库原生／顺序 Turn 与 rebind。跨权威会话租约、输入续接、deadline、handoff 和未支持的 Temporal 绑定／共享会话在接受前拒绝。dev33 H2c1 原生／顺序入口见[实际指南](../../docs/temporal-agent-api.md)。以下含完整 Session 的示例仍为目标；可运行子集见[Session 指南](../../docs/session-api.md)。

- Agent/Session入口提供run、submit、wait、status、approve/reject、send_input、
  cancel与事件观察；异步优先，Local同步控制通过明确适配。
- run是持久submit加wait；wait超时、caller取消await、HTTP/SSE断连仅结束观察，
  不隐式取消已接受Run。wait_timeout、deadline_at和close_timeout分别定义。
- Local drive由Runtime的Supervisor独立托管；Temporal由服务器Workers推进。
  wait不是对legacy drive的直接包装，后端不支持的deadline/续接在准入前拒绝。
- SessionKey包含Scope、规范存储资源、namespace与session_id，固定协调后端和绑定修订。
  首期串行策略为reject_if_busy；审批/输入/核验中的原Turn跨重启保持占用。
  排队需耐久Turn身份/FIFO/容量/恢复协议，首期不得用内存列表或MQ冒充。
- 新输入与approve/send_input/reconcile分开；续接原Run使用原Release。
  空闲会话显式CAS rebind影响以后Turn；换存储资源是迁移/分支。
- 独立Agent拥有自建Runtime；共享Runtime创建的Agent借用宿主和池。
  默认owned关闭drain到稳定暂停/终态，保留待办及RunRef，不默认取消业务；
  超时报告CloseIncomplete并保留必要资源/归属，取消或移交需显式选择。
- Agent关闭而借用Runtime开放时，RunHandle仍可通过宿主控制；
  Runtime关闭后活句柄不隐式重开客户端，使用RunRef和显式attach/Reader重连。

RunOutcome表达业务状态与验证级别；WaitResult另表达观察原因/时间。
不新增业务timed_out状态，Schema校验不称为业务质量保证。
以下仅为目标API示意，不能按当前SDK直接执行：

~~~python
async with Agent(
    name="assistant",
    model=model,
    tools=[lookup_order],
) as agent:
    outcome = await agent.run(
        "查询订单状态",
        session_id="user-001",
        command_id="query-001",
    )
# 若等待审批：自建Runtime在drain后保留原RunRef，后续显式重连接。
~~~

共享Runtime示意：

~~~python
async with Runtime() as runtime:
    agent = runtime.create_agent(name="assistant", model=model, tools=[lookup_order])
    handle = await agent.submit("查询订单状态", command_id="query-002")
    observed = await handle.wait(wait_timeout=5)
    await agent.aclose()
    snapshot = await handle.status()  # 借用Agent关闭，不关闭开放Runtime。
~~~

会话消息、Run/Action事实、来源引用与展示delta分开存储/编码。
delta可携带Run/Action/Item关联、顺序与完成标记，但未完成工具参数不能提前派发。
事实事件支持持久游标和重连接；展示delta可选保存，丢失展示不能改变执行事实。
HTTP/UI不暴露内部可变状态，也不持有唯一执行进度。

Service负责可信身份、定义注册、托管、容量、通信、凭据、观察和保留；
Runtime负责托管任务/资源，不因Service或单个Agent生命周期增加Run权威。
SDK直接运行不依赖Service，身份与Scope不从用户提示词取得。
企业OIDC/资源ACL、全局额度、迁移/备份、保留/压缩与恢复控制台分别验收。

## 10. 开箱即用的参考组合

| 组合 | 默认能力与额外条件 | 验收要求 |
| --- | --- | --- |
| Local Basic | Local+SQLite、近期上下文、typed工具、审批与恢复；真实模型须显式配置 | 安装包首个Agent和自定义工具；无配置不得把offline echo当真实推理 |
| Local Knowledge | Basic+文本摄入/词法RAG、来源与引用校验 | 自己的文档可问答；删除/版本变化拒绝旧引用；答案质量单独测 |
| Managed Memory | Basic+显式摘要/记忆阶段与产物限额，调用/费用可见 | 重启不重复提炼、CAS/来源拒绝、辅助失败不重执行业务写 |
| Team/Workflow | 按成员固定不同绑定，受管理子Run与共享上限 | 不同知识库/工具可独立替换，无Scope泄漏，预算/取消传播保持 |
| Distributed | 已支持定义+Temporal，明确数据/策略/环境能力矩阵 | 相同公共案例、实际Workers故障/History重放、原发布恢复 |
| Workspace/Coding | 显式Workspace/Skill/Sandbox/Runner配置 | 文件/网络权限、真实停止、效果回执与可观察恢复边界 |
| Enterprise Service | 以上组合+身份/容量/数据运维和控制面 | 长期运行、拒绝/迁移/备份/清理/恢复管理证据 |

推荐默认是版本化组合，不是一个无限参数的Builder。
低层端口继续可用，业务用户只覆盖需要的部分。
真实模型、远程服务、大模型下载和付费能力均由使用者显式配置。

## 11. 当前基线与迁移

| 能力 | dev37当前状态 | 目标迁移 |
| --- | --- | --- |
| DecisionPolicy | Harness/NativeHarness已实现 | 保留导入与行为，文档补充狭义定位 |
| 执行与恢复 | Local/Temporal明确子集、共享采纳规则 | 从Engine逐步抽纯规则与受管理阶段，共同conformance |
| 组件装配 | H1a与Local H1b六类绑定，覆盖原生/顺序/图/Team/Dynamic/嵌套、固定父子Release及Profile v2 | 补Temporal绑定、其他规范资源身份/环境角色；Local Session H1c已交付，不把Local H1b当完整H1 |
| 上下文/记忆/RAG | 多个端口/适配器与可选链路已有实现 | 组合为推荐受管理管线，补自动阶段与作用域路由 |
| Agent/Session应用API | H2a Local stateless Agent/Runtime、AgentRun/RunRef/WaitResult、托管／观察／可重试关闭；H2b1 原生／顺序及 H2b2 同库复合 Session/Turn、busy、固定绑定与 CAS rebind；H2c1 Temporal 原生／顺序共同入口与固定 RPC 派发／detach | H2c2 已接通已注册高级入口；补远程会话、续接、Temporal 绑定与完整共同验收；旧RunHandle DTO保留 |
| Workspace/Skill/Sandbox | 尚未完整交付 | 分别实现，不能把现有可信Python称为隔离 |
| 实时事件 | 持久事实订阅已有，Agent delta尚未统一 | 独立展示协议，不改变采纳语义 |
| 企业Service | 有限HTTP/A2A与交接 | 身份、容量、运维、迁移/保留和恢复控制面后续验收 |

不一次重写LocalEngine。新增绑定与阶段采用独立版本封装；
原AgentSpec、序列/图/Team声明、command身份及默认Manifest不因新增缺省字段改变。
旧Run通过原发布继续；需要新语义的新Run使用新定义/Release。
兼容性同时测试真实旧wheel、本地原审批/结果、Temporal旧History和新请求身份。

## 12. 开发顺序与验收

| 阶段 | 交付范围 | 完成证据 |
| --- | --- | --- |
| H1：能力绑定 | 新增绑定声明、解析/准入、固定Release、按Agent选组件，支持原定义兼容 | 同Engine中不同Agent知识/上下文/工具；独立替换；漂移/拒绝；安装包与旧Run恢复 |
| H2a：Local stateless入口（dev31） | 固定声明、独立托管、纯观察等待、原根控制、owned/borrowed关闭与显式重连 | 实际线程/租约、观察取消/超时、暂停/关闭失败重试、旧审批与安装包；不代表完整H2 |
| H2b1：同库原生／顺序会话（dev32） | 原执行事务接受 Session/Turn，固定协调 locator／绑定修订，耐久 busy/mismatch 与 idle CAS rebind | 实际线程／未知效果／结果保存占用、重启审批、别名与 raw bypass 拒绝、schema1 双向升级及 schema2 旧 SDK 拒绝；不代表完整 H2b |
| H2c1：Temporal 原生入口（dev33） | 共同 Agent/AgentRun API、异步重连、RPC 配置固定、真实观察时间和客户端 detach | 取消／慢查询／在途 RPC／资源漂移回归、实际 Service/Worker 审批／重连／History 重放及安装包；不代表完整 H2 |
| H2：统一入口 | Agent/Session/WaitResult、独立任务托管、耐久busy拒绝、drain/句柄关闭；按Facade规范验收 | 等待取消不取消业务；暂停/关闭/重启不丢占用；shared不关闭池；超时保留租约；相同后端案例 |
| H2后续可选队列 | 有版本的耐久Turn FIFO，首期明确拒绝queue | 去重/容量/顺序/绑定/取消/重启；不能用临时内存或消息投递代替 |
| H2c2：Temporal 高级入口（dev34） | 注册 Graph／Team／Dynamic／嵌套共同入口、实际子 Run 审批／核验与有界原组件遍历 | 实际 Service／Worker／History、原发布重连和安装包；绑定／共享 Session 与完整 H2 继续待交付 |
| H2b2：同库复合会话（dev35） | 同一 AgentSession 接通 Graph／parallel／Team／Plan/DAG／嵌套，原子最终保存、成员绑定和耐久占用 | 真实 async/thread、子效果核验／重启、旧新 wheel/schema3；远程与完整 H2b 继续待交付 |
| H2b3：授权复合根 namespace（dev36） | 独立宿主根资源、按允许 namespace 开会话、固定绑定派发复核 | 同名地址／历史隔离、审批重启及安装包 schema4 拒绝；dev37 补齐 Profile／安装示例；远程和完整 H2 待交付 |
| H3：默认智能链路 | 近期召回、RAG、显式摘要/提炼/卸载的推荐组合，辅助结果可见 | 不重执行业务、来源/预算/取消故障；实际模型答案/引用/记忆质量逐项报告 |
| H4：环境与协作 | Workspace/Skill/Sandbox/子Agent及可观察Runner委派 | 文件/网络隔离、真实退出、重复交接、预算传播、同任务故障窗口 |
| H5：后端与服务成熟度 | 能力一致性、容量/保留/部署/身份/迁移与恢复管理 | 实际服务长期运行、故障/升级、外部开发者接入，明确未支持组合 |

真实任务评测贯穿H1–H5，不以端口数量或测试数量替代质量。
最终对标使用相同模型/任务/工具/预算/业务服务与故障场景；
尚未完成跨框架对等实验前，不宣称对齐或超过AgentScope。

## 13. 架构决策与依据

- HD-01：广义Harness包含Core，现有Harness保持DecisionPolicy兼容；避免概念和API混用。
- HD-02：能力绑定是声明与准入，执行权威唯一；插件不能通过配置获得授权或调度权。
- HD-03：纯策略与受管理I/O分开；组件可以组合而不丢费用、取消和接收证据。
- HD-04：执行、会话、记忆、来源、索引、产物与展示各有权威；缓存/遥测不用于恢复审批。
- HD-05：默认组合有版本，新任务解析新默认，原Run固定发布；历史迁移必须显式。
- HD-06：身份/凭据/沙箱分离；可信Python、容器和远程环境分别声明实际隔离能力。
- HD-07：后端用共同案例验收能力差异；不把Temporal当SQLite存储适配器。
- HD-08：渐进实现并保留原接口，先绑定/入口，再默认链路和环境/企业治理。
- HD-09：Agent/AgentHarness/Runtime/ExecutionAuthority各有责任，历史文件/API名称保持兼容。
- HD-10：wait取消只结束观察，显式命令才取消业务，业务deadline单独持久计时。
- HD-11：Session身份和占用耐久；首期忙碌拒绝，queue是后续独立能力。
- HD-12：owned/borrowed控制关闭，默认drain保留可恢复待办，关闭失败不放开执行归属。

规范入口：[总架构](../design.md)、[能力绑定契约](../specs/agent-capability-binding-contract.md)、
[框架能力](framework-capabilities.md)、[智能数据链路](intelligent-data-pipeline.md)、
[Facade/Session契约](../specs/agent-facade-session-contract.md)、[Run命令](../specs/run-command-contract.md)、[Action恢复](../specs/action-recovery-contract.md)、
[Runner能力](../specs/runner-capability-contract.md)。

参考：[Codex Harness/App Server](https://openai.com/index/unlocking-the-codex-harness/)说明循环、
会话/配置/工具和客户端协议分离；[Anthropic Managed Agents](https://www.anthropic.com/engineering/managed-agents)
说明Harness、会话日志和执行环境可独立替换；
[长期Agent实践](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
强调交接进度与验证。本文的RALF类型和取舍是本项目设计，不声称直接兼容这些系统。

## 14. 本地AgentScope参考与审查修订

参考用户指定的AgentScope checkout：2.0.10dev，commit
48c4b9ce0f9a3f86e5c3385d43cd2220245eef10（2026-10-08），并非此前v2.0.9稳定版快照。
它使用统一Agent入口、reply/reply_stream及事件化续接、Toolkit/配置/Middleware、
AgentState与独立应用Service/ChatRunRegistry/lifespan；没有导出HarnessAgent类型。
可借鉴入口渐进性、typed事件、宿主任务与资源统一管理、保存后释放会话锁。
RALF保持命令幂等/效果证据和纯策略边界，不照搬async Task取消即业务中断、
可吞最终事件的hook语义或将整体AgentState当Run恢复权威。
本轮三个P2及源码定位详见[修订与参考记录](../reviews/2026-10-08-agent-harness-facade.md)。

| H2b4a：远程原生／顺序会话（dev38） | 原 Local admission 接受远程 Session Turn；Redis／PG 原子准确消息回执；原 Run 中保存意图／模型 Action 对应标记／派发／核验回执 | 丢失响应及重启不重跑业务、终态只查询且未知保存占用、schema5 旧代码拒绝；复合根远程、跨权威共享、Temporal Session 和完整 H2 仍未交付 |

| H2b4b：远程复合根（dev39） | 已有 Graph／parallel／Team／Plan/DAG／嵌套根保存复用准确回执；原权威采纳结果、持久对应标记和最终成功；复用 session-resource 异步装配 | 原结果直接保存恢复不重跑决策／业务、审批重启及真实 Redis、schema6 旧代码拒绝；跨权威／Temporal 共享及完整 H2 未交付 |
