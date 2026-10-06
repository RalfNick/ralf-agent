# 常用 API 与 CLI 参考

版本：0.1.0.dev7／local-4。公开 API 为预览契约；有界召回、本地 RAG 和独立接收／采纳有本地行为证据，完整 M1 未完成。已交付边界见 [实现清单](implementation-status.md)，适配器要求见 [扩展指南](extending.md)。以下为常用入口，不替代端口契约。

## 定义与装配

从 `ralf_agent` 导入常用类型：

```python
from ralf_agent import (
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
| `SQLiteStore(path, readonly=False)` | 本地执行事实；固定文件身份，拒绝硬链接；默认写模式启用 WAL |
| `LocalEngine(store, providers=..., tools=..., ...)` | 默认租约／记忆、NativeHarness 与 PythonToolExecutor；scope/session_store/memory_store/policy/context_assembler/harness/tool_executor 可注入；可选 recall_policy、knowledge 默认 None |
| `Scope(workspace="default", principal="local-owner")` | 可信宿主传入的作用域；不是企业身份认证 |
| `OpenAIChatProvider(model, ...)` | 异步单次 Chat Completions 请求；可配置 base_url、timeout、token_parameter；密钥通过 api_key 或环境传入 |
| `ModelResponse(output=..., tool_calls=..., usage=...)` | Provider 决策数据；工具提案使用 `ToolCall(name, arguments, call_id=None)` |

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

这些类型也从 `ralf_agent` 导入。组件必须提供非空有限 JSON identity，影响行为的非秘密配置／版本固定在 Manifest。完整装配和阶段说明见 [执行组件指南](execution-components.md)。

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
| `submit(spec, input, *, command_id, budget=32, session_id=None)` | 返回 RunHandle；记录提交，不隐式启动 drive；定义／输入／预算／Session 构成请求身份 |
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

`policy(scope, tool_spec, arguments) -> None` 必须同步完成授权。拒绝抛 `ralf_agent.errors.AuthorizationDenied`；True／False、上下文对象、awaitable 等返回值一律拒绝。工具仍为可信宿主 Python 代码，当前没有沙箱。

| 记忆方法 | 契约 |
| --- | --- |
| `read(scope, session_id)` | 返回 `(revision, messages)` |
| `append(scope, session_id, message, *, expected_revision, message_id)` | CAS 与 message_id 去重；同 ID 不同内容冲突；返回提交版本 |
| `facts(scope, namespace)` | 返回未过期事实，含 key、value、version、expires_at |
| `put_fact(scope, namespace, key, value, *, expected_version, expires_at=None)` | 首次写 expected_version=0；CAS 成功后返回新版本；expires_at 为有限 Unix 秒 |

`InMemoryMemory` 和 `SQLiteMemory` 提供参考实现。远程记忆优先使用异步端口；线程安全同步后端可用 ThreadedMemoryAdapter。`backend_id` 必须稳定且不含秘密。Redis／PostgreSQL／托管向量库适配器尚未交付。

召回与知识常用类型也从 `ralf_agent` 导入：

| API | 契约 |
| --- | --- |
| `RecallQuery(max_items=32, max_chars=8000, scan_limit=256, text=None, cursor=None)` | 完整记录、canonical JSON 字符与候选额度；cursor 固定查询及 Scope |
| `MemoryRecallPolicy(facts=..., session=..., max_pages=1)` | Engine 显式启用分页；跨页共享原额度，初始查询无 cursor |
| `read_page(scope, session_id, query)`／`recall(scope, namespace, query)` | 返回 RecallPage；同步／异步端口，原生内存／SQLite 默认实现 |
| `validate_facts(scope, namespace, items) -> None` | 可选同步／异步事实有效性端口；内置按当前 key/version/TTL 校验；缺失时 Legacy 全量核对 |
| `Document(document_id, text, source_uri="", metadata={})` | 权威知识输入；有限 JSON metadata，正文不能为空 |
| `InMemoryKnowledgeStore()`／`SQLiteKnowledgeStore(path, chunk_size=1000, overlap=100)` | scoped put/get/get_chunk/chunks/delete/lexical；put/delete 使用 expected_version CAS |
| `RetrievalQuery(text, limit=5, max_chars=8000)` | 限制检索返回；RetrievalResult 含来源、版本、分数和 mode |
| `KnowledgeContext(retriever, namespace="default", limit=5, max_chars=8000)` | async references/validate；注入 knowledge=；来源按 Scope/版本/TTL 校验 |
| `LexicalRetriever(store)` | 默认中英文词法检索，无远程模型调用 |
| `EmbeddingProvider`／`VectorIndex` | 显式注入 async embed 与 scoped 索引；索引不保存知识正文 |
| `VectorRetriever(store, index, embedding)` | 显式 index_document 后检索；回读有效权威来源 |
| `InMemoryVectorIndex(dimensions=...)`／`SQLiteVectorIndex(path, dimensions=...)` | 本地真实 cosine 线性检索；维度与有限非零向量校验 |

Knowledge／Vector 组件由应用管理生命周期。召回输出额度不限制所有底层 I/O、embedding 费用或完整 Run 的历史读取。完整例子和兼容要求见 [召回与 RAG](recall-and-rag.md)。

## CLI

全局参数置于子命令前：`ralf --db PATH --factory MODULE:CALLABLE --format text COMMAND ...`。默认 JSON；text 适合终端阅读。工厂只用于显式可信配置的执行／控制，接收 db_path 并返回 LocalEngine。

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

CLI 没有独立的 submit／reconcile／增额命令；新任务通过生成项目入口或 SDK 提交。CLI 观察仅支持默认 Scope／SQLite。常见 typed error 从 `ralf_agent.errors` 导入，CLI 错误输出到 stderr、返回 2；成功处理命令返回 0，仍需检查 Run state。
