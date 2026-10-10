# dev65 剩余能力与架构验收清单

版本：39；日期：2026-10-11；维护者：RALF maintainers。当前增量基线：1b02e72/dev64，dev65 验收见文末。
读者：框架维护者、应用开发者及适配器贡献者。基线：da55f97 的 dev30，
以及已提交1cad308的dev31–36与已提交1f27300的dev37配置／首用及已提交e6a6de7的dev38远程原生／顺序及已提交9fcbb84的dev39复合根会话与已提交7898b78的dev40自动规则记忆及已提交0d17976的dev41受管理上下文及已提交ec9b5f5的dev42模型选择记忆阶段及已提交e413ddc的dev44高级／Temporal数据上下文和已提交5528670的dev45 Local高级自动记忆，以及已提交 adbc328 的 dev46 Temporal自动记忆与五类Agent绑定。

## 1. 结论与判定方式

RALF 已有可运行的通用 SDK 预览：模型／工具循环、顺序与图编排、动态 DAG、
受管理多 Agent、远程数据适配及有限 Temporal 分布式执行。尚未完成的主链路是
完整每 Agent 能力绑定、统一 Agent／Session 入口、推荐智能数据组合和长期运行治理。
H1a–H1f、Local stateless H2a、同库原生／顺序 H2b1／复合会话 H2b2 和 Temporal 原生／顺序入口 H2c1／已注册高级编排入口 H2c2 已交付；完整 H1/H2 尚未完成，H3–H5 有可复用基础但未达到各自交付门槛。
完整 M1、AgentScope 目标业务链路对齐及企业正式可用均不能标为完成。

H1c 的[验收记录](../architecture/reviews/2026-10-08-session-capability-bindings.md)：
修复后 1998 passed／43 配置依赖跳过，安装包绑定契约 155 passed，
实际 Redis 1 passed／PostgreSQL 1 skipped。共享远程 Session 存储不提供跨独立执行权威租约。

H1d 的[验收记录](../architecture/reviews/2026-10-08-scoped-data-bindings.md)：
2055 passed／44 配置依赖跳过，安装包211 passed；Facts／Knowledge 宿主允许范围已交付。
[固定 DeepSeek 试验](live-model-quality-dev28.md)业务10/16、范围提取4/4。
六个修复任务未写入却回答 resolved。dev29 增加显式纯 CompletionVerifier、回执对应规则及耐久有界反馈；动态计划 PlanVerifier、受管理模型验证与完整质量门槛仍待验收。

dev29 H1e 增加[可替换完成验证](completion-verification.md)，[验收与审查记录](../architecture/reviews/2026-10-08-completion-verification.md)：最终2113 passed／44配置依赖跳过，实际安装包250 passed，dev28十类原审批兼容恢复。[固定 DeepSeek 试验](live-model-quality-dev29.md)八个业务任务单次全部通过，三个修复各发生一次审批写入。完整 AgentScope 对齐、重复质量基线和企业验收仍未完成。

dev30 H1f 增加[每 Agent 执行限制](agent-limits.md)：静态决策／上下文／工具动作 caps、不可移除的宿主约束、固定发布与有界批次采纳；并行投影、模型 Planner 和嵌套子 Run 保持父级已接受的成员上限。[验收记录](../architecture/reviews/2026-10-08-agent-limits.md)：2183 passed／44配置依赖跳过，实际安装包320 passed，dev29十三类原审批兼容恢复。分布式容量、真实费用和长期治理仍待交付。

dev31 H2a 增加 [Local Agent API](agent-api.md)：固定声明、独立执行托管、纯观察等待、嵌套原根控制与可重试 owned/borrowed 关闭。十类实际旧 wheel 审批兼容恢复已验证；完整 H2b 会话／Turn、Temporal Facade 和 H3 自动阶段继续待交付，见[实施审查](../architecture/reviews/2026-10-09-local-agent-facade.md)。

dev32 H2b1 增加[同库原生／顺序 Sessions](session-api.md)：持久身份、Turn 顺序与占用、原绑定固定、稳定 busy/mismatch 回执和 idle CAS rebind。最终2280 passed／44配置依赖跳过、实际安装包159 passed；九类 schema1 审批双向旧新 wheel 恢复及 schema2 旧代码拒绝／新代码单次效果恢复通过，见[验收与取舍](../architecture/reviews/2026-10-09-local-session-turns.md)。远程／复合会话和完整 H2b 仍未完成。

dev33 H2c1 增加[Temporal 原生／顺序 Agent 入口](temporal-agent-api.md)：共同 DTO／异步重连、RPC 固定组件派发、真实时间的已有快照超时和 detach 关闭。实际持久 Service／Worker 的三项审批／重连／观察取消／History 重放探针通过；该 dev33 边界在 dev34 扩展，Temporal 绑定／共享会话和完整 H2 继续待交付。

dev34 H2c2 接通已注册 Graph／Team／Dynamic／嵌套 Agent 入口；通过原父子命令／发布身份验证读取实际子 Run 控制，有界固定派发观察保留客户端取消和 detach。Temporal 绑定、远程／复合会话与完整 H2 继续待交付。

dev35 H2b2 接通同库 Graph／并行／Team／动态 Plan/DAG／嵌套 Session Turns：固定成员绑定、原子最终保存、真实子处理器／未知效果／缺失结果占用、idle CAS 跨种类 rebind。成功接受启用 schema3，dev34 在派发前拒绝；详见[验收与取舍](../architecture/reviews/2026-10-09-local-composite-session-turns.md)。远程共享会话、复合根 namespace、Temporal 绑定和完整 H2 待交付。

dev36 H2b3 增加宿主授权的同库复合根 namespace、独立根资源、原绑定派发校验和 schema4 兼容门槛。Profile 专用声明、远程共享会话、Temporal 绑定及完整 H2 尚待交付。见[验收记录](../architecture/reviews/2026-10-09-composite-conversation-namespaces.md)。

dev37 补齐授权根会话的 JSON/TOML Profile 声明及 sync/async Runtime 装配，提供可安装 sessions starter 与原 Profile/Turn 重连；远程会话及 Temporal 绑定仍待交付。

本清单对照[总架构](../architecture/design.md)、[通用能力清单](../architecture/viewpoints/framework-capabilities.md)、
[AgentHarness H1–H5](../architecture/viewpoints/harness-runtime.md)、
[建设顺序](agentscope-alignment.md)和[当前实现](implementation-status.md)，并核对 SDK 源码。
它汇总剩余工作，不新增执行架构，也不替代各项能力的版本化规格。

**子集已交付**表示有运行实现但目标范围未覆盖；**未交付**表示目标公共能力／
默认链路尚不存在；**验收未完成**表示有实现或试验，仍缺最终配置、故障、升级、
质量或独立采用证据。同一层可以同时具有这三种状态。
不按端口、模块、适配器或测试数量换算完成百分比。

