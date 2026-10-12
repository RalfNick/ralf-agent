# 原执行权威下的模型续接与 Gemini 函数协议

基线 dev86 `5096210`。沿 R05／R03／R07／R26 提升实际模型工具链路，不新增调度器或状态机。
用户已授权持续能力建设、独立并行任务与本地提交；完整 R01–R26 保持，未验收不标完成。

## 公共数据与规则

保留原 ModelResponse 三字段及旧序列化。新增 `ContinuedModelResponse(ModelResponse)`，额外 `continuation: ModelContinuation`。
`ModelContinuation(protocol, owner_digest, decision_digest, data)` 是脱离原对象的有限 JSON 值，to_dict 返回脱离副本；四字段精确，protocol为非空≤128字符、两digest为64小写hex、data为dict、canonical UTF-8总量≤131072bytes。
decision_digest = digest({output:原始输出, tool_calls:[{name,arguments,call_id}]})；仅绑定原已完成模型响应，不能自行授权任何操作。
Provider可声明纯属性 `continuation_identity={protocol,owner_digest}`。Gemini函数Provider的owner_digest=digest(identity)，外层审计Provider显式委托该纯属性；无声明的Provider不得采纳续接。

新纯模块 `model_continuation.py` 提供：`decode_received_response(received)`、`provider_continuation_identity(provider)`、`validate_continuation(received, proposed, identity, *, enabled)`、`assistant_message(output, proposals, *, received=None, continuation=None)`。
validate返回脱离的四字段dict或None。enabled默认False；收到续接但未启用、原decision digest不匹配、owner/protocol不匹配、Harness更改output或原调用name/arguments/call_id/order，均在工具采纳前拒绝。ToolRegistry随后可正常补类型化默认参数；续接模型消息保留原模型参数，实际工具Action使用已解析参数，不伪造签名。
assistant_message无续接时与当前标准消息完全一致；有续接时使用received原call字段且附 `model_continuation` 四字段，原完整工具组由现有Context选择保护。
完成响应先由原权威保存 received_response（含续接），再校验／采纳；失败不把已完成模型变为可重试。审批重启、接受后崩溃和未知效果沿原协议恢复。

## Local 与 Temporal

LocalEngine新增显式 `model_continuation=False`。仅True采用新的native kernel `local-5`，每步Manifest记录 `model_continuation_protocol=1`与所选Provider续接identity；bound根保持已有版本化能力并带该新字段。默认False不增加任何Manifest／response／消息字段。与旧代码不兼容的显式发布必须在业务I/O前拒绝。
Runtime Profile新可选component `model_continuation: {adapter: native}` 由原Builder转换为True；不声明沿旧模式。新Gemini函数Provider需要显式续接模式，不能在引擎未启用时丢弃续接。
TemporalRuntime同名显式选项，使用joint binding_protocol=6、model_continuation_protocol=1。原History采纳received_response与续接证据、保护原原始消息。所有受管理context/tool/artifact/sandbox等校验允许新的joint6并同时验证必需原协议；旧1–5默认身份与载荷不变。原Parent固定下发所选release，不增加第二套恢复权威。Temporal Profile显式配置接通。

joint6采用两个原History阶段：模型Activity只交回完整raw receipt与固定prepared_request；History先记录原模型响应及结算。随后零模型额度的纯model_adoption Activity仅执行原固定Harness与工具默认参数解析，History独立验证后采纳。receipt到adoption之间Worker退出时读取原History即可继续，不再调用模型；纯采纳失败明确拒绝，不把已完成模型改为unknown。旧1–5不增加该阶段，也不改变原Activity载荷。纯DTO、Harness与错误类型在Temporal Sandbox共享同一加载边界，避免有效提案被类型身份差异拒绝。

## Gemini 原生函数适配器

新增 `GeminiFunctionProvider`，复用原 HTTPModelProvider 生命周期和Gemini generation配置，默认tools=True；独立identity kind=`gemini-generate-content-functions`，version1。旧GeminiProvider不变。
声明functionDeclarations使用 `parametersJsonSchema` 保留JSON Schema，不启用Google托管工具或自动执行。
响应parts仅支持文本／thought标记／thoughtSignature／functionCall，严格拒绝未知媒体或服务端执行块。visible text用于输出；完整原parts次序和每part签名进入continuation.data={content:原model Content,call_ids:[host IDs]}。
functionCall.name/args/id严格验证；有原id原样保留并在functionResponse中回传；无id生成稳定合成hostID（index与原part digest），不向API伪造原id。重复原id／不完整参数／并行调用身份冲突拒绝。
请求将标准assistant/tool完整组映射为native model/functionResponse；有续接时校验owner与原decision、原模型name/args对应，使用原完整Content，保留签名part位置。tool结果JSON对象原样作为response，其他有限JSON包裹为{result:value}；原id匹配，无孤立／重复／缺失／不对应tool receipt。
SSE完整收集后才返回工具提案；保留原part边界与签名，text事件不泄露thought；STOP结束及usage-only后续按完整协议处理。参数碎片不伪装为已完成调用。拒绝截断、blocked、未知finish、重复结束和内容迟到；没有自动HTTP重试。

## 配置、使用与验收

Local／Temporal注册 `gemini-functions`，SDK公开新Provider／DTO；模型检查和RAG／Plan／Team显式CLI接通新适配器及续接模式，旧gemini文本选项保持。
至少覆盖unsigned/signed单／并行函数、原ID与无ID、多步模型选择、工具审批与重复控制请求、真实进程退出／终态恢复、Harness变更与默认参数、身份漂移、上下文截断完整组、SSE取消／中断、错误usage和当前默认旧86兼容。
真实Temporal服务／Worker重放以及源码／独立核心安装、构建和原默认回执兼容按实际证据验收；MockTransport只算协议，不算真实Gemini质量。无模型凭据不联网付费。

来源：[Gemini函数调用](https://ai.google.dev/gemini-api/docs/generate-content/function-calling?hl=en)、[REST Content／FunctionCall／FunctionDeclaration](https://ai.google.dev/api/generate-content)。签名留在原part、原call id回传，不合并签名part；本文仅转述协议要求。
