# 可组合的 Embedding、混合召回与重排

`0.1.0.dev19` 增加显式 HTTP Embedding、可替换排名融合／重排，以及一个来源权威下的并行混合检索。默认仍可完全离线运行。D1 的原子摄取和向量索引分开；D2 不启动后台索引、付费模型、自动摘要或记忆提炼。

## 安装后使用自己的文档

```sh
pip install /path/to/ralf_agent-0.1.0.dev19-py3-none-any.whl
ralf init my-hybrid-agent --template hybrid
cd my-hybrid-agent
python -m agent_app ingest /absolute/path/runbook.md --document-id runbook --command-id ingest-first --expected-version 0
python -m agent_app index --document-id runbook
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

第十六种包内模板使用 SQLite 知识权威、SQLite 向量索引、词项散列 HashEmbedding、词法召回、RRF 和保序重排。初始语料为空，没有内置业务文档或模型密钥。离线 Provider 复制证据并引用文档 ID／版本／URI；`grounded` 表示存在引用证据，不代表语义相关性或业务回答已经被验证。HashEmbedding 和 TokenOverlapReranker 都是词法基线。

默认执行库 `.ralf/runs.sqlite`、知识库 `.knowledge.sqlite` 后缀、向量库 `.vectors.sqlite` 后缀。摄取回执只确认知识提交；显式 `index` 返回 `index_call_completed`，不是持久索引作业回执。重复索引允许，部分失败需要显式重试；源修改后再次索引。向量命中始终回读现存来源，旧版本、删除、过期和跨 Scope 数据无法作为有效证据。

查询可加 `--submit-only`，再通过原工厂恢复：

```sh
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

保留原代码、Profile、模型配置和数据库用于恢复；更换 Embedding 模型／配置应选择新索引与新 Profile 版本，再显式重建。

## SDK：逐层组合

```python
from ralf_agent import (
    HashEmbeddingProvider,
    HybridRetriever,
    LexicalRetriever,
    RRFFusion,
    TokenOverlapReranker,
    VectorRetriever,
)

vector = VectorRetriever(store, index, HashEmbeddingProvider(dimensions=index.dimensions))
retriever = HybridRetriever(
    store,
    {"lexical": LexicalRetriever(store), "vector": vector},
    fusion=RRFFusion(rank_constant=60),
    reranker=TokenOverlapReranker(),
    branch_limit=10,
    candidate_limit=32,
    max_candidate_chars=64000,
)
# 索引为明确、独立的调用：
await vector.index_document(scope, "docs", "runbook")
result = await retriever.retrieve(scope, "docs", query)
print(result.mode, result.items)
```

每层都可独立替换，不要求继承框架类：

| 端口 | 契约 | 默认与替换 |
| --- | --- | --- |
| EmbeddingProvider | async embed(list[str]) → 按输入顺序的有限向量 | 离线 HashEmbedding；显式 OpenAIEmbeddingProvider；其他协议可自定义 |
| KnowledgeRetriever | retrieve／validate | 词法、权威回读的向量、Hybrid；来源 Store 独立替换 |
| RankFusion | 同步 fuse(分支→有序候选 ID, limit) → FusionRank 序列 | RRFFusion；自定义评分与次序，不改写候选正文 |
| Reranker／AsyncReranker | rerank(query, 候选快照, limit) → 已有候选 ID 子集／次序 | PreserveOrderReranker；TokenOverlapReranker；显式异步／模型实现 |

RRF 采用一基排名的倒数融合，避免直接相加不同后端未经标定的原始分数；同分按块 ID 稳定排序，可配置正权重。[RRF 原理参考](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)

候选源经同一 Store 校验，融合和重排只能提出 ID／排名；框架采用原候选正文与来源。返回 coroutine／generator／contextmanager 等与声明模式不符的惰性对象、重复／未知 ID、错误 Scope 或超限结果会明确拒绝。分支、方法、配置与组件身份在操作期间固定。重排结果立即冻结；融合计算后、外部重排前及重排后的等待完成后复核当前来源，避免已过期证据继续派发。

## 显式 HTTP Embedding

```python
from ralf_agent import OpenAIEmbeddingProvider

async with OpenAIEmbeddingProvider(
    model="YOUR_EMBEDDING_MODEL",
    base_url="https://YOUR_ENDPOINT/v1",
    api_key="YOUR_EXPLICIT_KEY",
    dimensions=1536,
) as embedding:
    report = await embedding.embed_result(["connection pool exhausted"])
    print(report.vectors, report.usage, report.batches)
```

