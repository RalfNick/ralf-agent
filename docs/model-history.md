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

参考召回与原生历史独立。默认策略拒绝把结构化 `model_continuation` 或完整四字段 opaque 包放入参考文本，普通业务 JSON 和文本协议说明仍可作为证据。

## 版本与边界

新模式固定 `model_history_protocol=1` 与策略注册，Local 原生 kernel 为 `local-6`，Temporal 为 joint7。每 Agent 绑定与 Graph/Team/动态/嵌套沿原成员发布下发；切换 Agent 时历史独立，不隐式串用另一模型 owner。未开启时 dev87 local-5/joint6 及普通默认身份和载荷保持；旧版本在新发布业务 I/O 前拒绝。

本能力保护一次 Agent 执行，不提供跨 Session Turn 原生 transcript。Session 仍召回参考证据；跨 Turn 的身份、CAS 保存、压缩与重绑定需另行验收。DeepSeek thinking、Responses encrypted reasoning 的完整适配、真实模型质量及完整 R01–R26 仍开放。
