# Changelog

记录用户可见行为和兼容边界。版本为开发预览；此记录不表示已经上传 PyPI、创建 Git 标签或发布 GitHub Release。

## 0.1.0.dev10 — Unreleased

新增不可变 ExecutionPlan v1、GraphWorkflowSpec、值引用／映射／条件、纯 WorkflowCompiler／WorkflowInterpreter／NodeTransform；提供 static 编译／解释和 identity 变换默认实现。图支持依赖、跳过传播、显式可选分支合并与 Schema 验收，当前串行调度。

图首次接受时固定计划与组件身份，保存节点输入／结果，恢复不重新编译。Agent 节点沿用审批、预算、效果核验和独立证据采纳；纯变换与节点完成原子提交。新增 JSON/TOML graph、组件工厂注册、只读计划／节点诊断和可编辑 graph starter。

默认旧 Agent／sequence 的请求摘要、local-4 Manifest、ExecutionStore v1 和原有 starter 文件保持兼容；工作流组件通过 Graph 入口启用。Graph 增加工作流 Manifest，dev9 不能继续这些新 Run。并行、循环、动态 Plan、ChildRun、通用异步自定义节点、流式数据编排及完整 M1 仍未交付或未验收。

## 0.1.0.dev9 — Unreleased

新增 ModelCapabilities、StreamingModelProvider 和 ModelStreamEvent。Chat Completions 支持 temperature/top_p/stop/seed 和 SSE；默认 identity 保持 dev8。流文本为临时展示，工具参数只在完整结束/JSON 校验后返回，Engine 仍独立接收完整响应。可选纯请求预检在预算预留和实际调用前执行，旧 Provider 保持兼容。

新增原生 Anthropic 文本/客户端工具及 Gemini 文本协议，认证、历史、生成参数、用量与流式归一化。DeepSeek 非思考 preset 明确关闭 thinking，采用对应地址/凭据和 max_tokens。Gemini 工具、opaque thinking continuation、server tools 和多模态不支持；不静默丢弃不可表达的命名/推理历史。

新增声明式模型 adapter 和独立 model starter；占位与非法配置在创建执行库前拒绝，密钥仅经显式参数/环境取得。独立 Review 修复空参数 delta、SSE 错误标记、畸形响应和原生历史丢失；关闭工具能力时也拒绝模型擅自返回工具。

保留 local-4、ExecutionStore v1、旧调用摘要和离线模板。协议 fixture 与安装恢复有本地证据；线上厂商/型号兼容、真实模型质量、分支并行、多 Agent、MCP/沙箱和 Temporal 仍未交付或未验收。

## 0.1.0.dev8 — Unreleased

新增公共 ExecutionEngine／RuntimeDiagnostics 和独立 RunDiagnostics，CLI 不要求 LocalEngine 继承关系或 .store。KnowledgeContextPort 支持直接实现知识流程；RecallPlanner 可以按 Agent／输入生成查询，实际计划保存到模型 Action，未知重试保持原查询和快照。MemoryRecallPolicy 保持配置 DTO。

新增不可变 RuntimeProfile／RuntimeCatalog、严格 JSON／TOML 加载、显式 ComponentRegistry、RuntimeBuilder 和资源管理。默认组件可声明装配；配置不动态 import/eval，自定义适配器由应用注册。Chat 凭据通过环境变量名称引用。附属资源在引擎停止后清理，失败保留重试句柄；不完整 close 不能释放归属或确认完成。

ProfiledEngine 按保存的 profile 身份恢复旧任务，默认版本仅控制新提交。回执查询先于新配置装配；缺失或改写原配置拒绝继续，无 profile 的旧 Run 要显式 legacy_factory。新增 --config、run --spec 及独立 config 模板，保留原 oncall/rag 路径。

默认 local-4、执行 Schema v1、请求摘要及 dev7 Manifest 不变，仅显式 profile/planner 增加身份。Catalog 不归档代码或外部数据；Graph／并行 Workflow、MCP／沙箱、多 Agent、模型流式／能力协商、Temporal 和完整 M1 验收仍未交付。

## 0.1.0.dev7 — Unreleased

新增可显式启用的 `MemoryRecallPolicy`、分页 `RecallQuery/RecallPage` 及同步／异步端口。内存／SQLite 后端限制候选数与返回字符量，Session 高水位保持完整消息顺序，事实 generation 固定分页集合；超大记录跳过并推进。旧后端通过 Legacy 桥接，明确标记全量读取，Threaded 桥保留真实线程归属。

新增独立 KnowledgeStore／Retriever／EmbeddingProvider／VectorIndex：内存和 SQLite 知识库提供 CAS、TTL、文档分块、范围隔离和删除版本；默认 LexicalRetriever 支持中英文词项，向量实现显式注入 Embedding 并作真实 cosine 排序，当前为本地线性检索。旧向量命中需回读权威来源并校验版本与摘要。

Engine 固定可选召回／知识配置，保存原引用与最终请求快照。每次实际模型派发前复核事实和知识，异步读取结束后复核全部已知有效期。未知模型重试拒绝已失效来源、保留原快照及预算；已收到响应直接采纳。新增可编辑 `ralf init --template rag`、源码示例及接入教程；不增加运行依赖或隐藏收费调用。

保留 local-4、ExecutionStore v1、默认 Manifest 和调用方摘要。未启用新能力的 dev6 Run 可用原配置续跑；启用新组件须保持原配置，不能把新默认策略加到旧 Run。Redis／PostgreSQL／托管向量库、自动语义记忆、多 Agent、MCP／沙箱、容量、并行与 Temporal 仍未交付，完整 M1 和真实模型质量尚待验收。