以下能力已经实现，不能再次列为从零建设项：Redis／PG Session/Facts、
PG Knowledge/Inbox/Outbox、Qdrant、HTTP Embedding、Hybrid/RRF／基础重排、
文本摄取、动态 DAG／嵌套／团队、Redis Streams、A2A 轮询、Temporal 声明子集、
显式记忆提炼／受管理模型摘要／Temporal 纯自定义上下文、持久 Run 事件订阅。
已有实现只覆盖各自声明的范围。

## 2. 分层剩余清单

### 组合、入口、模型与编排

| ID／层 | dev65 已交付基础 | 尚未完成的具体能力 | 阶段／状态 |
| --- | --- | --- | --- |
| R01 每 Agent 绑定 | Local 原生 Agent／顺序／Graph／Team／Dynamic／嵌套成员六类选择：provider、decision_policy、context、facts、knowledge、tool_set；稳定路径、固定父子发布与 Profile v2；Session 后端／允许的 namespace／同权威实际地址占用；Facts／Knowledge 宿主范围视图与来源校验；纯完成 verifier 的 inherit/ref/disabled；宿主与 Agent limits 的固定交集与动作额度；原生／顺序及高级 stage_policy 写目标；Temporal 九类版本化 provider/context/knowledge/tool_set/stage_policy/facts/limits/verifier/decision_policy；session 有 stateless 原生／顺序的固定有界读子集，与 Facts／Knowledge 宿主 namespace selector、原始检索资源固定及原有子 Run 子树 | Temporal session 外置写／持久路由及其余环境绑定角色；其他资源身份／selector／作用域视图；artifacts／workspace／sandbox／skills 绑定与准入；stage_policy 已支持 Local 原生／顺序／图／Team／动态／嵌套规则／模型选择记忆；上下文历史摘要与引用／产物组合已交付，其他阶段／组合仍待交付。前四类角色显式选择仍被拒绝 | H1：子集已交付 |
| R02 Agent／Session 入口 | H2a Local stateless Agent/Runtime/AgentRun、RunRef/WaitResult；独立任务托管、纯观察等待、原根流程控制路由、owned/borrowed 关闭与 CloseIncomplete 重试、显式重连；保留旧 RunHandle DTO；H2b1 同库原生／顺序及 H2b2 图／团队／动态／嵌套及 H2b3 授权根 namespace、H2b4a 远程原生／顺序及 H2b4b 复合根保存意图／准确回执／终态只查询恢复、异步 Profile 配置，SessionKey／路由／Turn／busy／CAS rebind；H2c1 Temporal 原生／顺序共同入口、异步重连、固定 RPC 组件与客户端 detach；H2c2 已注册 Graph／Team／Dynamic／嵌套入口与实际子 Run 控制；H2c3 Temporal History Session／原 Namespace UUID／耐久 Turn／busy／启动意图／空闲 CAS，普通与 managed Conversation 及原后代静默证据 | 跨权威会话租约、输入续接／业务 deadline、Temporal 其他绑定角色／外置 Session 数据、移交与耐久 FIFO | H2a／H2b1／H2b2／H2b3／H2b4a／H2b4b／H2c1／H2c2／H2c3：子集已交付；完整 H2 未交付 |
| R03 Harness 与公共规则 | 纯 Harness/NativeHarness、ToolExecutor、共享决策／证据规则、Workflow Compiler/Interpreter、固定声明的 AgentHarness 组合入口；Local 原生／顺序及高级实际 Agent、Temporal 的规则／模型选择记忆、历史摘要和数据上下文，独立来源／提案／意图／回执与 Run 额度 | 其余广义 Harness 受管理阶段及默认组合；逐步提取 RuntimeKernel 纯规则；Prepare/Verify/Memory 等阶段的身份、证据、取消和恢复协议。保持 Local/Temporal 各自唯一执行权威 | H1–H3：部分抽象已实现 |
| R04 配置与装配 | 版本 Profile/Catalog、JSON/TOML、注册工厂、sync/async 装配、owned 清理、历史配置路由 | 完整绑定／推荐组合配置；CLI/ProfiledEngine 异步工厂路由；插件显式安装／激活／兼容检查；配置／组件迁移、旧代码归档、部署版本管理；配置来源／监听按需分期 | H1／H5：子集已交付 |
| R05 模型适配 | Chat Completions、DeepSeek 非思考、Anthropic 文本／工具、Gemini 文本、stateless Responses/JSON/完整 SSE | Gemini 函数调用、Responses 续接及受限字段；能力／用量／错误／超时／重试一致性；路由/fallback/负载策略及效果不重复契约；国内外及本地模型真实兼容矩阵。兼容 URL 不证明每个模型支持同一能力 | A1／H5：协议子集已交付，线上验收未完成 |
| R06 多模态／实时 | 当前 Provider 链路为文本 | 图片／音频／视频媒体类型、来源／访问／限额及逐适配器验收；Realtime/TTS/高级压缩后置，不作为当前 v1 目标业务链路先决条件 | 能力未交付；高级实时后置 |
| R07 Agent 能力包 | 原生循环、可定制 AgentSpec、规划／团队／RAG starter、dev47 显式 semantic-knowledge／memory-recall／Plan／Team 默认组合 | 更完整 Search／业务 Plan／Team 与 Coding 能力包；默认 verifier／上下文／工具、替换示例、诊断及业务验收。Coding 依赖环境／Runner | H3／H4：组件有基础，完整默认组合未交付 |
| R08 静态 Workflow | 顺序、串行／有界并行 Graph、条件／映射、Agent/Transform/Tool 节点及嵌套 | 通用受管理异步自定义节点；HumanInput/Retrieve/Planner/Verifier 节点族；受限循环；first-success/quorum/reducer 合并和类型化工作流状态。复用审批、预算与恢复 | G1/G2／H5：子集已交付 |
| R09 流式 Workflow | 模型完整 SSE 收集、耐久 Run 事件游标 | 逐记录 StreamChannel/Source/Operator/Sink、背压、关闭／失败传播、检查点／重放和 Sink 效果身份。事件订阅和模型 delta 展示均不等于节点数据流 | G5：未交付 |
| R10 动态规划／验证 | Rule/Model Planner、Plan/Revision、动态 DAG/CAS 修订、受限 execute/verify/replan；CompleteVerifier 取最后结果；Local Agent 纯 CompletionVerifier 与持久回执／有界重试 | 受管理 async/model Verifier、计划级业务 oracle／停止条件；needs_input/send_input 续接；完整重复规划、依赖、参数、拒绝与停止实测。Schema 合法不等于业务计划正确 | H2／H3／A4：子集已交付，质量未验收 |
| R11 多 Agent | Sequential/Router/Supervisor、子 Run、隔离 Session、递归预算／取消和恢复；Local 成员及嵌套十类独立绑定与 Temporal 九类绑定与节点回执完成验证 | 其余角色及 Temporal 其他成员绑定；类型化交接／受控共享状态／reducer；按需 Debate/Critic 策略；跨权威关联、停止和未知远端效果；全局容量及团队质量验收。普通消息不能作为成功回执 | H1／H4／H5：基础团队已交付 |

### 工具、上下文、记忆与知识

