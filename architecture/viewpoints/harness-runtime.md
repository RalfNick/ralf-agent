# RALF AgentHarness 目标架构

Dev90 思考模型适配子集已验收：新增显式 DeepSeekThinkingProvider／deepseek-thinking，复用原 ModelContinuation／完整历史及 Local／Temporal 执行权威，接通 SDK／Profile／四类评测 CLI。保留非思考默认和原 Run；最终源码6519 passed／593配置依赖跳过（993.63s），独立核心安装266 passed／零跳过，实际源码Temporal4／安装Temporal12通过；308产品模块一致，旧89四类原Run和默认字节兼容。唯一审查2个P2已修复；自有服务退出0并等待。真实模型质量、完整 R05／H3／M1／R01–R26及独立采用继续开放。见[接入指南](../../docs/deepseek-thinking.md)及[本批记录](../reviews/2026-10-13-deepseek-thinking.md)。

Dev86 端到端任务评测子集已验收：源码5681 passed／447配置跳过（830.34s）、独立核心安装161；源码三次重复RAG24/24、Plan15/15、Team15/15及安装CLI／SDK例子、旧85默认／原Plan回执兼容与298模块一致通过。复用原执行权威，新增最终模型请求可见引用、实际成员／工具回执、独立Embedding计量和观察式恢复；2项Important／1项Minor经有效RED统一修复。离线／MockTransport不构成真实模型质量；完整H3／M1／R01–R26及外部采用保持开放。见[任务评测指南](../../docs/task-evaluation.md)与[本批验收](../reviews/2026-10-13-task-evaluation-chains.md)。

Dev84 第十四类artifacts绑定子集已验收，沿原managed Context／Local／Temporal权威和真实执行所有权；支持独立Context策略与物理target／namespace、ref/disabled/inherit、默认memory／SQLite／POSIX及custom sync/async替换和owned/borrowed装配。显式disabled-only不要求额外存储；继承及legacy发布保持。

最终源码5431 passed／447配置跳过（678.60s），核心104／SDK242安装、真实源码51／安装51（均零跳过）、旧83双向兼容／22原模板／旧Worker零Activity拒绝及291模块一致通过。九类Important经一轮34项有效失败复现统一修复；本任务Temporal PID12900／session19994实际退出0并已等待，用户Docker平台保留。完整R01–R26、远端／binary／GC／cache／治理与真实质量继续开放。 见[本批验收](../reviews/2026-10-12-artifact-bindings.md)与[指南](../../docs/artifact-bindings.md)。

内容核验不等于handler-end证明，已派发未知写可nonquiescent；joint5/ref未获grant读最多耐久fence重建一次。完整H1/H3、企业治理及AgentScope全面parity未验收。dev83 M1/M2仍分别延期。

Dev83 已验收受限原生 SandboxProvider／Docker 默认、原 ToolSource、显式异步声明和每 Agent sandbox ref/disabled 授权交集。Local／Temporal 六类审批重启、已采纳恢复、原生冷接管及真实停止通过。最终源码5280 passed／418配置跳过（763.57s (0:12:43)），核心182／SDK149安装、真实源码32／安装32、旧82双向恢复／22模板／旧Worker零Activity拒绝及287模块一致通过。六项Important统一修复，M1／M2两项Minor延期；自有Temporal实际退出并等待。完整R01–R26、远程沙箱、持久工作区、Artifact传输、外部Runner和真实质量继续开放。见[原生沙箱指南](../../docs/sandbox.md)。

Dev82 子集已验收：纯可替换 SkillSelector／LexicalSkillSelector、SkillDirectoryRetriever、JSON／可选 SKILL.md 声明，通过原 KnowledgeContext 自动提供被动目录；正文仍走原授权 skill_get，不增加工具权限或执行权威。最终源码5089 passed／386配置跳过（845.08s (0:14:05)），核心155／SDK271安装、真实源码8／安装8、旧81双向恢复／22模板／旧Worker业务I/O前拒绝及281模块一致通过。三项Important经10项有效失败复现统一修复，无新增延期Minor；自有Temporal实际退出并等待。完整R01–R26、语义选择、插件激活、Sandbox／Runner及真实质量仍开放。见[本批记录](../reviews/2026-10-12-skill-discovery-context.md)。

