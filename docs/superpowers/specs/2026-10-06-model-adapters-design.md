# 默认模型适配与流式响应设计

依据用户的 dev8 能力评审，优先改善模型默认覆盖和接入体验。此次 dev9 是模型层增量；不把协议回归当成线上厂商兼容或真实任务质量证明。

## 协议边界

- ModelProvider.complete(messages, tools) -> ModelResponse 保持不变。新增 ModelCapabilities(text/tools/streaming) 和可选纯 validate_request；内核在保存模型派发意图前验证最终 Harness 请求。旧自定义 Provider 缺少可选方法仍可用。
- OpenAIChatProvider 增加 temperature/top_p/stop/seed、流式调用；默认参数、identity 和未启用配置的 dev8 Manifest 保持完全一致。国内兼容服务通过 base_url 接入；DeepSeek 有明确默认地址、凭据变量与 max_tokens 的装配适配器，不自动猜模型能力。
- AnthropicProvider 转换 system、消息、函数声明及 tool_use/tool_result；完成原因和完整 JSON 校验后才返回工具提案。缓存输入与生成输出用量归一化；只支持文本和客户端函数工具，不支持 thinking/server tools/multimodal。
- GeminiProvider 使用原生 generateContent/streamGenerateContent，支持文本 system/history 和生成参数；tools=False。签名函数调用的原始内容无法由当前通用消息契约保真，故在发送前拒绝工具声明/历史，响应中的函数调用也拒绝；后续单独设计持续状态，不能静默丢弃签名。

## 流式与可靠性

新增 StreamingModelProvider.stream -> AsyncIterator[ModelStreamEvent]：text 为临时展示片段，response 为一次完整 ModelResponse。工具参数仅内部拼接，终止、结束原因、参数 JSON 与用量校验全部完成后才产生 response。截断、错误、取消或提前关闭不能产生最终提案。

complete 默认非流式，显式 stream=True 时收集同一流并返回完整结果。Engine 仍在完整响应后独立持久接收，不把 token/delta 当作 Action 或执行权限；断流保持现有未知模型成本语义。SSE 支持多行 data、空行边界、注释；限制帧/累计数据，响应退出时关闭连接。不重试请求或业务动作。注入的 HTTP client 仍由应用关闭。

## 装配与开箱

Registry 提供 chat-completions、deepseek-chat、anthropic-messages、gemini-content；配置只保存凭据环境变量名，全部新参数进入实际 identity。能力声明表达适配器实现/用户禁用能力，不保证具体模型、账户、地区或服务可用；请求失败不自动降级。

新增 model 独立 starter，使用明确占位 model 与凭据变量，要求用户编辑配置后运行；无需 import 仓库 examples。默认 oncall/rag/config 内容不变。教程同时提供国内兼容地址和原生协议配置，列出本地协议测试／线上人工测试／真实质量三种证据等级。

## 验收

协议级 HTTP/SSE fixture 验证请求、认证、生成参数、工具往返、使用量及错误脱敏。必须覆盖碎片 JSON、多工具、提前断流、拒绝/长度停止、超量、消费取消与连接清理；能力不支持时 HTTP 次数/派发/预算为零。旧 identity 精确相等；实际 dev8 wheel Run 经 dev9 原工厂续跑和回执重放。安装后的三个协议、新 model starter，以及已有离线模板均需验证。没有真实凭据/明确付费授权时不进行收费调用；未执行的线上验证保留为未验证。
