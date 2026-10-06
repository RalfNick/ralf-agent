# 模型适配、生成参数与流式结果

dev9 提供三个 HTTP 协议与 DeepSeek 非思考模式适配器，全部复用已有 httpx，不需要厂商 SDK。Provider 只调用模型，不执行工具或自动重试。协议回归、在线模型兼容和任务质量是不同的验证结果；当前只完成本地协议/运行时验证。

## 默认覆盖

| SDK / 配置 adapter | 文本 | 客户端函数工具 | SSE | 默认凭据变量 | 主要限制 |
| --- | --- | --- | --- | --- | --- |
| OpenAIChatProvider / chat-completions | 支持 | 支持 | 支持 | OPENAI_API_KEY | Chat Completions 兼容协议；不支持需保留 opaque reasoning 状态的工具循环 |
| DeepSeekChatProvider / deepseek-chat | 支持 | 支持 | 支持 | DEEPSEEK_API_KEY | 固定 thinking.type=disabled 和 max_tokens；不支持思考模式工具续接或 seed |
| AnthropicProvider / anthropic-messages | 支持 | 支持 | 支持 | ANTHROPIC_API_KEY | Messages 原生转换；不支持 thinking、server tools、多模态 |
| GeminiProvider / gemini-content | 支持 | 不支持 | 支持 | GEMINI_API_KEY | Developer API 原生文本；工具声明/历史在发送前拒绝，签名工具状态未交付 |

国内外满足 Chat Completions 契约的服务可用 base_url 接入；这不是所有服务/型号的兼容保证。原生 Anthropic 按 [Messages](https://platform.claude.com/docs/en/api/messages/create) 和 [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming) 转换 system、tool_use/tool_result 及结束/用量。Gemini 的 [原生 API](https://ai.google.dev/api/generate-content) 区分文本与函数签名；当前通用消息无法保真往返签名，所以明确拒绝工具能力。

DeepSeek 当前 [Chat API](https://api-docs.deepseek.com/api/create-chat-completion/) 默认思考模式启用；专用 adapter 显式关闭，避免丢弃续接状态。它不会选择模型或悄悄切模式。Chat 响应含 reasoning_content 且有工具时拒绝采纳。若服务返回不支持的块、截断、拒绝、非法参数或不一致的结束原因，Provider 返回错误。

## 配置与首次使用

```sh
ralf init my-model-agent --template model
cd my-model-agent
```

先编辑 runtime.toml，替换 YOUR_MODEL、选择实际协议和账户可用地址，然后通过自己的环境/凭据管理器提供密钥。模板拒绝未替换占位值，不能因 init 成功就认为模型已接通。调用真实服务可能收费。

国内协议配置示例不固定易变化的型号：

```toml
schema_version = 1
[default]
name = "assistant"
version = "1"
[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "deepseek-chat"
[profiles.providers.default.config]
model = "YOUR_MODEL"
api_key_env = "MY_DEEPSEEK_CREDENTIAL"
max_output_tokens = 2048
temperature = 0.2
stream = true
```

将 YOUR_MODEL 替换为服务支持的实际型号再运行。修改 adapter 为 anthropic-messages 或 gemini-content 时也要改 model 和对应凭据变量。使用 chat-completions 时可配置 base_url 和 token_parameter（max_completion_tokens／max_tokens）。不会根据地址猜测参数或失败后重试另一种协议。

```sh
python -m agent_app --input '解释这段业务输入' --command-id task-001
ralf --config runtime.toml resume RUN_ID
```

温度、top_p、stop、seed 为可选参数；省略时不发送。温度 Chat/Gemini 为 0–2，Anthropic 为 0–1；top_p 为 0–1，DeepSeek 要求 >0。stop 为 1–4 个非空字符串；seed 仅 Chat/Gemini，必须为有符号 64 位整数。参数进入实际非秘密 identity，变更后旧 Run 不能默默使用新配置。具体型号可能拒绝或忽略某些参数；没有参数自动路由或降级。

凭据通过 api_key 或对应环境取得，Profile 只保存 api_key_env 名称，显式变量缺失不回退厂商默认。不要把密钥放进 JSON/TOML、identity、输入或工具配置。配置声明、原适配器版本与数据需保留，历史恢复规则见 [运行装配](runtime-assembly.md)。

## 能力与流事件

ModelCapabilities(text/tools/streaming) 描述适配器实现的能力，应用可以关闭，不能打开尚未支持的协议行为。配置 `[profiles.providers.default.config.capabilities]` 可设置 tools=false 等。能力不表达账户权限、具体模型智力、上下文大小、收费额度或多模态支持。

```python
from contextlib import aclosing
from ralf_agent import OpenAIChatProvider, ModelCapabilities

# 凭据由应用环境提供；示例应在自己的 async 生命周期内使用。
provider = OpenAIChatProvider("YOUR_ACTUAL_MODEL", capabilities=ModelCapabilities(tools=False))
async with aclosing(provider.stream([{"role": "user", "content": "hello"}], [])) as stream:
    async for event in stream:
        if event.kind == "text":
            print(event.text, end="")
        else:
            completed_response = event.response
```

text 是临时展示，response 是唯一完整结果。工具参数片段只在 Provider 内拼接；完整结束、JSON 对象和用量校验后才返回 ToolCall，不能拿片段直接调用业务工具。SDK 使用者提前停止迭代须通过 aclosing 或显式 aclose 退出；借用的 HTTP client 不被关闭，自建的 client 随调用关闭。取消驱动的等待者不会取消 Engine 内部 shield 的执行；服务关闭仍按 [生命周期规则](extending.md) 停止实际任务、drain、close。

构造时 stream=True 表示 complete 使用 SSE 并收集完整结果。Engine 仍只对完整 ModelResponse 作独立持久接收，流片段不是耐久 RunEvent。断流/解析失败不产生新工具提案，已有派发沿用未知模型成本；没有 token 断点恢复或 UI 流式事件 API。SSE 帧上限 1 MB，累计响应上限 4 MB，按字节计算；非流式也限制最终接收正文，httpx.post 在本地检查前已经完整接收正文，不能声称网络层硬限流。

可选纯同步 validate_request 在实际 Harness 请求产生后、预算预留和派发前检查协议能力/形状；缺少此方法的旧自定义 Provider 保持兼容。方法只返回 None 或抛拒绝，不做 I/O、状态提交或授权；异步/惰性返回值拒绝。实际调用前再次检查，避免等待其他来源时发生变化。

## 验证矩阵

本地 HTTP/SSE fixture 验证三种协议的认证、地址、生成参数、文本/工具转换、用量、结束原因、碎片参数、错误脱敏及连接生命周期。Anthropic Agent 实测审批前不执行工具，批准后完成一次工具往返；默认 Chat identity 保留 dev8。DeepSeek 非思考 preset 的请求字段有本地证据。安装包的原任务恢复和独立模板另行验证，结果见 [实现进度](implementation-progress.md)。

在线账户/地区/型号兼容、真实延迟/Token/费用、工具选择和拒绝能力尚未执行。使用者可在自己的环境提交最小文本、工具往返、流式完成/取消四种用例，记录型号、地址、日期与非秘密配置；通过后只标记该组合。该流程不替代 [M1 真实任务集](m1-acceptance.md)。OpenAI Responses、厂商 SDK、多模态、模型自动路由、Gemini 签名工具和持久流事件仍需后续交付。
