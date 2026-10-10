# Temporal 持久 Session／Turn — dev60

此为 H2c3 子集：共用 SessionKey、SessionRef、TurnAdmission 与 AgentRun；
Session 协调 Workflow 保存绑定、串行 Turn、启动意图和 Conversation。
原 Agent／Parent Workflow 独占业务 Action、审批、预算和效果恢复。
客户端和协调 Activity 不执行模型或业务工具。

## 显式启用与首用

安装 `ralf-agent[temporal]`，宿主提供 Service、Client、Provider、ToolRegistry 和 Worker。
`enable_sessions=True` 将 `session_protocol=1` 和显式 `dispatch_admission="history-1"` 固定在发布中；默认关闭，
原 temporal-1/2/3 default/raw releases 与 raw `session_id` 保持其旧行为。

```python
from ralf_agent import AgentSpec, Runtime, Scope, ToolRegistry
from ralf_agent.temporal import TemporalEngine, build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime

# client 和 provider 由宿主创建；实例保持 borrowed 所有权。
execution = TemporalRuntime(
    providers={"default": provider},
    tools=ToolRegistry(),
    enable_sessions=True,
)
engine = TemporalEngine(
    client,
    task_queue="ralf-chat-v1",
    release=execution.manifest,
    scope=Scope("workspace", "trusted-user"),
)
async with build_temporal_worker(client, task_queue="ralf-chat-v1", runtime=execution):
    async with Runtime.from_temporal(engine) as runtime:
        session = await runtime.open_session(
            AgentSpec("assistant", "Answer the user's question"),
            "chat-123",
            namespace="support",
            command_id="open-chat-123",
        )
        run = await session.submit("hello", command_id="chat-123-turn-1", budget=32)
        result = await run.wait(wait_timeout=30)
        saved_session_ref = session.ref.to_dict()
        saved_run_ref = run.ref.to_dict()
```

Graph／Team／Dynamic Plan/DAG／嵌套使用 `execution.orchestration_release`，
成员仍受原六类 Temporal binding 约束。直接 Tool／Transform graph node 继续拒绝。
共享会话不是 `session` binding 角色：此版 Conversation 存储只在 Temporal History，
不支持将这一条链路换成 Redis／PostgreSQL SessionStore。
Local 已有这些适配器，不据此宣称 Temporal 外置 Session 数据已交付。

## 身份、配置与恢复

SessionKey 包含可信 Scope、实际 Temporal Namespace UUID 的资源 digest、
显式 namespace 和 session_id。UUID 来自 DescribeNamespace；端点别名不创建另一占用。
不同 Scope、实际 Namespace、namespace 或 session_id 是不同会话。
Namespace UUID 不支持迁移，也不是企业身份认证；宿主仍需保护 Service 凭据和 Scope 来源。

先Describe实际会话是否存在；冷会话在登记／创建前校验定义、发布、队列及command限额。
已有会话重放不按当前默认重新校验原绑定。随后全局登记 open 命令，再幂等创建协调 Workflow；
冲突 ID 不创建／固定新会话，并发冷读取仍由唯一Workflow ID与原绑定收束。
首次接受固定声明、发布、Worker 队列和 Activity timeout。
默认配置移动后，重放原命令仍返回原回执；新的不同配置须显式空闲 rebind。
Worker 更新需保留原队列与注册发布；命令 Registry 也必须有其原队列 Worker。
客户端连接相同 Namespace UUID，不能代替部署版本及队列迁移管理。

```python
from ralf_agent import Runtime, SessionRef, RunRef

async with Runtime.from_temporal(reconnected_engine) as runtime:
    session = await runtime.aattach_session(SessionRef.from_dict(saved_session_ref))
    run = await runtime.aattach(RunRef.from_dict(saved_run_ref))
    print(await session.status())
    print(await session.turns(after=0, limit=100))
    print(await session.diagnostics())  # busy / 原 Run / 控制错误；只查询
```

