# 有界记忆召回与本地 RAG

先使用本地 SQLite 和词法检索跑通知识问答，再按需要替换检索或存储。Session 与 Facts 保存应用记忆；Knowledge Store 保存显式摄入的文档及版本；Execution Store 保存 Run、Action、响应快照和回执。检索出的内容只是模型参考证据，不能授权工具或改变审批策略。

## 1. 先运行可编辑的独立应用

安装 SDK 后，无需克隆仓库：

```sh
relf init my-knowledge-agent --template rag
cd my-knowledge-agent
python -m agent_app --query '缓存连接失败怎么恢复'
python -m agent_app --query 'postgres connection refused'
python -m agent_app --query 'quantum entanglement teleportation'
```

模板生成 `agent_app/runtime.py`、稳定工厂 `agent_app.runtime:create_engine` 和使用说明。前两条查询匹配 SQLite 中真实摄入的本地文档；最后一条没有相关证据，返回 `grounded=false`、空引用和明确的拒答。离线 Provider 复制实际上下文证据，并返回 `document_id`、`version`、`source_uri` 和原文摘录。这里验证接入、检索和引用链路，未验证真实模型回答质量。

```sh
python -m agent_app --query '缓存连接失败怎么恢复' --submit-only
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

将 `RUN_ID` 替换为提交结果。该 Agent 执行阶段只读知识，不产生需要审批的业务写入。默认执行库为 `.ralf/runs.sqlite`；知识库位置是固定执行库绝对路径加 `.knowledge.sqlite`。跨工作目录时传入同一绝对 `--db`，并确保原工厂模块可导入：安装应用包，或显式配置它的导入路径。CLI 不会从任意目录自动发现一个尚未安装的项目。

初始化三个种子文档采用 `expected_version=0` 的创建 CAS。已有文档不被重写，使用者更新过的版本也会保留。已删除或过期的种子文档不会复活，也不会阻止工厂启动；重新摄入由使用者显式完成。`local://runbooks/...` 是 SQLite 内文档的来源标识，不表示访问了外部服务或读取了同名文件。

模板默认按查询生成稳定的提交命令 ID，同一查询重跑会找回原 Run。修改文档后需要重新检索时，显式传入新的 `--command-id`，例如 `python -m agent_app --query '缓存连接失败怎么恢复' --command-id cache-query-v2`；恢复原 Run 不会用新文档改写已保存的响应。

源码使用者也可运行独立 SDK 示例：

```sh
python -m examples.knowledge_agent --query '缓存连接失败怎么恢复'
relf --db .ralf/runs.sqlite --factory examples.knowledge_agent:create_engine --format text inspect RUN_ID
```

`examples` 不包含在 wheel 内；wheel 使用者使用 `relf init --template rag`。原有 `relf init DEST` 默认仍是 `oncall` 模板。生成目标必须是新目录或从外部访问的空目录，不能覆盖用户文件或替换调用者当前工作目录。

## 2. 有界记忆的选择和一致性

显式设置 `recall_policy=MemoryRecallPolicy()` 使用新的召回契约；未设置时保留原来的 Session/Facts 接入行为，避免静默改变既有应用的上下文选择。

```python
from relf_agent.memory import MemoryRecallPolicy, RecallQuery

policy = MemoryRecallPolicy(
    facts=RecallQuery(max_items=32, max_chars=8000, scan_limit=256),
    session=RecallQuery(max_items=20, max_chars=8000, scan_limit=256),
    max_pages=1,
)

engine = LocalEngine(
    execution_store,
    providers=providers,
    tools=tools,
    recall_policy=policy,
)
```

`RecallQuery` 还可携带 `text`，按 canonical 值或消息作区分大小写的子串过滤。直接使用分页接口时还可传入 `cursor`；Engine 的 `MemoryRecallPolicy` 内查询不接受预设游标，由 Engine 管理每次召回的分页起点。页结果包含 `items`、`next_cursor`、`used_chars`、`scanned`、`skipped`、`snapshot_id` 和 `backend_bounded`。`max_items` 限制返回条目，`max_chars` 限制返回 JSON 内容，`scan_limit` 限制候选扫描；Engine 的 `max_pages` 分摊原查询额度，不能通过多页绕过总条目、字符或扫描额度。最终模型上下文还受 Agent 的上下文字符上限约束。

原生内存与 SQLite 后端支持有界页。`backend_bounded=true` 表示实现遵守候选扫描和返回内容限制，不表示精确限制磁盘读取字节、数据库查询成本或 tokenizer token。旧接口通过适配器使用时，会先全量物化再限制输出，明确返回 `backend_bounded=false`；加上召回策略并不会自动使旧后端具有真正的存储层分页。

Facts 页使用插入序号的 keyset 游标。写入改变命名空间 generation，使旧游标失效，避免边读边写后静默遗漏或混合不同事实集合。Session 页优先选择最近完整消息，提供给模型时仍按时间正序排列；游标固定最初 revision 水位，后续 append 不混入这次读取。清空或改写历史会改变 generation，旧游标不能继续使用。SQLite 首次建立页索引、或发现旧 writer 修改后需要重建一次；不能据此声称全部历史 I/O 已被消除。

## 3. 文档摄入、版本和检索

```python
from relf_agent import Scope
from relf_agent.retrieval import (
    Document,
    KnowledgeContext,
    LexicalRetriever,
    SQLiteKnowledgeStore,
)

scope = Scope()
store = SQLiteKnowledgeStore("knowledge.sqlite", chunk_size=1000, overlap=100)
version = store.put(
    scope,
    "runbooks",
    Document(
        "cache-recovery",
        "缓存连接失败时先检查服务健康状态和网络连通性。",
        source_uri="local://runbooks/cache-recovery",
        metadata={"language": "zh"},
    ),
    expected_version=0,
)
knowledge = KnowledgeContext(LexicalRetriever(store), namespace="runbooks", limit=5, max_chars=8000)
# 注入已有 LocalEngine：knowledge=knowledge，recall_policy=MemoryRecallPolicy()
```

