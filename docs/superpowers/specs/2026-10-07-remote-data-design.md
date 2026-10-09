# dev14 远程记忆与知识适配

目标：使用者保留同一 Session/Facts/Knowledge/Vector 端口，显式选择真实 Redis、PostgreSQL、Qdrant。默认内存/SQLite 无新增安装依赖。用户已要求实现，沿既有架构直接开发。

RedisMemory 提供原生 async Session/Facts、消息去重、CAS、TTL 与分页/引用核验。Lua 原子处理 revision/message_id；所有同操作 key 使用一个 scope 哈希标签，避免 Cluster 跨槽。过期事实保留版本，仅隐藏读取，不能因 TTL 重置 CAS。保留设置由服务部署决定，不宣传 Redis 是执行权威。connect 创建 owned 客户端，传入客户端是 borrowed。

PostgresMemory 提供相同 async 记忆端口；PostgresKnowledgeStore 提供原始文档、Chunk、版本、删除墓碑、TTL、来源核验与词法基线。使用 psycopg3，可选依赖；独立连接/事务锁，不在共享连接上交错多 Task 事务。新增行竞争也须序列化。所有查询使用参数，标识符固定；显式 initialize 建表，不能自动破坏现有数据。客户端异常只公开 typed error，不能把凭据/SQL 内容写入 Run。

QdrantVectorIndex 使用既有 httpx，无 SDK 依赖。固定 collection/维度/Cosine，通过显式 initialize 创建或验证；uuid 点身份包含 Scope/namespace/chunk。查询和删除始终过滤 Scope、namespace；存入版本/摘要，正文仍由 KnowledgeStore 权威回读。wait=true 且完成状态检查，不能把 acknowledged 当作已写入。支持 borrowed/owned client、有限 timeout、非 2xx/无效响应 typed error。

所有远程适配器要求显式稳定 backend_id、非空 Scope/namespace、有限 timestamp/数值、纯配置验证、async 关闭。RuntimeBuilder.abuild 注册工厂；URL/DSN/key 通过环境变量名称引用，配置不含密钥。先提供直接构造/注册示例和 Redis/PG 默认组件工厂，向量组合显式注入 Embedding。

验收：真实服务 CAS 竞争、重复 message_id 冲突、高水位分页、scope 隔离、过期版本保留、失效引用、连接关闭；Qdrant 维度/过滤/写入/删除和 RAG 过期来源；断线及失败清理。HTTP fixture 与真实服务分别记录，不把 skipped 或模拟协议测试当作真实连接证据。CI 使用隔离服务，开发环境可启动仓库外临时实例，退出清理。

依赖：可选 redis>=5,<9、psycopg[binary]>=3.2,<4；基础依赖不变。官方行为参考：[Redis Lua 原子性](https://redis.io/docs/latest/develop/programmability/eval-intro/)、[异步客户端关闭](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html)、[psycopg 事务与共享连接](https://www.psycopg.org/psycopg3/docs/advanced/async.html)、[Qdrant 写入完成](https://api.qdrant.tech/api-reference/points/upsert-points)。
