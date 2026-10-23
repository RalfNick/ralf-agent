# 常用 API 与 CLI 参考

[文档目录](README.md) · [核心概念](concepts.md) · [扩展指南](extending.md)

本页汇总常用 SDK 与 CLI 入口，公开 API 仍为预览契约，不替代各专题和端口契约。Local 内核与已启用绑定的版本身份分别固定；当前支持范围见[实现清单](implementation-status.md)，具体配置及生命周期以链接的专题指南为准。下文保留标注开发版本的演进说明。

## Local 应用入口

[完整使用与关闭指南](agent-api.md)覆盖 H2a 已实现的 Local stateless 子集。

| API | 使用方式与关键约束 |
| --- | --- |
| `AgentHarness(definition)` | 固定原生／绑定／复合声明；现有纯 Harness 策略不变，不隐藏 I/O |
| `Runtime(engine, owned=False, ...)` | 独立托管 Local 任务；from_profile/afrom_profile 支持原 Builder 与可信 Scope |
| `Agent(runtime=..., definition=...)`／`Agent(model=..., tools=..., db_path=...)` | 共享宿主或独立创建本地宿主；submit/run 必须提供 command_id |
| `AgentRun` | 在线观察／显式控制；pending 定位嵌套动作原所属 Run；关闭后须显式重连 |
| `RunRef`／`WaitResult`／`CloseReport` | 原权威／Scope／发布定位、观察结果、关闭责任；等待取消不取消业务 |
| `RunHandle` | 保留旧 submit 返回的定义 DTO；不改名、不替换成在线 AgentRun |

dev32 增加 [Agent.open_session／AgentSession／SessionRef](session-api.md)，同库原生／顺序 Turn 和 rebind 复用执行事务；更广的会话组合、deadline、queue、handoff 仍明确拒绝。dev33 [Temporal Agent API](temporal-agent-api.md)增加 Runtime.from_temporal、areference/aattach；原生／顺序远程入口采用固定 RPC 组件与 detach 关闭。dev34 H2c2 扩展到已注册 Graph／Team／Dynamic／嵌套定义，pending 携带实际子 Run 引用；通过 aattach 控制其原动作，父取消由服务器传播。

## 定义与装配

从 `relf_agent` 导入常用类型：

```python
from relf_agent import (
    AgentSpec,
    WorkflowSpec,
    LocalEngine,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
    OpenAIChatProvider,
    ModelResponse,
    ToolCall,
    Scope,
    InMemoryMemory,
    NativeHarness,
    PythonToolExecutor,
)
```