文档以 `Scope`、namespace 和 document ID 分区，更新使用 `expected_version` 比较并交换。创建传入 `expected_version=0`，首次持久版本为 1；后续显式更新时传入当前版本。冲突抛出 `KnowledgeVersionConflict`，不把未知版本的写入当作覆盖。可选 `expires_at` 到期后内容不再参与检索。文档按字符分块；来源 URI 和 metadata 随引用保留。

`LexicalRetriever` 对词项进行匹配，支持本地中文与英文文本。它不是语义 embedding 检索，不保证同义词或跨语言召回。应用需要根据语料和任务决定检索器、阈值与召回量，不能把离线示例的命中率当成模型质量基线。

`KnowledgeContext.references(scope, text)` 返回带 key/version、正文、来源和知识校验信息的引用；`validate(scope, references)` 重新核对来源。注入的新材料需匹配 Scope、namespace、当前文档版本、chunk 内容摘要和过期状态。引用材料受上下文预算选择，检索命中不意味着每条材料都进入模型快照。

启用 Recall 或 Knowledge 时，每次真正调用模型前会验证保存的事实版本和知识来源，并在最后一次异步校验返回后复核已知有效期。保存的是全部检索候选引用；ContextBuilder／Harness 的选择和最终快照决定实际发送的材料。校验采用保守规则，未选入快照的候选失效也会阻止派发。内置事实校验按 key/version/TTL 查询；旧后端的 Legacy 校验需要全量 facts 读取。召回额度不能使整个 Run 的历史 I/O 都有界，最终会话保存仍需取得完整会话 revision，兼容 blob 写入和索引重建也可能扫描历史。

模型 Action 已保存的 snapshot 是执行证据。未知模型调用重试时验证原引用，来源失效则拒绝新的派发，保留原 snapshot 和未知 Attempt／预算预留；不会用新知识替换它。已独立收到的模型响应直接采纳，不重复检索或调用模型。当前验证提供各次读取的版本检查及最终有效期检查，跨多个后端没有原子快照，也不能追回已发送的材料。来源校验不保证文档可信、模型必然正确或引用语义充分。输出 Schema 验证字段结构；替换为真实模型后，模型生成的引用仍需应用校验，不能把输入来源验证等同于答案引用验证。

## 4. 注入 embedding 的真实 cosine 检索

```python
from relf_agent.vector import SQLiteVectorIndex, VectorRetriever


async def make_vector_knowledge(store, embedding_provider):
    index = SQLiteVectorIndex("vectors.sqlite", dimensions=embedding_provider.dimensions)
    retriever = VectorRetriever(store, index, embedding_provider)
    await retriever.index_document(Scope(), "runbooks", "cache-recovery")
    return KnowledgeContext(retriever, namespace="runbooks"), index
```

`EmbeddingProvider` 声明非空、有限 JSON `identity`，正整数 `dimensions`，以及 `async embed(texts: list[str]) -> list[list[float]]`。上面的函数需要显式注入 embedding 实现，不会自行选择或调用远程模型。已有 Hash 离线基线与 HTTP Embedding 配置见[混合检索](hybrid-retrieval.md)。`index_document` 从知识库读取真实 chunks，取得向量并写入索引。查询使用同一 provider 对问题取得向量，以 cosine 相似度检索；embedding identity 进入索引命名空间，避免把不同模型的向量混用。

可替换 `InMemoryVectorIndex` 或 `SQLiteVectorIndex`。当前实现是本地线性搜索，不是 ANN 索引或托管向量数据库；大语料应另外评估检索时间与索引资源。向量必须具有正确维度和有限数值，知识来源仍经过 `KnowledgeContext` 的版本、摘要和范围校验。语料更新后显式重新索引，不能假定旧向量自动代表新版本。

`RetrievalQuery(text, limit=5, max_chars=8000)` 控制检索结果条目和序列化字符量，结果标记 `mode=lexical` 或 `mode=vector`。`KnowledgeContext` 再按最终引用 JSON 计量。这些输出额度不代表限制全部索引扫描、网络请求、embedding token 或费用。应用拥有并关闭注入的向量索引和 embedding 客户端。

## 5. 生命周期与交付边界

Memory Store、Knowledge Store、Retriever 和 embedding 客户端均可替换。配置进入固定发布身份；改变后端、检索器或策略可能使原 Run 无法继续，应使用原工厂和配置恢复。注入组件由调用者管理资源。示例的 `KnowledgeEngine.close()` 先让父 Engine 检查活动执行并关闭，再关闭该应用自己拥有的知识连接；它没有要求生产内核关闭任意注入对象。

`Scope` 的分区依赖可信本地应用提供身份，不是企业认证、租户 ACL 或跨进程授权服务。检索文档按参考证据注入，不能覆盖系统策略；它也不等于已经消除了提示注入风险。

本教程使用本地摄入、分块、召回、版本与引用链路，不需要远程数据服务。已有远程存储／Qdrant适配见[远程数据](remote-data.md)，摄取与混合检索见[文档摄取](document-ingestion.md)和[混合检索](hybrid-retrieval.md)；这些实现不等于企业知识权限或所有部署均已验收。模型执行 credits 账本尚未覆盖检索或 embedding 费用。离线示例不发起收费调用；使用真实模型和 embedding provider 后，由应用管理对应凭据、费用及服务生命周期。
