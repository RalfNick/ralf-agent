# 全库事实索引与权威召回

dev56 提供显式全库派生索引基础，dev57 补齐 PostgreSQL 原生扫描；整个 R15/H3 的自动更新、治理和质量仍未完成。
它扩展既有 Facts、EmbeddingProvider、VectorIndex 与 CAS 存储，Local/Temporal 执行权威不变。

## 默认链路与替换

FactScanner / AsyncFactScanner 提供 fact_snapshot 与 scan_facts。
枚举包含 current/expired 原记录，按 UTF-8 字节和数量限制、Scope/namespace/epoch/generation 固定游标；
一个记录放不下时拒绝，不跳过后伪装完成。SQLite 用有界原始字节读取，首用激活持久 epoch，重开保持。
PostgreSQL 显式 initialize 增加 epoch 表，扫描沿既有 Facts writer/advisory 锁；named server cursor 每次只取一个有界 key/value 记录，避免普通 libpq 结果先缓冲整页。
Redis 采用同 hash slot 原子 Lua，固定持久 epoch/generation；原始 JSON 不经 cjson 转换，保留大整数。
普通 facts()/recall()仍不返回过期内容。扫描是宿主的显式索引／生命周期操作，不自动赋给 Agent 历史读取权限。

IndexedMemoryStore 组合原 Facts、Embedding、VectorIndex 和可替换 Catalog。
FactIndexMetadataStore / AsyncFactIndexMetadataStore 定义 load 的已完成 revision/value 与 save 的原子 CAS 回执；
可以替换为独立数据库实现，并显式声明物理资源和格式 identity。FactIndexCatalog 用独立私有 namespace 的 CAS memory transport 保存派生索引控制记录，
不把这些记录作为 Agent 事实，不调度 Run。默认 JSON/TOML 工厂使用 SQLite source/vector/catalog。
SDK 可分别注入同步／异步数据、任意合规 Embedding 和 VectorIndex；Hash 是离线词项基线。

```python
from relf_agent import (
    FactIndexCatalog,
    HashEmbeddingProvider,
    IndexedMemoryStore,
    RecallQuery,
    Scope,
    SQLiteMemory,
    SQLiteVectorIndex,
)

scope = Scope()
source = SQLiteMemory(".ralf/facts.sqlite")
metadata = SQLiteMemory(".ralf/fact-index-catalog.sqlite")
vectors = SQLiteVectorIndex(".ralf/fact-vectors.sqlite", dimensions=128)
memory = IndexedMemoryStore(
    source,
    HashEmbeddingProvider(dimensions=128),
    vectors,
    FactIndexCatalog(metadata),
)
try:
    source.put_fact(scope, "assistant", "preference", "Use Chinese", expected_version=0)
    result = await memory.rebuild(scope, "assistant", max_pages=64)
    if result["status"] == "ready":
        page = await memory.recall(scope, "assistant", RecallQuery(text="Chinese"))
        await memory.validate_facts(scope, "assistant", page.items)
finally:
    vectors.close()
    metadata.close()
    source.close()
```

SDK 注入都是 borrowed，宿主停止使用后关闭资源；RuntimeBuilder 创建的依赖按原资源账本 owned 关闭。
Agent 默认事实 namespace 是 Agent.name；显式每 Agent 绑定使用宿主选定的物理 namespace。
建立索引前 seed、写入或迁移事实；初版写后需显式 rebuild，不隐藏自动 Embedding 开销。

## 构建、采纳与恢复

rebuild 每次处理有限页，返回 building 或 ready。同一有效来源快照沿原 build_id/cursor 续接。
一页经过扫描／Embedding 接收回执／幂等向量 upsert／页游标提交；最后才激活完整索引。
未接受响应的请求可能重复；已保存的 Embedding 响应被重开复用。
向量提交但进度 ACK 丢失时，同稳定 chunk ID 再次 upsert，允许幂等派生写重复。
源变化、配置／实际 SQL 资源漂移、损坏或伪造完整状态拒绝，不把 partial 当成 ready。

