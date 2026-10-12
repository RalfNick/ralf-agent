# 完整模型历史

`CompleteModelHistory` 是纯同步、可替换的历史策略，保护一次 Agent 执行中的原模型交互。适用于需要回传原生签名或推理状态的模型，也适用于需要保留全部工具证据的普通 Provider。执行与恢复仍由 Local Engine 或 Temporal History 负责。

```python
from ralf_agent import CompleteModelHistory, LocalEngine, SQLiteStore, ToolRegistry

engine = LocalEngine(
    SQLiteStore("runs.sqlite"),
    providers={"default": provider},
    tools=ToolRegistry(),
    model_continuation=True,
    model_history=CompleteModelHistory(),
)
```

`provider` 是宿主装配的模型组件，例如 `GeminiFunctionProvider` 或自定义 Provider。完整历史要求显式开启 [模型续接](model-continuation.md)，不要求每个响应都带续接。旧配置保持原行为。

## 保存与恢复

原执行权威先保存接收证据，再采纳决策。已采纳的工具轮和最终轮都保存一次原 assistant；工具默认参数只进入实际 Action，历史保留原调用参数。业务输出按 Schema 规范化，原 JSON 字符串的空白和格式保留。自定义 Provider 的非字符串有限 JSON 输出映射为 canonical JSON 文本，Action 保留原类型；合法 null 保留 null。

完成验证 retry 只追加反馈 user，不重建或重复插入 assistant。响应接收、采纳或验证后恢复使用原持久证据继续。拒绝、取消或迟到响应留在接收证据中，不混入已采纳历史。

完整模式保留本次交互的 system、task、assistant、tool 和反馈顺序。可选参考在 task 之后、原交互之前插入。默认不调用摘要模型压缩这一段历史；超出字符或已配置计量预算明确失败。调用方应设置合理额度或拆分业务步骤，摘要不能替代原生续接。

## 配置与替换

Local Runtime Profile：

```json
{
  "name": "native-history",
  "version": "1",
  "providers": {"default": {"adapter": "offline-echo"}},
  "components": {
    "model_continuation": {"adapter": "native"},
    "model_history": {"adapter": "complete"}
  }
}
```

真实模型使用相应 provider adapter 替换 `offline-echo`；同步/异步 Builder 共用声明。Temporal Profile 的 `model_history` 同样放在 components，将续接配置改为 `execution: {"model_continuation": true}`。`TemporalRuntime` 也接受同名 SDK 参数。

`ModelHistoryPolicy` 公共端口：

```python
identity: dict
assemble(history, references, max_chars, *, context) -> tuple[list[dict], dict]
validate(history, messages) -> None
```

两方法必须纯同步、不执行 I/O、不修改输入。身份和两个方法的可执行指纹进入原 Release；组件或方法漂移在模型 I/O 前拒绝。可用 `ComponentRegistry.register("model_history", "business", factory)` 注册替换工厂。原权威仍执行公共历史校验，替换策略不能绕过完整消息保护。

## 大结果与参考记忆

默认禁止改写工具结果。如应用接受既有 `ManagedDataContext` 的 Artifact 引用和预览，可显式设置 `CompleteModelHistory(allow_tool_result_projection=True)`，Profile 对应 `config: {"allow_tool_result_projection": true}`。只有 tool.content 可投影；调用 ID、名称、参数、assistant 签名和顺序保留。Artifact 写入、读取验证和回执仍由原权威管理；不能声称投影后回传了完整原工具内容。

参考召回与原生历史独立。框架在投影或替换策略前拒绝结构化 `model_continuation`、完整四字段 opaque 包及 `ralf-native-model-turn` envelope，包括嵌套值；序列化不能绕过来源资格。普通业务 JSON 和文本协议说明仍可作为证据。

## 版本与边界

新模式固定 `model_history_protocol=1` 与策略注册，Local 原生 kernel 为 `local-6`，Temporal 为 joint7。每 Agent 绑定与 Graph/Team/动态/嵌套沿原成员发布下发；切换 Agent 时历史独立，不隐式串用另一模型 owner。未开启时 dev87 local-5/joint6 及普通默认身份和载荷保持；旧版本在新发布业务 I/O 前拒绝。

dev88 已验收范围为一次 Agent 执行。跨Session模式已完成dev89子集验收，交付范围见[验收记录](../architecture/reviews/2026-10-13-session-model-history.md)。DeepSeek thinking、Responses encrypted reasoning 的完整适配、真实模型质量及完整 R01–R26 仍开放。

