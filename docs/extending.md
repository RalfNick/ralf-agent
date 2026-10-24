# Relf-Agent 扩展指南

更新：2026-10-24。面向 SDK／适配器开发者；a2 是历史公开入口，当前准备包含 `2d17808` 修复的独立 a7，原 a6 及更早包与证据保持。本指南描述执行、装配、召回和知识端口；当前扩展组件、限制和候选资格见[实现清单](implementation-status.md)、[a7 清单](alpha7-validation-status.md)及[首版范围](releases/0.1.0a2.md)，企业适配与完整 M1 仍未验收。

完整目标要求每层交付公共契约、默认实现、替换示例和共同验收，见[通用框架能力矩阵](../architecture/viewpoints/framework-capabilities.md)。静态图／并行、动态规划／团队和远程数据已有实现，分别见[静态 Workflow](static-workflows.md)、[编排](orchestration.md)与[远程数据](remote-data.md)。默认实现不一定默认启用；每 Agent 能力绑定、推荐组合与 Local/Temporal 契约差异见[整体审查](../architecture/reviews/2026-10-08-agent-framework-alignment.md)。下表以本地装配契约为主，Temporal 支持范围单独声明。

## 先选择扩展方式

从[连续工单示例](support-journey.md)开始即可完成基础定制，不需要实现所有端口。

| 方式 | 当前适用范围 | 开发者需要承担什么 |
| --- | --- | --- |
| 结构化端口替换 | Provider、纯 Harness／Context、工具执行器、Session／Facts／Knowledge／Embedding／Vector 等明确端口 | 实现对应方法、身份、Scope／CAS／来源与生命周期；使用现有注入或注册工厂 |
| 继承扩展 | 受管理记忆 `ManagedMemoryPolicy`、受管理上下文 `ManagedContextPipeline` 及其已声明钩子 | 保留阶段证据、来源准入、预算和恢复约束；不是仅实现同名方法即可替换 |
| 当前受限 | Local／Temporal Facade 的具体 Engine、Artifact 绑定后的 managed Context、其余未支持的受管理阶段 | 使用已有支持入口；不能靠适配数据库或删除类型检查获得新执行后端／组合 |

例如，自定义普通 `ContextBuilder` 可直接注入 `context_assembler`；只有需要原受管理阶段或显式 Artifact 绑定时，才需要满足 managed Context 契约。自定义长期记忆后端与替换自动提炼策略也是两件事：前者按存储端口接入，后者仍遵守 `ManagedMemoryPolicy` 的准入约束。

CLI 的 `--factory`／底层 ExecutionEngine 可按公共端口替换；高层 Local Runtime 当前仍要求 LocalEngine，Temporal Facade 要求 TemporalEngine。不要把底层端口可替换理解为所有 Facade 已支持任意执行器。优先针对实际业务扩展需求验证，保留明确拒绝，避免通过继承内部状态机改变执行权威。

## 1. 装配组件

