# 语义 RAG 参考应用

`python -m ralf_agent.semantic_rag_reference` 是随 SDK 安装的完整参考应用：原文摄取、显式索引、权威来源回读、原 Agent Run、答案与引用评分、终态重新连接。它复用 `evaluate_rag`，不增加执行权威或调度器。没有 Provider 时显示 `not_run`，不读取凭据、不载入或下载模型。

```sh
python -m ralf_agent.semantic_rag_reference
```

本应用的 `typed_answers=True` 使用通用问题类型指令：数量为 JSON number，多字段答案为 JSON object，时间等文本保持字符串。它不读取或披露 oracle，不把 `"30"` 自动改成 `30`。旧 `evaluate_rag`／`ralf-evaluate-rag` 默认仍为 False，原提示、Agent version 1 与报告字段保持；显式启用时使用 Agent version 2，并在报告写入 `typed_answers=true`。旧 Run 继续使用原定义，改变配置后新建提交。

## 安装与显式模型下载

创建独立环境，安装包含本模块的当前 preview wheel；不需要仓库 import path。模型依赖是显式可选安装，SDK 基础依赖不会自动安装或下载它们。以下版本在 macOS ARM CPU／Python 3.14.6 上实际验证过，其他平台应选择可用的 CPU wheel，并记录自己的固定依赖与评测配置。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install /absolute/path/to/ralf_agent-preview.whl
.venv/bin/python -m pip install 'sentence-transformers==5.7.0' 'transformers==5.19.0' 'torch==2.14.1' 'huggingface-hub==1.33.0'
.venv/bin/python -m pip freeze > semantic-dependencies.txt
```

模型是 [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)，固定 revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`。只下载以下 11 个 safetensors／tokenizer／configuration 文件，不选择 pickle、ONNX、OpenVINO 或 Python 文件。

```sh
HF_HUB_DISABLE_IMPLICIT_TOKEN=1 .venv/bin/hf download \
  sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
  model.safetensors config.json config_sentence_transformers.json modules.json \
  sentence_bert_config.json special_tokens_map.json tokenizer.json \
  tokenizer_config.json sentencepiece.bpe.model unigram.json 1_Pooling/config.json \
  --revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42 \
  --local-dir ./models/paraphrase-multilingual-MiniLM-L12-v2
```

应用核对内置文件大小与 SHA-256；加载使用 `local_files_only=True`、`trust_remote_code=False`、`token=False` 和 safetensors。模型输出固定为 384 维 float32、mean pooling、128 token 序列、归一化、无 query prefix、CPU；长文本会按该模型的 token 上限截断。identity 包含资产、配置和实际库版本，更换后需要重新索引。构造模型是显式本地工作，普通启动不后台建索引或启动服务。

先验证完整本地链路，生成使用明确的离线 fixture，Embedding 使用实际神经模型：

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m ralf_agent.semantic_rag_reference \
  --offline --model-directory ./models/paraphrase-multilingual-MiniLM-L12-v2 \
  --repeats 3 --max-cases 8 --max-calls 24 --max-embedding-calls 128 \
  --evidence-dir ./private-semantic-offline-evidence --report ./semantic-offline-report.json
```

离线生成使 `model_quality`／`semantic_quality` 保持 null；神经 Embedding 的配置仍明确标记为非 fixture、非 Hash baseline。一次相似句向量命中不代表通用语义质量。

## 配置真实生成与完整重复评测

生成与本地 Embedding 独立选择。用户先设置明确的 `RALF_GENERATION_MODEL`、`RALF_GENERATION_URL`、`RALF_GENERATION_KEY`；不要把密钥写入 JSON、TOML、命令行参数或报告。下面 CLI 明确选择已有 DeepSeek thinking 适配器并固定 low effort；SDK 示例固定 non-thinking DeepSeekChatProvider。二者是不同的生成配置，应分别记录与重复评测；实际调用可能收费。

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m ralf_agent.semantic_rag_reference \
  --provider deepseek-thinking --reasoning-effort low \
  --model-env RALF_GENERATION_MODEL --base-url-env RALF_GENERATION_URL \
  --key-env RALF_GENERATION_KEY \
  --model-directory ./models/paraphrase-multilingual-MiniLM-L12-v2 \
  --typed-answers --repeats 3 --max-cases 8 --max-calls 24 \
  --max-embedding-calls 128 --max-output-tokens 2048 --timeout 45 \
  --evidence-dir ./private-semantic-live-evidence --report ./semantic-live-report.json
```

