# 可替换的文档解析、分块与原子摄取

`0.1.0.dev18` 提供独立 DocumentParser、Chunker、IngestionCoordinator 和同步／异步原子存储端口。默认 UTF-8 文本／Markdown、字符分块、SQLite 词法检索无需模型或外部服务。内存、SQLite 和 PostgreSQL 实现相同的原子摄取回执契约。

## 安装后直接使用

```sh
pip install /path/to/ralf_agent-0.1.0.dev18-py3-none-any.whl
ralf init my-doc-agent --template ingest
cd my-doc-agent
python -m agent_app ingest /absolute/path/runbook.md --document-id runbook --command-id ingest-first --expected-version 0
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

以上使用本地构建的预览 wheel，不要求已有 PyPI 发布；源码开发安装另见 README。以上命令需要显式提供你自己的 `.txt`／`.md`／`.markdown` 文件。初始知识库为空；查询默认复制词法证据，并返回文档 ID、版本和来源 URI；无证据时返回 `grounded=false`。离线 Provider 证明接入与恢复，不代表真实模型回答质量。

默认执行库为 `.ralf/runs.sqlite`，知识库为 `.ralf/runs.sqlite.knowledge.sqlite`。选择其他路径时，将 `--db PATH` 放在 `ingest`／`query` 子命令之前。查询可加 `--submit-only`，再通过原工厂恢复：

```sh
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

## SDK 默认链路

```python
import asyncio
from ralf_agent import IngestionCoordinator, Scope, SourceDocument, SQLiteKnowledgeStore


async def main():
    with SQLiteKnowledgeStore("knowledge.sqlite") as store:
        receipt = await IngestionCoordinator(store).ingest(
            Scope(),
            "runbooks",
            SourceDocument(
                "pool",
                b"Pool timeout: inspect the connection pool.",
                source_uri="user://runbooks/pool",
            ),
            command_id="ingest-pool-v1",
            expected_version=0,
        )
        print(receipt.to_dict())


asyncio.run(main())
```

来源由宿主显式读取并提供 `bytes`。`source_uri` 仅为定位标识，框架不会抓取 URL、启动连接器或自动下载模型。TextDocumentParser 接受 `text/plain`／`text/markdown`，保留解码后的内容（包括 Markdown 标记与 CRLF），拒绝非法 UTF-8。默认 CharacterChunker 沿用 Store 的 `chunk_size`／`overlap`（未声明时为 1000／100），旧 `put` 的分块、标识和元数据保持兼容。

回执 `status=knowledge_committed` 表示同一知识权威已原子提交文档版本、完整块集、词项和不可变摄取回执。字段包括可信 Scope／namespace、command ID、后端身份、原始字节 SHA256、解析后内容摘要、首次解析／分块配置及实现摘要、块 ID 和来源定位。`locations.unit=parsed_character` 为解析后文本字符偏移；它不是原文件字节偏移。空文本允许成功提交零个块。

## 替换一个组件

无需继承框架基类。实现同步纯方法和明确 identity 即可；框架在数据库写入前冻结并校验完整返回值：

```python
from ralf_agent import ChunkSpan, IngestionCoordinator, ParagraphChunker


class WholeDocumentChunker:
    identity = {"kind": "whole-document", "version": "1"}

    def split(self, parsed):
        text = parsed.document.text
        return (ChunkSpan(0, len(text), {"section": "whole"}),) if text else ()


# 选择现成段落分块器，或只替换这一层：
coordinator = IngestionCoordinator(store, chunker=ParagraphChunker(size=1000))
custom = IngestionCoordinator(store, chunker=WholeDocumentChunker())
```

自定义 Parser 实现 `parse(SourceDocument) -> ParsedDocument`，其中 Document 必须保留来源 document_id／URI，ParsedDocument 的 source_sha256 必须对应原字节。Parser 可转换正文；分块位置必须在转换后文本范围内，顺序递增，覆盖全部非空白正文，允许明确的块重叠。自定义 ChunkSpan.metadata 保存在块元数据 `_chunk` 下；文档已有 `_chunk` 时拒绝冲突。