| 扩展点 | 注入位置 | 必须满足的约束 |
| --- | --- | --- |
| ExecutionEngine | SDK／CLI 工厂返回值 | submit/drive/status/events/approve/cancel/reconcile/wait_for_threads/close 公共契约；不要求继承 LocalEngine 或暴露 store |
| RuntimeDiagnostics | 可选 engine.diagnostics | 返回独立 RunDiagnostics；缺失时 CLI 仍能输出结果 |
| ModelProvider | `providers={name: provider}` | `identity` 非空有限 JSON；`async complete` 返回 ModelResponse；可选纯同步 validate_request 返回 None，最终输出在公共采纳边界校验，不执行工具 |
| StreamingModelProvider／ModelCapabilities | `provider.stream`／`capabilities` | 实现的协议能力可禁用，不能凭声明打开；片段仅展示，完整 response 才返回工具，提前退出须 aclose |
| Harness | `harness=`，默认 NativeHarness | 非空有限 JSON identity；同步纯 prepare／propose 返回 ModelRequest／DecisionProposal；不执行工具或提交状态 |
| WorkflowCompiler／WorkflowInterpreter | `workflow_compiler=`／`workflow_interpreter=`；默认 static | Graph 首次编译后固定 ExecutionPlan；解释器只选择合格节点，公共边界检查输入、跳过和完成；同步纯端口 |
| NodeTransform | `workflow_transforms={name: component}`；默认 identity | transform(input, config) 返回已完成有限 JSON；版本固定、同步纯计算，不执行外部 I/O |
| ToolExecutor | `tool_executor=`，默认 PythonToolExecutor | 非空有限 JSON identity；async execute／reconcile 接收固定 DispatchEnvelope，返回 EffectObservation 或核验未知 None |
| 工具与核验 | `tools=ToolRegistry()` | 参数 Schema、效果类别、version/config、稳定幂等键；单次调用不隐藏业务重试 |
| SessionStore／AsyncSessionStore | `session_store=` | `backend_id`、read、append；CAS 与 message_id 去重同时成立 |
| LongTermMemoryStore／AsyncLongTermMemoryStore | `memory_store=` | `backend_id`、facts、put_fact；范围、版本及到期语义一致 |
| MemoryRecallPolicy | `recall_policy=`，默认 None | 固定查询及全局额度；同步／异步 read_page/recall，旧端口走明确 Legacy 桥 |
| RecallPlanner | `recall_planner=`，默认 None | identity、同步纯 plan 返回 MemoryRecallPolicy；与 recall_policy 互斥，原 Action 恢复不重新规划 |
| FactReferenceValidator | 记忆后端可选 validate_facts | 返回 None 或抛拒绝；校验当前 Scope/namespace/key/version/TTL；缺失时全量 Legacy 校验 |
| KnowledgeContextPort／KnowledgeRetriever | `knowledge=`，默认 None | identity、limit/max_chars、async references/validate；结构化端口不要求继承 KnowledgeContext，固定来源与配置，调用后复核 |
| SkillSelector | SkillDirectoryRetriever(selector=...)，默认 LexicalSkillSelector | 普通固定 identity、纯同步 select→有界唯一已允许名称；不访问模型／正文，不授予权限；原 KnowledgeContext 配置与每 Agent Knowledge 绑定可复用 |
| KnowledgeStore／EmbeddingProvider／VectorIndex | 注入 Retriever | 权威知识 CAS/TTL 与索引分离；模型身份、维度、来源过滤和显式重新索引 |
| ContextBuilder | `context_assembler=` | identity 与确定性 assemble；返回实际消息和 JSON Manifest |
| ExecutionStore v1 | 第一个构造参数 | 原子命令／事务、Run CAS、事件、预算、活跃 Session 和未知效果查询；不另建调度器 |
| CoordinatorLease | `coordinator=` | 同一执行权威只允许一个持有者，活跃调用结束前不能交出归属 |
| 当前工具授权 | `policy=` | 可信宿主同步授权函数，只允许返回 None；拒绝抛 AuthorizationDenied，任何其他返回值均拒绝 |

同步返回 `None` 表示检查已经执行并完成授权。上下文管理器、awaitable、generator、True／False、字典等不能表示授权；框架不进入它们，也不调用它们的任意生命周期方法。对已识别的 coroutine／generator 仅做关闭清理，然后报配置错误。人工审批的 `approved` 则必须是布尔值：`False` 拒绝，`True` 批准；字符串、数字或 `None` 在 Local 命令接受前拒绝，不做真值转换。

Local、Temporal、Binding 和运行装配共用 `relf_agent.ports.validate_component_identity` 的组件身份与方法形状检查：identity 必须是非空有限 JSON 对象，采纳的是独立副本；检查不调用组件方法。异步端口接受 `async def` 方法或具有 `async def __call__` 的 callable 对象，同步返回 coroutine 的普通函数不满足异步端口。同步纯策略拒绝 coroutine／generator／async-generator 方法；身份或方法读取失败报告配置错误。组件被实际调用后，其返回值与恢复身份仍由各执行边界分别校验。