| API | 使用方式与关键约束 |
| --- | --- |
| `AgentSpec(name, instructions, tools=(), ...)` | 允许工具名与 Provider 别名固定；默认最多 8 次决策；output_schema 为可选 JSON Schema |
| `WorkflowSpec(name, steps, version="1")` | 非空 AgentSpec 顺序步骤；前步验收后的输出作为下一步输入 |
| `GraphWorkflowSpec(name, nodes, version="1", output=None, output_schema=None, max_concurrency=1)` | 不可变静态图，默认串行，2..32 显式并行；依赖、条件、输入／结果绑定与节点状态持久恢复 |
| `TeamSpec(name, members, strategy="sequential", ...)` | 有限 Agent／sequence／graph／team／dynamic 成员树、纯委派策略、child_budget/max_concurrency/max_depth，父子 Run 管理 |
| `DynamicWorkflowSpec(name, members, planner="rule", verifier="complete", ...)` | 有限委派计划，flat／DAG 模式、max_revisions/max_steps/max_concurrency/max_depth，Plan→Execute→Verify→Replan |
| `GraphNode`／`ValueRef`／`Literal`／`InputMap`／`BranchCondition` | Agent、纯变换或受管理 Tool 节点；明确缺失／null、依赖祖先引用与分支合并 |
| `ExecutionPlan`／`WorkflowCompiler`／`WorkflowInterpreter`／`WorkflowSelection` | 计划 v1／Tool v2 与纯编译／选择端口；默认 static，公共边界验证选择语义 |
| `NodeTransform`／`IdentityTransform` | 同步纯 JSON 计算；通过 workflow_transforms 注册，不执行外部效果 |
| `SQLiteStore(path, readonly=False)` | 本地执行事实；固定文件身份，拒绝硬链接；默认写模式启用 WAL |
| `LocalEngine(store, providers=..., tools=..., ...)` | 默认租约／记忆、NativeHarness 与 PythonToolExecutor；scope/session_store/memory_store/policy/context_assembler/harness/tool_executor 可注入；可选 recall_policy、recall_planner、knowledge、runtime_profile 默认 None |
| `ExecutionEngine` | 公共 submit/drive/status/events/approve/cancel/reconcile/wait_for_threads/close，不要求具体继承关系 |
| `RuntimeDiagnostics`／`RunDiagnostics` | 可选丰富诊断；返回独立 snapshot/manifest/release_digest/budget |
| `RuntimeProfile(name, version, providers, components={})` | 固定有限 JSON 声明，公开视图是副本；identity 摘要进入接受时的发布 |
| `RuntimeCatalog.register/set_default/resolve`／`load_catalog(path)` | 同版本内容不可覆盖；JSON/TOML 加载不执行代码 |
| `ComponentRegistry.register(kind, name, factory)`／`RuntimeBuilder.build(profile, db_path)` | 显式构造适配器；BuildContext.own 接管同步关闭资源，返回 RuntimeInstance |
| `ProfiledEngine(catalog, db_path, builder=None, ...)` | 按原 profile 路由任务；一次一个本地实例，缺失版本不回退新默认 |
| `RunReader`／`CommandReceiptReader` | 可替换只读任务端口；后者是可选控制回执查询能力，默认 SQLiteRunReader 两者均实现 |
| `load_spec(path)` | 严格 JSON/TOML Agent、sequence、graph、team 或 dynamic 声明；见[静态 Workflow](static-workflows.md)及[编排](orchestration.md) |
| `Scope(workspace="default", principal="local-owner")` | 可信宿主传入的作用域；不是企业身份认证 |
| `OpenAIChatProvider(model, ...)` | 异步 Chat Completions；base_url/timeout/token_parameter、temperature/top_p/stop/seed、stream/capabilities 可配置；密钥通过 api_key 或环境传入 |
| `DeepSeekChatProvider`／`AnthropicProvider`／`GeminiProvider` | 分别接入对应模型协议；思考模式、函数工具与原生续接按[模型接入](model-adapters.md)、[DeepSeek 思考](deepseek-thinking.md)及[续接指南](model-continuation.md)显式配置 |
| `ModelCapabilities`／`StreamingModelProvider`／`ModelStreamEvent` | text/tools/streaming 布尔能力；stream 是异步迭代 text 片段与唯一完整 response，提前结束须 aclose |
| `ModelResponse(output=..., tool_calls=..., usage=...)` | Provider 决策数据；工具提案使用 `ToolCall(name, arguments, call_id=None)` |

工具来源可单独替换，详见[受管理工具](managed-tools.md)：

| API | 契约 |
| --- | --- |
| `ToolDescriptor`／`ToolPolicy` | 固定远端 Schema 与宿主效果／审批策略；幂等写需明确保留参数 |
| `ToolSource`／`register_tool_source` | 异步发现／调用，选择性原子注册到 ToolRegistry；源由宿主管理 |
| `MCPTransport`／`MCPToolSource` | 可替换传输；保留 MCP 结果、校验固定描述与结构化输出 |
| `MCPStdioTransport` | POSIX argv 子进程、一次会话、有限超时与真实 worker 归属 |

执行组件可单独替换：

