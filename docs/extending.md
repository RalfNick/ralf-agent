# Ralf-Agent 扩展指南

版本：0.1.0.dev10；日期：2026-10-06。面向 SDK／适配器开发者。本指南描述执行、装配、召回和知识端口；企业适配与完整 M1 验收仍按 [实现清单](implementation-status.md) 分期。

完整目标要求每层交付公共契约、默认实现、替换示例和共同验收，见[通用框架能力矩阵](../architecture/viewpoints/framework-capabilities.md)。该矩阵保留 dev9 基线，规划、团队及高级数据端口仍未交付；下表列当前 SDK 能力，新增串行图见[静态 Workflow](static-workflows.md)。

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
| KnowledgeStore／EmbeddingProvider／VectorIndex | 注入 Retriever | 权威知识 CAS/TTL 与索引分离；模型身份、维度、来源过滤和显式重新索引 |
| ContextBuilder | `context_assembler=` | identity 与确定性 assemble；返回实际消息和 JSON Manifest |
| ExecutionStore v1 | 第一个构造参数 | 原子命令／事务、Run CAS、事件、预算、活跃 Session 和未知效果查询；不另建调度器 |
| CoordinatorLease | `coordinator=` | 同一执行权威只允许一个持有者，活跃调用结束前不能交出归属 |
| 当前工具授权 | `policy=` | 可信宿主同步授权函数，只允许返回 None；拒绝抛 AuthorizationDenied，任何其他返回值均拒绝 |

同步返回 `None` 表示检查已经执行并完成授权。上下文管理器、awaitable、generator、True／False、字典等不能表示授权；框架不进入它们，也不调用它们的任意生命周期方法。对已识别的 coroutine／generator 仅做关闭清理，然后报配置错误。

默认 `LocalEngine(SQLiteStore(path), ...)` 会创建 POSIX 文件租约和共享 SQLite 记忆。自定义存储通过端口接入，不需要 `.conn`／`.path`；同时显式注入 `coordinator`、`session_store`、`memory_store`。当前 ExecutionStore 方法是 Coordinator 线程内的同步事务操作；远程数据库需单独验证延迟、原子性和失败语义。

Harness／ToolExecutor 不需要首次使用者额外配置。自定义组件只变换提案或执行一个派发，不取得 Engine 的审批／预算／状态权威。DispatchEnvelope 和 EffectObservation 的 JSON 属性是独立视图；ModelRequest／DecisionProposal 是分离的输入数据，frozen 顶层不保证嵌套 JSON 深度不可变。具体签名、阶段与离线例子见 [执行组件指南](execution-components.md)。

模型层默认提供 Chat、DeepSeek 非思考 preset、Anthropic 文本/客户端工具及 Gemini 文本，见 [模型指南](model-adapters.md)。原生不能表达的消息字段明确拒绝；不靠丢弃 name、推理历史或签名来获得兼容。旧自定义 Provider 缺少预检或 streaming 仍可执行 complete。

默认组件也可通过 JSON/TOML RuntimeProfile 装配；ComponentRegistry 显式注册第三方工厂，BuildContext.own 接管同步 close 的附属客户端。RuntimeCatalog 不覆盖已注册版本，ProfiledEngine 根据 Run 保存的原 profile 解析。它不归档 Python 实现或后端数据，恢复仍需保留它们。完整例子、默认适配器、关闭重试和历史版本配置见 [运行装配](runtime-assembly.md)。

## 2. 远程记忆

远程后端优先使用对应的异步 Protocol，方法名称及返回结构与同步后端一致；引擎会等待返回。同步 SQLite／内存接口用于本地快速操作，不能把阻塞网络请求直接写进同步 `read/facts`。

对于已存在且线程安全的同步客户端，可显式桥接：

```python
from ralf_agent import ThreadedMemoryAdapter

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

`facts(scope, namespace)` 只返回当前 Scope 下未过期的已确认事实；`put_fact(..., expected_version)` 不静默覆盖其他写入。dev7 的原生内存／SQLite 提供 read_page/recall 及事实校验；远程后端可实现同步／异步同名端口。未实现新端口时 Legacy 桥仍全量读取，不能宣称底层有界。默认模型输入行为保留，需要显式配置 `MemoryRecallPolicy()` 才启用分页。知识库、检索器、向量索引和 Embedding 分别替换；实际签名、引用与规模边界见 [召回与 RAG](recall-and-rag.md)。Redis、PostgreSQL、托管向量数据库尚未提供现成适配器。

## 3. 身份与不可变发布

identity／backend_id 表达端点、数据库／namespace、模型、版本及影响行为的非秘密配置。不要存入 API key、连接凭据或用户隐私。独立内存实例默认具有不同身份；人为指定同一身份时，使用者负责后端语义保持一致。

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

存储 close 抛异常时，Engine 进入 close_failed，保留租约并拒绝 submit／drive／控制／读取操作；可以重试 close。存储已关闭但租约释放失败时只重试释放，不重复关闭存储。成功 close 可重复调用，原 Engine 始终不可再执行。自定义存储应允许部分关闭失败后的安全重试，自定义租约应按原持有者身份幂等释放。

追踪只覆盖框架托管的同步调用。自定义 async 适配器内部直接使用 asyncio.to_thread、创建自己的后台线程或交出外部调用后，必须自行保证取消、真实完成与资源归属契约；不能把仅取消等待当作实际工作已结束。

自建 Agent 的跨进程控制使用 `--factory module:callable`。同步工厂接收 db_path，返回符合 ExecutionEngine 的对象；工厂应放在可导入包中，或在仓库目录使用 `PYTHONPATH=.`。内置适配器可直接用 `--config runtime.toml` 和 `run --spec agent.toml`，两种入口互斥。完整可运行示例见 [custom_runtime.py](../examples/custom_runtime.py)；独立配置模板用 `ralf init my-agent --template config`。

SDK 入口程序应导入同一个配置模块，工具实现保留稳定的包／模块名。示例入口已经这样装配；在 `__main__` 重新定义工具后，再从其他模块加载同名函数，属于不同的发布身份。

CLI 的 `inspect/status/events` 使用只读 SQLite 和默认 Scope；不载入工厂、不取得执行租约。已注入 Harness／Executor 的恢复命令也必须使用原 factory。自定义 Scope／非 SQLite 的观察可使用 SDK `engine.status/events`，独立 Read API 尚未发布。

## 6. 接入验收与升级

新的适配器至少覆盖：隔离 Scope、重启后稳定身份、CAS 冲突、重复请求去重、未知成本保留、已确认效果不重跑、取消期间不新增后续调用、晚到证据不覆盖原结果、组件变化拒绝恢复。参考 `tests/test_memory.py`、`tests/test_extension_contracts.py`、`tests/test_engine.py` 中的真实数据库和异步测试。

dev8 保留 dev6/dev7 的 `local-4`、默认 Manifest、SQLite Schema v1 与调用方摘要，默认 Run 可以用原工厂续跑。Recall／Knowledge／planner／profile 仅在显式启用时增加固定身份；旧的无 profile Run 经 ProfiledEngine 恢复需明确的 legacy_factory，不能回退当前默认。改变策略或知识配置后，同一提交仍找回原回执，但继续执行拒绝不匹配配置。dev3–dev5 的 local-3 Run 可观察、取消及人工核验，续跑需原版本与配置。dev1／dev2 的旧 submit 摘要重放需原版本。没有自动 Run／摘要迁移；未知效果先在原日志核验。policy 继续仅允许同步返回 None 或抛拒绝异常。
