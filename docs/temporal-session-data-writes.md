# Temporal 原生／顺序持久会话

状态：dev66 原生／顺序子集已验收。范围是原生 Agent 和顺序 Workflow；完整
[外置 Session 契约](../architecture/specs/temporal-session-data-contract.md)仍包含未交付的复合根／成员地址。

`TemporalRuntime(session_writes=True)` 显式启用原 History 管理的保存协议。
默认关闭，既有 dev65 只读资源和 History Conversation 保持原行为。
Worker 注册 `session_store` 或 BindingCatalog 的 session 资源；每 Agent 可选择 inherit/ref/disabled。
持久顺序会话的所有步骤必须选择相同实际来源和 namespace；不能部分 disabled 或更换数据位置。
高级 Graph／Team／Dynamic／嵌套选中外置来源时继续在接受前拒绝。

```python
from ralf_agent import AgentSpec, Runtime, Scope, SQLiteMemory, ToolRegistry
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal import TemporalEngine, build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime


async def example(client):
    source = SQLiteMemory("session-data.sqlite")
    execution = TemporalRuntime(
        providers={"default": EchoProvider("offline")},
        tools=ToolRegistry(),
        session_store=source,
        enable_sessions=True,
        session_writes=True,
    )
    engine = TemporalEngine(
        client,
        task_queue="my-agent",
        release=execution.manifest,
        scope=Scope("app", "developer"),
    )
    host = Runtime.from_temporal(engine)
    try:
        async with build_temporal_worker(client, task_queue=engine.task_queue, runtime=execution):
            session = await host.open_session(
                AgentSpec("answer", "Answer"), "chat", command_id="open"
            )
            turn = await session.submit("hello", command_id="first")
            result = await turn.wait(wait_timeout=30)
            # 查看 result.snapshot；UNKNOWN 使用显式 engine.drive 核验原保存。
            print(result.snapshot.state)
            await execution.close_session_execution()
    finally:
        # 未完成时抛 CloseIncomplete，并保留下列借用资源供宿主继续处理。
        await execution.close_session_execution()
        await host.aclose()
        await engine.aclose()
        source.store.close()
```

示例要求已有真实 Temporal Client／Service。SQLite 只用于同宿主恢复，必须留在创建线程。
停止 Worker 前须等待实际保存操作和结束通知；`close_session_execution(wait_timeout=...)`
不能完成时抛 `CloseIncomplete`，宿主必须继续持有资源并重试关闭。注册的数据客户端均为 borrowed；
ExecutionOwner 只拥有实际处理器和内部线程池，不关闭数据库／Redis 池。
调用方 wait 取消只结束观察；业务取消用原 Run 命令。取消后未结束保存仍保持 Session busy。

原 Run 先记录有界完整写意图、原 context revision、固定来源／Scope／地址、稳定 message_id
和模型响应摘要。独立阶段 inspect → admitted CAS append → verify → received receipt → adopt，
最后才允许步骤成功。每次实际 append 预留一个 execution credit，不是货币费用上限。
核验不能重跑模型／工具；ACK 不是精确回执，已提交记录也不是实际 handler 结束的证明。
UNKNOWN 保留原额度和 Turn 占用；缺失记录、CAS 基点未变且已证明原 handler 结束时，
活跃 Run 才能重试相同原意图／ID。取消 Run 不重派写入；迟到原回执只能结算，不能恢复成功。

`engine.session_stages(run_id)` 是纯 History 观察，`status().actions` 保存原派发身份。
独立 `session_execution_ended` Update 接受原 Scope／Action／请求摘要／Release 的宿主结束证据；
只能在实际 handler 完成或实际 Worker 已退出后提供，不能由 timeout／回执存在推断。
此处沿用可信宿主边界，尚非企业身份权限体系。

SessionKey 包含实际 Temporal Namespace UUID、真实数据集 UUID、Scope、namespace 和 session_id。
内存 UUID 随实例生命周期变化，不能冒充重启持久默认；SQLite UUID 保存在实际数据库中。
Redis／PostgreSQL 先初始化已有端口，再显式执行 `await source.initialize_session_identity()`，
在实际 prefix／已解析 Session schema 保存 UUID；显示 backend_id 和连接类不是数据集身份。
初始化仅用于宿主装配，执行期间使用原固定只读 identity inspection，缺失／变化不能被自动修复。
自定义可写资源需要稳定 `session_dataset_id` 和 sync/async `inspect_session_identity()`，返回相同
32 位小写十六进制 UUID；固定方法、物理资源及精确 receipt 仍须满足默认端口契约。

顺序成员在原 Session 根地址逐步骤保存；下一步骤／Turn 可有界召回已提交数据。
失败／取消前已保存的步骤记录仍保留，框架不伪造数据库回滚。History 的成功 Conversation
投影与外置 Session 证据分开保护，模型上下文只注入外置数据一次。
idle rebind 可以更新定义／绑定版本，但不能借此迁移数据集或 namespace。
多个独立 Local／Temporal 执行权威共享同一数据库仍不拥有跨权威 Session 租约。

本能力不包括高级编排的根／成员保存、Profile 默认装配、FIFO、输入续接、跨权威租约、
保留／迁移、真实模型质量或完整 H1/H2/H3/M1。交付证据见[最终验收](../architecture/reviews/2026-10-11-temporal-session-data-writes.md)。