Session RunRef 使用实际 Namespace UUID 生成的 locator。
先 `aattach_session` 或直接 `aattach` 发现该 Namespace 后校验原 Scope／发布。
原非 Session RunRef 继续使用 endpoint locator，不自动升级成 UUID locator。
旧 dev59 的纯 Manifest 读取器允许未知字段；它没有 Session Workflow 注册，且旧 Worker
在 Context／模型／工具前因完整发布不匹配拒绝执行。此为 Worker 派发边界，不能称旧纯状态主动拒绝。
同一 Runtime 内更换实际 Client／Scope／Namespace 或在 await 后漂移，明确拒绝。

## 串行 Turn、观察与关闭

忙碌时新输入抛 `SessionBusy`，带耐久拒绝回执与原 RunRef；不分配第二个 Turn。
审批、核验、未知效果、预算 hold、未确认静默和 deferred journal ACK 均保留占用。
根 Run 终态还会独立检查所有已启动后代的原请求／发布／静默证据。
完成且静默的成功 Turn 才提交完整 user/assistant Conversation 对。
失败／取消只释放已确认静默的占用，不保存成功回复。
同一 ID 的 busy 拒绝在以后空闲时仍保持，业务新请求使用新 ID。

提交先接受 Turn／RunID／启动意图，再登记并启动原子 Workflow。
Worker 断开后仍保持原意图，恢复不重新执行已经采纳的模型决策或已完成成员。
`submit` 等待原 Run 启动回执；没有原队列 Worker 时可能持续等待。
取消调用方等待只停止观察，RPC 仍由 Runtime 托管。
`wait` 超时、断连与 detach 不提交业务 cancel；显式调用 `run.cancel` 才申请取消。
关闭会话入口只关闭借用句柄；Runtime 先排空已发出的 RPC，再 detach 客户端。
SDK不清理业务 Workflow，不隐式停止宿主 Worker／Service／客户端池。

协调失败保留 busy 和可查询的 `diagnostics()["error"]`。
修复原 Worker／注册后重放原 open/submit 命令唤醒协调，不换 RunID。
Query/status/turns/attachment/wait 不驱动恢复。审批停放没有定时高频轮询。

```python
rebound = await session.rebind(
    AgentSpec("assistant", "New instructions"),
    expected_binding_revision=session.ref.binding_revision,
    command_id="rebind-chat-123-v2",
)
```

只在空闲接受 CAS；历史回执、旧 Run 与 Conversation 保持。
旧 Ref 可查询及重放原命令，新输入则拒绝；使用返回的新 Ref 继续。
不能用 rebind 改 SessionKey、导入另一 Turn 或迁移历史。
模型派发前经原 History 许可，Scope／Run／Action／release／请求摘要均固定；
普通 Knowledge 异步复验期间取消也在来源读取返回后阻止 Provider 调用。

## 上下文、容量与未交付能力

本轮任务保持模型消息第二项；历史对话作为独立 sourced reference 装配。
Knowledge/Facts 检索仍针对本轮任务；Conversation 来源与两者分别校验。
支持原普通 ContextBuilder 及 ManagedContextPipeline 的有界完整对话投影。
Conversation 不替代 Run 的原工具消息、记忆提炼来源或知识版本。

每会话至多4096个控制回执；Conversation 保留最多128条消息和262144个规范JSON字符，
按完整最早 pair 裁剪，单项输入限131072字符。单个完成 pair 超额则保留占用并报容量错误。
这些是安全界限，不是长期 History 压缩、保留治理或 payload 卸载验收。
队列 FIFO、send_input、外置 Session 数据、跨后端协调、迁移、Continue-As-New、
全局配额、自动 Temporal Profile 和其他 binding 角色继续未交付。
真实模型上下文质量、完整 H1/H2/H3/M1 与企业部署分别验收。

证据见 [dev60 验收](../architecture/reviews/2026-10-11-temporal-sessions.md)。