dev123 将同一异步判断用于已有 ToolSource／MCPTransport、MemoryPipeline.extractor、ManagedDataContext Artifact、基础 ExecutionEngine 的 drive／wait_for_threads，以及 Facts 索引维护的生成／CAS 操作。替换组件仍需满足原身份、参数、已完成返回值、来源和关闭契约；支持 callable 不授予执行权限，也不表示可以替换所有 Facade 或 vendor 客户端。流式生成器、线程桥和具体数据库客户端保留各自声明的模式。

Artifact 的 put／get 可以成组使用同步或异步实现，不能混用。本批验证了异步 callable 组的实际卸载与读取，以及混合模式拒绝；不将其解释为所有同步 Artifact 返回值的预先拒绝。同步存储仍沿用既有 memory_call 的调用和等待语义。

默认 `LocalEngine(SQLiteStore(path), ...)` 会创建 POSIX 文件租约和共享 SQLite 记忆。自定义存储通过端口接入，不需要 `.conn`／`.path`；同时显式注入 `coordinator`、`session_store`、`memory_store`。当前 ExecutionStore 方法是 Coordinator 线程内的同步事务操作；远程数据库需单独验证延迟、原子性和失败语义。

基础 ExecutionStore 不要求实现持久 Session 扩展。`Runtime.capabilities` 对缺少该扩展的存储返回空的 `session_definitions`／`remote_session_definitions` 和 `session_storage=None`；已有基础 Run 执行仍可用。只有声明同步 `create_session_admission` 工厂时才报告持久 Session，额外组合仍按原 `session_admission_version` 门槛报告。此查询不会创建 Session 或调用工厂。

Session ID 在 submit 中可省略（None，此时采用 Run ID）；显式指定时必须是非空、非纯空白字符串。默认 Session 后端的 read/append 也要求该字符串契约，不接受数字或隐式字符串转换。合法名字保留原值，不裁剪、大小写折叠或重写，以保持请求摘要和历史身份。自定义 Session 适配器应遵循同一契约。

Harness／ToolExecutor 不需要首次使用者额外配置。自定义组件只变换提案或执行一个派发，不取得 Engine 的审批／预算／状态权威。DispatchEnvelope 和 EffectObservation 的 JSON 属性是独立视图；ModelRequest／DecisionProposal 是分离的输入数据，frozen 顶层不保证嵌套 JSON 深度不可变。具体签名、阶段与离线例子见 [执行组件指南](execution-components.md)。

模型层默认提供 Chat、DeepSeek 非思考 preset、Anthropic 文本/客户端工具及 Gemini 文本，见 [模型指南](model-adapters.md)。原生不能表达的消息字段明确拒绝；不靠丢弃 name、推理历史或签名来获得兼容。旧自定义 Provider 缺少预检或 streaming 仍可执行 complete。

默认组件也可通过 JSON/TOML RuntimeProfile 装配；ComponentRegistry 显式注册第三方工厂，BuildContext.own 接管同步 close 的附属客户端。RuntimeCatalog 不覆盖已注册版本，ProfiledEngine 根据 Run 保存的原 profile 解析。它不归档 Python 实现或后端数据，恢复仍需保留它们。完整例子、默认适配器、关闭重试和历史版本配置见 [运行装配](runtime-assembly.md)。

## 2. 远程记忆

远程后端优先使用对应的异步 Protocol，方法名称及返回结构与同步后端一致；引擎会等待返回。同步 SQLite／内存接口用于本地快速操作，不能把阻塞网络请求直接写进同步 `read/facts`。

对于已存在且线程安全的同步客户端，可显式桥接：

```python
from relf_agent import ThreadedMemoryAdapter

# 使用者自己的后端，先通过范围/CAS/去重/TTL 契约测试。
# redis_sessions = MyRedisSessions(...)
# sql_facts = MySqlFacts(...)
# sessions = ThreadedMemoryAdapter(redis_sessions)
# facts = ThreadedMemoryAdapter(sql_facts)
# LocalEngine(..., session_store=sessions, memory_store=facts)
```