Dev81 子集已验收：原生写真实生命周期及显式可替换 ToolExecutionPort／tracked owner，原 Temporal History 分别保存独占调用身份、实际结束与效果回执；容量拒绝／RPC失败／观察者取消的通知保持受管理重试。最终源码5021 passed／378配置跳过（758.54s），核心67／SDK232安装、真实源码8／安装8、旧80双向恢复／22模板／旧Worker执行前拒绝及278模块一致通过。三项Important经3项RED→GREEN统一修复，无新延期Minor；原自有服务停止并实际等待退出。完整R01–R26、Sandbox／Runner与质量目标仍开放。 见[本批记录](../reviews/2026-10-12-native-write-lifetime.md)。

Dev80：纯可替换 Skill 文档解析、可选有界 YAML、固定 SKILL.md 文件目录及 skills-markdown 默认声明子集已验收。最终源码4954 passed／370配置跳过（713.55s），无YAML核心35／SDK359安装、真实源码6／安装6、旧79双向恢复／22模板／272模块一致通过。三项Important经14项RED→GREEN修复，两项Minor延期；原自有服务停止并等待。selector／异步加载／自动Context／Sandbox及完整R01–R26仍开放。见[本批记录](../reviews/2026-10-12-skill-documents.md)。

当前dev79交付每Agent Skills原工具绑定；最终源码4823／364配置跳过、核心55／SDK127安装、真实六类、旧78双向兼容／执行前拒绝及自有服务停止通过。selector／自动目录阶段与完整H4仍开放。[本批证据](../reviews/2026-10-12-skills-bindings.md)。

当前dev78交付可替换Skills目录与原受管理读工具；最终源码4757／357配置跳过、核心142／SDK204安装、真实7项、旧77兼容及自有服务停止通过。专用skills角色与完整H4仍开放。[本批证据](../reviews/2026-10-12-skills-catalog.md)。

当前dev77子集已验收补Workspace CAS写入与单根租约，保持原Engine／History权威；证据与未完成门槛见[本批记录](../reviews/2026-10-12-workspace-writes.md)。其他环境绑定／Skills／Sandbox／Runner／H5与真实质量继续开放。

当前dev76：Local／Temporal每Agent只读Workspace成为第十一类绑定；已有外置Session读写、会话树、自动记忆／上下文与Profile Host。最终源码4501／345配置跳过、核心59／扩展160安装、源码及安装各六项实际服务与旧75双向恢复通过；1项Important修复，1项错误分类Minor延后，自有服务已停止。Workspace写入、其他环境角色、H4/H5和真实质量仍开放。
后文早期记录为历史范围；最新支持与拒绝见[实现清单](../../docs/implementation-status.md)及文末增量。



Dev46 已增加[Temporal 自动记忆与五类 Agent 绑定](../../docs/temporal-memory-bindings.md)：显式 temporal-3、原声明子树、History 选择响应／CAS／核验与父子证据恢复；旧发布保持。其他 Temporal 绑定角色／资源 selector、共享 Session、语义质量与完整 H1/H3 仍待验收。

版本：1.11；日期：2026-10-11；维护者：RALF maintainers。
状态：根据用户认可的理想架构形成的目标设计；当前实现为0.1.0.dev77（本批基于dev76/0501054）；dev43 的历史入口基线为（H1a–H1f、Local stateless H2a、同库原生／顺序 H2b1／复合 Session H2b2／授权根 namespace H2b3／远程原生顺序 H2b4a／复合根 H2b4b、Temporal 原生入口 H2c1／高级编排入口 H2c2）。
读者：框架维护者、Agent应用开发者、适配器作者与企业部署团队。
除明确标为 H1a–H1f、dev31 Local stateless H2a 、dev32 同库原生／顺序 Session H2b1 与 dev33 Temporal 原生／顺序入口 H2c1 、dev34 高级编排入口 H2c2 与 dev35 同库复合会话 H2b2、dev36 授权根 namespace H2b3 与 dev38 远程原生／顺序 H2b4a 与 dev39 远程复合根 H2b4b 的子集外，本文中的接口和示例仍为目标设计。AgentHarness 当前固定声明并复用 Local 权威，dev40–42 已实现原生／顺序 Local 的规则记忆、受管理历史摘要和模型选择记忆；dev43 增加版本化 Local 推荐组合、确定性引用压缩和产物投影；dev44 已接通 Local 高级编排与 Temporal 自动历史压缩／大结果卸载，分别保留原 Run 节点投影与 History 阶段证据。dev46 已接通 Temporal 自动记忆与五类绑定；dev47 增加显式语义知识、相关候选排序及 Plan／Team 推荐组合，语义引用质量及完整 H3 仍待验收。
[绑定使用教程](../../docs/agent-bindings.md)与 [Local Agent API](../../docs/agent-api.md)记录实际支持与拒绝；dev32 同库原生／顺序 Session/Turn 子集已交付；dev33 Temporal 原生／顺序入口已交付；dev34 已注册高级入口已交付；dev35同库复合会话与dev36授权根namespace已交付；dev38–39 远程原生／顺序及复合根会话已交付；dev46 已交付 Temporal 五类绑定子集；其余角色／共享 Session 与完整 H2 尚未交付。
已交付范围始终以[实现状态](../../docs/implementation-status.md)为准。
历史文件名harness-runtime.md保留以保护已有审查/链接；目标组件名称统一为AgentHarness。

