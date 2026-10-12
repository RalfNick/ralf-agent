# DeepSeek 思考模型与完整工具循环

`DeepSeekThinkingProvider`／`deepseek-thinking` 是显式思考模式适配器。
它保存模型原生 `reasoning_content` 和工具调用，再通过既有续接契约回传。
旧 `DeepSeekChatProvider`／`deepseek-chat` 保持非思考模式及原发布身份。
模型型号由使用者明确指定，协议支持不代表某个账户或型号已通过线上测试。

## SDK 接入

```python
import asyncio
import os

from ralf_agent import (
    AgentSpec,
    CompleteModelHistory,
    DeepSeekThinkingProvider,
    LocalEngine,
    SQLiteStore,
    ToolRegistry,
)


async def main():
    tools = ToolRegistry()

    @tools.tool(effect="read_only", description="Look up an inventory record")
    def lookup(record_id: str):
        return {"record_id": record_id, "available": 3}

    provider = DeepSeekThinkingProvider(
        os.environ["RALF_GENERATION_MODEL"],
        reasoning_effort="high",
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

凭据来自 `DEEPSEEK_API_KEY`，或由宿主通过 `api_key`／借用 HTTP client 注入。
自建 client 随模型调用关闭，借用 client 由调用方在自己的异步生命周期关闭。
Provider 不执行业务工具、不重试 HTTP，也不决定授权、审批或取消业务 Run。
成员 Agent 可沿原 `provider` 能力绑定使用不同模型；RAG、Plan、Team、图和嵌套
沿同一个 Provider 端口接入，不需要改变业务工具。

## 配置与替换

Local JSON/TOML Profile 使用以下声明，同步 `build` 和异步 `abuild` 共用该入口：

```toml
schema_version = 1
[default]
name = "assistant"
version = "1"
[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "deepseek-thinking"
[profiles.providers.default.config]
model = "YOUR_ACTUAL_MODEL"
api_key_env = "MY_DEEPSEEK_CREDENTIAL"
reasoning_effort = "high"
max_output_tokens = 2048
stream = true
[profiles.components.model_continuation]
adapter = "native"
[profiles.components.model_history]
adapter = "complete"
```

Temporal Profile 用同一 provider declaration，将续接设置放在
`execution={"model_continuation": True}`；完整历史仍是 `components.model_history`。
没有显式启用续接的配置在资源装配前拒绝。替换 Provider 仍需保留固定版本与原
发布声明，不能用一个新模型接管已有 Run 的续接证据。

单 Run 完整历史默认 `scope="run"`。需要跨会话轮次时显式选
`CompleteModelHistory(scope="session")`，并装配原 Session 存储与会话入口；见
[跨 Turn 原生历史](model-history.md)。普通短期记忆摘录和 RAG reference 不具有
原生消息身份，不用于重建推理续接。

## 参数与消息边界

适配器固定 `thinking.type=enabled`。`reasoning_effort` 只接受 `low/high/max`，
默认 `high`；`top_p` 只接受 0.95–1.0。`stop`、输出额度、timeout、stream 和
能力限制沿原 HTTP 契约；JSON 对象模式只支持非流式并要求明确 JSON 指令。
不接受服务会忽略的 temperature、seed 或 penalty 配置。

带 tools 的请求回传所有原 assistant 的 `reasoning_content`，包含无工具调用的
最终回答。续接验证原模型 owner、决策摘要与原 native message；arguments 字符串
原样发送，真实工具默认参数只进入 Action。结果必须构成完整工具组；缺失、重复、
错误 owner 或改写的历史在 HTTP 派发前失败。无 tools 时普通文本历史可使用，
已有原生续接依然验证并保留。这些字段依据
[DeepSeek 官方思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)。

协议允许的空字符串和显式 null 原样保存，不合成推理内容。SSE 首个工具 chunk
固定调用身份，后续累加 arguments，按[官方 Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)处理。
函数名为协议允许的字母、数字、下划线或连字符，最长 128 字符。
完整历史的单组工具调用上限为 256，call_id 最长 1024 字符，沿原模型历史契约；
超限的原生响应在工具采纳前拒绝。
推理字段仅作为原生协议证据保存，不作为最终答案或 SSE text 展示。流式文本片段
是临时显示；完整结束后 response 才能进入原接收／采纳阶段。异常、截断或超限
不产生工具决策。每个续接保留原 131072 UTF-8 bytes 限额；完整历史超预算明确
失败，不裁剪、摘要或切换到非思考模式。

无效模型响应返回 `ProviderError`；已派发调用的模型费用可能未知，Run 按原契约
保留 `waiting_reconciliation`，不把它改为可自动重试的业务失败。被拒绝的原生
响应不会创建工具 Action；status／diagnostics 只是观察，不派发调用。Provider
没有内部重试；宿主再次显式 drive 可以按原契约重试未知模型调用，原未知额度
继续保留，不能据此保证模型费用恰好一次。业务工具仍需原审批和采纳证据。

原生字段保存在私有 Run／Session 证据中，应按应用的数据保留与访问策略管理；
公共评测报告只含统计和有限配置摘要，不输出原推理或凭据。

## 验证实际模型

```sh
ralf-check-model --adapter deepseek-thinking --model "$RALF_GENERATION_MODEL" \
  --reasoning-effort high --max-calls 6 --max-output-tokens 2048 --timeout 60

ralf-evaluate-orchestration --provider deepseek-thinking --kind team \
  --model-env RALF_GENERATION_MODEL --key-env DEEPSEEK_API_KEY \
  --reasoning-effort high --repeats 3 --max-calls 64 --max-output-tokens 2048
```

RAG／规划评测也可选 `--provider deepseek-thinking`；RAG 的语义 Embedding 按
[完整任务评测](task-evaluation.md)独立配置。CLI 仅在显式选择真实 Provider 后
读取凭据。兼容探针覆盖协议，规划执行器只测提案，端到端 RAG／Plan／Team 则按
各自冻结业务 oracle 评分；这些分数不能互相替代。

本批 HTTP MockTransport 仅证明协议与执行集成；真实 Temporal Service 验证
执行恢复。当前没有模型凭据，真实 DeepSeek 思考质量、费用、线上型号兼容及
对等框架比较仍未验收。完整 R05／H3／M1／R01–R26 不因本适配器而标为完成。