桥接器不能包装 SQLiteMemory 或原生异步后端。其底层客户端必须支持工作线程调用；客户端由使用者关闭。原生异步组件直接注入，不需要桥接。

`read(scope, session_id)` 返回 `(revision, messages)`；`append(..., expected_revision, message_id)` 使用比较交换，并在重复 message_id 时返回原提交，不同内容则冲突。会话消息、长期事实与执行状态分别存储，替换记忆不会替换审批／效果／预算日志。

`expires_at` 使用 Unix 秒，仅接受 `None` 或可表示为有限浮点数的 int／float；`None` 表示永不过期，过去时间合法，NaN／无穷／布尔／字符串等在写入前拒绝，不改变 CAS 版本。

`facts(scope, namespace)` 只返回当前 Scope 下未过期的已确认事实；`put_fact(..., expected_version)` 不静默覆盖其他写入。本地内存／SQLite 及 dev14 Redis／PostgreSQL 提供 read_page/recall 与事实校验。未实现新端口时 Legacy 桥仍全量读取，不能宣称底层有界。默认模型输入行为保留，需要显式配置 `MemoryRecallPolicy()` 才启用分页。知识库、检索器、向量索引和 Embedding 分别替换；见[召回与 RAG](recall-and-rag.md)及[真实远程适配器](remote-data.md)。

Facts 的 `recall` 默认按游标分页。已有语义排序后端声明可选 `recall_mode="window"`，表示一次请求使用完整 `scan_limit` 候选窗口，输出不超过 `max_items`／`max_chars`，不接受或返回游标。`FactsBindingResource` 通过该结构化元数据保留原查询窗口，不要求继承内置语义类；添加来源信息后仍遵守字符上限，超限结果省略且计入 `skipped`，不自动扩大查询或补发请求。非默认模式进入资源身份并在调用前后校验，旧游标后端无需修改。

## 3. 身份与不可变发布

identity／backend_id 表达端点、数据库／namespace、模型、版本及影响行为的非秘密配置。不要存入 API key、连接凭据或用户隐私。独立内存实例默认具有不同身份；人为指定同一身份时，使用者负责后端语义保持一致。

方法漂移保护有明确边界：框架固定已登记的直接方法（包括绑定对象、函数及其代码入口），在调用前后复核。内置 `LexicalRetriever` 固定 Store 的 `lexical/get_chunk`；`VectorRetriever` 固定 Store 的 `get/get_chunk/chunks`、Index 的 `upsert/search/delete_document` 和 Embedding 的 `embed`；`HybridRetriever` 固定自己的来源 `get_chunk`，分支按其原直接端口检查。改变这些实现需创建新组合并按原版本规则发布，不能在同一个运行组件中热替换。

该检查不递归追踪任意 Python 闭包、全局变量、客户端内部缓存、网络路由或数据库内容，也不隔离不可信 Python。第三方适配器必须自行固定实际后端，保证 `validate` 回读当前来源；原数据按 CAS／版本更新仍然合法，并由来源校验拒绝旧引用。公共 identity／backend_id 编码不因这次运行时检查变化，旧任务仍需保留匹配组件与 Worker。

工具实例状态、partial 绑定参数、闭包和外部依赖不会自动序列化；改变它们时同步更新 `ToolSpec.version/config` 并构造新的 Registry。Provider／Harness／ToolExecutor／ContextBuilder／记忆的 identity 应反映实际当前配置。内核在恢复、异步装配后的派发、模型响应采纳、工具授权后，以及最终会话写入完成后、提交节点／Run 成功前复核固定发布。会话读取和保存固定使用同一执行组件；若适配器在等待期间更换实际后端，Run 失败，已发生的外部写入仍可能存在。