Dev45 已交付 Local 图／并行／Team／动态／嵌套实际 Agent 的受管理规则／模型字段选择记忆和推荐默认组合；原节点／子 Run 保留来源与额度，显式终态根 resume 只恢复已结束子 Run 的证据，不新增派发。dev45 时 Temporal 自动记忆尚未交付；dev46 已接通写入与五类绑定，完整 H3 质量仍待验收，见[高级记忆契约](../../docs/composite-memory-stages.md)。

Dev47 提供[显式语义知识、相关事实召回与 Plan／Team 起步组合](../../docs/h3-intelligent-combinations.md)，复用原受管理阶段和唯一执行权威；旧版本 1 Profile／ManagedDataContext 身份保持。词项相关排序只覆盖有界候选，完整 H3 质量尚未验收。

Dev48 新增[显式 HTTP 重排](../../docs/http-reranking.md)，沿既有 AsyncReranker／原知识权威完成来源前后校验及 owned 异步装配；不改变旧排序和默认组合。检索准备不是持久化模型 Action，不保证付费调用恰好一次或计费上限。

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

| 能力 | dev37 历史基线及注明版本的增量（当前见本文开头和实现清单） | 后续目标 |
| --- | --- | --- |
| DecisionPolicy | Harness/NativeHarness已实现 | 保留导入与行为，文档补充狭义定位 |
| 执行与恢复 | Local/Temporal明确子集、共享采纳规则 | 从Engine逐步抽纯规则与受管理阶段，共同conformance |
| 组件装配 | H1a与Local H1b六类绑定，覆盖原生/顺序/图/Team/Dynamic/嵌套、固定父子Release及Profile v2 | 补Temporal绑定、其他规范资源身份/环境角色；Local Session H1c已交付，不把Local H1b当完整H1 |
| 上下文/记忆/RAG | 多个端口/适配器与可选链路已有实现 | 组合为推荐受管理管线，补自动阶段与作用域路由 |
| Agent/Session应用API | H2a Local stateless Agent/Runtime、AgentRun/RunRef/WaitResult、托管／观察／可重试关闭；H2b1 原生／顺序及 H2b2 同库复合 Session/Turn、busy、固定绑定与 CAS rebind；H2c1 Temporal 原生／顺序共同入口与固定 RPC 派发／detach | H2c2 已接通已注册高级入口；补远程会话、续接、Temporal 绑定与完整共同验收；旧RunHandle DTO保留 |
| Workspace/Skill/Sandbox | Workspace读写、Skill目录与dev83受限Docker／原工具／Sandbox角色子集已验收 | 远端、持久共享工作区、Artifact传输及完整H4仍未交付 |
| Artifact绑定（dev84候选） | 第十四类独立角色，借用physical target／namespace，纯managed Context派生；Local／Temporal六组合SQLite/file恢复子集通过 | 独立进程崩溃／真实async取消／旧83 Worker拒绝／最终review／全量安装与制品待验收；remote／binary／GC／cache另交付 |
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

Dev49 [Query transform／语义 Facts 召回](../../docs/query-and-semantic-recall.md)沿原检索与记忆端口组合，确定性默认和语义有序上下文均可替换；来源与已接受的引用快照仍由原权威管理。语义召回限候选窗口，Temporal仅 Query Knowledge 端口；不增加持久向量／自由记忆修订或第三套运行状态机。


dev50 在 H3/R17 增加显式 ModelQueryTransform，以已配置 async Provider 形成无工具、有界查询提案；原数据端口校验来源，原 Local Run／Temporal Knowledge History 保存已接受上下文。它属于检索准备，不新增执行权威或独立耐久模型 Action；默认不开启，接受前可重复付费。Temporal Facts、自动查询策略和完整 H3 质量仍待实现。


