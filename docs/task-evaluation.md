# RAG 与 Plan／Team 完整任务评测

显式 `evaluate_orchestration(..., completion_gate=True)`／CLI `--completion-gate`启用库存父级回执门禁，并用独立oracle复核当前修订、原工具和采纳结果。安装后例子见[业务完成验证](parent-completion.md)。默认False保留旧报告和两成员评分；fixtures继续`model_quality=null`。

dev86 提供可安装的 SDK 和 CLI，复用版本 2 推荐 Runtime、原摄取、检索和受管理 Agent。
此处评测完整任务执行；原 `relf-evaluate-planning` 仍只评估规划提案。
Gemini 原生函数选 `--provider gemini-functions`，DeepSeek 思考选 `--provider deepseek-thinking`，Responses 推理选 `--provider openai-responses-reasoning`；SDK 显式传 `model_continuation=True`。
旧 `gemini` 保留文本模式；续接接入及协议边界见[模型续接](model-continuation.md)。
离线样例用于运行协议回归，真实质量与框架对等比较需要单独的实际证据。
Plan 默认使用原规则 DAG，Team 使用固定 Supervisor；自主模型规划、计划修订和
未知任务上的团队策略质量仍需另外的端到端任务，不能由本组有限库存案例推出。

## 安装后直接运行

```sh
pip install relf-agent
relf-evaluate-rag --offline
relf-evaluate-orchestration --offline --kind plan-and-execute
relf-evaluate-orchestration --offline --kind team
```

源码未发布时，先从仓库构建 wheel，再安装该本地 wheel；无需复制 `examples`。
默认不传 `--offline` 或 `--provider` 时输出 `not_run`，不联网。
`--repeats 3 --max-calls 64` 对同一冻结案例重复运行，失败和未尝试项保留在分母中。
未通过返回码 1，缺配置或非法配置返回码 2；无配置的默认展示返回码 0。

## SDK 与组件替换

```python
import asyncio
from relf_agent import (
    EvaluationLimits,
    OfflineRAGProvider,
    OfflineOrchestrationProvider,
    evaluate_rag,
    evaluate_orchestration,
)


async def main():
    rag = await evaluate_rag(
        OfflineRAGProvider(),
        limits=EvaluationLimits(repeats=2),
    )
    team = await evaluate_orchestration(
        OfflineOrchestrationProvider(),
        kind="team",
        limits=EvaluationLimits(max_calls=64, repeats=2),
    )
    return rag["passed"], team["passed"]


print(asyncio.run(main()))
```

`provider` 接受原异步 ModelProvider；RAG 的 `embedding` 接受异步 EmbeddingProvider。
两者均借用，SDK 不关闭客户端。调用方负责在同一事件循环关闭自己拥有的客户端。
配置和实际方法在本次评测中固定，执行中替换组件会拒绝采纳结果。
没有 Provider 时不隐式读取任何凭据；真实生成默认要求显式 Embedding。
离线 RAG 缺省 HashEmbedding 是词项散列基线。

`load_rag_cases()` 与 `load_orchestration_cases()` 返回脱离默认模板的 JSON。
传入 `cases=` 可以替换完整业务数据和 oracle；这些 expected 字段不进入模型请求。
CLI `--cases` 读取 `{version: "1", cases: [...]}`；包内含默认，不依赖 checkout。
RAG 可审阅副本为 [冻结案例](../evals/rag-cases.json)。

## 显式真实模型配置

RAG 生成可选 OpenAI 兼容、Anthropic 或 Gemini 文本协议。
Plan／Team 必须有工具能力；当前 Gemini 适配器仅支持文本，配置后在派发前返回
`not_run`／`provider_tools_unsupported`，质量保持 null。
以下环境变量名只是用户自己设置的配置入口，不会推断模型型号、复制凭据或自动下载模型。

```sh
relf-evaluate-rag --provider openai \
  --model-env RALF_GENERATION_MODEL --base-url-env RALF_GENERATION_URL \
  --key-env RALF_GENERATION_KEY \
  --embedding-model-env RALF_EMBEDDING_MODEL \
  --embedding-base-url-env RALF_EMBEDDING_URL \
  --embedding-key-env RALF_EMBEDDING_KEY --embedding-dimensions 1024 \
  --max-cases 8 --repeats 3 --max-calls 24 --max-embedding-calls 128 \
  --max-output-tokens 2048 --timeout 60 \
  --evidence-dir ./private-rag-evidence --report ./rag-report.json

relf-evaluate-orchestration --provider openai --kind team \
  --model-env RALF_GENERATION_MODEL --base-url-env RALF_GENERATION_URL \
  --key-env RALF_GENERATION_KEY --repeats 3 --max-calls 64
```

生成和 Embedding 端点、模型、密钥独立配置；不能把 DeepSeek 生成模型当成 Embedding。
dimensions 必须与选定的 Embedding 型号实际输出一致。CLI 关闭自己创建的异步组件。
SDK 真实 Provider 的身份应声明与 EvaluationLimits 一致的输出和超时上限。
内置 HTTP 型号的实际协议支持仍须运行验证。

## 评分、计量与私有证据

| 链路 | 实际执行证据 | 评分维度 |
| --- | --- | --- |
| RAG | 原 Ingestion 回执、SQLite 来源与索引、原生模型 Action 最终请求 | 答案、停止、引用来源／版本／原文、必要支撑、实际展示的召回支撑、终态重连 |
| Plan／Team | 原受管理 researcher／writer 子 Run、inventory_lookup／calculator 完成回执 | 状态、金额、原工具参数、前序证据、成员、停止与原权威重连 |

正确答案配伪造／旧版本／隐藏的引用仍失败；正确金额配错误参数或缺工具回执仍失败。
RAG 引用只接受最终模型请求实际展示的文档文字；候选、压缩 metadata、未展示的全文均不算。
截断 canonical JSON 时排除 metadata 和未完整展示的转义字符，保持原 chunk digest。
`retrieval_support` 独立于模型答案，分母含全部冻结来源支撑；它不证明答案正确。

模型与 Embedding 分开计量。`max_calls` 是模型调用上限，`max_embedding_calls` 是单文本
Adapter 调用上限。内置 HTTP Embedding 每次仅发一批；任意自定义客户端的内部重试或请求
数量由适配器负责。有 `embed_result` 时保留原生逐批 usage；否则费用／用量保持未知。
模型金额只使用模型的已知用量和显式单价；Embedding 费用保持 null。
`max_cost_usd` 在通用协议无法保证硬货币上限时返回 `not_run`。
summary 的 attempted 指模型已调用的案例；摄取／索引调用另看 embedding_calls。

公开报告仅含有限身份字段、digest、布尔评分、计数、用量和时延；不含问题、答案、
引用正文或 Adapter 异常。`--report` 必须为新文件，派发前以 0600 独占创建。
`--evidence-dir` 必须无本批同名数据库，包含原始内容的 SQLite 文件同样为 0600。
SDK 默认临时证据在返回后清理；需要排障或恢复时显式保留目录。

终态重新装配只重开来源和索引，回到原 Run／回执，不再次摄取、索引或生成。
进程在模型派发后退出时，恢复测试只观察原记录，不自动重试未知调用以提高成绩。
这里恢复证据不等于所有故障窗口或 Temporal 端到端评测已完成。

离线 `model_quality`、`semantic_quality` 为 null。显式真实组件的分数只对应本次冻结
任务及组件配置；并不证明通用模型质量、AgentScope 等框架对等成绩或外部采用。
完整 H3／M1／R01–R26 继续保持未验收。