没有工具提案的 DecisionProposal 必须给出完整最终结果：缺少输出或空白文本会在采纳前拒绝；False、0、空对象／数组属于合法 JSON。默认 NativeHarness 透明转交 ModelResponse，自定义 Harness 可以变换原始响应，最终验收对象仍是它提出的输出。配置输出 Schema 时，文本按 JSON 解析后再校验；Schema 允许 null 时可返回 None 或 JSON null，编码后的空白文本仍拒绝。

Registry 的 Schema/config 描述是独立副本，policy 可以读取它们；修改副本不会改变登记的工具或原审批。核验历史未知效果使用原 Manifest 成本，不要求当前工具仍注册。

模型收到完整响应后独立保存 received_response，才调用 Harness.propose 并执行 DecisionCommit；handler／执行器自动核验观察独立保存 effect_observation，才执行 ResultCommit。接收阶段的证据不能因取消被抹去；恢复不重复已保存响应的模型调用或已保存回执的 handler／query。人工 reconcile 的结果已有命令 payload 证据，仍与命令去重及结果提交共用原子事务，不另建接收窗口。当前故障窗口证据状态见 [验收协议](m1-acceptance.md)。

## 4. 存储及租约

ExecutionStore 的 `run()` 返回与底层记录分离的 JSON 快照；`save_run()` 原子比较 revision，只在成功时更新传入 revision。`command()` 的 apply、Run／事件／预算及回执在同一原子事务中提交。submit 的摘要只包含调用方的 definition、input、budget 和 session_id；回执去重先于当前 Provider／工具／记忆／上下文配置解析，首次接受才固定 Release。相同请求重提不更新原发布、事件或预算，不同请求保持 idempotency_conflict。事务中不能 await 外部 I/O。

`session_owner()` 和 `unresolved_effect()` 必须按可信 Scope 查询当前权威事实，在同一事务内与提交保持一致。当前 SQLite 实现扫描聚合记录；企业实现需要索引、保留与数据迁移方案，这仍是后续工作。

`SQLiteStore` 在构造时固定 canonical 绝对路径。连接前及开启 WAL 前拒绝硬链接和非普通主文件，取得租约／开始事务时复核文件身份；普通 symlink 使用同一实际路径和锁，后续 chdir 不改变它。数据库目录、主文件及 WAL／锁文件由运行方管理；不支持网络文件系统或任意外部并发替换。`FileCoordinator` 使用这个固定路径获取 OS 锁。自定义 lease 必须协调同一存储的所有使用者；只有 TTL 的 Redis 锁不满足“旧执行者仍能提交时不能交接”的约束。多进程／分布式需要执行 epoch、Worker 交接和独立能力验收。

这些是 Local 的存储与所有权端口。TemporalEngine 会以 Workflow／History 作为执行权威，需实现独立后端及相同外部契约，不能仅把 SQLiteStore 换成远程数据库就宣称支持分布式执行。

## 5. 生命周期与 CLI

Engine 成功构造后拥有 execution store 与 coordinator；`close()` 等待条件由调用者满足，活跃工具／记忆调用或排队的 drive 尚未结束时会拒绝关闭。框架托管的同步工具、核验函数与 ThreadedMemoryAdapter 调用按实际工作线程退出追踪；取消全部 Task 或关闭事件循环不表示线程已停止。同 Run 的线程尚活跃时拒绝 drive，cancel 不提前把实际执行判成遗失 Attempt。完成调用和无调用者的 Run 锁会释放。传入的 Provider、ToolExecutor、HTTP client、session_store、memory_store 由调用者管理，Engine 不隐式关闭它们。构造失败会释放已获得租约，直接传入的 store 仍由调用者关闭。

服务关闭时先停止接收新请求，完成或取消并 await 自己管理的驱动 Task，再 `await engine.wait_for_threads()`，最后 `engine.close()`。等待方法不取消 Task，也不释放租约；取消等待不会丢弃线程归属，已经关闭旧事件循环时可以在新循环等待。线程结束仅表示本地执行已退出；若取消使回执没有采纳，未知效果仍需按执行日志核验。同步线程不能被 asyncio 强制终止，需要 handler 自身的超时／协作退出策略。