## 跨 Session 的完整历史

显式选择 `CompleteModelHistory(scope="session")`。组件仍是纯策略；原 Local Run/SQLite 或 Temporal History 负责来源、读取采纳、保存和发布。默认 `scope="run"` 的原身份及行为保持。

```python
import asyncio
from ralf_agent import AgentSpec, Runtime, RuntimeBuilder, RuntimeProfile

async def main():
    profile = RuntimeProfile(
        "conversation", "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "model_continuation": {"adapter": "native"},
            "model_history": {"adapter": "complete", "config": {"scope": "session"}},
        },
    )
    engine = await RuntimeBuilder().abuild(profile, "conversation.sqlite")
    async with Runtime(engine, owned=True) as runtime:
        session = await runtime.create_agent(AgentSpec("assistant", "Answer the request")).open_session(
            "chat", command_id="open-chat",
        )
        handle = await session.submit("Remember this task", command_id="turn-1")
        print((await handle.wait(wait_timeout=10)).snapshot.result)

asyncio.run(main())
```

`offline-echo` 用于验证配置和使用链路；真实模型替换 providers 声明。第二轮沿同一个 Session 提交。`wait` 观察业务状态，Session 在原执行与保存处理器结束后才释放 busy；长流程按 [Session 指南](session-api.md)观察和恢复。更换进程后使用原 SessionRef 重连，不重新生成会话或审批身份。

每次模型请求包含原 system、已发布过去轮次的原 user/assistant/tool/反馈、当前 task、可选参考和当前交互。检索、事实召回及业务验证使用当前 task。每个实际 Agent 成员按原声明路径和模型 owner 独立续接；图节点、Team、动态计划和嵌套的聚合结果不伪造为成员 assistant。

完整过去轮次只在原根 Run 成功后发布。外置后端的候选写入和业务成功是两个事务；准确回执不会自动赋予成功资格。丢失 ACK 时检查原稳定 message ID，恢复不会重跑已采纳模型或工具，也不会通过读取最新 revision 强行覆盖原 CAS。Local 同连接 SQLite 的原生追加与根成功在同一事务完成。

原生数据使用内部隔离地址，归一化 Session 答案仍可作为可选参考。默认完整历史不做摘要或裁剪；新 session envelope 上限为 999,998 canonical chars，原单项有界页包含外围列表的总上限为 1,000,000 chars，每 stream 最多 128 条、8 MiB。超限明确拒绝。需要大结果投影时显式允许 tool.content 投影；存储保留原文。

每 Agent 可继承、禁用或通过 Catalog 的 `model_history` 角色替换策略。只有显式该角色的绑定 Descriptor 使用 v2，旧十四角色的 v1 编码保持。自定义 session 策略额外实现纯同步 `assemble_frame(frame, references, max_chars, *, context)` 与 `validate_frame(frame, messages)`；框架独立保护所有过去及当前原消息。替换 Session 数据后端沿原 SessionStore 的 read_page、append/CAS、inspect_message 和 dataset identity 接入。

替换 Local ExecutionStore 无需提供 SQL 连接；新模式需要声明可选原生发布能力版本1，提供同步 `prepare_native_history`、`native_history_publications`、`publish_native_history`。启用和发布分别随原接受/成功事务完成，发布按稳定ID去重且准确回读；prepare/publish 返回已完成的None，读取返回有界JSON列表。惰性上下文管理器不代表已经执行。适配器保证自己的原事务原子性，Session数据回执仍不能代替执行发布证据。

新 session 模式固定 `model_history_protocol=2`、Local local7、Temporal joint8。Local schema13 仅在新 Run 有效接受事务中启用；接受失败不升级。旧版本拒绝新发布或数据库后，使用新版本恢复原 Run。idle rebind 开启新的续接 epoch，不把旧模型签名迁移给新 owner。

128条和8MiB是框架的原生数据硬上限，不保证Temporal服务在此之前不会达到自己的History限制。本批外置SQLite探针在原服务记录104个已接受Turn后被 `history-service` 以History过大终止；原证据保留。另设128MiB History上限的私有服务用于检验原128→129容量契约，不能据此声称默认部署具备同样长会话能力。服务上限和Continue-As-New仍属于[长期执行治理](remaining-work.md)；[Temporal官方配置源码](https://github.com/temporalio/temporal/blob/main/common/dynamicconfig/constants.go)列出 `limit.historySize.error` 等独立门槛。