| API | 契约 |
| --- | --- |
| `Harness.prepare(spec, messages, tools) -> ModelRequest` | 同步纯数据变换；禁止模型／工具调用、I/O 和状态提交 |
| `Harness.propose(spec, response) -> DecisionProposal` | 从已收到响应提出 output／ToolCall；内核仍作完整验收 |
| `NativeHarness()` | 默认透明转交原始请求／提案 |
| `ToolExecutor.execute(envelope) -> EffectObservation` | async，执行一个派发 Attempt，返回有限 JSON 证据 |
| `ToolExecutor.reconcile(envelope) -> EffectObservation \| None` | async，核验原效果，未知返回 None |
| `PythonToolExecutor(tools)` | 默认执行 Registry 中固定 Manifest 的可信 Python 工具 |
| `DispatchEnvelope(context, tool_manifest, arguments, operation_digest)` | 固定的派发上下文与 JSON 数据；对象不是权限令牌 |
| `EffectObservation(result, source="tool-handler")` | 未采纳的确认结果；result 视图与内部快照分离 |

这些类型也从 `relf_agent` 导入。组件必须提供非空有限 JSON identity，影响行为的非秘密配置／版本固定在 Manifest。完整装配和阶段说明见 [执行组件指南](execution-components.md)。

没有工具提案时，输出必须完整且非空白。合法 JSON 的 `0`／`False`／空容器可以作为结果；`None` 需要显式允许 null 的输出 Schema。启用 Schema 时，字符串先按 JSON 解析，然后校验。

## Run、命令与观察

装配 engine 后，SDK 的基本生命周期为：

```python
# 在 async 函数中，engine 由可信配置工厂构造。
spec = AgentSpec("assistant", "根据输入给出完整结果。")
handle = engine.submit(spec, "任务输入", command_id="request-001", budget=16)
snapshot = await engine.drive(handle.run_id)
print(snapshot.state, snapshot.result, snapshot.error)
```

| 方法 | 结果和语义 |
| --- | --- |
| `submit(spec, input, *, command_id, budget=32, session_id=None)` | 返回 RunHandle；记录提交，不隐式启动 drive；定义／输入／预算／Session 构成请求身份。Session 省略时用 Run ID，显式指定必须为非空字符串，保留原值 |
| `await drive(run_id)` | 推进原 Run 到终态或等待；返回 RunSnapshot；同 Run 未完成调用阻止第二次执行 |
| `status(run_id)` | 当前 Scope 的 RunSnapshot：state、result、error、pending、actions |
| `events(run_id, *, after=0, limit=1000)` | 有序 RunEvent；after 使用最后 seq；event_id 为 run_id:seq |
| `approve(run_id, action_id, target_digest, *, command_id, approved=True)` | 保存本地所有者审批决定，返回 CommandReceipt；approved=False 表示拒绝 |
| `cancel(run_id, *, command_id)` | 保存停止后续调度的决定，不撤销已派发效果 |
| `reconcile(run_id, action_id, result, *, command_id)` | 明确确认未知工具效果，结果必须来自已核实的业务证据 |
| `await wait_for_threads()` | 等待框架管理的实际同步调用退出，不取消 drive Task、不释放租约 |
| `close()`／`with engine` | 关闭 Store 并释放租约；活动调用阻止关闭，失败关闭仅允许重试关闭 |

RunHandle 包含 `run_id` 和 `receipt`，`to_dict()` 便于 JSON 输出；`handle.status(engine)`／`handle.events(engine, after)` 是观察便捷方法。CommandReceipt 的 `record_state/apply_state` 描述命令处理，不等同于 Run 成功。

Engine 拥有执行 Store 和 Coordinator。显式注入的 Provider、ToolExecutor、客户端及记忆组件由调用者管理和关闭。恢复时保留稳定的工厂模块、配置身份和原数据库路径。

模型 response_received／工具 receipt_received 表示证据已独立保存、尚未完成采纳。恢复使用原 received_response／effect_observation，不重发对应调用。取消后的证据仍可结算和采纳，不产生后续 Action、不重新打开终态。人工 reconcile 保持命令／结果同事务；详情见 [恢复指南](recovery-guide.md)。

## 工具、授权和记忆