| ID／层 | dev65 已交付基础 | 尚未完成的具体能力 | 阶段／状态 |
| --- | --- | --- | --- |
| R12 工具接入／工具包 | typed Python/Schema/默认参数、ToolRegistry、async ToolSource、MCP stdio、A2A ToolSource、授权／审批／核验 | MCP HTTP/持续 Session/OAuth；固定 executable/argv 的 CLI Runner；通用受控 HTTP 工具适配；搜索／文件／浏览器工具包与发现；有状态工具租约和停止证据 | H4：子集已交付 |
| R13 Workspace/Skills/Sandbox/Runner | 可信 Python、MCP 受管理进程生命周期；Runner 目标契约 | Workspace／文件权限／资源租约；Skills 生命周期／能力注册／来源；容器／远端 Sandbox 文件、网络、进程和资源隔离；Coding Runner、Codex 首个适配及各外部 Runner 验收。普通子进程不是安全沙箱 | H4：目标能力未交付 |
| R14 上下文 | ContextBuilder/Counter/Budgeter/Summarizer、完整工具组／近期召回／摘录、实际快照；显式独立模型摘要；Temporal 纯自定义 Context；Local 原生／顺序及高级编排受管理规则／模型摘要与引用摘录／产物投影；Temporal History 受管理摘要／Knowledge 摘录／产物阶段；最新完成反馈及其后工具证据原子保留 | dev54 可替换 TextTokenizer／字节默认／可选 tiktoken／canonical 输出预留已交付；模型协议完整计量、实际模型词表与长上下文验收；Session／RAG 语义压缩和质量；覆盖／来源失效策略和辅助失败恢复；不同模型长上下文事实保留实测。UTF-8 token 估算不是精确用量 | H3：确定性与显式路径已交付 |
| R15 短期／长期记忆 | memory/SQLite/Redis/PG 的 sync/async、CAS/去重/TTL/分页/来源；opt-in MemoryPipeline 规则／模型字段选择；原生／顺序及高级实际 Agent 的受管理规则／模型字段选择阶段、原节点／子 Run 证据恢复与 JSON／TOML 默认工厂；Temporal History 自动规则／模型选择、准确CAS核验与根子证据恢复；dev47 有界候选词项相关排序；dev49 有界原生候选语义排序／任务查询与有序上下文组合；dev56 memory/SQLite/Redis、dev57 PostgreSQL 全库扫描、可替换 CAS Catalog、分阶段索引／激活与权威召回；dev58 Temporal有界Facts绑定／namespace／纯planner／原Context采纳 | PostgreSQL/Qdrant等远端联合索引组合验收；自动增量／修复／删除传播；自由合成；语义冲突／修订／撤回／遗忘／可信度策略和多事实原子采纳；最终 Session append 大历史效率；导出／迁移／保留；真实记忆利用。追加来源观察不是自主信念修订 | H3／H5：存储和显式提炼已交付 |
| R16 摄取／知识生命周期 | text/Markdown Parser；dev51 HTML／dev52 DOCX 正文／dev53 可选文本 PDF Parser 与摄取模板；字符／段落与 dev54 可替换 token Chunker；memory/SQLite/PG 原子文档／块／词项／回执 | PDF OCR／布局与兼容语料、其他 Office、网页／业务连接器及游标／增量；语义分块及模型词表兼容；来源目录／ACL；后台索引、修复、删除传播和版本重建。knowledge_committed 不代表向量就绪 | H3／H5：基础已交付 |
| R17 检索／Embedding／向量／重排 | HTTP Embedding、Hash 基线、本地 cosine/Qdrant、词法／向量／Hybrid、RRF/保序/词项重排、来源回读、dev47 显式 HTTP 语义组合、dev48 HTTP 语义重排适配；dev49 替换式查询改写及默认字面 aliases；dev50 显式模型改写适配 | 可选本地语义模型；自动查询策略；pgvector 参考适配及其他库逐项验收；索引发布／修复／迁移；端到端召回、答案和引用质量。Hash/TokenOverlap 不证明语义质量 | H3／G4：显式语义组合已交付，质量未闭环 |
| R18 Artifact／缓存 | Scope 隔离 memory/SQLite／dev55 POSIX 文件 JSON 产物、摘要／TTL／读取限额／事务容量；Local 原生／顺序及高级编排、Temporal 上下文自动卸载／预览与独立意图／回执 | S3 等远端 Artifact；引用保留／孤儿 GC／全局磁盘限额及恢复依赖；CacheStore/Policy 的键、版本和失效。默认关闭缓存合法；语义答案缓存后置 | H3／H5：显式产物已交付，缓存未交付 |

### 执行、通信、服务与验收

| ID／层 | dev65 已交付基础 | 尚未完成的具体能力 | 阶段／状态 |
| --- | --- | --- | --- |
| R19 执行模式／后端一致性 | Local 单 Coordinator/SQLite；Temporal 独立 History，原生 Agent/sequence 与显式发布的 Agent-node Graph/Team/Dynamic/嵌套、RAG；scoped Facts/Knowledge 与 opt-in History Sessions | 单 Coordinator 多 Process Worker；Temporal 其余环境绑定角色／selector、完整外置 Session 读写／持久地址、其他受管理 Harness 阶段及直接 Tool/Transform 图节点等组合；共同能力／故障／升级门禁；Continue-As-New、部署版本及长期容量。PG Facts/Knowledge 不等于 PG ExecutionStore/分布式调度 | H5／C1：分布式子集已交付 |
| R20 MQ／A2A | memory/SQLite/Redis Streams、Inbox/Outbox、PG 共享回执；A2A JSON-RPC0.3 文本/数据 polling、async controls | 保留／压缩／积压／重投递与 failover 认证；额外 Broker 按需；A2A SSE/push/files/Task continuation 及真实停止约定。ack 不等于效果确认，不承诺跨系统全局恰好一次 | H4／H5：子集已交付 |
| R21 控制／审批／预算／容量 | 幂等命令与 DAG patch、local policy、固定动作、unknown holds／父子额度；每 Agent 固定决策／上下文／工具Action caps；Temporal timer/审批期限 | Local deadline／审批过期、输入／鉴权续接；not-executed/in-progress 核验证据；业务资源别名规范化；真实费用／共享账户；独立并发／工作区额度／背压，真实调用未退出仍占容量 | H2／H5：基础已交付 |
| R22 事件／展示／观察 | 耐久 Run 事件／游标／分页、pull 订阅、SSE 编码、只读 CLI、opt-in middleware | 托管 HTTP/SSE/WebSocket；类型化 Agent/model delta、结束／取消／重连；OTel trace/metrics、跨 Run/远端关联、审计／脱敏／保留。展示 hook 不得丢失业务证据 | H2／H5／B2：观察基础已交付 |
| R23 Service／交互／作业 | packaged 本地 HTTP/A2A service、owned shutdown、remote CLI、二十一种 wheel starter | 统一 Agent Service/sessions/资源库、默认托管／共享池、TUI/Web 基础控制台；渠道／定时／后台／唤醒／索引；审批／核验／恢复管理。现有模板不是完整应用平台 | H5／B1/B2：有限服务已交付 |
| R24 企业身份／运维 | 宿主 Scope、本地授权、版本固定和部分容量保护 | OIDC/企业 actor、资源 ACL/SourceCatalog、凭据代理、工作区配额；保留／迁移／备份／恢复、升级回滚、健康／HA/故障演练、自部署文档和控制面。Scope 字段不是认证体系 | H5／C2：企业目标未交付 |
| R25 扩展验收／首用 | SDK/API/教程/恢复/发布/贡献文档、适配测试、wheel starter 和旧新兼容证据 | 外部作者可复用的按角色 AdapterContractSuite；完整声明→默认→替换→生命周期→错误→恢复示例；独立开发者换模型/库/工具/节点；性能／升级矩阵、稳定 API 弃用策略。公开 PyPI/Release／社区采用本轮未核验 | 横向验收：部分已交付 |
| R26 真实质量／M1／比较 | 冻结 20 案例规划、八案例业务执行器；dev21 真实小试验；独立 response/receipt 窗口和 Worker 故障证据 | 完整最终配置重复业务／规划／记忆／RAG 引用任务；M1 20 类原型完整 fixture/评分器；成组窗口／Temporal 契约报告；独立首次采用；同模型/工具/服务的 AgentScope/LangGraph 实现与成绩 | A4／M1／D：验收未完成 |

