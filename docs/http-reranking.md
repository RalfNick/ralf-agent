# 显式 HTTP 语义重排

dev48 提供 `HTTPReranker`，实现原 `AsyncReranker`。先由已有 lexical／vector／RRF
取得有界候选，再由显式配置的服务排序；原 KnowledgeStore 负责来源版本、TTL、文本 digest
和 Scope 校验。重排只选原候选 ID，远端新文档／来源／权限不会成为证据。

协议参考 [Cohere Rerank v2 官方接口](https://docs.cohere.com/v2/reference/rerank)，
2026-10-10 核对：向调用方指定的 `base_url + /rerank` 发送
`model/query/documents/top_n`；响应 `results` 按排名给出 `index/relevance_score`，可选
`meta.billed_units.search_units`。没有商用端点或模型默认值，不承诺所有厂商接口兼容。
服务可能自行截断长文档；客户端字符限额不是模型 tokenizer 或语义质量保证。

## 配置语义知识组合

```python
from relf_agent import RuntimeBuilder, recommended_profile

profile = recommended_profile(
    "semantic-knowledge",
    embedding={
        "type": "openai",
        "config": {
            "model": "YOUR_EMBED_MODEL",
            "dimensions": 1024,
            "base_url": "https://YOUR_EMBED_SERVICE/v1",
            "api_key_env": "APP_EMBED_KEY",
        },
    },
    reranker={
        "type": "http",
        "config": {
            "model": "YOUR_RERANK_MODEL",
            "base_url": "https://YOUR_RERANK_SERVICE/v2",
            "api_key_env": "APP_RERANK_KEY",
            "timeout": 30,
        },
    },
    name="my-knowledge",
    version="2",
)
# 在 async 应用中显式构造；该步骤不发送 Embedding／Rerank 请求。
# instance = await RuntimeBuilder().abuild(profile, "runs.sqlite")
```

向已有 `sqlite-hybrid-http`／`postgres-qdrant-hybrid` 配置添加同样的
`reranker` 声明，使用 `abuild`。本地离线 Hash 基线配 HTTP 重排时，显式选择
`knowledge.adapter="sqlite-hybrid-rerank-http"`；默认 Hash 不构成语义 Embedding。
原同步 `sqlite-hybrid` 拒绝 HTTP 重排，且在打开数据库前拒绝。

测试／自部署无鉴权端点显式写 `anonymous=true`，不能同时配置 `api_key_env`。
只在显式选定适配器时读取指定环境变量；秘密不进入 Profile／Manifest／组件 identity。
JSON／TOML 配置复用原声明语言，例如：

```toml
[profiles.components.knowledge]
adapter = "sqlite-hybrid-rerank-http"
[profiles.components.knowledge.config]
namespace = "manuals"
[profiles.components.knowledge.config.reranker]
type = "http"
[profiles.components.knowledge.config.reranker.config]
model = "YOUR_MODEL"
base_url = "http://127.0.0.1:8080/v2"
anonymous = true
```

原 `reranker="preserve-order"`／`"token-overlap"` 仍可用；省略新选项时，dev47 的七个
推荐 Profile 和原 Knowledge 组件身份保持。修改重排服务、模型或限额应发布新 Profile 版本，
旧 Run 继续使用原定义及已接受的引用快照。

## SDK 替换及生命周期

```python
from relf_agent import HTTPReranker, HybridRetriever

ranker = HTTPReranker("YOUR_MODEL", base_url="https://YOUR_SERVICE/v2", api_key=host_key)
retriever = HybridRetriever(knowledge_store, branches, reranker=ranker)
# report = await ranker.rerank_result(query, candidates, limit=5)
# report.ids / report.scores / report.usage 是独立副本。
# 最后 await ranker.aclose()
```

SDK 直接注入的 ranker／客户端由调用方管理；借用的 `httpx.AsyncClient` 不由 ranker 关闭。
Profile 工厂用 `own_async` 管理 ranker 和其惰性客户端，随 Runtime 关闭，后续装配失败也会清理。
限于同一事件循环；运行中禁止关闭，取消须等待实际 HTTP coroutine 退出。
响应流清理若失败或再次被取消，适配器保留实际流；后续 `aclose` 先完成其清理。
客户端和响应的 HTTPX `is_closed` 标志不作为实际释放完成证据。
关闭失败或被取消后禁止新请求，但可以重试 `aclose`；并发关闭明确拒绝。
owned 客户端使用独立的显式传输，不读取环境代理／证书配置；需要这些宿主配置时，
SDK 注入自管的 `httpx.AsyncClient`。方法、配置或客户端被替换会拒绝采纳／关闭，
调用方需恢复原组件或执行自己的资源处置，不能静默关闭替换客户端。

默认最多 256 个候选、4096 查询字符、32768 单文档字符、262144 总字符、1 MiB 响应。
所有候选／Unicode／限额先校验；无候选不发请求。非空候选要求非空查询。
每次只有一个 POST，无自动重试和重定向；完整流式响应有上限。
索引必须是唯一的原精确整数，数量须为 `min(limit,候选数)`；分数有限且按降序排列。
错误、空／部分／重复结果、伪造索引、无效计量均失败，不伪装成成功检索。
服务响应模型字段若存在须一致；不采纳返回的文档文本。

## 恢复、质量和费用边界

Hybrid 在重排前后回读来源。远程等待期间来源变化会拒绝结果，阻止旧文本进入新的模型请求。
`failure_policy="degrade"` 只容许已声明的召回分支降级，不会静默绕过失败的重排服务。
已持久化模型响应及引用快照的 Action 恢复不重新重排该 Action；下一次模型决策仍有独立检索。
**检索准备本身不是持久化模型 Action**：准备中断、重启或显式重试可能再次产生付费请求。
execution credits 不包含 Embedding／Rerank 真实费用，也不提供费用硬上限。

直接 `rerank_result` 可取得 search_units，缺失时为 `None`。分数用于排名，不能视为可信度、
业务正确性或统一费用单位；Hybrid 的候选 score 仍保留原融合含义，usage 不自动计入 Run 账本。
实际语义、答案和引用质量需要固定业务任务与模型评测。本轮只使用协议夹具，未调用真实服务模型。
Temporal 可显式注册该 Knowledge 端口，复用原 Context／History 校验；本轮仅纯协议测试，
Local Profile 不替代 Worker 装配，不新增 Temporal 发布协议。