```python
def lookup(arguments, context):
    return {"record": arguments["record"], "status": "open"}


tools = ToolRegistry()
tools.register(
    ToolSpec(
        "lookup",
        "读取记录",
        {
            "type": "object",
            "properties": {"record": {"type": "string"}},
            "required": ["record"],
            "additionalProperties": False,
        },
        effect="read_only",
        version="1",
        config={"dataset": "records:v1"},
    ),
    lookup,
)
```

handler 接收 JSON 参数和 InvocationContext。Context 提供 scope、run_id、action_id、attempt_id、effect_key 和 execution_epoch。业务重试／核验使用原 effect_key；effect 可选 read_only、idempotent_write、queryable_write、unqueryable_write。需要审批时设置 `requires_approval=True`，核验函数通过 `register(..., reconciler=...)` 注入。SDK 不隐藏业务重试。

`policy(scope, tool_spec, arguments) -> None` 必须同步完成授权。拒绝抛 `relf_agent.errors.AuthorizationDenied`；True／False、上下文对象、awaitable 等返回值一律拒绝。默认 Python 工具为可信宿主代码；隔离执行需要显式配置 [Sandbox 工具源](sandbox.md)，不自动隔离任意 Python handler。

| 记忆方法 | 契约 |
| --- | --- |
| `read(scope, session_id)` | 返回 `(revision, messages)` |
| `append(scope, session_id, message, *, expected_revision, message_id)` | CAS 与 message_id 去重；同 ID 不同内容冲突；返回提交版本 |
| `facts(scope, namespace)` | 返回未过期事实，含 key、value、version、expires_at |
| `put_fact(scope, namespace, key, value, *, expected_version, expires_at=None)` | 首次写 expected_version=0；CAS 成功后返回新版本；expires_at 为有限 Unix 秒 |

`InMemoryMemory` 和 `SQLiteMemory` 提供本地实现；RedisMemory 与 PostgresMemory 提供异步远程实现。线程安全同步后端可用 ThreadedMemoryAdapter。`backend_id` 必须稳定且不含秘密。可选依赖、初始化与资源归属见[远程数据](remote-data.md)。

召回与知识常用类型也从 `relf_agent` 导入：

