# Temporal 固定 Session 数据读取

状态：dev65 固定有界读子集。本批是[完整外置 Session 契约](../architecture/specs/temporal-session-data-contract.md)
的固定资源/读取前置；尚未开放外置持久 Session、自动结果保存或高级成员跨 Turn 地址。

原生 Agent/顺序 Workflow 的 Worker 可显式提供 `session_store` 或在 BindingCatalog 登记
`role=session`，通过 inherit/ref/disabled 选择来源和宿主允许的 namespace。数据读取进入原
Context Activity；原 Run History 保存有界读结果与来源证据，普通/managed Context 都保持。
数据后端不调度 Run，不替代 History。现有 History Session 不因这一配置自动变成外置数据库。

```python
from ralf_agent import BindingCatalog, Scope, SessionBindingResource, SQLiteMemory, ToolRegistry
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.recall import RecallQuery

scope = Scope("app", "developer")
sessions = SQLiteMemory("session-data.sqlite")
catalog = BindingCatalog(scope=scope)
catalog.register(
    "session",
    "private",
    "1",
    SessionBindingResource(sessions, namespaces=("research",), default_namespace="research"),
)
execution = TemporalRuntime(
    providers={"default": EchoProvider("offline")},
    tools=ToolRegistry(),
    binding_catalog=catalog,
    session_query=RecallQuery(max_items=20, max_chars=8000, scan_limit=256),
)
# AgentBindingDescriptor(session=BindingSelection.ref("private", "1"))
# 客户端仍沿原 TemporalEngine/Runtime.from_temporal 装配；Worker停止后由宿主关闭sessions。
```

读取地址当前为原 Run/node 私有地址，`private_address(run_id, node)` 返回版本化逻辑键，
选择视图再映射获准 namespace。只适用于显式受控的数据预装配/自定义适配器读取；
不会自动串接前一个 Run 的对话，也不保存这次回答。要延续会话仍使用已交付的 History Session。
外置资源参与持久 SessionKey、成员稳定路径和原 CAS 保存门禁是后续完整链路，不能拿本页作为已交付说明。
选中外置来源后 open_session/SessionTurn 与 Graph/Team/Dynamic 子树在命令接受前明确拒绝；
未选择来源或 disabled 的原组合保持原行为；模型 Planner 继承宿主来源，嵌套 Dynamic 也纳入检查。

默认 memory/SQLite、线程安全同步桥接与 native async Redis/PostgreSQL 复用原有界 read_page。
没有全历史 read 的隐式 fallback。query 不接受初始 cursor；返回 RecallPage 必须 backend_bounded=True，
数量/字符/扫描预算匹配，snapshot_id 使用带非负整数 revision 的 JSON（默认四种后端已兼容）。
PostgreSQL 必须在注册前显式 await initialize()，表路由固定后不受 borrowed connection 的 search_path 变化影响。
自定义实现还须明确物理 resource identity 与精确消息 receipt v1；SQLite 必须留在创建线程。

Worker 固定实际对象/方法、SQLite文件/连接、Redis数据库/prefix/client/pool、PG数据库/connection/初始化解析的实际 table schema；
内存还固定实例身份，同名新的空内存不能冒充原来源。资源均 borrowed，调用方在 Worker 实际停止后关闭。
Model 使用原 History 已接受的 Session snapshot，后端数据随后变化不替换它；新的合法上下文阶段可重新读。
Session 数据引用、History Conversation、Knowledge 和 Facts 分开，摘要/压缩与 Artifact 投影保持原来源。

本页不证明真实模型质量、分布式会话租约或完整 H1/H2/H3。安装/服务/回归证据见[本批验收](../architecture/reviews/2026-10-11-temporal-session-data-reads.md)，
完整受管理读写与每 Agent 持久绑定继续实施。
