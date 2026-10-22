---
title: 会话、记忆与 RAG
description: 区分对话历史、长期事实与知识文档，控制进入模型的内容，并保留可追溯来源。
locale: zh
slug: sessions-memory
sources: [docs/session-api.md, docs/recall-and-rag.md, docs/managed-memory.md, docs/document-ingestion.md, docs/hybrid-retrieval.md, docs/context-artifacts.md, docs/support-journey.md, docs/html-ingestion.md, docs/docx-ingestion.md, docs/pdf-ingestion.md]
---

## 先区分四种数据

| 组件 | 保存什么 | 典型用途 |
| --- | --- | --- |
| Session / Turn | 会话身份、每轮输入、消息与原 Run 引用 | 同一客户连续提问、跨进程继续对话 |
| Facts / 长期记忆 | 有 Scope、namespace、版本与来源的事实 | 已确认的偏好、业务约定与观察结果 |
| Knowledge / RAG | 摄入文档、分块、版本、来源与检索引用 | 从产品说明、运维手册、政策资料中找证据 |
| Context / Artifact | 本次模型实际使用的消息与引用；大内容的独立产物 | 控制请求体积，按需读取工具大结果 |

Execution Store 另行保存 Run、Action、审批、响应快照和回执。删除会话消息不能替代取消任务，替换知识库也不会改变原执行记录。

## 多轮会话如何继续

一个 Session 可以包含多个有序 Turn，每个接受的 Turn 指向原 Run。先处理上一轮的审批、[持久用户输入](/zh/docs/user-input/)或恢复，确认会话空闲后，再提交下一轮。

在新工作目录将下面完整的无密钥示例保存为 `session_agent.py`。[模型与工具](/zh/docs/models-tools/)中的 `AgentSpec` 是声明，这里创建的是提供 `open_session` 并拥有本地 Runtime 的 `Agent` 入口。

```python
import asyncio
from ralf_agent import Agent, ModelResponse

class OfflineSupport:
    identity = {"kind": "website-session-fixture", "version": "1"}

    async def complete(self, messages, tools):
        found = any("123" in str(message.get("content", ""))
                    for message in messages)
        return ModelResponse(output={"order": "123" if found else None})

async def main():
    async with Agent(
        model=OfflineSupport(), name="support",
        instructions="Keep the customer's order in the conversation.",
        db_path=".ralf/session.sqlite",
    ) as agent:
        session = await agent.open_session("customer-42", command_id="open-42")
        first = await session.submit("My order is 123", command_id="turn-1")
        observed = await first.wait(wait_timeout=10)
        print(observed.snapshot.state, observed.snapshot.result)

        if observed.snapshot.state != "succeeded":
            print(await first.pending())
            return
        for _ in range(100):
            if not (await session.status()).busy:
                break
            await asyncio.sleep(0.01)
        else:
            print("Session still busy; inspect the original run:", first.ref.to_dict())
            return
        second = await session.run("What was the order?", command_id="turn-2")
        print(second.snapshot.state, second.snapshot.result)

asyncio.run(main())
```

运行 `python session_agent.py`，应得到两条 `succeeded`、`order: 123` 的结果。离线 Provider 只检查上下文中是否包含保存的文本，验证会话装配与执行，不衡量真实模型记忆质量。有界状态检查允许宿主短暂收尾；持续 busy 时检查原 Run，不提交新 Turn。原样重复文件回读相同轮次。跨进程继续及真实模型选项见[连续应用教程](/zh/docs/app-tutorial/)，精确契约见 [API 与 CLI 参考](/zh/docs/api-reference/)。

等待超时只表示观察窗口结束，原任务可能仍在执行。保留原句柄继续等待或显式控制，不要因为超时提交下一 Turn。即使 Run 已终结，会话也可能短暂保持 busy，等待执行与未结义务收尾。

同一命令 ID 回读原回执；曾因 busy 被拒绝的命令也会回读原拒绝。处理阻塞、确认空闲后，新的提交尝试使用新的命令 ID。跨进程恢复保留原 Session 引用、Run 引用、配置和数据，不把 `attach` 或 `status` 当作执行恢复。

## 先跑一个离线知识助手

在已安装 SDK 的环境中，选择新目录：

```bash
ralf init my-knowledge-agent --template rag
cd my-knowledge-agent
python -m agent_app --query 'postgres connection refused'
python -m agent_app --query 'quantum entanglement teleportation'
```

第一条查询匹配模板真实摄入的本地文档；第二条应返回 `grounded=false`、空引用与拒答。检查结果中的 `document_id`、`version`、`source_uri` 和摘录，理解答案依据。

模板使用 SQLite 词法检索与离线 Provider，不下载 Embedding、不调用模型服务。它验证检索、引用与执行链路，不是回答质量评分。`local://...` 是来源标识，不表示发起网络请求。

相同查询默认使用稳定命令 ID，重复执行会回读原 Run。文档更新后要重新回答，请显式使用新 `--command-id`；恢复旧 Run 不会用新文档替换已保存的响应。

## 摄取与更新自己的文档

使用独立 `ingest` 模板导入一份 UTF-8 Markdown：