每层的完成条件都是：公共契约、最小默认、另一实现替换、配置／注入、身份／错误／
生命周期、安装包场景和必要的真实证据。缺少必需能力应在准入前拒绝。
维护经过验收的组合矩阵，无需先实现所有数据库与全部角色的笛卡尔积。

## 3. 沿既有架构继续的顺序

~~~mermaid
flowchart LR
    H1a[H1a 已交付] --> H1b[Local H1b 已交付]
    H1b --> H1c[Local Session H1c 已交付]
    H1c --> H1d[Local 数据范围 H1d 已交付]
    H1d --> H1e[Local 纯完成验证 H1e 及执行限制 H1f 已交付]
    H1e --> H1f[Local 执行限制 H1f 已交付]
    H1f --> H2a[H2a Local stateless 入口已交付]
    H1f --> H1[H1 剩余绑定与资源身份]
    H2a --> H2b1[H2b1 同库会话已交付]
    H2b1 --> H2c1[H2c1 Temporal 原生入口已交付]
    H2c1 --> H2c2[H2c2 已注册高级 Temporal 入口]
    H2c2 --> H2b2[H2b2 同库复合会话已交付]
    H2b2 --> H2b3[H2b3 授权根 namespace 已交付]
    H2b3 --> H2[H2 剩余会话与绑定]
    H1 --> H2
    H2 --> H3[H3 推荐智能数据链路]
    H3 --> H4[H4 环境与协作]
    H4 --> H5[H5 后端与服务治理]
    Q[真实质量与共同案例] -.贯穿.-> H1
    Q -.贯穿.-> H3
    Q -.贯穿.-> H5
~~~

1. **H1/H2 闭环组合与入口。** R01–R04，以及 R10/R21/R22 的续接与等待。
   H2a 已有 Local stateless 入口与独立托管，H2b1 已有同库原生／顺序 Session／Turn 占用及稳定绑定，H2c1 已有 Temporal 原生／顺序共同入口，H2c2 已接通已注册高级编排、H2b2 已接通同库复合会话；继续完成跨权威会话与 Temporal 其余绑定角色。
   旧审批、原发布恢复及 caller/HTTP 断连共同验收；H2b 首期忙碌拒绝，耐久 FIFO 后续 opt-in。
2. **H3 做三个可安装、可替换的参考组合。** Local Basic、Local Knowledge、Managed Memory；
   补 R07/R14–R18 的受管理阶段、自动卸载、语义可选组件和明确失败降级。
   复用已有摘要／提炼，不能在纯 Context/Harness 方法隐藏模型 I/O。
3. **H4 补环境与工具。** R11–R13/R20 的 Workspace、Skills、Sandbox、CLI/MCP HTTP、
   Coding/Runner 和协作，验收隔离、真实停止、租约、交接及未知效果。
4. **H5 做长运行和正式部署。** R19–R25 的多进程、Temporal 扩展、容量、保留、
   服务流式、身份、迁移／备份与恢复管理。R09 流式 Workflow 独立交付，UI 流式不替代它。
5. **真实质量贯穿；比较另行形成结论。** R26 固定最终配置与完整任务，报告业务、规划、
   引用、记忆及外部采用；对等实验不由功能数量推导优越性。

这些是分期依赖，不是一次重写计划。保留原 AgentSpec/Profile/Release/command 身份，
由各自执行权威采纳受管理阶段；新增 Facade 不创建第三套 Run 状态机。

## 4. 实现与证据的区别

既有真实 Redis/PG/Qdrant、Temporal Worker/History 故障证据已经记录，
远端版本矩阵、长期负载、failover、完整组合和运行治理仍需分别验收。
受支持版本以[远程数据](remote-data.md)及历史记录为准，不将既有测试重复列为从未执行。

[dev21 真实模型试验](live-model-quality.md)保留 38 次调用：原业务配置 0/8、
选定规划 3/6、摘要与来源字段选择各 3/3、修订指令子集 3/4、JSON 缺失输入子集 3/3。
它们使用不同阶段配置，不能拼成最终配置 8/8，也不证明通用摘要、事实真值或跨框架优越性。

[M1 协议](m1-acceptance.md)仍缺完整真实任务、独立接收窗口成组报告、Temporal
契约映射及外部采用。单项故障回归已有通过证据；缺成组重复／升级／采用报告时，
标为验收未完成。当前没有对等 AgentScope/LangGraph 的成绩。

dev25 审计时，127 个 SDK 模块与已测试快照一致；历史回归为 **1902 passed、42 skipped**，安装包契约测试为 **60 passed**，见[H1a 记录](../architecture/reviews/2026-10-08-agent-capability-bindings.md)。
dev26 已实现 Local 高级编排绑定；修复后完整回归 **1959 passed、42 skipped**，安装包契约 **117 passed**，原生／H1a 实际旧 wheel 升级及新复合发布降级拒绝已验证。验证与独立审查见[H1b 记录](../architecture/reviews/2026-10-08-composite-agent-bindings.md)。未调用真实模型或发布远端。
skipped 不计为通过，测试数不替代剩余功能和验收。

## 5. 范围与维护

v1 目标业务链路包含 SDK/CLI/API/基础控制台、General/RAG/Plan/Coding、
三种执行模式及企业私有部署。持续公网群聊、拖拽编排、公共插件市场、
运行中热迁移、语义答案缓存和高级 Realtime/TTS 等按原设计后置。
配置监听、额外 Broker/向量库及团队策略按需扩展，不用适配器数量定义成熟度。

后续更新对应 ID 的实际范围和证据，并同步实现状态；保留 dev9/dev20 历史基线，
明确其日期。完成子集不表示整层完成，只有目标范围和验收均满足才关闭该项。

### dev34 H2c2 verification

