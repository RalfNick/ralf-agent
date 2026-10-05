# 常用 API 与 CLI 参考

版本：0.1.0.dev5。公开 API 为预览契约；已交付边界见 [实现清单](implementation-status.md)，适配器要求见 [扩展指南](extending.md)。以下为常用入口，不替代端口契约。

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
)
```

| API | 使用方式与关键约束 |
| --- | --- |
| `AgentSpec(name, instructions, tools=(), ...)` | 允许工具名与 Provider 别名固定；默认最多 8 次决策；output_schema 为可选 JSON Schema |
| `WorkflowSpec(name, steps, version="1")` | 非空 AgentSpec 顺序步骤；前步验收后的输出作为下一步输入 |
| `SQLiteStore(path, readonly=False)` | 本地执行事实；固定文件身份，拒绝硬链接；默认写模式启用 WAL |
| `LocalEngine(store, providers=..., tools=..., ...)` | 默认使用 Store 提供的租约和记忆；scope/session_store/memory_store/policy/context_assembler 可注入 |
| `Scope(workspace="default", principal="local-owner")` | 可信宿主传入的作用域；不是企业身份认证 |
| `OpenAIChatProvider(model, ...)` | 异步单次 Chat Completions 请求；可配置 base_url、timeout、token_parameter；密钥通过 api_key 或环境传入 |
| `ModelResponse(output=..., tool_calls=..., usage=...)` | Provider 决策数据；工具提案使用 `ToolCall(name, arguments, call_id=None)` |

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

Engine 拥有执行 Store 和 Coordinator。显式注入的 Provider、客户端及记忆组件由调用者管理和关闭。恢复时保留稳定的工厂模块、配置身份和原数据库路径。

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

`InMemoryMemory` 和 `SQLiteMemory` 提供参考实现。远程记忆优先使用异步端口；线程安全同步后端可用 ThreadedMemoryAdapter。`backend_id` 必须稳定且不含秘密。Redis／PostgreSQL／向量适配器尚未交付。

## CLI

全局参数置于子命令前：`ralf --db PATH --factory MODULE:CALLABLE --format text COMMAND ...`。默认 JSON；text 适合终端阅读。工厂只用于显式可信配置的执行／控制，接收 db_path 并返回 LocalEngine。

| 子命令 | 用途 |
| --- | --- |
| `init DIRECTORY` | 在新／空目录生成独立离线 Agent 项目；从目标目录外执行 |
| `demo --ticket INC-001 [--command-id ID]` | 内置离线测试案例；使用自己的 Demo 配置，不接收 factory |
| `inspect RUN_ID` | 只读简要诊断、pending 和后续命令 |
| `status RUN_ID` | 只读完整 RunSnapshot |
| `events RUN_ID [--after SEQ] [--limit N]` | 只读事件分页，每页最多 1000 |
| `approve RUN_ID ACTION_ID --digest DIGEST --command-id ID [--reject]` | 显式审批决定 |
| `resume RUN_ID` | 原工厂下继续执行 |
| `cancel RUN_ID --command-id ID` | 显式取消 |

CLI 没有独立的 submit／reconcile／增额命令；新任务通过生成项目入口或 SDK 提交。CLI 观察仅支持默认 Scope／SQLite。常见 typed error 从 `ralf_agent.errors` 导入，CLI 错误输出到 stderr、返回 2；成功处理命令返回 0，仍需检查 Run state。
