# Responses 推理续接与原生历史

`OpenAIResponsesReasoningProvider`／`openai-responses-reasoning` 是显式原生续接适配器。
它保存有序 reasoning、message 和 function_call 项，包括密文、原参数及 assistant phase，
通过既有 ModelContinuation 和 Local／Temporal 接收、采纳与恢复流程运行。
原 `OpenAIResponsesProvider`／`openai-responses` 保持无推理状态模式与旧发布身份。

## SDK 起步

安装核心包即可接入 HTTP 协议。以下例子需要宿主设置 `OPENAI_API_KEY` 和明确的
`RALF_GENERATION_MODEL`，没有隐含模型型号或在线调用回退。

```python
import asyncio
import os

from ralf_agent import (
    AgentSpec,
    CompleteModelHistory,
    LocalEngine,
    OpenAIResponsesReasoningProvider,
    SQLiteStore,
    ToolRegistry,
)


async def main():
    tools = ToolRegistry()

    @tools.tool(effect="read_only", description="Look up an inventory record")
    def lookup(record_id: str):
        return {"record_id": record_id, "available": 3}

    provider = OpenAIResponsesReasoningProvider(
        os.environ["RALF_GENERATION_MODEL"],
        reasoning_effort="high",
        reasoning_context="all_turns",
        max_output_tokens=2048,
        timeout=60,
    )
    with LocalEngine(
        SQLiteStore("runs.sqlite"),
        providers={"default": provider},
        tools=tools,
        model_continuation=True,
        model_history=CompleteModelHistory(),
    ) as engine:
        agent = AgentSpec("inventory", "Use inventory evidence.", tools=("lookup",))
        handle = engine.submit(agent, "Check item A-1", command_id="inventory-001")
        result = await engine.drive(handle.run_id)
        print(result.state, result.result)


asyncio.run(main())
```

`client` 注入时借用，由应用自己的异步生命周期关闭；未注入时沿原 HTTP 请求生命周期
创建与关闭。模型只提出决策，业务工具、审批、额度和取消由原执行权威管理。
RAG、图、Plan、Team 和嵌套的实际 Agent 共用这个模型端口；`provider` 绑定可让各成员
选择不同固定模型。更换已接受 Run 的模型身份会拒绝恢复，须保留原发布版本。

## Profile 与 Temporal

Local JSON/TOML 的同步 `build` 和异步 `abuild` 都支持下述显式声明：

```toml
schema_version = 1
[default]
name = "assistant"
version = "1"
[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "openai-responses-reasoning"
[profiles.providers.default.config]
model = "YOUR_ACTUAL_MODEL"
api_key_env = "MY_OPENAI_CREDENTIAL"
reasoning_effort = "high"
reasoning_context = "all_turns"
max_output_tokens = 2048
stream = true
[profiles.components.model_continuation]
adapter = "native"
[profiles.components.model_history]
adapter = "complete"
```

Temporal Profile 使用同一 Provider 声明，将续接开关放在
`execution={"model_continuation": True}`；`components.model_history` 仍声明完整历史。
缺少显式续接时，声明在 owned 工厂装配前拒绝。SDK 的 `TemporalRuntime` 同样显式
开启 `model_continuation=True`，不创建本地执行数据库。

单 Run 完整历史默认 `scope="run"`。跨会话 Turn 使用
`CompleteModelHistory(scope="session")` 和[原持久 Session 入口](model-history.md)；
会回传先前工具组及最终原生回答。普通短期摘录、知识引用和自动摘要不替代这些原始证据。
完整历史超过上下文额度时明确失败，不偷偷丢弃密文、工具结果或 final phase。

## 可设置的推理与格式

| SDK/Profile 选项 | 可选值 | 默认 |
| --- | --- | --- |
| reasoning_effort | none、minimal、low、medium、high、xhigh、max | None，省略，使用模型默认 |
| reasoning_context | auto、current_turn、all_turns | None，省略 |
| reasoning_summary | auto、concise、detailed | None，省略 |
| reasoning_mode | standard、pro | None，省略 |