Registered advanced Temporal entry is delivered; full H2 remains open. Final
2352passed56skipped,231 installed contracts and12+12 actual Service/Worker probes
pass. Actual dev33 old/current7 histories and Local schema1/schema2 wheel recovery
retain original evidence. [Review/rulings](../architecture/reviews/2026-10-09-temporal-composite-agent-facade.md) records the pruning/import/bookkeeping fixes; old marker-less histories retain their original evidence rules.


### dev35 H2b2 verification

Final2393 passed/56 explicit service/optional skips; outside-checkout wheel259 passed.
Actual dev34↔dev35 native/sequence schema1/schema2 approval recovery passes4 cases
each direction; six composite schema3 cases preserve Turns/receipts/manifests and
one effect per Action. Old read-only/writable SDKs refuse3 before dispatch. A real
COMMIT failure and failed rollback were independently reproduced and fixed in one
RED→GREEN pass. [Review/evidence and all rulings](../architecture/reviews/2026-10-09-local-composite-session-turns.md)
records installed/package gates and remaining full H2/H3 scope.

### dev36 H2b3 verification

Authorized colocated composite root namespaces are delivered through SDK/factory
assembly; dedicated Profile declaration, remote Sessions and full H2 remain open.
Independent Run admission evidence also protects configured None selection while
genuine legacy Turns retain their original behavior in mixed schema4 databases.
[Review/evidence and all rulings](../architecture/reviews/2026-10-09-composite-conversation-namespaces.md)
records original approval/recovery, actual old/new wheels and final gates.


dev38 H2b4a 接通 Redis／PostgreSQL 原生 Agent／顺序 Workflow 持久 Turn；
Scope 内保守地址准入、schema5 原子激活、独立原绑定证据、保存意图和准确
回执支持丢失响应及终态只查询恢复。远程数据与 Local 执行权威保持分离，
没有跨库原子性、跨权威共享会话或真实模型质量的新验收结论。


dev39 H2b4b 已接通 Local 远程复合根会话及 JSON／TOML 异步装配；保存
未知时直接恢复已采纳结果，保持原唯一执行权威与成员绑定。schema6 前向
激活、元数据缺失拒绝、审批重启单次效果及终态只查询纳入验收。完整 H2
仍缺跨权威共享租约、Temporal 绑定／Session、FIFO／续接／deadline，
H3 自动阶段、默认智能组合及企业治理继续沿原清单推进。


dev40 H3a 首期接通 Local 原生／顺序自动规则记忆；每 Agent 可继承、选择、关闭
宿主写目标。来源是已验证结果观察，提案／预算／意图／回执由原 Run 权威保存；
丢失确认和终态只查询恢复不重复模型、业务工具或已确认事实。新阶段使用 schema7；
默认关闭且旧发布身份保留。Graph／Team／动态／嵌套／Temporal 阶段、模型自动
选择、ContextPipeline 和默认智能组合仍按原清单推进。见[接入与边界](managed-memory-stages.md)。


dev41 H3b1 接通原生／顺序同 Run 完整遗漏历史组的受管理规则／模型摘要；
每 Agent 复用 context 绑定与 JSON／TOML managed-summary 工厂。原 Engine 保存
来源／意图／响应／快照与独立预算证据，未知调用保留额度且不重试，
终态恢复不发起模型调用。新能力原子启用 schema8，默认身份与旧 schema 保持。
Session／RAG 自动摘要、产物卸载、Graph／Team／动态／嵌套／Temporal 阶段、
模型提炼、默认智能组合和真实质量门槛仍未完成。见[使用与边界](managed-context-stages.md)。


dev42 H3a2 接通 Local 原生／顺序的自动模型字段选择，复用已有 stage_policy
与 sourced-memory(-async) JSON／TOML 工厂。原 Run 保存选择请求／响应／字段和
独立预算，未确认调用不重试、非法输出不写事实；已完成结果值由宿主取回。
新语义9原子准入，默认与schema1–8保持。自由合成、语义修订、Session／RAG
压缩、产物卸载、推荐默认组合、高级／Temporal阶段与完整H3仍待交付。
见[接入与边界](managed-model-memory-stages.md)。

### dev43 H3 recommended combinations

[推荐组合与恢复](recommended-harness.md)交付版本化 Local Basic／Local Knowledge／Managed Memory、确定性引用压缩与原 Run 大结果产物投影。Schema10 opt-in；仅原生／顺序 Local。执行日志保留完整效果证据，不声称减少总存储、语义质量或完成 H3。高级／Temporal 自动阶段、远程产物／GC 继续待交付。

[dev43 架构审查与实际恢复证据](../architecture/reviews/2026-10-10-h3-default-data-context.md)记录三项独立审查修复、四个进程退出窗口和 dev42↔dev43 的 Schema1/8/9 实际审批恢复。

最终 dev43：2773 passed／66 skipped；Ruff、格式和 Git 空白检查通过。最终 wheel 安装后150契约测试；实际四个进程退出恢复窗口、Schema1/8/9 双向旧新 wheel 审批及三个推荐组合的双 Turn／重启通过。未调用真实模型，完整 H3／M1 质量验收仍待完成。

### dev44 H3 高级与 Temporal 数据上下文

[高级编排与 Temporal 指南](composite-temporal-context.md)：Local 图／并行／Team／动态／嵌套 Agent 复用原协议，Schema11 opt-in；并行节点证据与摘要预算隔离。Temporal 显式 temporal-2 注册，以原 History 分阶段持久计划、产物读／写派发／核验、摘要回执与快照采纳；默认 temporal-1 身份与分支保持。写／摘要单次派发，未知保留额度和远程不确定性。

准备完成后的外部模型／摘要／产物写由原 History 原子准入；取消先接受时拒绝新派发。产物写超时的不确定性不会被后续成功工具清除；并行根 Action 存在而 execution 投影丢失时明确拒绝恢复／查询。

Basic／Knowledge 数据上下文已扩展；高级／Temporal 自动记忆写入、每 Agent Temporal 绑定、语义引用压缩、远程产物默认适配／GC、真实质量与完整 H3 仍未完成。卸载不减少原库／History 体积。

最终 dev44：2809 passed／72 skipped；真实 Temporal 7 passed（五类 Worker 恢复、读取期间取消、原纯上下文与父子 History replay）；安装后 93 契约、六项推荐组合高级入口、dev43↔44 六项审批恢复及旧版 Schema11 拒绝通过。Ruff／格式／空白检查通过。此轮未调用真实模型。[验收记录](../architecture/reviews/2026-10-10-h3-composite-temporal-context.md)

### dev45 H3 Local 高级自动记忆

[高级记忆与恢复](composite-memory-stages.md)：原规则／模型字段选择支持 Local 图／并行／Team／动态 flat/DAG／嵌套实际 Agent；Schema12 原子准入，原生／顺序 Schema7/9 与策略类保持。并行事实固定 workflow_node、额度与记录留在原 Run；每成员可选择宿主授权写目标。推荐 managed-memory 已验证同步／异步装配和统一入口重连。