Parser／Chunker 不做 I/O，不能返回 coroutine、generator、contextmanager 或其他惰性包装。实例、方法或 identity 在处理过程中变化会拒绝确认。新的数据库适配器实现 `IngestionKnowledgeStore` 或 `AsyncIngestionKnowledgeStore`：`ingest(scope, namespace, prepared, *, command_id)` 与 `ingestion_receipt(scope, namespace, command_id)`。`PreparedIngestion` 为完成且有界的数据；内置存储拒绝可执行的 DTO 子类，并在事务之前重新校验。仅提供旧 `KnowledgeStore.put` 的适配器不能自动获得原子摄取支持。

## 重放、更新与失败

同一 Scope／namespace／command ID 的请求身份包含源字节摘要、document_id、media_type、URI、元数据、expected_version 和 expires_at，独立于首次解析／分块配置。相同请求重提返回原回执，即使后续配置别名移动、文档更新、过期或删除；回执证明历史提交，不能证明当前文档仍存在。变更请求使用旧 command ID 会返回 `IdempotencyConflict`。重开存储须保持原后端身份；SQLite 默认身份包含路径及 chunk_size／overlap。建议通过 Coordinator 的显式 Chunker 改变新摄取策略，保留原 Store 设置；若需要自定义稳定 backend_id，应从首次摄取起固定。

更新必须提供新的 command ID 和当前 expected_version。文档写入、块、词项或回执任一阶段失败均回滚；CAS 失败不保存成功回执。SQLite 摄取必须拥有事务边界，拒绝在已有未提交事务中使用，避免把尚未提交的数据确认成成功。PostgreSQL 共享事务与文档／namespace advisory 锁，独立连接也会原子去重和限制容量。

取消或网络回复丢失时，事务可能已经提交。使用完全相同的 command ID 和请求查询／重提，恢复原回执；不要自动生成新 ID 盲目重试。Coordinator 借用 Store；宿主负责连接初始化与关闭，不拥有 Run 执行权。内存后端回执仅在进程存活期间存在，SQLite／PostgreSQL 才提供跨进程保存。

## 有界输入与向量索引

默认来源最大 1MiB，解析后正文最大 1MiB 字符，单文档最多 4096 块，源／块元数据各最多 64KiB JSON 字符，展开块文本和元数据分别最多 4MiB。每 Scope／namespace 最多保留 4096 摄取回执；满容量拒绝新写入但仍允许原请求重放。没有自动 TTL、回执清理或迁移；保留去重证据的管理策略另行设计。

向量索引是独立派生数据，必须显式调用既有 `VectorRetriever.index_document`。摄取回执不表示向量已经就绪，也不宣称知识库与 Qdrant 之间存在分布式事务：

```python
# 已初始化的 index 与显式提供的 embedding；宿主拥有它们的生命周期。
from ralf_agent import VectorRetriever

retriever = VectorRetriever(store, index, embedding)
await retriever.index_document(scope, "runbooks", "pool")
```

默认 HashEmbedding 是词项散列基线。查询向量命中仍回读知识权威，拒绝删除、过期、跨 Scope 和旧版本块。[远程接入](remote-data.md)说明 PostgreSQL/Qdrant 与资源所有权；HTTP 语义 Embedding、融合／重排、受管理摘要及显式记忆提炼已有实现；后台索引、PDF／其他 Office／网页连接器、源 ACL 仍待交付，见[智能数据链路设计](../architecture/viewpoints/intelligent-data-pipeline.md)。


dev51 增加显式 [HtmlDocumentParser 与 HTML 摄取模板](html-ingestion.md)，默认 TextDocumentParser／原回执格式仍保持。HTML 位置对应解析文本，pre 内保留代码换行和缩进，不自动联网或渲染 CSS。

dev52 增加显式 [DocxDocumentParser 与 DOCX 摄取模板](docx-ingestion.md)，支持正文段落、表格文本和原回执恢复，不改变文本／HTML 默认策略。

dev53 增加 [PdfDocumentParser 与可选 PDF 摄取](pdf-ingestion.md)，复用原同步解析端口和原子回执；核心无需 pypdf，显式启用 pdf extra。原默认解析仍保持。