适配器实现 `/embeddings` 的 float 协议：显式 model 与 input，通过返回的 index 恢复顺序，拒绝缺项、重复索引、错误模型、维度、布尔／非有限／零向量及错误完成。`send_dimensions=True` 才发送可选 dimensions 字段；是否支持这一参数由所选模型决定。[协议依据](https://developers.openai.com/api/reference/resources/embeddings/methods/create)

提供模型、端点、维度与凭据；SDK 不读取默认宿主密钥。显式选择无认证本地端点时可 `api_key=None`。默认客户端首次请求时创建并由 Provider 关闭；传入 httpx.AsyncClient 则借用，不关闭宿主客户端。Provider 固定事件循环，活动请求期间拒绝关闭；取消等待真正的 HTTP 操作退出，关闭失败保留重试句柄并拒绝继续使用。连接／响应错误不记录远端正文、密钥或输入。没有隐式重试、重定向或模型下载。

请求在第一批发送前完成全部输入校验；空列表不产生请求。绝对上限为 4096 个输入、单文本 32768 字符、总文本 4MiB 字符、总向量标量 4000000。默认 batch_size=32（最多 256），每批最多 262144 字符、解码响应最多 8MiB，timeout 默认 60 秒且不超过 300。可调小这些界限。字符数不等于供应商 token 限额，使用者仍需按实际模型约束分块。

`embed` 保持旧向量列表接口；`embed_result` 额外返回不可变 EmbeddingResponse，按请求记录供应商 prompt_tokens／total_tokens，缺失时为 null。费用未估算；embedding／外部重排不计入已有 synthetic execution credits。部分批次失败或取消前可能已产生供应商费用，不能依据本地未返回结果推断零费用。

国内外提供相同 float/index 协议的端点可显式配置；型号兼容、维度与线上语义质量需逐端点验证。本轮本地 HTTP fixture 使用散列向量，只证明协议与生命周期；未调用真实语义模型。

## 声明式装配

新增三个名字，原声明保持：`sqlite-hybrid` 为同步离线默认，`sqlite-hybrid-http` 为显式异步 HTTP，`postgres-qdrant-hybrid` 为异步远程默认／HTTP。示例：

```python
from ralf_agent import RuntimeBuilder, RuntimeProfile

profile = RuntimeProfile(
    "my-hybrid",
    "1",
    {"default": {"adapter": "offline-echo"}},
    components={
        "knowledge": {
            "adapter": "sqlite-hybrid",
            "config": {
                "namespace": "docs",
                "path": "knowledge.sqlite",
                "index_path": "vectors.sqlite",
                "reranker": "token-overlap",
                "embedding": {"type": "hash", "config": {"dimensions": 128}},
                "fusion": {"rank_constant": 60, "weights": {"lexical": 1, "vector": 1}},
            },
        }
    },
)
runtime = RuntimeBuilder(base_dir=APPLICATION_DIR).build(profile, RUN_DB)
```

HTTP 声明为 `embedding.type='openai'`，config 明确 model／dimensions／base_url 和 `api_key_env`；不接受内联密钥。无认证端点需显式 `anonymous=True`。HTTP／远程使用 `await RuntimeBuilder(...).abuild(...)` 并 `await runtime.aclose()`，不能通过同步 ProfiledEngine／CLI 偷渡异步资源。装配不请求 Embedding 或索引，但可按显式 initialize 初始化远程表／collection。未知字段、权重分支、维度冲突和缺少环境引用在执行库／远程连接分配前拒绝。

PostgreSQL/Qdrant 额外声明 dsn_env、backend_id、url_env、index_backend_id、collection 与显式 initialize。连接与配置参考[远程接入](remote-data.md)和[异步装配](async-assembly.md)。只选择新 Profile／保留旧版本即可切换，运行中替换组件不能改变已接受任务的恢复配置。

## 容量、失败与边界

Hybrid 支持 1–8 个命名分支；每分支不超过 256 候选，总候选不超过 256，配置要求 branch_limit × 分支数 ≤ candidate_limit；候选 JSON 总预算最多 1MiB（默认 64000），查询最多 32768 字符。最终返回仍服从调用方 limit／max_chars。并行分支采用结构化任务，失败／取消会等待其他分支退出，组件借用生命周期由宿主管理；插件内部创建的线程／远程请求须由插件负责真实退出。

默认 `failure_policy='strict'`：任一失败即拒绝。显式 `degrade` 只允许 ProviderError／MemoryBackendError 的召回分支失败，结果 mode 包含缺失名字，例如 `hybrid:rrf:degraded:vector`；全部分支失败仍拒绝。错误 Schema／重复候选／来源冲突／越界／Scope／固定身份／来源权威失败始终拒绝。默认 KnowledgeContext 保留引用格式，调用方可通过 retriever.retrieve 的 mode 观察降级；它不是企业检索诊断平台。

本轮增加协议与组合能力，不证明语义召回、答案／引用正确性或同等模型下优于其他框架。D3 token 上下文、大结果卸载、摘要／长期记忆提炼，D4 真实质量与外部采用，仍见[智能数据设计](../architecture/viewpoints/intelligent-data-pipeline.md)。