纯观察不做恢复；显式终态根 resume 通过原有子 Run 锁恢复已结束 Agent／嵌套子 Run 证据，再结算父额度，不新增模型或 CAS。未知且不可证明的事实继续保留。Temporal 自动记忆写入、自由合成／语义修订、真实质量与完整 H3 未完成。

最终 dev45：2877 passed／72 skipped；安装后 186 契约通过，24 个进程退出窗口、dev44↔45 十项实际审批恢复、旧版 Schema12 拒绝与原 Policy 类不变通过。独立审查无阻塞问题；Ruff／格式／空白检查和 wheel／sdist 构建通过。[验收记录](../architecture/reviews/2026-10-10-composite-memory-stages.md)

### dev46 Temporal 自动记忆与每 Agent 绑定

[Temporal 指南](temporal-memory-bindings.md)：temporal-3 发布复用 AgentDefinition／BoundDefinition 与 scoped catalog；provider／context／knowledge／tool_set／stage_policy 五类选择沿原声明子树进入各实际 Agent。History 分阶段保存来源、选择响应、字段采纳、CAS 与核验，选择／写只有一次尝试。显式根 drive 通过原有子 Run 控制恢复未知事实；无法证明的效果／远程停止继续持有父额度。

旧 temporal-1／2 发布保持；未支持角色／selector、共享 Session、语义修订／遗忘、真实模型质量和完整 H3 仍待完成。

最终 dev46：2919 passed／92 skipped；真实 localhost Temporal 26 passed，安装后 151 契约通过；旧协议六项双向审批 JSON 快照恢复、原 manifest 相等与旧 wheel 拒绝 temporal-3 通过。独立 review 三项 Important 由七项 RED→GREEN 测试修复，无待办 Minor。Ruff／格式／空白检查与 wheel／sdist 构建通过。未调用真实模型，完整 H3／M1 继续待验收。[证据与决策](../architecture/reviews/2026-10-10-temporal-memory-bindings.md)

### dev47 H3 智能数据与编排起步组合

新增显式 HTTP 语义知识组合、相关事实／完整近期 Session 选择，以及使用原 Spec／AgentHarness 的 Plan／Team 默认和可替换成员；保留旧三个 Profile 及 ManagedDataContext 的版本身份。混合来源从正相关 Facts 开始交替 Knowledge，保存源选择用于摘要恢复，不改变原执行权威。

最终 2972 passed／92 skipped，安装后 75 契约、八个进程退出窗口、六项 dev46↔47 原审批与准确 Manifest 恢复、旧 wheel 拒绝新工厂及两示例通过；wheel／sdist、Ruff／格式／空白检查通过。独立审查的三项召回问题由七项 RED→GREEN 用例修复，文档矛盾同步校正，无延后 Minor。本轮未调用真实生成／Embedding 模型，未重新运行远程数据库／Temporal 服务；完整 H3／M1 与真实质量仍待验收。[指南](h3-intelligent-combinations.md)、[验收及决策](../architecture/reviews/2026-10-10-h3-intelligent-combinations.md)。

### dev48 H3 显式 HTTP 重排

R17 增加原 AsyncReranker 的 indexed-results HTTP 适配、原候选ID／分数／明确计量报告，
复用 Hybrid 来源前后校验；语义组合可显式启用，Hash+HTTP 需独立异步工厂。
原排序、七类推荐声明和运行权威保持。真实传输／响应流失败或取消清理可重试，不以 HTTPX 标志判定已释放。

最终3019 passed／92 skipped，安装103契约、12次双向审批与2次语义身份恢复通过；
旧 wheel 在建库前拒绝新适配器；构建／静态检查通过。准备中断仍可能重复付费检索，
dev48验收时，真实语义质量、本地语义模型、query transform、索引治理和完整 H3／M1 仍待验收；query transform 在下述dev49交付。
[使用指南](http-reranking.md)、[验收及完整决策](../architecture/reviews/2026-10-10-h3-http-reranking.md)。

### dev49 H3 Query transform 与语义 Facts

R17 提供 sync/async QueryTransform、确定性默认和原 Retriever 组合；R15 提供有界候选语义 Facts 召回、TaskRecallPlanner、有序引用选择与显式语义记忆 Profile。保留原来源、CAS、引用快照和执行权威；原七类默认声明及旧 Embedding 类保持。Query Knowledge 可显式注册 Temporal，语义 Facts 目前只在 Local；候选窗口外的全库索引、生成改写默认适配、语义修订／遗忘、真实质量和完整 H3/M1仍待验收。

[指南](query-and-semantic-recall.md)、[验收与完整决策](../architecture/reviews/2026-10-10-query-semantic-recall.md)。

最终3105 passed／92条件依赖跳过，安装86新增契约；dev48↔49的12组审批恢复及2组语义Knowledge身份恢复、旧wheel的3类声明建库前拒绝通过。审查的3项Important以TTL／同标识原生资源替换／校验输入变异回归修复，无延后Minor。构建、静态与文档链接检查通过；只做本地提交。


### dev50 H3 显式模型查询改写

R17 增加 ModelQueryTransform，复用已装配的 async ModelProvider，严格限制无工具的 JSON 查询提案。R15 的 Local 语义 Facts 与原 Knowledge 组合均可显式选择命名 Provider；作用域、原始正文与来源仍由原数据权威管理。旧八类 Profile 不自动启用模型改写。检索准备在接受前可能重复付费；Temporal 只覆盖 Knowledge，不宣称 Facts 召回。全库索引、自动查询策略、本地语义模型、质量与完整 H3/M1 仍待验收。

[指南](model-query-transform.md)、[验收记录](../architecture/reviews/2026-10-10-model-query-transform.md)。

最终冻结回归3168 passed／92 skipped，529.76s；Ruff／格式／Git 空白检查通过，wheel／sdist 构建通过。
安装后64项新增契约，dev49↔50八类默认16组身份恢复（12组实际审批／单次效果、4组语义身份-only）、旧 wheel 三项 model 声明建库前拒绝及187模块打包一致性通过。一次独立审查发现的 Facts 提案后读顺序问题由12项 RED→GREEN 修复；无延后 Minor。


### dev51 H3 HTML 摄取

R16 增加可替换纯 HTML Parser 和 ingest 模板 .html/.htm 支持，复用原分块／来源／原子回执。原文本默认保持兼容；新回执保存解析后位置。SDK 重启和两个 SQLite 实际进程退出窗口验证原子性；真实 PostgreSQL、本轮线上模型质量未重新认证。PDF/Office、网页连接器、CSS/语义解析、来源生命周期与完整 H3/M1 仍待交付。

[指南](html-ingestion.md)、[验收](../architecture/reviews/2026-10-10-html-ingestion.md)。

最终冻结回归3197 passed／92 skipped，533.12s；Ruff／格式／Git 空白检查通过，wheel／sdist 构建通过。
安装包82项解析／摄取契约、188模块打包一致性、三组旧新回执／默认 pipeline 兼容及旧版未提交 HTML 拒绝通过。独立审查4个 Important／1个 Minor 经11项复现用例在一轮修复闭环，无延后 Minor。

### dev52 H3 DOCX 正文摄取

