# dev91：Responses 推理续接

## 目标与既有授权

落实 R05 尚未交付的 Responses 推理续接，让用户在单 Agent、RAG、Plan/Team 和原 Local/Temporal 执行权威中显式替换模型协议。持续建设 R01–R26、独立任务并行、逐批验证及仅本地提交已获用户授权；本批沿既有架构实施，不增加执行状态机。完整能力和真实模型质量仍需各自验收。

## 选择

采用新增 `OpenAIResponsesReasoningProvider` / `openai-responses-reasoning`。直接修改原 Provider 会改变旧发布身份和接受范围；服务端 `previous_response_id` 又引入远端隐式历史。新增适配器复用原 HTTP 生命周期、ModelContinuation、ModelHistory 与执行权威，保留原 `OpenAIResponsesProvider` 和默认声明字节。

## 公共契约

构造参数：显式 `model`；`api_key=None`、`base_url=https://api.openai.com/v1`、`max_output_tokens=1024`、`timeout=60`、借用 `client=None`、`stream=False`、`capabilities=None`、`json_mode=False`、`output_schema=None`、`schema_name=ralf_output`。原严格 JSON 格式规则复用。

推理选项均默认 None，省略时由选定模型决定：`reasoning_effort` 接受 none/minimal/low/medium/high/xhigh/max；`reasoning_context` 接受 auto/current_turn/all_turns；`reasoning_summary` 接受 auto/concise/detailed；`reasoning_mode` 接受 standard/pro。每个非 None 设置固定到身份并映射 effort/context/summary/mode。实际型号支持的组合仍由服务兼容测试验证。该适配器不接受 temperature/top_p/stop/seed，也不选择默认型号。

身份 kind=`openai-responses-reasoning`、version=1；协议 `openai-responses-reasoning-v1`。`owner_digest=digest(identity)`，`decision_digest` 绑定原 output/tool_calls。续接 data 只有 `output`：原有序输出项列表的脱离副本。最终回答也返回 ContinuedModelResponse。原 128KiB 续接 UTF-8 上限保持；超限拒绝，不裁剪签名或偷偷改用无状态模式。

## 请求与响应

固定 `store=False`、`include=[reasoning.encrypted_content]`；不使用 previous_response_id/conversation/background/服务端工具。请求保留原 system/user 文本，assistant 使用已验证的原输出列表，tool 映射 function_call_output。工具组必须完整，ID/名称/参数/顺序和拥有者与原决策一致；没有续接的函数历史拒绝。没有工具的普通文字历史可以接入；存在续接时始终验证原协议。

允许 output 项 reasoning、assistant message、客户端 function_call；保留 ID、原参数字符串、summary/content、encrypted_content、status 和 message phase；可选 reasoning.content、function_call.async/status 与 output_text.logprobs 的显式 null 作为无内容／同步缺省原样保存，true 或程序 caller 仍拒绝。reasoning 项必须提供非空 encrypted_content，不能靠 reasoning item ID 从远端恢复。message phase 可省略/null/commentary/final_answer，commentary 只保留在原生历史中，不投影为最终 output；只有 commentary 且无工具的响应拒绝。未标 phase 的文本和 final_answer 正常成为最终决策，JSON 校验只作用于最终文字。空最终决策、拒绝、截断、服务端工具、媒体、非空 annotations、不支持字段拒绝。

每组最多 256 个函数调用；call_id 非空且最多1024字符；function name 采用官方 ASCII 字母/数字/_/-、1–64；output item ID 有界且组内唯一。重复/孤立/缺失工具结果、foreign continuation 和签后决策变化拒绝。实际 ToolAction 默认参数与签名前原参数保持分离。

usage 映射 input_tokens/output_tokens，校验非负整数、total 和已知 breakdown；reasoning_tokens 已含在 output_tokens 中，不重复加计。未知成本仍沿原预算契约。

## SSE

专用流状态沿原 Responses 语义事件协议验证 sequence、响应/item/part身份、参数与最终 snapshot。支持 reasoning item、summary part/text 以及可回放 reasoning content；reasoning 和 commentary 不作为最终 text delta 输出。added encrypted_content 可以是未完整密文，不能作为回放证据；done/final 必须完整且一致。只在 `response.completed` 完整且与已观察证据一致后形成 response，失败/断流/取消/非法增量不产生可执行提案。完整终态 snapshot 可以独立验证，未观察的中间事件不伪造。

## 装配、生命周期与兼容

SDK 导出、ComponentRegistry、sync/async Profile 和 Temporal execution.model_continuation 显式接入；缺少 opt-in 在 owned 工厂之前拒绝。每 Agent provider ref 复用原绑定。四类评测 CLI 提供显式选项，推理参数按 adapter 校验，在读取凭据/创建客户端之前拒绝无关配置。旧默认、旧 Run/Action/Schema 及旧 Provider 不迁移；没有新 Engine/History 协议。

借用 HTTP client 由调用者关闭；自建客户端沿原请求生命周期关闭。Provider 不执行工具和内建重试；未知模型调用沿原 reconciliation/held credit 语义。纯查询和重连不派发；宿主显式 drive 的既有重试含义保持。

## 验收

协议 JSON/SSE 边界及 RED/GREEN；装配/CLI 和替换身份；真实 Local 工具循环/RAG、审批重启、硬退出 receipt/adoption、跨 Turn 原 final 历史、graph/team/实际 ModelPlanner/嵌套；真实 Temporal 独立 Worker 丢失、审批/receipt/final Session 恢复与 History replay。完整源码、独立 wheel 安装、SDK/TOML 例子、原 dev90 默认和原 Run 兼容、制品来源一致、静态检查、一次独立审查和自有服务正常停止后本地提交。

真实 API 型号、任务质量、模型费用与外部采用缺证时继续开放；MockTransport 和真实 Temporal Service 不等于真实模型。

## 协议依据（2026-10-13 查询）

[官方推理指南](https://developers.openai.com/api/docs/guides/reasoning)、[Responses Create](https://developers.openai.com/api/reference/python/resources/responses/methods/create)、[流事件](https://developers.openai.com/api/reference/resources/responses/streaming-events)、[函数调用](https://developers.openai.com/api/docs/guides/function-calling)。现行 stateless 默认返回密文，legacy include 仍接受；保存 phase 和原完整 output 是手工历史续接的要求。这里只实现上述声明的文本/客户端函数范围。