recall 先检查已激活索引与当前源快照，查询向量后回读原事实、核验 key/version/value digest/TTL。
引用携带索引发布标记，新的模型派发走原 validate_facts；已经被执行权威接受的模型响应保持原采纳规则。
游标绑定查询、发布和 query-vector digest；续接期间重新计算的查询向量变化会拒绝混合结果。
原 FactsView 可以限定实际范围并追加 provenance，不会因索引给 Agent 开放 raw expired 扫描。

## JSON/TOML 接入

```json
{
  "memory_store": {
    "adapter": "indexed-recall-async",
    "config": {
      "backend": {"adapter": "sqlite", "config": {"path": "facts.sqlite"}},
      "embedding": {"adapter": "hash", "config": {"dimensions": 128}},
      "batch_size": 32,
      "max_page_bytes": 64000,
      "max_records": 100000
    }
  },
  "recall_planner": {"adapter": "task-text"}
}
```

上述为 Profile.components；使用 abuild。index/catalog 省略时分别使用独立 SQLite 默认文件。
嵌套组件独立注册为 embedding_provider / vector_index / fact_index_catalog；自定义工厂可同步或异步。
显式 HTTP 采用 embedding adapter=http，沿用 model/dimensions/base_url/api_key_env 或 anonymous 的配置。
index 默认从已知 embedding dimensions 取得维度；自定义 Embedding 未在 config 声明维度时须显式配置 index dimensions。
index adapter=qdrant 显式声明 url_env、backend_id、collection、dimensions，可选 api_key_env、timeout、initialize。
initialize 默认为 false，仅核验既有集合；true 才允许创建缺失集合，不替换既有配置。物理 URL/Collection 固定于发布身份，变更需新构建。
单页最多128记录，自动受32768向量数值预算缩小；64000字节来源、32768字符单文本和1MiB接收回执限额；总记录默认最多100000，可显式缩小。
额度包含过期扫描记录；越限保留可检查的 partial，不激活不完整索引。
查询从全库排序的前256候选中分页，这个上限独立于 RecallQuery.max_items/scan_limit；next_cursor=None 表示当前 top256 窗口已结束，
不证明所有匹配事实均已枚举。事实全库迁移应使用 FactScanner，而非 recall。

## 当前证据与开放范围

memory/SQLite 全库330事实、过期和他域排除；四个真实进程提交窗口保留2次 batch Embedding，最终4向量。
FactsView分页/provenance、JSON/TOML装配及原Run重开有测试；真实本地Redis270条及客户端／SQLite向量重开通过，
原ready回执复用不重做Embedding。Qdrant新工厂和collection切换采用HTTP fixture验证，仍需真实服务组合验收。
PostgreSQL16.15 真实服务已验证270条全库索引、连接／向量重开、配置Agent和四进程窗口；新[PG验收](../architecture/reviews/2026-10-11-postgres-fact-indexing.md)独立记录。
dev58 [Temporal Facts绑定](temporal-facts.md)已接通原Context History与scope/namespace视图；跨机器索引服务及真实语义质量仍独立验收。dev56回归／安装证据见[验收](../architecture/reviews/2026-10-11-fact-indexing.md)。
PostgreSQL source/catalog 都可通过既有 backend adapter=postgres 配置 dsn_env、backend_id、initialize；使用 abuild，实际连接由资源账本 owned 关闭。
旧数据库在首次采用新 Scanner 前显式调用 PostgresMemory.initialize 或设置 initialize=true；这是新增表，不是执行历史热迁移。
更换数据库时更新 backend_id/Profile；隐藏环境别名移动不算同一个发布。
多页期间的每次 SourceMutation 都须重新构建；索引损坏修复、旧 namespace GC、全局容量、删除传播、
自由信念修订和真实语义质量继续按 R15/R17/R26 验收。native memory/SQLite cosine 搜索为小语料线性扫描，
查询 scan_limit限制候选回读／输出，不是向量底层扫描成本或真实费用上限。

见[持续队列](continuous-development.md)与[能力清单](remaining-work.md)。