每项非 None 配置进入固定身份。实际型号支持哪些值仍需在线兼容验证；不把 HTTP
接受误认为任务质量通过。该适配器不接受 temperature、top_p、seed 或 stop。
JSON object 与显式严格 object Schema 互斥；沿原格式规则校验最终回答。

请求固定 `store=False`，显式 include `reasoning.encrypted_content`，手工回传完整
output items，不依赖 `previous_response_id`。现行官方 stateless 请求已默认返回密文，
legacy include 仍兼容。相关含义见[官方推理指南](https://developers.openai.com/api/docs/guides/reasoning)。

## 证据与错误边界

reasoning 密文必须完整且非空；适配器只保存和回传，不解密。可选 content 和 async 的显式 null
按缺省语义原样保留，function status 与 output_text.logprobs 的可选 null 同样保留。
async=true、不完整 status 与非空 logprobs 仍不支持。原参数字符串保持空格、
键顺序和转义，工具使用解析后的参数及注册默认值。assistant `commentary` 保存在
原生历史，`final_answer`／未标 phase 的文字用于最终结果；只有 commentary 且没有
工具的响应拒绝完成。不会把中间说明混入 JSON 最终答案。

函数名最多64个 ASCII 字母、数字、下划线或连字符；call_id 最长1024字符，每组
最多256个调用；本适配器要求原 output item ID 存在且组内唯一，不合成缺失 ID。续接四字段 canonical UTF-8 上限131072 bytes。拒绝缺失/重复/孤立
工具结果、错误拥有者、签后决策修改、媒体、服务端工具、异步/程序调用、非空引用
annotations 和未知语义字段。大密文超限在工具采纳前拒绝，后续可单独建设 Artifact
协议，但本适配器不会裁剪原证据。

SSE 的 added reasoning 密文可能还不完整；只有最终完整 snapshot 可成为续接。
已观察的文本、参数、身份、done metadata 必须与该 snapshot 一致。推理和 commentary
不会作为最终 text delta 展示；可见回答是临时流片段，完整 response 才进入执行权威。
断流、取消、失败、截断和不一致证据不会产生可执行工具提案。协议依据见
[Responses 创建参数](https://developers.openai.com/api/reference/python/resources/responses/methods/create)与
[流事件](https://developers.openai.com/api/reference/resources/responses/streaming-events)。

用量映射 input_tokens/output_tokens；推理 token 已含在 output_tokens，不重复计费。
这是报告用量，不是货币费用上限。Provider 无内部 HTTP 重试；无有效响应的已派发
模型调用沿原 waiting_reconciliation 和未知额度责任。status/diagnostics/重连只是观察；
宿主再次显式 drive 仍可能按原契约重试未知模型调用，不能保证模型费用恰好一次。

## 真实模型验收入口

```sh
ralf-check-model --adapter openai-responses-reasoning --model "$RALF_GENERATION_MODEL" \
  --reasoning-effort high --reasoning-context all_turns \
  --max-calls 6 --max-output-tokens 2048 --timeout 60

ralf-evaluate-orchestration --provider openai-responses-reasoning --kind team \
  --model-env RALF_GENERATION_MODEL --key-env OPENAI_API_KEY \
  --reasoning-effort high --repeats 3 --max-calls 64 --max-output-tokens 2048
```

RAG／规划评测同样可显式选择；SDK 评测传 `model_continuation=True`。CLI 在选择
适配器后才读取凭据，无配置时不调用模型。规划提案、协议兼容和端到端业务任务分别
评分，RAG 的语义 Embedding 仍需独立配置，见[任务评测指南](task-evaluation.md)。

本批使用 HTTP 协议 fixture 与真实 Local／Temporal 恢复测试，不证明线上模型、账户
兼容、答案质量或费用。当前真实 Responses 质量、完整 R05/H3/M1/R01–R26 与外部采用
保持开放，实际验证记录见[本批验收](../architecture/reviews/2026-10-13-responses-reasoning.md)。
