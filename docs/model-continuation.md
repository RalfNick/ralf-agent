# 模型续接与 Gemini 函数工具

dev88 新增显式 [完整模型历史](model-history.md)，保护工具轮、最终响应和验证重试的原交互。
原 dev87 续接模式仍保留旧行为；跨 Session Turn 原生 transcript 尚未交付。

`GeminiFunctionProvider` 是显式原生函数适配器，提供文本、客户端函数调用和完整 SSE。
原 `GeminiProvider`／`gemini-content` 保持文本模式。工具执行、审批、预算和效果恢复由
原 Local／Temporal 引擎负责；Provider 不执行工具，也不自动重试 HTTP 请求。

## 从配置接入

在本地 Profile 中同时声明模型适配器和续接模式：

```toml
schema_version = 1
[default]
name = "assistant"
version = "1"
[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "gemini-functions"
[profiles.providers.default.config]
model = "YOUR_ACTUAL_MODEL"
api_key_env = "MY_GEMINI_CREDENTIAL"
max_output_tokens = 2048
stream = true
[profiles.components.model_continuation]
adapter = "native"
```

型号和凭据由使用者显式提供；组件声明只保存凭据变量名。用原工具注册机制声明
业务函数，并在 `AgentSpec.tools` 中允许使用。顺序／Graph／Team／动态 DAG／嵌套的
实际 Agent 使用同一模式，成员模型仍可通过原能力绑定替换。

Python 注入使用 `LocalEngine(..., model_continuation=True)`；原默认为 False。
`RuntimeBuilder.build` 和 `abuild` 都支持上述 Profile。推荐组合可显式追加
`components={"model_continuation": {"adapter": "native"}}`；未追加不修改原组合身份。
没有启用模式时，声明需要续接的 Provider 会在接受 Run 前拒绝。

Temporal 使用独立声明 `TemporalProfile(..., execution={"model_continuation": True})`，
或 `TemporalRuntime(..., model_continuation=True)`。该配置固定 joint 6 发布和续接协议 1；
不能把本地 component 与 Temporal execution 混用。原 Profile 及协议 1–5 默认不迁移。
恢复需要保留原 Provider、工具实现、配置和 Worker 发布，不能把旧 Run 指向修改后的版本。

## 替换为自己的续接协议

普通模型继续返回原三字段 `ModelResponse`。需要原生状态的 Provider 返回：

```python
from ralf_agent import ContinuedModelResponse, ModelContinuation, ToolCall
from ralf_agent.types import digest

raw = {
    "output": None,
    "tool_calls": [{"name": "lookup", "arguments": {"key": "A"}, "call_id": "call-1"}],
}
state = ModelContinuation(
    protocol="my-functions-v1",
    owner_digest=digest(provider.identity),
    decision_digest=digest(raw),
    data={"native_content": native_content},
)
response = ContinuedModelResponse(
    tool_calls=(ToolCall("lookup", {"key": "A"}, "call-1"),),
    continuation=state,
)
```

Provider 声明纯同步属性 `continuation_identity={"protocol": ..., "owner_digest": ...}`，
并在自己的请求编码器中读取 assistant 消息的 `model_continuation`。外层包装器必须
显式委托原身份，不能因计量或审计包装而改变签名所有者。续接 data 是有限 JSON 对象，
四字段 canonical UTF-8 总量最多 128 KiB；它只保存模型证据，不能授予工具权限。
`to_dict()` 返回脱离的副本；修改导出数据不改变原响应。

引擎先保存完整 `received_response`，再验证原模型决策和 Harness 提案。Harness 改变
输出、工具名、参数、ID 或次序会被拒绝；合法的类型化工具默认值随后用于真实 Action，
模型消息仍保留签名前的原参数。Temporal History 根据固定发布独立检查原提案和默认值，
不直接相信 Activity 自报的解析结果。

## 原生协议边界与恢复

Gemini 完整原始 Content／Part 次序及 `thoughtSignature` 留在续接数据中；签名块不合并。
有 native call ID 时原样返回 `functionResponse.id`。服务省略 ID 时生成稳定的 host ID，
只用于匹配本地回执，不能伪造 native ID。单组重复、孤立、缺失或不匹配回执拒绝；
一个已完成工具组之后，可以再次提出完全相同的无 ID 调用。

函数声明使用 `parametersJsonSchema` 保留原 JSON Schema。
本地支持的函数名为声明与调用语法的交集：ASCII 字母或下划线开头，随后为字母、数字、
下划线或连字符，总长最多 128；点和冒号在发送前拒绝，不能声明引擎无法续接的名称。
媒体、服务端执行、
`partialArgs`／`willContinue` 增量参数协议尚不支持；未知块明确拒绝。默认完整
`functionCall` SSE 帧在 STOP 后形成最终响应，thought 文本不会作为展示事件输出。
断流、提前取消或不完整参数不会形成可执行工具提案。借用 HTTP client 由调用方关闭；
自建 client 在请求结束时关闭。模型流展示与耐久 Run 事件仍是不同接口。

模型已完成但尚未采纳时重启，从原接收证据恢复，不能重新调用模型。
Temporal joint6 先由模型 Activity 交回完整 receipt，History 保存并结算，再执行零额度的
纯 `model_adoption`；采纳可安全重试，失败保留原响应并明确拒绝。Provider 返回到模型
Activity 完成被服务记录之前的进程退出仍可能丢失响应，不能保证任意远端调用恰好一次。
工具审批暂停后
重建仍使用原签名和原 Action；重复审批不会创建另一业务动作。模型派发后没有完整响应
仍沿用未知结果／成本边界，不因续接模式自动重试。Context 只能按完整工具组裁剪；
最近未结束的工具组及其续接必须保留，预算不足则明确拒绝。

协议依据：[Gemini GenerateContent 函数调用](https://ai.google.dev/gemini-api/docs/generate-content/function-calling?hl=en)、
[REST Content 与 FunctionCall](https://ai.google.dev/api/generate-content)。本适配器使用 GenerateContent，
不混用 Interactions API 的消息格式。

## 显式验收入口

```sh
ralf-check-model --adapter gemini-functions --model YOUR_ACTUAL_MODEL --cases text,structured,tool,stream,stream_close
ralf-evaluate-orchestration --provider gemini-functions --model YOUR_ACTUAL_MODEL --kind team
```

`--adapter`／`--provider` 的新选项显式启用续接。RAG 的生成模型同样可用
`--provider gemini-functions`，语义 Embedding 必须单独配置。
SDK 评测入口显式传 `model_continuation=True`；旧入口默认保持 False。
协议 fixture、真实 Local 进程恢复和 Temporal Service 测试分别记录；
MockTransport 或离线策略不证明真实 Gemini 型号兼容、任务质量或费用上限。