dev51 补 H3/R16 的纯 HTML DocumentParser 与可安装摄取链路，原知识端口保存原始来源摘要、解析策略和分块回执；不增加后台抓取、网络请求或执行权威。

dev52 沿原纯 DocumentParser 增加 DOCX 正文与 ingest 模板，仍使用原知识权威和原子回执；不把解析器升级为 Harness 调度或连接器后台任务。

dev53 使用原 DocumentParser／知识权威接入可选文本 PDF，显式依赖与调用内资源配置不进入 Harness 纯决策；没有新增后台执行权威或隐藏模型 I/O。


dev54 通过现有 Counter／Chunker 组合可替换 TextTokenizer、可选本地装配 tiktoken、canonical 输出预留与 token 分块，保持字符默认、原知识原子回执和 Local/Temporal 权威。词表装配属于宿主 I/O，纯 Harness 计量不下载资产。详见[tokenizer 子集](../../docs/tokenization.md)，协议开销、质量和完整 H3 继续独立验收。
dev55 复用 ArtifactStore 引用与受管理阶段加入可选 FileArtifactStore：本地 POSIX 正文文件与有界 SQLite 回执，声明固定／owned 关闭及进程提交窗口恢复；不增加执行权威。详见[文件 Artifact](../../docs/file-artifacts.md)。GC、引用保留、S3／磁盘全局配额仍独立验收。

### dev56 派生事实索引

FactScanner 提供独立宿主扫描能力；包含过期记录不意味着赋给 Agent 历史事实权限。
IndexedMemoryStore 组合 source／embedding／vector／metadata，数据原记录始终为权威；独立 CAS Catalog 只保存派生构建证据，不新增 Run 调度。
接收 embedding、向量发布、页进度和完整 active 分阶段保存；召回走原 FactsView／validate_facts 和执行权威采纳。
SDK borrowed、工厂 owned；默认 SQLite/Hash 与显式 async Redis/Qdrant 接入保持原身份和生命周期约定。
新组合仅 Local Facts 范围；Temporal Facts binding、自动增量与真实语义质量继续按 H1/H3 逐项验收。
见[设计与限制](../../docs/fact-indexing.md)。

### dev57 PostgreSQL 来源与索引

复用Facts扫描契约、原事务／writer advisory锁与CAS Catalog；新增持久epoch表及有界named cursor。
PG来源／Catalog可以在SDK或已有async工厂中替换，保留owned/borrowed及Scope边界。只做数据能力补齐，不引入执行权威。
实际PG恢复和取消释放通过独立验证；Temporal绑定和索引自动维护另验收。

### dev58 Temporal Facts 读链路

沿原 temporal-3 增加显式 Facts 注册、每 Agent inherit/ref/disabled 和 host namespace allowlist。
有界 recall/planner、Knowledge/Facts 来源分类、snapshot采纳、原生资源固定与取消最终admission由原组件/History承担。
不添加执行权威，也不把事实写授权作为读范围；纯 RuntimeKernel 规则与 Activity I/O 分离。
[专项契约与验收](../../docs/temporal-facts.md)记录原生、顺序及高级实际Agent恢复；共享Session、Knowledge视图及其他角色继续后续门槛。


### dev59 Temporal Knowledge 范围与检索固定

KnowledgeBindingResource 使用原 catalog/Agent 路径选择；Scope、宿主 namespace allowlist、默认与显式选择在原 History 固定。
具体 namespace 写入 effective manifest，独立 Knowledge source evidence 经纯采纳边界校验；Facts 同时启用时保持来源分类。
原生检索组合（Lexical/Vector/Hybrid/Query）、实际 SQLite/PG 资源、方法、HTTP 客户端固定，旧 global/raw 发布保持。
知识来源 I/O 完成并复核后才请求 History dispatch admission；取消等待期间不启动新模型。
SDK borrowed 资源由宿主在 Worker 停止后关闭，不创建第三执行权威；[指南与验收](../../docs/temporal-knowledge-bindings.md)。
后续门槛仍含共享 Session／续接、其他绑定角色、自动 Temporal Profile、索引生命周期与语义质量。

### dev60 Temporal History Session／Turn