存储 close 抛异常或没有同步返回 None 时，Engine 进入 close_failed，保留租约并拒绝 submit／drive／控制／读取操作；可以重试 close。存储已关闭但租约释放失败时只重试释放，不重复关闭存储。成功 close 可重复调用，原 Engine 始终不可再执行。Coordinator 的 acquire/release 同样必须同步完成并返回 None；引擎不进入返回的上下文管理器或等待 coroutine。自定义存储应允许部分关闭失败后的安全重试，自定义租约应按原持有者身份幂等释放。

acquire 抛异常时，适配器负责清理本次获取产生的临时资源，保持原持有者不变；Engine 不调用 release，以免复用同一 Store／租约时释放已有执行权。acquire 已返回但完成值无效，或之后的构造失败时，Engine 才尝试幂等释放；直接注入的 Store 仍由调用方清理。

追踪只覆盖框架托管的同步调用。自定义 async 适配器内部直接使用 asyncio.to_thread、创建自己的后台线程或交出外部调用后，必须自行保证取消、真实完成与资源归属契约；不能把仅取消等待当作实际工作已结束。

自建 Agent 的跨进程控制使用 `--factory module:callable`。同步工厂接收 db_path，返回符合 ExecutionEngine 的对象；工厂应放在可导入包中，或在仓库目录使用 `PYTHONPATH=.`。内置适配器可直接用 `--config runtime.toml` 和 `run --spec agent.toml`，两种入口互斥。完整可运行示例见 [custom_runtime.py](../examples/custom_runtime.py)；独立配置模板用 `relf init my-agent --template config`。

SDK 入口程序应导入同一个配置模块，工具实现保留稳定的包／模块名。示例入口已经这样装配；在 `__main__` 重新定义工具后，再从其他模块加载同名函数，属于不同的发布身份。

CLI 的 `inspect/status/events` 使用只读 SQLite 和默认 Scope；不载入工厂、不取得执行租约。已注入 Harness／Executor 的恢复命令也必须使用原 factory。自定义 Scope／非 SQLite 的观察可使用 SDK `engine.status/events`，独立 Read API 尚未发布。

dev13 可使用 register_async/abuild 和 own_async/aclose 管理异步组件客户端；原同步执行权契约不变。异步启动、创建循环、取消后的清理任务及重试见[异步装配](async-assembly.md)。

dev14 的 TeamStrategy、Planner 和 PlanVerifier 有默认实现，可通过 Engine 映射或 ComponentRegistry 显式替换。策略返回有限 JSON 提案，成员沿用 AgentSpec 与现有执行组件；调用方无需实现第二套工具循环。约束、ModelPlanner 接入和父子恢复见[编排指南](orchestration.md)。

## 6. 接入验收与升级

新的适配器至少覆盖：隔离 Scope、重启后稳定身份、CAS 冲突、重复请求去重、未知成本保留、已确认效果不重跑、取消期间不新增后续调用、晚到证据不覆盖原结果、组件变化拒绝恢复。参考 `tests/test_memory.py`、`tests/test_extension_contracts.py`、`tests/test_engine.py` 中的真实数据库和异步测试。

dev8 保留 dev6/dev7 的 `local-4`、默认 Manifest、SQLite Schema v1 与调用方摘要，默认 Run 可以用原工厂续跑。Recall／Knowledge／planner／profile 仅在显式启用时增加固定身份；旧的无 profile Run 经 ProfiledEngine 恢复需明确的 legacy_factory，不能回退当前默认。改变策略或知识配置后，同一提交仍找回原回执，但继续执行拒绝不匹配配置。dev3–dev5 的 local-3 Run 可观察、取消及人工核验，续跑需原版本与配置。dev1／dev2 的旧 submit 摘要重放需原版本。没有自动 Run／摘要迁移；未知效果先在原日志核验。policy 继续仅允许同步返回 None 或抛拒绝异常。