每次使用新 report／evidence 目录。失败和未尝试项保留在分母中；没有失败重试来提高成绩。原严格 oracle 分别检查答案、决策、实际展示来源、literal quote、版本与支撑，正确引用不替代正确答案。`max_calls`／`max_embedding_calls` 是适配器调用上限；通用端口不能据此保证外部费用上限。费用未知时保持 null。

默认八个任务与原文随包提供。`--cases /absolute/path/cases.json` 接受原 `{ "version": "1", "cases": [...] }` 格式，完整替换问题、文档与评分数据；示例见 [task-evaluation.md](task-evaluation.md)。`expected` 只进入独立评分，不进入模型请求。`--no-typed-answers` 显式选择旧提示。Provider 可改成已有 OpenAI、Anthropic、Gemini 等适配器；SDK 可直接注入自己的原异步 Provider／EmbeddingProvider，无需继承参考实现。

## SDK 接入与生命周期

```python
import asyncio
import os
import httpx
from ralf_agent.providers import DeepSeekChatProvider
from ralf_agent.planning_evaluation import EvaluationLimits
from ralf_agent.semantic_rag_reference import evaluate_semantic_rag

async def main():
    async with httpx.AsyncClient(follow_redirects=False) as client:
        provider = DeepSeekChatProvider(
            os.environ["RALF_GENERATION_MODEL"],
            api_key=os.environ["RALF_GENERATION_KEY"],
            base_url=os.environ["RALF_GENERATION_URL"],
            client=client, json_mode=True, max_output_tokens=2048, timeout=45, temperature=0,
        )
        return await evaluate_semantic_rag(
            provider,
            model_directory="./models/paraphrase-multilingual-MiniLM-L12-v2",
            typed_answers=True,
            limits=EvaluationLimits(max_cases=8, repeats=3, max_calls=24,
                                    max_output_tokens=2048, timeout_seconds=45),
            evidence_dir="./private-semantic-sdk-evidence",
        )

report = asyncio.run(main())
```

Generation Provider 与显式 `embedding=` 均借用，宿主负责它们的原生命周期。应用只拥有自己从 `model_directory` 构造的 CPU provider。`LocalSentenceEmbeddingProvider(model_directory, *, revision=REVISION, asset_manifest=None)` 可独立使用；可选 manifest 必须与内置固定资产和配置一致，不能自报另一组权重。

`await embedding.aclose(wait_timeout=30)` 停止新调用并等待原 CPU worker。观察者取消不取消已运行的 worker；等待不完整抛出 `CloseIncomplete` 并保留原模型／executor。`evaluate_semantic_rag` 的该异常附带 `local_embedding` 与已有的 `evaluation_report`；清理等待再次被取消也保留同一个原对象并抛出 `CloseIncomplete`。SDK 宿主须在原事件循环关闭前处理该异常，释放工作后重试该原对象的 `aclose`。推理配置漂移仍拒绝 identity／新 Embedding 调用，清理继续排空原 worker／executor，不采用替代组件。这只是资源清理，不是 Agent Action 重试或新回执。

原 RAG 查询是只读任务，本应用没有业务写入审批。终态重新连接只观察原 Run 与摄取回执，不重做摄取、索引、Embedding 或生成；评分中的 recovery 不覆盖所有进程故障窗口。需要业务写入的 Agent 应通过原 ToolSpec 审批／取消／恢复机制另行声明。

阶段门槛见 [delivery-gates.md](delivery-gates.md)：固定最终配置的真实生成重复结果必须单独登记。本指南的接入证明与离线 fixture 不自动关闭质量门槛，也不代表完整 M1／R01–R26 验收。