沿共同 Session DTO 增加原 Namespace UUID 资源、固定声明／发布／队列、耐久串行 Turn 与空闲 CAS；先全局登记命令再固定 Session，先接受原 Turn/RunID 再幂等启动。Session 协调 History 只保存交互与启动责任，原 Run/Parent History 独占业务审批／Action／预算。
根与已启动后代的原请求／发布／静默／未知效果／ACK 证据独立确认后保存完整 Conversation 并释放；普通与 managed Context 将其作为独立来源，不改变当前任务查询。RPC 冻结／托管与 detach 责任复用已有 Facade。见[实际子集](../../docs/temporal-sessions.md)。
History Conversation 是首个默认；外置 Session 数据、其余 binding、输入续接／FIFO、部署迁移／Continue-As-New 和完整 H2/H3 仍待交付。

### dev61 Temporal 每 Agent LimitsPolicy

沿 H1f 使用原公共纯提案端口；固定策略注册，原 Run History 在每实际 Agent 节点首次推进时采纳数值交集。Agent disabled 不移除宿主约束；Context／managed／model 使用 caps，工具批次整体准入。没有新调度器或状态权威。见[限制与恢复](../../docs/temporal-agent-limits.md)，其余角色和 H1–H5 保持目标状态。

### dev62 Temporal 纯 CompletionVerifier

复用公共同步纯完成规则和原 Agent／Action 链路。原 History 采纳回执对应的 verdict，accept 后记忆、retry 有界反馈、reject 失败；不增加状态权威。八类 Temporal 绑定现包含 verifier，模型验证和其余角色仍待实现。见[完成验证](../../docs/temporal-completion-verification.md)。

### dev63 Temporal DecisionPolicy

DecisionPolicy 复用公共纯 Harness prepare/propose。固定 host/ref/inherit 选择、identity及两个实际方法、原请求/响应/提案证据，原 History 校验并采纳；必需角色disabled拒绝。实际准备工具只能是原描述的无重复子集，mandatory Schema／权限／审批／限制保持。只支持编译器零参数super闭包及可验证Python基类方法，不允许直接类访问或其他opaque捕获。默认无额外策略的旧发布保持；源代码/解释器变更保留原Worker，不宣称跨版本指纹相等。九类绑定当前已包含decision_policy，外置Session、环境角色和完整H1/H2继续开放。见[指南](../../docs/temporal-decision-policy.md)。

### dev64 默认 Session 数据核验前置

内存/SQLite 增加精确 scoped message receipt，同步与异步端口共用结果契约；Local 独立数据复用原保存恢复，同库默认保持。完整 Temporal 外置数据责任见[目标规格](../specs/temporal-session-data-contract.md)，原 Run/Parent 承担数据完成门禁，Session Coordinator 保留占用/静默责任。规格与 SPI 不构成 Temporal 第十类绑定或完整 H1/H2/H3 交付。


### dev65 Temporal 固定 Session 数据读（依赖子集）

[有界读指南](../../docs/temporal-session-data-reads.md)接通 stateless 原生／顺序的 host 与每 Agent session inherit/ref/disabled、宿主 namespace、原始端口／客户端／物理资源固定。普通及 managed Context 将原 Scope、Run/node 私有地址、页、revision 和来源引用交给原 History 采纳；重放使用已接受证据。PostgreSQL 显式 initialize 固定解析后的 table schema。
这只是完整外置 Session 的读取依赖；不保存最终答案，不提供跨 Run Conversation。显式 History Session 与选中外置数据的高级组合（含嵌套模型 Planner）接受前拒绝。外置 CAS 写／原完成门禁、持久 SessionKey／跨 Turn 成员路径、Profile 组合与租约仍须按原目标交付。完整 H1/H2/H3/M1、R01–R26 和真实质量门槛继续开放。

### dev68 Temporal Context 读取责任（子集验收通过）

ContextExecutionOwner/Port 只托管实际 Task、明确桥接的线程和准确结束通知；原
Native History 独占许可、响应和结束事实及业务推进，原 Parent/Coordinator 复用静默
门禁。每 Agent 视图继承宿主拥有关系，数据／客户端仍 borrowed；关闭 Context
责任不代表模型、工具、产物写或整个 Worker 已静默。显式新协议为 binding2，旧
默认与 native save-v1 保持。真实进程退出后丢失结束通知仍需受信监督方确认并向原
UUID 提交准确证明。配置装配、自动监督与完整 H1/H2/H3 另验收，见[指南](../../docs/temporal-context-read-lifetime.md)。

### dev69 Temporal Profile 工厂与托管 Worker