| API | 契约 |
| --- | --- |
| `RecallQuery(max_items=32, max_chars=8000, scan_limit=256, text=None, cursor=None)` | 完整记录、canonical JSON 字符与候选额度；cursor 固定查询及 Scope |
| `MemoryRecallPolicy(facts=..., session=..., max_pages=1)` | Engine 显式启用分页；跨页共享原额度，初始查询无 cursor |
| `RecallPlanner.plan(scope, namespace, session_id, text)` | 纯同步返回 MemoryRecallPolicy；实际查询持久保存，未知重试不重新规划 |
| `read_page(scope, session_id, query)`／`recall(scope, namespace, query)` | 返回 RecallPage；同步／异步端口，原生内存／SQLite 默认实现 |
| `validate_facts(scope, namespace, items) -> None` | 可选同步／异步事实有效性端口；内置按当前 key/version/TTL 校验；缺失时 Legacy 全量核对 |
| `Document(document_id, text, source_uri="", metadata={})` | 权威知识输入；有限 JSON metadata，正文不能为空 |
| `InMemoryKnowledgeStore()`／`SQLiteKnowledgeStore(path, chunk_size=1000, overlap=100)` | scoped put/get/get_chunk/chunks/delete/lexical；put/delete 使用 expected_version CAS |
| `RetrievalQuery(text, limit=5, max_chars=8000)` | 限制检索返回；RetrievalResult 含来源、版本、分数和 mode |
| `KnowledgeContext(retriever, namespace="default", limit=5, max_chars=8000)` | async references/validate；注入 knowledge=；来源按 Scope/版本/TTL 校验 |
| `KnowledgeContextPort` | 可直接实现 identity/limit/max_chars/async references/validate，无需继承默认 Facade |
| `SkillSelector`／`LexicalSkillSelector(version="1")` | 固定普通 JSON identity、纯同步 select(query, entries, *, limit)→普通唯一名称列表；默认词项／中文 bigram，有界1–100，无模型调用 |
| `SandboxExecutionRejected` | 原生拒绝的 exact bool handler_not_started；确认未启动才撤销责任，未知启动保留到停止证据 |
| `SandboxProvider`／`SandboxRequest`／`SandboxObservation`／`SandboxResult` | 固定 Scope 与宿主调用身份的 async run/observe/stop；完成 DTO 保留真实停止证据，argv／时间／输出有界 |
| `DockerSandbox(socket_path, image, version="1")` | 显式已启动 Linux Docker 和已安装 SHA256 镜像；aopen 校验服务／镜像，受限临时容器，无隐藏拉取 |
| `SandboxToolSource(provider, version="1")` | 借用 Provider，复用原受管理 sandbox_run；宿主限额，取消等待保留实际操作，aclose 可重试，不关闭共享 Provider |
| `SandboxBindingResource(registry, names=[...])` | 借用原 native Sandbox 工具；每 Agent ref／disabled 只收紧 grants，不扩权、不执行或拥有资源 |
| `SkillDirectoryRetriever(catalog, *, version, names=None, selector=None, max_entries=1000)` | 借用原 SkillCatalogPort，原 async retrieve/validate 与 Knowledge DTO；被动元数据／Scope／names／来源固定，不读取正文或注册工具；见[目录发现](skill-discovery.md) |
| `LexicalRetriever(store)` | 默认中英文词法检索，无远程模型调用 |
| `EmbeddingProvider`／`VectorIndex` | 显式注入 async embed 与 scoped 索引；索引不保存知识正文 |
| `VectorRetriever(store, index, embedding)` | 显式 index_document 后检索；回读有效权威来源 |
| `InMemoryVectorIndex(dimensions=...)`／`SQLiteVectorIndex(path, dimensions=...)` | 本地真实 cosine 线性检索；维度与有限非零向量校验 |
| `RedisMemory.connect(url, backend_id=..., prefix="ralf", timeout=10)` | async owned 客户端；构造器借用客户端，Lua CAS/去重、逻辑 TTL、分页 |
| `PostgresMemory.connect(dsn, backend_id=...)` | async owned 连接；显式 initialize，事务 CAS/去重、逻辑 TTL、分页 |
| `PostgresKnowledgeStore.connect(dsn, backend_id=..., chunk_size=1000, overlap=100)` | async 文档权威；显式 initialize，CAS/TTL/删除版本和词法检索 |
| `QdrantVectorIndex(url, collection=..., dimensions=..., backend_id=..., client=None)` | async initialize/upsert/search/delete_document/aclose；固定 Cosine，Scope 过滤，失败关闭可重试 |
| `HashEmbeddingProvider(dimensions=128)` | async 确定性词项散列基线，可替换 EmbeddingProvider；不作为语义模型 |

Knowledge／Vector 组件由应用管理生命周期。召回输出额度不限制所有底层 I/O、embedding 费用或完整 Run 的历史读取。完整例子和兼容要求见 [召回与 RAG](recall-and-rag.md)。

## CLI

全局参数置于子命令前：`relf --db PATH --factory MODULE:CALLABLE --format text COMMAND ...`。默认 JSON；text 适合终端阅读。工厂只用于显式可信配置的执行／控制，接收 db_path 并返回 LocalEngine。

| 子命令 | 用途 |
| --- | --- |
| `init DIRECTORY` | 在新／空目录生成独立离线 Agent 项目；从目标目录外执行 |
| `demo --ticket INC-001 [--command-id ID]` | 内置离线测试案例；使用自己的 Demo 配置，不接收 factory |
| `inspect RUN_ID` | 只读简要诊断、pending、unresolved_effects、recorded_evidence 和后续命令 |
| `status RUN_ID` | 只读完整 RunSnapshot |
| `events RUN_ID [--after SEQ] [--limit N]` | 只读事件分页，每页最多 1000 |
| `approve RUN_ID ACTION_ID --digest DIGEST --command-id ID [--reject]` | 显式审批决定 |
| `resume RUN_ID` | 原工厂下继续执行 |
| `cancel RUN_ID --command-id ID` | 显式取消 |