## Tool sources and managed graph operations

[Managed tools](managed-tools.md) exposes borrowed async ToolSource and MCPTransport ports, immutable descriptors and host policies. Register a selected source into ToolRegistry and use the names from AgentSpec or GraphNode(tool=...). The default POSIX stdio transport manages one operation/process group at a time; custom persistent clients need explicit host shutdown. Pure transforms retain their no-I/O contract.

## DAG, nested execution and remote composition

Use Planner.plan -> DAGProposal/PlanningConclusion with registered capabilities, rather than mutating accepted plan state. All child member types use the same execution-tree budget/parent-release checks; see [DAG/nesting](dynamic-dag.md). Pure static compiler/interpreter/scheduler contracts remain available.

MessageBus, sync/async Inbox/Outbox and CommandAdapter accept structural composition. A2AClientPort allows a third-party client; transport does not execute work. Supply durable commit-before-return and stable identity guarantees, including return-None completion. See [remote handoff](remote-handoff.md).

TemporalRuntime registers Provider/ToolExecutor/EffectJournal independently of the local builder. New execution backends must declare a capability subset and their own authority, not reuse ExecutionStore as distributed locking. EffectJournal received/acknowledge must return None only after durable completion. See [Temporal](temporal-execution.md).


## 服务与异步执行控制

同步或原生异步的 submit/status/cancel 可通过 TaskControlBridge 统一调用，全部方法须使用同一模式，返回真实完成的 SDK DTO，Scope 与注册方法不能在 await 间漂移。桥接不使用线程模拟 LocalEngine、不隐式 drive 或关闭资源。PostgresInbox/PostgresOutbox 是共享交接的默认实现，用户实现可替换 AsyncInbox/AsyncOutbox，但须满足事务身份、容量和不可变完成契约。默认 LocalA2AService 接管本地 Engine/Inbox 并安全关闭；A2AApplication 借用远程资源。示例与契约见[异步交接](async-handoff.md)。

## Temporal 组件注册

使用 `TemporalRuntime` 的命名 TeamStrategy／Planner／PlanVerifier 注册表可替换默认策略，输出必须为已完成的类型化提案。显式扩展发布保存 identity／config／方法代码摘要，执行前后校验；模型 Planner 声明无工具的 AgentSpec，使用受管理子任务结果。RAG 复用 KnowledgeContext 的异步检索／校验端口，执行限制使用 TemporalExecutionPolicy。详见[分布式编排](temporal-composition.md)。这些注册表不自动发现插件，不执行隐藏的 Provider 调用，不承诺企业身份体系。

## 替换 Parser、Chunker 或原子知识存储

从 dev18 起，DocumentParser.parse 与 Chunker.split 是独立的纯同步结构化端口。每层有无需服务的默认实现；IngestionCoordinator 通过关键字参数替换组件，先冻结有界 DTO，再交给 IngestionKnowledgeStore／AsyncIngestionKnowledgeStore 原子保存。SourceDocument／ParsedDocument／ChunkSpan／PreparedIngestion／IngestionReceipt 分离原始来源、解析正文、位置与历史接受证据。借用 Store 的生命周期由宿主管理；原 KnowledgeStore.put 和默认分块行为保持。具体扩展示例、去重／CAS／取消／向量边界见[摄取指南](document-ingestion.md)。

## 替换 Embedding、融合或重排

新 HybridRetriever 明确传入来源 Store 与命名召回分支。每层只替换一个 Protocol 即可；融合／重排返回 ID 提案，原正文与来源仍归知识权威。RankFusion 同步纯计算，Reranker／AsyncReranker 明确模式，完成结果有界且冻结。现成离线 RRF／保序／词项重排不宣称语义模型能力。HTTP Embedding 需显式模型／维度／凭据和异步资源生命周期；配置、扩展及恢复见[混合检索指南](hybrid-retrieval.md)。