```bash
ralf init my-doc-agent --template ingest
cd my-doc-agent
python - <<'PY'
from pathlib import Path
Path("runbook.md").write_text(
    "Pool timeout: inspect the connection pool and service health.",
    encoding="utf-8",
)
PY
python -m agent_app ingest runbook.md --document-id runbook \
  --command-id ingest-first --expected-version 0
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

`expected_version=0` 表示只在文档不存在时创建；更新需传入当前版本，避免覆盖并发变更。相同摄取命令与源内容返回原摄取回执，修改内容使用新命令。来源摘要、文档版本、分块和回执一同保存。

默认支持文本与 Markdown；HTML、DOCX、文本 PDF 有各自解析器和限制，PDF 需要可选依赖，图片 OCR 与页面视觉理解不在该文本链路中。详见[文档摄取](repo:docs/document-ingestion.md)及格式专题。

## 从词法到语义检索

| 检索方式 | 适合的起点 | 配置关注点 |
| --- | --- | --- |
| 词法 | 术语明确、小规模本地手册 | 查询词、分块、来源版本与返回条数 |
| 向量 | 需要按语义接近程度召回 | 显式 Embedding、维度、模型身份与重新索引 |
| Hybrid | 结合关键词和向量候选 | 分支额度、融合策略、候选总量与可选重排 |

本地向量实现使用线性搜索，不能当作 ANN 或托管向量库。离线 Hash Embedding 只是接入基线；真实 Embedding／重排服务需要自己的凭据与费用管理。文档更新后显式重新索引，不能假定旧向量代表新内容。见[混合检索](repo:docs/hybrid-retrieval.md)。

## 跑通摄取、索引与混合检索

安装后另选新目录。模板初始语料为空，以下命令依次创建原文、提交来源、建立向量索引并查询：

```bash
ralf init my-hybrid-agent --template hybrid
cd my-hybrid-agent
python - <<'TEXT'
from pathlib import Path
Path("runbook.md").write_text("Pool timeout: inspect the connection pool and service health.", encoding="utf-8")
TEXT
python -m agent_app ingest runbook.md --document-id runbook --command-id ingest-first --expected-version 0
python -m agent_app index --document-id runbook
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

应依次得到 `knowledge_committed`、`index_call_completed`，以及包含 `grounded=true` 和 `runbook` 版本／来源的查询结果。修改 `agent_app/runtime.py` 可替换检索组合。默认是 HashEmbedding＋词法候选＋RRF，保留融合后的顺序；散列向量只是词法接入基线，不是语义模型。索引失败不回滚摄取，需显式重试索引。更新文档时使用当前 expected version 和新命令 ID 摄取，再次索引，并以新 ID 查询。

### 显式验证语义 Embedding 端点

以下可选完整探针会发送真实 HTTP 请求，可能产生供应商费用。通过凭据管理方式设置代码中的四个环境变量，选择兼容 float `/embeddings` 的端点和型号实际维度。保存为 `semantic_probe.py`，运行 `python semantic_probe.py`：

```python
import asyncio
import os
from ralf_agent import OpenAIEmbeddingProvider

async def main():
    async with OpenAIEmbeddingProvider(
        model=os.environ["RALF_EMBED_MODEL"],
        base_url=os.environ["RALF_EMBED_BASE_URL"],
        api_key=os.environ["RALF_EMBED_API_KEY"],
        dimensions=int(os.environ["RALF_EMBED_DIMENSIONS"]),
    ) as embedding:
        report = await embedding.embed_result(["connection pool exhausted"])
        print(len(report.vectors), len(report.vectors[0]), report.usage)

asyncio.run(main())
```

应得到一个配置维度的向量，用量缺失时仍为未知。这只检查有限协议响应，不验证语义检索质量。仅在型号支持该请求字段时设置 `send_dimensions=True`。将其用于 RAG 时选择**新的** Profile／索引，Knowledge adapter 使用 `sqlite-hybrid-http`，设置 `embedding.type="openai"` 及 `config.model`、`dimensions`、`base_url`、`api_key_env`。通过 `await RuntimeBuilder(base_dir=...).abuild(profile, db_path)` 装配，使用 `await assembly.aclose()` 关闭异步资源。应用需先摄取来源，再显式调用所选向量 Retriever 的 `index_document(scope, namespace, document_id)`；构建 Profile 本身不会索引文档。保留原 Profile 和索引用于旧 Run；更换模型或维度后重建全部来源向量，再按[测试与评估](/zh/docs/testing/)分别验证检索与回答质量。

## 长期记忆与上下文的边界

先从可信宿主显式写入 Facts 开始。需要自动提炼时，选择受管理记忆，配置允许字段和来源路径；任务成功与记忆提交有各自回执，不能只凭业务 Run 成功推断记忆已保存。模型提出的内容不自动成为已确认事实。

召回可限制条目数、字符量和扫描候选数。Context 仍需选择实际进入模型的完整消息组、事实与引用；过大的工具结果可以显式保存为 Artifact，再按需读取。字符／估算 Token 额度不等于供应商精确 Token 或费用上限。

检索来源会校验版本、摘要与有效期；模型输出的答案和引用仍需应用验证。可信 Scope 与资源绑定控制读取范围，但不单独提供认证或企业文档 ACL。继续阅读[运行与部署](/zh/docs/operations/)，管理这些组件的配置与生命周期。