CLI 没有独立的 submit／reconcile／增额命令；新任务通过生成项目入口或 SDK 提交。CLI 观察仅支持默认 Scope／SQLite。常见 typed error 从 `relf_agent.errors` 导入，CLI 错误输出到 stderr、返回 2；成功处理命令返回 0，仍需检查 Run state。

`GraphWorkflowSpec(..., max_concurrency=1)` 默认串行，2..32 显式并行。`WorkflowScheduler`／`StaticWorkflowScheduler` 返回 detached `WorkflowBatch`；通过 Engine 参数或 Profile 的 `workflow_scheduler` 组件替换。节点隔离与恢复见[并行指南](parallel-workflows.md)。

## 异步装配（dev13）

AsyncLifecycle.aclose、ComponentRegistry.register_async、RuntimeBuilder.abuild、BuildContext.own_async 和 RuntimeInstance.aclose/async with 是显式 SDK 入口。原 ExecutionEngine/Store/Coordinator 仍同步关闭；同步 CLI/ProfiledEngine 不路由异步工厂。归属、事件循环和失败/取消重试见[异步装配](async-assembly.md)。

## 规划与团队（dev14）

| API | 契约 |
| --- | --- |
| `TeamStrategy.select(TeamRequest) -> TeamSelection` | 纯同步提出 ChildCall 或最终 JSON；通过 team_strategies 映射注入 |
| `SequentialTeam`／`RouterTeam`／`SupervisorTeam` | 默认顺序、显式路由、Worker 并行后 Supervisor 汇总 |
| `Planner.plan(PlanningRequest, AgentCaller) -> PlanProposal \| DAGProposal \| PlanningConclusion \| None` | async 提案；None 仅允许实际子调用尚待恢复时返回 |
| `RulePlanner`／`ModelPlanner` | 默认有限成员计划；受管理 tool-free 模型子 Run，沿用审批/预算/响应恢复 |
| `PlanProposal(steps)`／`PlanStep(id, member, input)` | 固定有限 JSON、allowlist、唯一 ID；收到提案与修订采纳分开保存 |
| `PlanVerifier.verify(PlanningRequest) -> Verification` | 纯同步完成/失败/重规划判断；CompleteVerifier 默认取最后 Worker 结果 |
| `Verification(status, result=None)` | status 为 succeeded/failed/replan，修订/步骤/总预算有界 |

TeamRequest、PlanningRequest、ChildCall、TeamSelection 与上述类型均从公共包导入。Planner 的 caller 只允许注册的 @planner Agent，遵守父并发额度；业务 Worker 在采纳计划后委派。child_budget 先从父额度整体预留，未知效果保守保留；父失败/取消传播到孩子。审批/reconcile 针对真实 child Run，恢复驱动父 Run；详情见[编排指南](orchestration.md)。

## dev15 DAG, transport and distributed ports

DAGNode/DAGProposal, RuleDAGPlanner/ModelDAGPlanner and PlanningConclusion extend the existing Planner boundary. LocalEngine.patch_plan performs scoped idempotency/CAS. See [DAG](dynamic-dag.md) for typed bindings and nested member support.

MessageBus with InMemoryMessageBus/RedisStreamsBus; Inbox/AsyncInbox and Outbox/AsyncOutbox with SQLite defaults; CommandAdapter with LocalCommandAdapter/AsyncCommandAdapter; EngineCommandDispatcher and consume_delivery. Public validation/call helpers enforce native async vs completed sync boundaries without inheritance. A2AClientPort/A2AClient, A2AApplication and A2AToolSource expose the fixed polling subset. See [handoff](remote-handoff.md).

