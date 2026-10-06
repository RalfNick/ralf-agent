# 默认模型层 Review

日期：2026-10-06；基线：`ecaee56`／dev8；修订：dev9／local-4。

## 交付与证据边界

提供 Chat Completions、原生 Anthropic 文本/客户端工具和 Gemini 原生文本；DeepSeek preset 固定非思考模式。公共 ModelCapabilities、StreamingModelProvider、ModelStreamEvent 表达实际适配器能力和临时文本/完整响应。生成参数和可选纯预检进入实际调用路径；Registry、独立 model 模板与教程提供可编辑入口。

HTTP/SSE fixture 验证协议；没有进行真实模型/账户调用，不报告线上厂商兼容或模型质量。Gemini 函数签名、思考工具续接、server tools、多模态、Responses API、路由和耐久 token 事件仍未交付。用户的五项能力建议继续作为分期目标，本轮完成模型层这一增量，不宣称达到 AgentScope。

## 独立复核及修复

[复核回归](../../tests/test_model_review.py)去重后 9 failed／1 passed，修复后 10 passed，使用 -W error；合法输入片段 "{}" 保留正例。五项实证 P2 已闭环：

1. Anthropic 的空 input_json_delta 被当作无片段，跳过 JSON 解析并采用占位 {}。现在明确记录是否收到片段；收到后即使串为空也必须完整解析，非法片段不成为 ToolCall。
2. Chat SSE 忽略 event:error，带正常形状的 error 帧仍可返回工具。现在错误标记立即拒绝；结束后异常同样拒绝，没有终态响应事件。
3. 畸形嵌套 JSON 触发 AttributeError，越过统一错误边界。输入转换归一到 ValidationError，响应/流归一到 ProviderError，错误信息不包含上游正文。
4. 原生历史合并丢弃说话人 name。无法表达的字段现在在预检/转换时拒绝，不能把 Alice/Bob 合成匿名消息来继续调用。
5. 非思考 preset 接受不支持的 reasoning 历史。现在请求拒绝该历史；Chat 响应含推理状态和工具时也拒绝采纳，专用 DeepSeek 请求明确发送 disabled。

Root 额外回归修复了非列表/整数 tool call、明确 finish_reason 与 calls 不一致、响应端关闭工具能力仍返回工具等边界。原先缺少 finish_reason 的旧 Chat fixture 保持接受已完整解析的内容/工具；SSE 始终要求明确结束原因和 [DONE]。这些限制针对协议完整性，不代替业务 Schema、审批和授权。

## 执行与生命周期

预检针对 Harness 最终请求，在新 Action/预算预留前执行；实际网络前再执行，随后重读取消状态。预检不是授权或执行阶段，只允许同步 None/异常，旧 Provider 可不实现。模型生成能力变化反映 identity；新的默认字段缺省不改变旧 Chat identity。

Provider 全部消费并验证流后才产出唯一完整响应；工具片段不对外发布。Engine 收到完整 ModelResponse 后沿用独立接收/采纳，不新增 token Action。截断/网络错误保留未知模型成本；取消全部实际 Task 时响应关闭、借用 client 仍开放，不生成工具。仅取消 shield 的 drive 等待者仍保持原执行，这是既有运行契约。

SSE 帧/累计字节有限；非流式 httpx.post 的正文在上限检查前已收完，该限制不表示网络/内存硬隔离。SDK 提前停止迭代必须 aclose/aclosing；借用 client 的外部生命周期仍由应用管理。Anthropic 未出现任何参数 delta 的合法空工具语义尚未做线上判定，不把不确定案例列为实现缺陷。

实际全套、wheel 升级、旧模板和装配结果记录于 [实现进度](../../docs/implementation-progress.md)。不自动迁移 kernel、执行 Schema、调用方摘要或已经接受的模型配置。