R16 增加纯 DocxDocumentParser 与 ingest 模板 .docx 支持，复用原知识／分块／词项／回执。正文段落和表格文本保持来源、空白和解析文本位置；ZIP/XML 预算及无效包在提交前拒绝。完整 Word 排版／样式、图片、页眉脚注、PDF／其他 Office、连接器和知识生命周期仍待交付。验收见[记录](../architecture/reviews/2026-10-10-docx-ingestion.md)。

dev52 最终验收：3230 passed／92 skipped，实际安装包115 passed；189个 Python 模块工件一致。旧新文本／HTML回执双向恢复与旧版重读已提交 DOCX 已验证；未提交 DOCX 在旧版拒绝且无写入。审查1个 P2与常见文本结构共五项复现经一轮 RED→GREEN修复。

### dev53 H3 可选文本 PDF 摄取

R16 增加可替换 PdfDocumentParser 和 ingest 模板 .pdf 支持；核心安装不依赖 pypdf，需显式 pdf extra。原知识权威／来源／分块／回执保持。原子恢复与身份边界见[验收](../architecture/reviews/2026-10-10-pdf-ingestion.md)；OCR／布局、复杂字体与实际语料兼容、来源／索引生命周期仍待完善。

dev53 最终验收：3256 passed／92 skipped，实际安装包141 passed；190模块工件一致。实际无 pypdf 环境的核心／文本首用／既有 PDF 回执重读通过；三种旧 Parser 与默认 pipeline 双向旧新恢复兼容。审查 P1 Form 静默缺失和 P2 RTL 身份经八项复现在一轮修复闭环，详见验收记录。

持续执行状态：2026-10-10 用户要求不中断推进；当前执行目标 active。批次与依赖接续见[持续队列](continuous-development.md)，不以本地提交或测试数量宣布全能力完成。

## dev54 token 计量与分块增量

沿既有 Counter／Chunker 接入 TextTokenizer、UTF8ByteTokenizer、可选 TiktokenTokenizer、TokenizerMessageCounter、TokenChunker；budgeted／managed 声明显式 byte counter 和输出预留。默认字符身份与摄取模板不变。中文／emoji／特殊标记、惰性结果、原子失败／进程中断、Local 审批重启与 Temporal 状态采纳见[使用边界](tokenization.md)。实际模型词表、真实 Temporal 新组合、语义分块、协议完整计量和长期上下文质量仍待独立验收。

[dev54 最终验收](../architecture/reviews/2026-10-10-tokenization.md)：3296 passed／92 配置依赖跳过，安装包127项通过，192源码模块一致；独立核心无 tokenizer/pdf extra 和实际 cl100k_base 均通过。持续目标 active，下一批文件 Artifact。


## dev55 文件 Artifact 增量

R18 增加 FileArtifactStore、SDK／JSON/TOML 配置和 owned 关闭，默认 SQLite 保持。
沿用原 Scope／引用／digest／TTL／读取限额／namespace 容量与 Local／Temporal 受管理阶段。
正文与索引分离；先 fsync 正文／目录再提交索引；孤儿重提也重新同步，不把缺失或损坏确认为成功。
真实进程发布窗口／多进程容量、Local 图／Team／动态 DAG／嵌套卸载恢复有测试；
Temporal runtime/state 与真实 Worker/History 的证据分开，详见[验收](../architecture/reviews/2026-10-11-file-artifacts.md)。
文件后端不是云对象存储；GC／引用保留／全局磁盘限额继续开放。

最终3343 passed／98配置依赖跳过、实际安装包117项及193模块一致、独立 core venv 和 dev54↔55 原回执兼容通过。后续另行验证实际本机 Service：安装 dev55 wheel 的 file6及原SQLite6实际 Worker/History 全部通过；98配置跳过仍是原全量结果，不作为真实服务验收。

## dev56 全库事实索引增量

R15/R17 的显式 full-corpus 构建基础扩展 FactScanner、EmbeddingProvider、VectorIndex 与 CAS 元数据端口。
默认 SQLite/Hash、SDK sync/async 注入、JSON/TOML 独立 role 工厂及 Qdrant 配置；旧 bounded semantic-recall 和默认声明不自动升级。
四个实际进程窗口验证已接受 embedding 复用、向量 ACK 丢失幂等 upsert 和完整 active publication。
Redis 实际本地服务验证超过256条事实、原始大整数／Unicode／过期、snapshot 拒绝与客户端及 SQLite 向量重开。
Qdrant 新组合先验证 HTTP fixture 协议与生命周期，不替代真实服务验收。
每次事实写入后显式 rebuild；查询为全库向量排序的前256候选分页，不承诺枚举所有匹配项。
总记录／单页／输入／回执额度限制的是索引工作，不是模型账单上限。
PostgreSQL 新扫描、Temporal Facts绑定、自动增量／信念修订／遗忘、全局容量／GC／修复及真实语义质量仍未验收。
最终3397 passed／98配置依赖跳过、74安装包契约、197模块一致、独立core venv和dev55↔56原回执兼容通过。证据见[dev56 验收](../architecture/reviews/2026-10-11-fact-indexing.md)，不关闭整个 R15/H3/M1。

## dev57 PostgreSQL 原生索引增量

R15 补齐 PostgresMemory 的 native snapshot/scan_facts，复用原事务／advisory writer 锁，新增 epoch 表；有界 named server cursor 不将整页大正文装入 libpq。
真实 PostgreSQL16.15 覆盖Unicode／大整数／expired、key/value截断、无遗漏byte分页、270条索引／连接重开、四个真实进程窗口和配置Agent/owned关闭。
CI远程契约明确纳入Redis／PG新索引测试。PG/Qdrant联合组合、Temporal Facts绑定、自动维护／修复／质量仍开放。
最终3436 passed／68服务依赖跳过、安装73／模块198一致／core-only、原回执及真实PG56↔57升级通过。证据见[dev57验收](../architecture/reviews/2026-10-11-postgres-fact-indexing.md)；不关闭整个R15/H3/M1。

## dev58 Temporal Facts 绑定增量

在原 temporal-3/Context Activity/History 中加入 Facts 读链路、scoped namespace、MemoryRecallPolicy/纯 planner 和固定原生资源。
Knowledge/Facts 的校验与来源分类分开，普通/managed采纳固定证据；多页维持游标query身份与总预算。
默认关闭，不新增第三权威。原生/顺序/高级实际Agent兼容原子树投影；实际服务、安装、升级及质量证据见[dev58验收](../architecture/reviews/2026-10-11-temporal-facts.md)。
Temporal其他角色、Knowledge selector、共享Session、索引自动生命周期及完整H1/H3/M1继续未验收。

最终dev58：3417 passed/119未配置服务跳过；真实Temporal新增12＋原组合16、安装新增12、安装94契约／200模块一致、core-only／57↔58默认Run与Temporal manifest兼容、真实Redis/PG Activity探针通过。全量已固定版本并完成。仅本地提交；完整能力与质量门槛继续开放。


## dev59 Temporal Knowledge 绑定增量