## 0.1.0.dev6 — Unreleased

尚未公开发布。本轮组件与两个接收／采纳窗口已通过本地回归；完整 M1 未完成。

### 新增

- 公开 Harness、NativeHarness、ModelRequest／DecisionProposal 及 ToolExecutor、PythonToolExecutor、DispatchEnvelope／EffectObservation；默认装配保持简洁，自定义 identity 固定到 Manifest。
- 模型完整响应与 handler／执行器核验观察先独立接收，再分别执行 DecisionCommit／ResultCommit；receiver commit 后的恢复、取消和精确结算由真实进程回归验证。
- 源码离线 execution_components 示例，展示按 Agent 的策略与受审批业务执行器，以及顺序 Workflow。
- CLI inspect 展示等待采纳的耐久证据，区别于未确认写效果。

### 边界修复

- 固定真正调用的 Provider／Executor 对象并在调用前和接收后复核身份，防止注册表替换掩盖实际组件配置漂移。
- 意图保存后的未开始调用明确记录 not_dispatched，并释放本次预留；历史未知 Attempt 仍可阻断／核验，不让零结算重试覆盖真正派发的费用。

### 兼容与范围

内核升级为 local-4。dev3–dev5 的 local-3 Run 仍可观察／取消／人工核验，继续必须使用原版本和原配置，不自动迁移；dev3 起的请求摘要和 SQLite Schema v1 不变。人工 reconcile 仍为命令去重与结果同事务。真实模型质量、RAG／向量适配、容量控制、并行、MCP／沙箱与 Temporal 未因本轮组件分离而交付。

## 0.1.0.dev5 — Unreleased

尚未公开发布，M1 仍为核心预览。

### 新增

- 独立离线 Agent 项目入口 `ralf init DIRECTORY`，生成项目可使用安装的 SDK，不依赖源码 examples。
- CLI 只读 `inspect` 诊断和全局 `--format text` 可读输出；默认 JSON 保留。
- 首次使用、恢复、常用 API 与发布指南，以及安全报告政策。
- M1 验收、LangGraph 对等比较和外部采用协议；20 个任务原型与 JSON Schema 为待实现的评测规格，没有真实模型成绩。

### 修复

- 初始化拒绝替换当前工作目录，避免 `ralf init .` 成功后同一 Shell 无法找到生成的应用；其他新／空目标仍原子生成。

### 兼容与范围

保留 dev4 运行时协议、local-3 内核身份及 dev3 调用方摘要；合法 dev3／dev4 Run 和回执保持兼容。本轮集中改善首次使用和诊断，未新增 Temporal、多进程、MCP 或企业能力。

## 0.1.0.dev4 — 2026-10-05

### 新增

- `LocalEngine.wait_for_threads()`，用于服务关闭前等待框架管理的真实同步调用。

### 修复

- 同步授权策略仅允许返回 None；上下文管理器、布尔、容器和其他非 None 返回值在工具执行意图前拒绝。
- 线程工具、核验函数和 ThreadedMemoryAdapter 的真实完成独立于 Task；取消全部 Task 或关闭循环不会提前释放 Coordinator。
- Store 关闭失败后旧 Engine 停止其他操作并保留租约；安全重试关闭。Store 已关闭而租约释放失败时只重试释放。

### 兼容与范围

保留 local-3、SQLite Schema v1 和 dev3 调用方请求摘要，合法 dev3 Run／回执可继续使用。曾返回 True／False 等值的 policy 需改为返回 None 或抛 AuthorizationDenied。M1 尚未完成：Harness／ToolExecutor 分离、独立响应／效果回执持久化窗口、容量与分页召回、Temporal 探针及真实模型质量验证仍待交付。

## 0.1.0.dev3 — 2026-10-05

- 固定 SQLite 路径与文件身份，拒绝硬链接，避免别名绕过同一数据库的 Coordinator。
- submit 请求身份与首次解析 Release 分离，配置变化后重复原请求仍返回原回执。
- 公共 final_output 边界拒绝缺失／空白模型结果，保留合法 Schema null。
- 会话保存后复核固定后端，释放已完成 Task／Run 锁，统一验证长期记忆过期时间。
- 拒绝直接异步和 generator 授权配置，以及同步策略返回的 awaitable／generator；dev4 进一步收紧为唯一 None 返回契约。
- 内核身份升级为 local-3；自动迁移尚未实现。dev1／dev2 Run 的继续执行和旧 submit 重放需要原版本与配置。

## 0.1.0.dev2 — 2026-10-05

- 显式 ExecutionStore、CoordinatorLease、ContextBuilder 及同步／异步记忆扩展端口；自建 Agent 使用可信 CLI factory 恢复。
- 修复晚到结果／取消竞态、固定历史成本结算、可变工具配置与后端身份、上下文真实选择记录。
- 增加打包与已安装 CLI 验证，整理扩展与实现范围。内核身份 local-2。

## 0.1.0.dev1 — 2026-10-05

- 原生 Agent、顺序 Workflow、SQLite 执行日志、模型／工具提案采纳、审批／取消／未知效果核验、整数 credits 预算。
- 内存和 SQLite 会话／长期事实、离线 Demo、真实进程崩溃恢复测试、基础 CLI 与架构契约。
- 初始 M1 核心预览；后续修订继续完善可靠性和扩展边界。