AsyncExecutionEngine/AsyncRuntimeDiagnostics are separate from synchronous local ports. TemporalEngine, TemporalRuntime, build_temporal_worker, replay_temporal_history and EffectJournal/PostgresEffectJournal provide explicit registered distributed execution. See the [capability subset](temporal-execution.md). EvaluationLimits/evaluate_planning/load_planning_cases/score_planning_proposal and relf-evaluate-planning expose [proposal evaluation](planning-evaluation.md).


## 异步交接与服务

SyncTaskControls/AsyncTaskControls 与 TaskControlBridge 是独立的完成控制端口，支持结构化委托和可调用对象；不转移执行权威或资源所有权。PostgresInbox/PostgresOutbox.connect + initialize 提供共享持久交接，LocalA2AService 提供单机 ASGI lifespan、drive 跟踪与真实 handler drain。`relf init --template a2a` 生成可编辑独立服务。参数、容量、重放与远程资源关闭见[异步交接](async-handoff.md)。

## 分布式编排与业务评测

`TemporalRuntime(..., team_strategies={}, planners={}, plan_verifiers={}, knowledge=None, execution_policy=None)` 提供显式组件替换；`runtime.orchestration_release` 固定扩展发布，配合 `build_temporal_worker(..., release=release)` 与 `TemporalEngine(..., release=release)`。原生默认用 `runtime.manifest`。`TemporalExecutionPolicy` 是不可变的每任务限制。`patch_plan` 使用原计划修订号 CAS；审批与核验针对实际叶子 Run。详见 [分布式指南](temporal-composition.md)。

`evaluate_business(provider=None, *, cases=None, limits=None, evidence_dir=None, offline=False, prices=None)` 默认不调用模型；`load_business_cases(path=None)` 返回独立任务集。CLI 为 `relf-evaluate-business`；[评测指南](business-evaluation.md)说明预算与结果边界。

## Document ingestion (dev18)

Public pure ports: `DocumentParser.parse(SourceDocument) -> ParsedDocument`, `Chunker.split(ParsedDocument) -> tuple[ChunkSpan, ...]`; defaults `TextDocumentParser`, `CharacterChunker`, `ParagraphChunker`. `IngestionCoordinator(store, parser=None, chunker=None)` borrows a sync/async atomic store; `await ingest(scope, namespace, source, command_id=..., expected_version=..., expires_at=None)` returns immutable `IngestionReceipt`.

`IngestionKnowledgeStore` and `AsyncIngestionKnowledgeStore` expose `ingest(scope, namespace, PreparedIngestion, command_id=...)` and `ingestion_receipt(scope, namespace, command_id)`. In-memory/SQLite/PostgreSQL implement them; vector indexing is separate. DTOs and examples, bounds, commit/replay/CAS and parsed-character locations are documented in the [ingestion guide](document-ingestion.md).

## Hybrid retrieval (dev19)

`OpenAIEmbeddingProvider.embed` preserves the async vector-list port; `embed_result` adds immutable `EmbeddingResponse` with per-request usage. `RankFusion` / `RRFFusion` return `FusionRank`; `Reranker` / `AsyncReranker`, `PreserveOrderReranker` / `TokenOverlapReranker` propose only existing candidate IDs. `HybridRetriever(store, retrievers, ...)` uses existing RetrievalQuery/Result and validates the source authority around all ranking awaits. See [guide](hybrid-retrieval.md) for bounds, borrowed/owned lifecycle, failure modes and additive factory declarations.

## Context and explicit artifacts (dev20)

MessageCounter, ContextMeasure, ContextBudgeter, WholeGroupBudgeter,
CanonicalCharacterCounter, UTF8TokenEstimator, ContextSummarizer, ContextSummary,
ExcerptContextSummarizer, BudgetedContextAssembler and optional
ContextRequestValidator provide pure opt-in context assembly/actual-request
measurement. ArtifactReference, ArtifactStore/AsyncArtifactStore,
InMemoryArtifactStore and SQLiteArtifactStore provide explicit scoped JSON
storage. Structural extension contracts, defaults and limits are documented in
[context/artifacts](context-artifacts.md). No implicit model summaries,
automatic fact extraction or Temporal custom context support is claimed.