显式 TemporalProfile Catalog 接入原组件工厂和十类 BindingCatalog 角色；BuildContext 无 Local Store。TemporalRuntimeAssembly 固定 Scope／版本／客户端／队列，只托管实际 Activity 与资源。原 Session／Context Owner 仍提交准确 end proof，原 History 唯一推进业务。SDK hosting Task 保持整个 Worker 生命周期；关闭或致命退出拒绝新入口，实际调用和通知排空后才释放工厂资源。高级宿主只可在执行前明确移交拥有关系。完整多版本路由、环境角色、集群容量与质量仍未交付，见[配置指南](../../docs/temporal-profiles.md)和[子集验收](../reviews/2026-10-11-temporal-profile-assembly.md)。

## dev70 Temporal 多版本 Host（子集验收通过）

沿 R04/H1/H5，TemporalProfileHost 只组合原 Assembly 与 Facade，不创建第三套业务状态。全 Catalog 固定和纯预检先于 I/O；原 Registry/Coordinator 队列需保留，默认选择不迁移旧 Run/Session。可信 Scope、实际 namespace UUID、原 Manifest 与版本均参与重连验证。所有版本实际调用、桥接线程和原结束通知排空后，才停止所有 Worker 并清理共享 owned ledger。借用 SDK Client 不清理。配置现在可声明既有 PostgreSQL EffectJournal；Local 与旧 dev69 拒绝该新声明。

见[指南](../../docs/temporal-profiles.md)及[验收](../reviews/2026-10-11-temporal-profile-host.md)。本子集最终全量／安装／兼容门槛通过；完整 R01–R26、其余环境角色、部署版本／迁移、容量／保留、企业身份及真实质量继续开放。

## dev71 Temporal 启动参数预检

沿原 Host 启动生命周期，在 namespace RPC、Client 和启动 Task 固定前校验普通参数；原 Engine 超时契约、实际 SDK 字段、基础标量和全部版本 build_id 统一拒绝。拒绝后可在原 Host 纠正重试，合法零值不改变 SDK 行为。复杂对象、插件和极端数值仍委托 SDK 构造；此增量不新增执行权威或全局容量。见[验收记录](../reviews/2026-10-11-temporal-startup-preflight.md)。

## dev72 CLI 工具子集

沿原 Toolkit/ToolSource 增加固定命令 JSON 工具、受管理进程／线程与 async owned 装配。PolicyGate、Action 和效果恢复仍由原 Engine/History 管理；普通进程不替代 Workspace/Sandbox 或 DelegatedRunner。详见[指南](../../docs/cli-tools.md)及[验收记录](../reviews/2026-10-11-cli-tools.md)。

## dev73 固定业务工具

Toolkit沿原ToolSource扩展HTTP固定POST，CLI补齐读取与纯规划示例；实际客户端／线程关闭不依赖等待者，Action效果仍由原权威管理。[工具指南](../../docs/http-tools.md)／[验收](../reviews/2026-10-11-fixed-business-tools.md)。

## dev74 MCP HTTP（子集验收通过）

Toolkit仅替换固定传输，MCPToolSource、PolicyGate和Local／History权威保持。实际Client关闭与未知效果证据独立；[指南](../../docs/mcp-http.md)／[验收](../reviews/2026-10-11-mcp-http.md)。完整环境绑定与H4仍待交付。

## dev75 只读Workspace（子集验收通过）

沿原工具接入可替换WorkspacePort／POSIX文件／内存默认实现，有界路径与可信Scope、实际线程／FD拥有和原结果恢复。[指南](../../docs/workspace.md)／[子集验收](../reviews/2026-10-11-workspace-read.md)通过；Agent.workspace角色、写入租约、Skills／Sandbox／Runner和完整H4仍开放。

## dev76候选：每Agent只读Workspace

借用原注册工具并固定完整Source／root／版本／额度，ref只收紧已授予工具，disabled移除Workspace工具，保留业务工具。Local原状态推进与Temporal原History共享纯选择，不增加环境客户端或第三执行权威。继承默认发布不增加记录；显式Temporal选择需要宿主注册Workspace资源并发布protocol1。[指南](../../docs/workspace.md)及[验收](../reviews/2026-10-11-workspace-bindings.md)保留后续写入／路径selector／Skills／Sandbox边界。

## dev77子集已验收：受管理Workspace写入

可替换WritePort、Memory／File默认与原生Source2，原Action审批／保留效果键／回执核验不变。单根文件租约保留到真实线程退出，CAS与原inode正文核验分别保护写前／写后窗口；Model策略和Binding仍只收紧原工具授权。[指南](../../docs/workspace-writes.md)／[子集验收](../reviews/2026-10-12-workspace-writes.md)。不是Sandbox或跨主机事务，完整H4/H5仍开放。
