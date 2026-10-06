# 分页记忆与知识来源 Review

日期：2026-10-06；基线：`b37a6a3`／dev6；修订：dev7／local-4。

## 交付边界

本轮增加显式启用的 MemoryRecallPolicy、RecallQuery/Page 和同步／异步端口，内置内存／SQLite 分页、Legacy 全量桥与 Threaded 桥。KnowledgeStore 是文档版本与正文权威，VectorIndex 是可重建派生索引；默认词法 Retriever 和显式 Embedding 的真实 cosine 检索共用 KnowledgeContext。两类存储均独立于执行事实，可由应用替换。可编辑 `ralf init --template rag` 不依赖仓库 examples。

默认 `recall_policy=None`、`knowledge=None` 保留 dev6 的 Manifest、请求摘要与上下文选择；新配置仅在显式启用时进入发布身份。Kernel 保留 local-4，执行 Schema v1 不迁移。来源材料是证据，不是工具权限或企业 ACL。

## 独立复核与修复

1. **事实过期／改版后仍派发。** 真实内存事实在知识检索等待期间过期或更新，原代码仍成功调用模型。增加 FactReferenceValidator／AsyncFactReferenceValidator，内置按 current key/version/TTL 校验，SQLite 只查询元数据；Legacy 全量核对正文。原模型 Action 保存事实引用，新的实际派发及未知重试复核原引用。拒绝重试保留原快照、未知 Attempt 与原预算预留。
2. **前一个来源在后一个异步验证期间到期。** 公开 KnowledgeContext 与自定义 Retriever 实测会返回成功。公共 Chunk 校验和 Facade 在最后 await 后统一复核所有已知有效期；Engine 在完成事实验证后也复核知识有效期。测试覆盖当前有效和等待中失效两种结果。
3. **代理身份掩盖实际后端变更。** wrapper.backend_id 固定，异步 read_page/recall/validate_facts 的真实 bound client 在等待中改身份，原代码继续派发。Engine、Legacy 和 Threaded 桥捕获实际方法 owner/backend_id，并在返回后核对；三条 native async 路径由真实 RED→GREEN 回归覆盖。
4. **非法整数游标／限额穿透 SQL 边界。** 将真实 facts cursor 的 position 或 RetrievalQuery.limit 改为 `10**100` 会触发 SQLite OverflowError。统一校验可支持的整数范围和游标 JSON 深度错误，返回 ValidationError；空列表 JSON 至少需要 2 字符，预算 1 在入口拒绝。

独立 reviewer 的 13 项行为回归与既有 10 项进程接收测试合计 23 项通过，使用 `-W error`。Root 的 Engine／知识进程／独立复核组合 24 项通过。完整集成与安装制品结果见 [实现进度](../../docs/implementation-progress.md)。

## 恢复证据

[知识进程回归](../../tests/test_knowledge_process_recovery.py)在最外层 commit 成功后注入 `os._exit(77)`。model_dispatched 后删除来源：恢复不重新检索、不调用模型、不替换原引用和快照，Run 拒绝派发并保留 held=2。model_response_recorded 后删除来源：直接采纳已收响应，检索／模型各一次，spent=2。原执行证据与当前有效知识保持不同语义。

新事实／知识校验使用全部检索候选，ContextBuilder／Harness 的实际选择与 snapshot 决定发送内容；这是保守策略，候选失效即拒绝。各次来源读取能核对当前版本，最后检查所有已知有效期；多个后端之间没有原子快照，不能承诺并发更新绝不发生在最后校验之后。已经披露给模型的内容不能追回。

## 规模与剩余门槛

原生 Recall 限制候选数及返回 JSON 字符，不是磁盘字节、网络成本或 tokenizer 限额。SQLite 第一次索引、旧 writer 同步、兼容 blob append 和最终 Session revision 读取仍可能 O(n)。Legacy Recall 与校验仍全量物化；Run／未知效果聚合扫描、容量、保留及迁移仍需另行实现。

本地向量默认是线性 cosine 搜索；Embedding 显式配置，身份分隔索引，更新后显式重新索引。旧向量只用于定位，再回读当前权威版本；删除／TTL／摘要不匹配的旧命中不能复活来源。当前没有 ANN、托管向量适配、外部文档同步、企业权限或检索费用账本。离线引用示例不证明模型回答质量。

完整 M1 的成组故障报告、真实模型、Temporal 独立权威和外部采用仍未验收；MCP／沙箱、多 Agent、分支并行和分布式也未因这些接口交付。