## Managed memory, summaries and Temporal context (dev21)

MemoryExtractor, RuleMemoryExtractor, ModelMemoryExtractor, FactProposal, MemoryAdmissionPolicy and MemoryPipeline provide explicit successful-Run consolidation over CAS/recall/validation ports. ManagedModelSummarizer, ManagedSummary and FrozenContextSummarizer bridge durable tool-free model Runs to pure context assembly. See [managed memory](managed-memory.md) and [Temporal registration](temporal-custom-context.md). Chat Completions/DeepSeek adapters accept explicit `json_mode=True` for non-streaming JSON objects; output Schema and semantic checks still belong to adoption.

## dev22 model and typed-tool APIs

OpenAIResponsesProvider implements the existing text/function Provider and streaming ports. infer_tool_schema and ToolRegistry.register_function/tool bridge bounded JSON annotations/keyword calls to existing tool dispatch. evaluate_model_compatibility runs managed narrow scenarios; no provider returns not_run. See [contracts, examples and limits](sdk-model-tools.md).

## Invocation observation and durable events

InvocationRecord/InvocationMiddleware, NoopMiddleware/LoggingMiddleware and
MiddlewareProvider/MiddlewareToolExecutor provide opt-in existing-port wrappers.
EventCursor/EventEnvelope, SyncRunEventSource/AsyncRunEventSource and
RunEventSubscription provide bounded scoped pull/reconnect and SSE encoding.
See [middleware and events](middleware-and-events.md) for defaults, exact schemas,
configuration, borrowed lifecycle and installed CLI/template examples.

## Per-Agent bindings (dev25 H1a)

AgentDefinition/BoundDefinition and AgentBindingDescriptor/BindingSelection are additive public values.
BindingCatalog holds scoped borrowed components; LocalEngine.binding_capabilities describes the supported subset.
See [binding examples and refusal matrix](agent-bindings.md); Agent/Runtime Facade remains target-only.

## Local 完成验证

`LocalEngine(..., verifier=None)` 默认保持 Schema 完成语义。`CompletionVerifier.verify(CompletionRequest) -> CompletionVerdict` 支持纯同步接受／拒绝／有界重试；`SchemaCompletionVerifier` 与 `ToolReceiptVerifier` 为默认适配器。Verifier 角色可按 Agent 绑定并由 Profile 装配，详见[完成验证](completion-verification.md)。

## Local 每 Agent 执行限制

`LocalEngine(..., limits=None)` 的宿主上限与 `limits` Agent 绑定始终取交集；`FixedAgentLimits(max_decisions=None,max_context_chars=None,max_tool_actions=None)` 是 opt-in 默认，`AgentLimitsPolicy.propose(AgentSpec)->AgentLimitProposal` 可替换。接受时固定 caps，执行读取原发布；Profile 的 limits/fixed 适配及声明路径见[教程](agent-limits.md)。

## Temporal 声明装配

`TemporalProfile`／`TemporalProfileCatalog.from_file` 是纯不可变声明和版本查找；`TemporalRuntimeBuilder.abuild` 复用明确工厂与原执行权威，返回 `TemporalRuntimeAssembly`。Assembly 提供固定 `profile/scope/release/capabilities`、`start_worker/create_engine/aclose` 与执行前 `detach_components`。Owned 清理、Scope／队列绑定、线程及原通知排空、远程数据和默认关闭开关见[完整指南](temporal-profiles.md)。

`AuditRecord`／`AuditSink`、`InMemoryAuditSink` 与 `ServiceAudit` 提供可选的有界RPC脱敏观察；`A2AApplication(..., audit=...)` 默认关闭，`LocalA2AService`透传同一选项。替换与持久性边界见[服务审计](service-audit.md)。

`LocalEngine.compact_messages(run_id, *, command_id)` 在原SQLite事务中压缩一个普通成功Agent的冗余工作消息，返回原CommandReceipt；原效果／回执／事件保留，复杂恢复组合明确拒绝。边界见[Local保留](local-retention.md)。
