# Temporal 根会话与成员私有会话

状态：dev67 本批验收通过；适用范围与后续门槛见[验收记录](../architecture/reviews/2026-10-11-temporal-session-trees.md)。

通过 `TemporalRuntime(session_topology=CompositeSessionTopology(), enable_sessions=True,
session_writes=True)` 显式启用 tree-v1／save-v2。不注册拓扑时保留原 save-v1 行为。
已有真实 Temporal Service／Client 是前提；离线原型或接口声明不代表分布式验收。

```python
from ralf_agent import (
    AgentSpec,
    CompositeSessionTopology,
    GraphNode,
    GraphWorkflowSpec,
    Runtime,
    Scope,
    SessionBindingResource,
    SQLiteMemory,
    TemporalEngine,
    TemporalRuntime,
    ToolRegistry,
    build_temporal_worker,
)
from ralf_agent.runtime_builder import EchoProvider


async def example(client):
    source = SQLiteMemory("session-tree.sqlite")
    execution = TemporalRuntime(
        providers={"default": EchoProvider("offline")},
        tools=ToolRegistry(),
        session_store=SessionBindingResource(
            source, namespaces=("chat",), default_namespace="chat"
        ),
        enable_sessions=True,
        session_writes=True,
        session_topology=CompositeSessionTopology(),
    )
    engine = TemporalEngine(
        client,
        task_queue="session-tree",
        release=execution.orchestration_release,
        scope=Scope("app", "developer"),
    )
    host = Runtime.from_temporal(engine)
    try:
        async with build_temporal_worker(client, task_queue=engine.task_queue, runtime=execution):
            graph = GraphWorkflowSpec(
                "assistant", [GraphNode("answer", agent=AgentSpec("answer", "Answer"))]
            )
            session = await host.open_session(graph, "conversation", command_id="open")
            turn = await session.submit("hello", command_id="first", budget=32)
            result = await turn.wait(wait_timeout=30)
            print(result.snapshot.state)
            # UNKNOWN 使用 engine.drive(turn.turn.run.run_id) 核验原意图／回执。
            await execution.close_session_execution()
    finally:
        await execution.close_session_execution()
        await host.aclose()
        await engine.aclose()
        source.store.close()
```

原顶层 Parent 在派发成员前读取并采纳根 Conversation，预留一个根写额度。
原生成员的每个步骤独立读取、采纳和保存私有数据；顺序、并行、Team、Plan/DAG、
模型 Planner 和嵌套成员使用结构化声明路径。原 Parent 最终结果具有独立聚合证据，
无需额外模型或业务 Run；根保存的精确回执采纳后才能成功并释放 Turn。

根 Conversation 使用宿主 `session_store`。它不从任意成员的后端反推。
只有成员选择外置来源时，根可保持 History Conversation；此时没有根数据库保存。
每 Agent 的 `session` 选择支持 inherit/ref/disabled，以及宿主允许的 namespace selector。
根和成员地址、Knowledge、Facts 及产物引用分别记录；外置根不重复注入其 History 副本。

根和每个成员步骤的 Conversation 快照只读一次并由原 History 固定。
工具循环、模型摘要和大结果卸载重建上下文时复用它，仍校验固定资源及实际数据集身份。
下一 Turn 读取新的已提交快照。Facts 和 Knowledge 的召回／版本校验有各自契约。

默认私有身份包括原根 SessionKey、绑定修订、结构化路径和原 Agent 声明摘要。
同一成员跨 Turn 可续接；不同并行节点、嵌套路径、步骤或声明不会别名。
idle rebind 保留根位置并派生新私有代际；根物理位置迁移及私有代际迁移需要独立协议。
自定义同步 `SessionTopology` 必须提供非秘密身份、稳定 root/member 方法，注册后配置／方法固定。
成员可以在默认 lineage ID 后加至多128字符的路由后缀；不能移除原身份、改写根、Scope 或 namespace。

只读快照不是执行租约。Temporal History 保持唯一调度权威；数据端口只提供 CAS 与回执。
跨独立执行权威租约、耐久 FIFO 和运行中迁移尚未交付。选中外置数据的高级 stateless Run
须通过 `open_session` 取得原 Turn；已存在回执先重放，不因新配置重新解释请求。

收到 ACK 或查到回执都不能证明真实处理器结束。未知保存只允许核验原 ID，不能重新调用
模型或工具。根读取采用单次尝试，超时不证明真实读者停止；原结束通知送达前保留占用。
取消时处理器未结束、回执未采纳或后代仍有未知效果，Session 持续 busy；
迟到证据只结算原保存，不把取消改为成功。原进程退出须有真实结束证据，不能由超时推断。

所有注册后端、纯拓扑和客户端池均 borrowed；`close_session_execution` 只关闭自身执行资源。
根读／Session 写处理器或其结束通知未完成时返回 `CloseIncomplete`，宿主需保留资源并重试。
原生成员 Context 中其他只读 I/O 的终止证明仍待统一治理；这个 wait/close 不表示整个 Worker 已静默。
SQLite 仅用于同宿主；Redis/PostgreSQL 需显式初始化实际数据集身份。三类后端共用相同端口。

执行额度并非费用上限。本指南和离线模型组合测试不证明真实规划、答案或引用质量，
也不完成整体 H1/H2/H3、M1 或 AgentScope 对齐验收。
