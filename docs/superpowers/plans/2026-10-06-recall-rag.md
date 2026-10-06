# 有额度的记忆召回与本地 RAG 实现计划

**Goal:** 提供短期／长期记忆分页、字符与候选额度，本地默认词法 RAG，以及可注入 Embedding 的真实向量检索，使使用者能直接运行知识问答并替换后端。

**Architecture:** Session／事实／知识权威存储与向量索引保持独立。Engine 可显式注入 MemoryRecallPolicy 与 KnowledgeContext；固定组件配置、保存实际知识引用及请求快照，每次真正调用模型前检查原引用当前有效性。已收到模型响应直接采纳，不重新检索。

**Tech stack:** 现有 Python 3.11+、asyncio、SQLite、标准库 JSON／cosine；不新增运行依赖或默认收费模型调用。

**Spec:** [记忆／知识设计](../../../architecture/design.md#6-记忆知识与上下文治理)、[动作恢复契约](../../../architecture/specs/action-recovery-contract.md)、[支持状态](../../implementation-status.md)。

## 范围和兼容

- 包版本 dev7，kernel local-4／ExecutionStore v1。AgentSpec、调用方请求摘要与现有默认 ContextAssembler identity 保持不变。
- recall_policy=None、knowledge=None 时保留现有默认读取与 Manifest；新能力显式启用，Manifest 仅为启用组件增加可选身份。dev6 默认 Run 续跑、提交回执与旧工厂需要真实安装验证。
- read/facts/append/put_fact 保留；内置后端提供新分页端口，旧适配器通过明确的全量 Legacy 桥输出有界结果，不把它称为后端读取有界。
- Scope 来自可信宿主；没有企业 ACL／OIDC。字符／候选额度不是 Token、embedding 调用费用或数据库 I/O 硬限额。
- 本地词法检索可直接使用；EmbeddingProvider 必须显式注入，向量索引用真实 cosine 线性检索，仅针对小规模本地使用。

## 冻结接口

- RecallQuery(max_items=32, max_chars=8000, scan_limit=256, text=None, cursor=None)。RecallPage(items, next_cursor, used_chars, scanned, skipped, snapshot_id, backend_bounded=True)。有限 JSON 副本；used_chars 等于实际 canonical(items) 长度。
- SessionStore.read_page(scope, session_id, query)；LongTermMemoryStore.recall(scope, namespace, query)。同步／异步可用，线程桥保留真实工作线程归属。
- MemoryRecallPolicy(facts=RecallQuery(), session=RecallQuery(max_items=20), max_pages=1)。初始配置禁止 cursor；跨页预分配固定额度，合并不超过整体记录／字符／候选限制。
- facts 以稳定整数记录序号分页，cursor 固定 Scope/backend/namespace/query/generation；写入后旧 cursor 失效，TTL 每页即时生效。旧 facts() 顺序保持不变。Session 首次 revision 水位，返回完整消息且时间正序，追加不进入旧分页。
- Document／DocumentRecord／Chunk／RetrievedChunk：正文、稳定文档／chunk 身份、版本、Scope／namespace、source_uri、metadata、有效期。知识 put/delete 使用 CAS，正文与分块原子保存。
- KnowledgeStore 提供 put/get/get_chunk/chunks/delete/lexical；InMemory／SQLite 默认实现。LexicalRetriever 与 VectorRetriever 提供 async retrieve(scope, namespace, RetrievalQuery) 和 validate(scope, namespace, items)。
- EmbeddingProvider.identity／dimensions／async embed(texts)；VectorIndex scoped upsert/search/delete_document；InMemory／SQLite 向量索引只返回身份、版本、摘要及分数，正文来自权威知识存储。
- KnowledgeContext(retriever, namespace='default', limit=5, max_chars=8000) 提供 identity、async references(scope,text) 和 validate(scope,references)。Engine 参数 knowledge 接入它。
- 事实有效性端口 validate_facts(scope, namespace, items) 同步／异步返回 None，按原引用与当前 key/version/TTL 核对；内置元数据查询，旧接口 Legacy 全量比对。启用 Recall／Knowledge 的模型 Action 保存原 facts，在真正派发前验证；跨后端校验结束后统一复核已知有效期。

## Review Focus

- 游标跨 Scope／查询／后端拒绝；超大键／记录跳过后必须推进，空页可带 cursor。
- 事实版本变化导致 cursor 失效；Session 高水位不被后续追加混入，旧 writer 更新／清空不可导致序号复用泄露。
- SQLite 分页索引可重建，旧 blob 与新索引原子双写；首次迁移／旧 writer 同步及 legacy append 仍可能 O(n)，不夸大整个 I/O 上界。
- 旧向量命中不能复活过期／删除／改版来源，不能跨 Scope；维度、非有限／零向量和 embedding 身份变化明确拒绝。
- 知识检索与模型派发之间来源改变必须阻止注入；未知模型 Attempt 恢复复用原快照，验证原引用，不用新知识替换它。
- 实际读取／检索组件在 await 中换源不能被同身份注册表替换掩盖；收到事实后的费用与状态仍遵守 dev6 契约。
- 标清 retrieved references 与最终 Context/Harness 选入引用，不能把所有检索候选都描述为已发送。

## Task 1: 分页记忆

**Files:** recall.py、memory.py、test_recall.py，以及线程生命周期回归。

- [x] RED：预算、Scope、cursor、TTL、CAS、Oversize 推进、旧适配器、线程取消。
- [x] GREEN：DTO／policy／同步异步端口、内存与 SQLite 分页、Legacy／Threaded 桥及事实有效性校验。

## Task 2: 本地知识与向量检索

**Files:** retrieval.py、vector.py、test_retrieval.py、test_vector.py。

- [x] RED：来源版本／删除／有效期、分块／CAS、词法结果、向量排序／维度／过滤、失效命中 hydration。
- [x] GREEN：权威知识后端、词法默认 Retriever、显式 Embedding＋向量索引及 KnowledgeContext。

## Task 3: Engine 采纳与恢复

**Files:** engine.py、__init__.py、pyproject.toml；新增 integration/recovery tests。

- [x] RED：显式额度读取、自定义 async 后端、错误结果／身份变化、知识新注入、原快照 retry／已收到响应恢复。
- [x] GREEN：可选 Manifest 身份、固定组件调用、有界上下文来源聚合、知识／事实引用保存与派发前再验证，旧默认行为兼容。

## Task 4: 开箱路径与文档

**Files:** starter.py、cli.py、新 RAG starter/example 测试、knowledge_agent.py、recall-and-rag.md；更新现有支持与架构文档。

- [x] RED→GREEN：ralf init --template rag 的独立可编辑项目、相关来源引用和无证据回答、原工厂恢复、源码示例；oncall 模板保持兼容。
- [x] 公开 API、默认选择、拓展方式、兼容／资源／费用与规模边界有明确教程。

## Task 5: 集成验证和交付

- [x] 全套 pytest -q -W error：571 passed；Ruff lint/format；Git 空白检查；文档链接及代码片段验证。
- [x] 独立整体 review，修复实质问题并保留 13 项独立行为回归；真实进程与线程取消证据通过。
- [x] 仓库外安装 wheel，原生与 RAG starter、实际 dev6 默认 Run／回执兼容、来源失效和快照恢复；验证包／源码版本与制品内容。
- [x] 整理本地提交与交付证据。完整 M1、真实模型质量、企业权限、Redis／PG／Qdrant 适配、MCP、多 Agent、并行及 Temporal 继续标未交付。

验证环境为 macOS／Python 3.12.7。安装使用独立环境和 PATH 白名单，借用已安装第三方依赖，无网络下载或真实模型调用；原业务写入一次。默认 dev6 → dev7 精确回执／Manifest 一致；两个知识窗口分别保留未知派发预算与直接采纳已收响应。完整结果见 [实现进度](../../implementation-progress.md) 与 [独立 Review](../../../architecture/reviews/2026-10-06-recall-rag.md)。