新增 KnowledgeBindingResource 宿主 namespace selector，原 Context History 采纳具体 Scope／namespace／版本／文本摘要，保留原路径与实际 Agent 子树。
原生 SQLite/PG 资源、Lexical/Vector/Hybrid/Query 组合、方法和 HTTP client 固定；最后来源 await 在 History admission 前。
原 raw/global Knowledge 发布保持；新 scoped 发布启用 knowledge_protocol=1。SDK borrowed 工厂装配，未新增独立执行状态机。
恢复／安装／兼容证据见[dev59验收](../architecture/reviews/2026-10-11-temporal-knowledge.md)。共享 Session、其余绑定角色、自动 Temporal Profile、索引生命周期和真实语义质量继续开放。

最终dev59：3436 passed/131未配置服务跳过；真实源码Temporal12+原组合28、安装Temporal12+独立63、202模块一致、core-only与58↔59原默认/raw发布兼容、真实PG Activity探针通过。两项review P2已闭环，服务正常退出。仅本地提交，不将子集验收当全能力完成。

## dev60 Temporal History Session 增量

H2c3 复用共同 DTO／异步入口；实际 Namespace UUID、原绑定修订、串行 Turn、稳定 busy／mismatch、先接受后启动与空闲 CAS。Conversation 保存在协调 History，业务 Run／Parent 独占 Action／审批／预算；独立原根与后代静默证据才释放，普通／managed 上下文保持本轮 Knowledge/Facts 查询。
[指南](temporal-sessions.md)及[验收](../architecture/reviews/2026-10-11-temporal-sessions.md)分别记录实际恢复、安装及兼容证据。
此为 History Conversation 默认子集；Temporal 外置 SessionStore、其余角色、输入续接／FIFO、迁移／保留／Continue-As-New 和完整 H2/H3/M1 继续开放。

最终dev60：3466 passed/146未配置服务跳过（536.83s）；真实源码Temporal27＋最终入口3，最终安装Temporal15＋103契约，207模块一致。独立core安装和59↔60默认发布／原回执／21 starter、旧Worker新发布拒绝通过；四项P2闭环，自有Service停止。全能力目标继续active。

## dev61 Temporal Agent limits 增量

R01/H1f 接通可替换纯 LimitsPolicy、强制 host/Spec 交集、原 History 逐 Agent 节点采纳、决定／上下文／工具 Action caps 与整批拒绝。详情和恢复证据见[限制指南](temporal-agent-limits.md)及[验收记录](../architecture/reviews/2026-10-11-temporal-agent-limits.md)。其他 Temporal 角色／外置 Session 数据、全局容量、H3 质量及完整 M1 继续开放。

最终dev61：全量3492/164（523.45s、56122 exit0），源码实际12恢复+6超限、最终安装18真实Temporal/85契约、209模块、core-only与60→61→60原审批/回执/一次测试工具兼容。宿主入口P2、沙箱异常身份P2与错误码Minor已闭环，自有Service83761 exit0且stopped；只做本地提交。完整能力目标继续active。

## dev62 Temporal 纯完成验证

沿 R01/H1e 复用 CompletionVerifier 与 ToolReceiptVerifier，Worker 提出纯 verdict，原 Run History 固定当前节点原输入与已提交回执并一次采纳。accept 才进入原记忆和完成链路；retry 保留原额度、审批和受保护反馈，reject 明确失败。宿主／每 Agent inherit/ref/disabled 支持原生、顺序、图、Team、动态及嵌套。实际十八项恢复／取消／重放通过；最终交付证据见[验收记录](../architecture/reviews/2026-10-11-temporal-completion-verification.md)。模型验证、DecisionPolicy／外置 Session 和其他环境角色、H3 质量及完整 M1 继续开放。

最终dev62：全量3519 passed/182 skipped（537.24s，8978 exit0），源码实际Temporal18/133.86s、最终安装18/133.40s及163契约；212模块、core-only与61→62→61原审批／回执／一次工具兼容。只读review140通过且无待办P1/P2/Minor；两处控制／反馈P2已RED→GREEN。自有Service25330正常exit0且stopped。未调用真实模型、未重验远端数据库；只本地提交，完整R01–R26目标继续active。

## dev63 Temporal DecisionPolicy

沿 R01/H1 公共纯 Harness 的 prepare/propose，提供宿主默认／每 Agent inherit/ref；固定实际方法、编译器 super 闭包及原 Scope。实际模型请求与原响应/提案证据由原 Run History 一次采纳；不改变审批、Schema、limits、完成规则和记忆责任。Temporal 九类绑定已接通，外置 Session/环境角色、完整 Profile/服务治理和真实质量仍待交付。见[指南](temporal-decision-policy.md)和[验收](../architecture/reviews/2026-10-11-temporal-decision-policy.md)。

最终dev63：全量3563 passed/198 skipped（485.75s，95622 exit0）；冻结源码实际16/125.73s、最终安装实际16/126.11s及195契约。214模块、core-only与62→63→62原审批／回执／一次工具兼容通过。独立审查2项P2由2RED→195GREEN闭环，无待办Minor。自有Service75051正常exit0且stopped。未调用真实模型／重验远端数据库；仅本地提交，完整R01–R26继续active。

### dev64 默认精确 Session 回执

R01/R02/R14 增加默认 memory/SQLite 的准确消息核验和 threaded sync 桥接；Local 独立资源使用既有远程保存权威，同库仍原子保存。原生/Team 的真实进程写前/写后恢复、七类复合根与 borrowed 生命周期有测试。完整 Temporal 外置 Session 读/写/完成门禁仍待实施，见[目标契约](../architecture/specs/temporal-session-data-contract.md)和[指南](session-receipts.md)。不把默认 SPI 当作第十类 Temporal 绑定、跨权威租约或完整 H1/H2/H3。


## dev65 Temporal Session 有界读依赖

R01/R02/R14：host／每 Agent session 选择接入原 Context/managed History，支持 native/sequence stateless 私有地址。源码、安装包和真实服务证据见[验收](../architecture/reviews/2026-10-11-temporal-session-data-reads.md)。外置持久会话尚无自动保存／稳定跨 Turn 路由，不能作为完整第十类绑定或 H1/H2 完成；高级组合与 History Sessions 选中外置源时接受前拒绝。下一步继续原写意图／精确回执／完成门禁、根和成员持久地址，再推进其他 R01–R26 能力。

PostgreSQL 的新 Session 读取固定 initialize 解析的表 schema；旧 Facts／Knowledge 发布的跨 schema 恢复身份及迁移仍须独立验收，不能以本批读取固定推断已有发布格式已升级。


### dev65 最终结果

最终全量3642 passed/204 skipped（620.69s，44944 exit0）；安装140契约及独立相关39项（有重叠）、真实安装服务7及最终源码/安装各4个Temporal窗口、217模块一致、freshcore/文档例子及实际64↔65默认/审批/History兼容通过。Ruff/格式/空白通过；三项自有服务全部关闭。只本地提交，无真实模型或完整H1/H2/H3/M1质量宣称。后续按完整外置Session写/持久路由继续，不关闭R01–R26目标。
