# Redis、PostgreSQL 与 Qdrant

dev14 提供真实服务适配器，默认内存/SQLite 继续可用。远程数据接入不改变 LocalEngine 的单 Coordinator 执行权；Redis/PG 数据端口不是分布式执行后端。

| 实现 | 角色 | 默认行为 |
| --- | --- | --- |
| RedisMemory | Session、Facts、分页、事实核验 | Lua 原子 CAS/消息去重，同操作 key 位于同一 hash slot，逻辑 TTL |
| PostgresMemory | Session、Facts、分页、事实核验 | 参数化 SQL、事务/advisory lock、消息索引与高水位 |
| PostgresKnowledgeStore | 原始文档与 Chunk 权威 | CAS、TTL、删除墓碑、中文/英文词法检索 |
| QdrantVectorIndex | 派生 Cosine 索引 | 固定维度/collection、Scope 过滤、稳定 UUID、确认写入完成 |
| HashEmbeddingProvider | 可替换 EmbeddingProvider 的离线基线 | 确定性词项散列；不属于语义模型 |

dev57 原生 PostgresMemory 也提供 FactScanner／fact_snapshot：持久 scoped epoch/generation、named server cursor 及读取前 key/value 字节限制。
显式 initialize 新增 ralf_memory_fact_scan_epochs 表，不改已有 Session/Facts；旧应用不采用扫描时继续原接口。
SDK和indexed-recall-async工厂可组合PG来源与PG或SQLite Catalog；见[全库事实索引](fact-indexing.md)。这是数据端口，仍不替代执行权威。

## 安装与直接接入

源码开发环境安装可选客户端；Qdrant 使用既有 httpx，无 SDK 依赖。基础安装和公共导入不要求 redis/psycopg。

```shell
python -m pip install -e ".[remote]"
```

也可单独选 `.[redis]` 或 `.[postgres]`。这些是客户端；Redis/PG/Qdrant 服务由使用者部署。SDK connect 不初始化 PG 表，显式调用 initialize；建表为新增 ralf_* 表/索引，不执行破坏性重建。

```python
import asyncio
import os

from ralf_agent import PostgresMemory, Scope


async def application():
    async with await PostgresMemory.connect(
        os.environ["RALF_POSTGRES_DSN"], backend_id="business-memory-v1"
    ) as memory:
        await memory.initialize()
        scope = Scope()
        revision = await memory.append(
            scope,
            "conversation",
            {"role": "user", "content": "你好"},
            expected_revision=0,
            message_id="message-1",
        )
        return revision, await memory.read(scope, "conversation")


if __name__ == "__main__":
    print(asyncio.run(application()))
```

RedisMemory.connect 同样创建 owned 客户端；传入 redis.asyncio.Redis 则默认 borrowed。PG 借用连接须 autocommit=True，同一连接上的两个适配器共享事务锁；应用不能同时绕过适配器独立操作该连接。connect 创建 owned 连接；aclose 关闭 owned，borrowed 仍由应用管理。

backend_id 必须稳定且显式表示实际数据域。切换服务、数据库或前缀时更新身份/Profile；隐藏环境别名变化不能作为同一个发布。Scope 来自可信宿主，数据过滤不是企业身份认证。

## 通过 RuntimeBuilder 装配

session_store/memory_store 注册了 async `redis`、`postgres`；knowledge 注册 `postgres-lexical`、`postgres-qdrant`。通过 abuild/async with 使用，默认同步 CLI/ProfiledEngine 暂不装配这些异步工厂。CLI 的只读 inspect/status/events 可观察本地执行日志。

```python
import asyncio

from ralf_agent import AgentSpec, RuntimeBuilder, RuntimeProfile


async def application():
    declaration = {
        "adapter": "postgres",
        "config": {"dsn_env": "RALF_POSTGRES_DSN", "backend_id": "app-memory", "initialize": True},
    }
    profile = RuntimeProfile(
        "remote-app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"session_store": declaration, "memory_store": declaration},
    )
    async with await RuntimeBuilder().abuild(profile, ".ralf/remote.sqlite") as runtime:
        handle = runtime.submit(AgentSpec("assistant", "Answer"), "hello", command_id="first")
        return await runtime.drive(handle.run_id)


if __name__ == "__main__":
    print(asyncio.run(application()))
```

JSON/TOML 只保存 `url_env`／`dsn_env`／`api_key_env` 的变量名称，不保存凭据。缺失环境值在创建执行库前拒绝。PG 工厂 initialize 默认 False；显式 True 请求初始化，生产部署可由数据库管理员先建表。owned 资源交给 dev13 生命周期，失败/取消保留清理句柄。

## PG + Qdrant 的 RAG 组合

knowledge 选择 postgres-qdrant，config 包含 dsn_env/backend_id、url_env/index_backend_id、collection、dimensions（默认128）、namespace、可选 api_key_env/initialize/timeout/chunk_size/overlap/limit/max_chars。同样可用 JSON/TOML。

初始化之后显式写入 Document，并调用 `await runtime.knowledge.retriever.index_document(scope, namespace, document_id)`。检索通过索引取得版本/摘要，再回读 PG Chunk；删除/过期/更新来源不能仅凭旧向量命中成为上下文。索引写入和文档事务没有跨服务原子提交，部分失败需显式重建索引。

默认 HashEmbeddingProvider 用于无网络/费用的接入基线。生产语义检索应实现/注入 EmbeddingProvider，并构造 `VectorRetriever(store, index, embedding)`；Embedding identity/维度参与索引 namespace，变更后需要重新索引。默认 factory 可替换为使用者注册的 async 工厂，端口不要求继承默认实现。

## 一致性与验证范围

重复 message_id+相同 JSON 返回原 revision；不同内容报 IdempotencyConflict。Session 分页固定高水位，后续追加不混入旧页；Facts 写入改变 generation，使旧游标失效。过期事实隐藏读取但保留版本/记录，防止 CAS 重置；当前没有自动清理/迁移或物理 TTL 删除。

Qdrant 只支持配置的 Cosine 向量，所有搜索/删除含 workspace/principal/namespace 条件；`wait=true` 且 result.status=completed 才确认更新。aclose 开始即禁止新操作，owned 客户端关闭异常/取消后保留可重试清理；borrowed 客户端不关闭。服务超时/畸形响应为安全 typed error，不能从已确认的索引写入推导跨系统业务恰好一次。[Qdrant 写入契约](https://api.qdrant.tech/api-reference/points/upsert-points)

本轮已实际验证 Redis8.8.0/redis-py8.1.0、PostgreSQL16.2/psycopg3.3.6、Qdrant1.19.2，覆盖 CAS 竞争、Scope、TTL、分页、文档删除/引用、真实 RAG 装配和关闭。Redis Cluster/failover、历史服务版本、生产拓扑/性能和真实语义检索质量尚未验收。[Redis 原子 Lua](https://redis.io/docs/latest/develop/programmability/eval-intro/)、[psycopg 共享连接说明](https://www.psycopg.org/psycopg3/docs/advanced/async.html)

测试使用 RALF_TEST_POSTGRES_DSN 与 RALF_TEST_QDRANT_URL；Redis 套件启动隔离临时 redis-server。没有服务/可选客户端时相关用例会明确 skip；完整真实服务结果与 SDK fixture 分开记录。
