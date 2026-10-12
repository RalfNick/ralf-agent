# 完整已采纳模型链路与历史策略

基线 dev87 `c8696e8`。继续 R03/R05/R07/R26 的完整模型工具使用链路，不改变 Harness 策略或 Local/Temporal 唯一执行权威。

## 目标与阶段

本批补齐一次 Agent 执行中的最终响应、完成验证重试和原生历史的完整保存/请求保护，提供默认实现、纯替换端口和 Local/Temporal 配置。后续沿同一协议完成独立于参考记忆的跨 Session Turn 原生 transcript，再交付 DeepSeek thinking 和 Responses reasoning 的完整适配与任务验收。不是把工具中间轮续接当成完整会话支持。

## 公共契约

保留 dev87 的四字段 ModelContinuation、三字段 ModelResponse 和 ContinuedModelResponse，不更改其字节编码。
新增纯同步 `ModelHistoryPolicy`：`identity: dict`，`assemble(history, references, max_chars, *, context) -> (messages, manifest)`，`validate(history, messages) -> None`。注册使用 model_history_registration(policy)，包括纯 identity 与 assemble/validate 可执行指纹，执行对象和真实方法绑定也固定。公共 validate_reference_evidence(references) 在任何参考投影/替换策略前拒绝 opaque 包。历史为原执行权威保存的一次 Agent 交互，不包括 Session 参考记忆；不得执行 I/O 或修改输入。
默认 `CompleteModelHistory(allow_tool_result_projection=False)` 保留完整 system/task/assistant/tool/验证反馈顺序。参考证据只在第二条消息之后、原交互开始之前加入；不能替代或重排已有模型消息。字符和已配置计量预算均须通过，超出明确 ValidationError，不静默删除早期 reasoning/调用，也不调用摘要模型降级。
`allow_tool_result_projection=True` 是显式允许已有工具结果内容投影的策略；仅 tool.content 可以改变，其余字段/调用 ID/顺序与原消息一致。默认禁止，ManagedDataContext 的原 artifact 写入/回执权威保持，不赋予该策略存储权限。
公共 `validate_model_history(history, messages, *, allow_tool_result_projection=False)` 提供框架保护：列表为有限 JSON；原两条 head 完全相同，原 tail 为完整后缀；前置附加只能是普通 user 参考消息，不能插入原交互中；不接受丢消息、重复、变更原 assistant continuation/参数、错误工具组或未完成工具组。纯 DTO 验证、Context/Harness 实际请求均在模型 I/O 前执行。
默认 assemble 对完整原历史先验证预算，再按既有 select_references 选可容纳参考，不重做检索。Context 的可选 validate_request 继续测量；执行对象/方法身份固定。opaque continuation 不进入摘要或参考证据文本。

## 接收、采纳与重试

Local 和 Temporal 在原决策采纳边界，工具轮和无工具最终轮均持久保存完整原 assistant 一次。有 continuation 时以 received_response 和原已采纳 output 构造，而非业务 final_output。工具类型默认参数仍只用于 Action，不更改模型原参数。
完成验证 retry 在新模式只追加反馈 user；不重建 normalized assistant，也不重复添加 assistant。JSON Schema 业务结果的规范化不改变历史中的原 JSON 文本。
无效/拒绝/迟到/取消响应保留原接收证据，但不能混入已采纳历史。模型 receipt 后、采纳前恢复及采纳后、验证前恢复均不得重复模型调用或 assistant。

## 版本、绑定与配置

LocalEngine 新增 `model_history=None`；配置对象要求已有 `model_continuation=True`，初始化在取得资源前校验。仅非 None 的新发布固定 `model_history_protocol=1`、`model_history` 组件注册身份，原生 kernel `local-6`。bound Agent 原绑定 kernel 保持，附该门槛；Graph/Team/Dynamic/nested 成员随原下发 Manifest 固定策略，不增加第三套状态。
TemporalRuntime 同名参数，非 None 使用 joint `binding_protocol=7`，保留 continuation_protocol=1 和原两阶段 receipt/adoption。History 自身验证策略门槛、原消息与实际请求；Worker 仍负责原模型/Context I/O。所有原受管理阶段校验兼容 joint7 并验证自身门槛。旧1–6载荷/顺序不增加阶段或字段。
Local Profile `components.model_history={adapter: complete, config: {allow_tool_result_projection: false}}`；Temporal Profile 同组件，要求 `execution.model_continuation=true`。没有配置保持旧默认身份。SDK 导出 Protocol/默认策略；组件可由 Registry 替换。
旧 dev87 默认及 continuation local-5/joint6 不改消息/回放，旧代码在新发布业务 I/O 前拒绝。

## 验收

- 原最终 continuation → verifier retry → 原输出/签名完整，最终再次采纳一次；归一化 JSON 不改原文字。
- 多次工具后原历史不可被普通/计量/managed Context 或自定义 Harness 截断/修改；超预算零后续模型调用，managed 模型摘要不被调用。
- 显式 artifact 投影仍保存原 assistant 及调用 ID，默认拒绝结果改写；参考消息不泄漏 opaque history。
- Local receipt/采纳/验证间重启，重复提交与审批；Temporal History 状态恢复及实际 Worker 重启/History replay；含 Graph/Team/Dynamic/nested 固定组件测试。
- 配置 sync/async、独立安装、构建、旧87默认与原 Run 兼容；一轮独立 review 修复后运行相应回归。
- MockTransport/离线不算真实模型质量；跨 Turn transcript、DeepSeek thinking、Responses reasoning、完整 R01–R26 保持未验收。

用户已授权独立并行开发、持续执行和仅本地提交；不推送，不新增重复审批。
