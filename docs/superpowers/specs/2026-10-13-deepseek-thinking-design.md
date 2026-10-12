# DeepSeek Thinking: Native Continuation Design

本批补齐R05思考模型适配，并贯通R07单Agent/RAG/Plan/Team及R01每Agent配置；完整R01–R26、真实模型质量和独立采用继续开放。基线dev89 `fe4474d`。

## Public contract

- 新增独立`DeepSeekThinkingProvider`及显式`deepseek-thinking`适配器。旧`DeepSeekChatProvider`、默认配置、原Run/Session和发布指纹不迁移。
- `model`由使用者显式提供；默认base URL为`https://api.deepseek.com`，credential来自`api_key`或`DEEPSEEK_API_KEY`。identity不含credential。
- 固定`thinking={type: enabled}`；`reasoning_effort`支持`low/high/max`，默认`high`。`top_p`仅接受0.95–1.0；不提供被服务忽略的temperature/seed/penalty参数。支持既有max_output_tokens/timeout/stop/stream/capabilities及非流式JSON模式。非法参数在I/O前拒绝。
- 所有完成响应（工具和最终回答）返回`ContinuedModelResponse`；protocol为`deepseek-thinking-v1`，owner为固定identity摘要。data仅`message`字段，保存原assistant `role/content/reasoning_content/tool_calls`及原arguments字符串；decision摘要对应原解析output/tool calls，不纳入实际工具默认参数。
- 每个assistant响应需要存在`reasoning_content`（字符串或显式null），保留空字符串/null，不合成推理内容。只接受单一完整choice/stop或tool_calls。拒绝截断、空最终答案、未知非文本字段、非法usage、重复调用和非法JSON。reasoning不是最终答案或流式text事件。
- 消息续接验证原owner、decision和完整native message；带工具时所有assistant历史（包含final）都必须具有本适配器的原续接证据。普通system/user/feedback和完整tool结果沿原顺序传递；未知/重复/不完整结果组拒绝。原native arguments不被规范化、默认值或摘要替代。
- 无工具时普通文本历史可接入；已存在的续接仍验证并保留。跨Turn使用显式`CompleteModelHistory(scope="session")`，不从普通reference召回猜测原生历史。
- 复用原131072 UTF-8续接证据上限、完整历史单组256调用／call_id 1024字符上限和HTTP/SSE限额；原生函数名支持官方128字符。超限失败，禁止截断、摘要或隐式降级。SSE首个工具chunk固定id/type/name，后续只累加arguments；reasoning字符串拼接或保留显式null，完全缺字段失败。SSE只有完整结束后产生response，reasoning fragments不产生业务决策。

## Authority, configuration, lifecycle

SDK/Local Profile/Temporal Profile/CLI均显式启用`model_continuation`，新组件通过现有注册、能力绑定、固定版本和资源生命周期装配。原Local收到→采纳两阶段、Temporal History、审批及效果恢复是唯一执行权威；Provider不执行工具、不重试业务效果，也不新增状态机。

新的CLI选择接入模型兼容、规划、RAG和团队端到端执行器，显式effort参数严格传递；离线/MockTransport与真实付费服务分别标注。现环境未提供有效模型credential，不追索历史key；缺少真实试验保持质量验收开放。

## Acceptance

协议JSON/SSE有效及失败、参数/owner/原arguments、完整final跨Turn、组件替换与sync/async配置先RED后GREEN。Local需覆盖原生及实际RAG/Plan/Team/图/嵌套、审批重启和收到/采纳窗口；Temporal需实际Worker恢复及History replay，不以纯fixture代替服务证明。旧默认/原Run兼容、安装包、文档和一轮独立审查后本地提交，不推送。

协议依据：[DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)及[Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)。服务型号及协议变化需通过实际模型兼容矩阵确认，本批不将协议Mock标为线上型号支持。
