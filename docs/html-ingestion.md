# HTML 文档摄取 — dev51

`HtmlDocumentParser` 是现有 `DocumentParser` 的纯同步默认适配器，解析应用提供的 UTF-8 HTML 字节。
原默认 `TextDocumentParser` 仍仅支持 text/plain、text/markdown；无需新依赖，不自动读取文件或抓取 URL。

```python
from ralf_agent import HtmlDocumentParser, IngestionCoordinator, Scope, SourceDocument, SQLiteKnowledgeStore

source = SourceDocument(
    "runbook", b"<h1>Pool timeout</h1><p>Inspect connections.</p>",
    media_type="text/html", source_uri="book://runbook",
)
# 在应用自己的 async 函数中：
# with SQLiteKnowledgeStore("knowledge.sqlite") as store:
#     receipt = await IngestionCoordinator(store, parser=HtmlDocumentParser()).ingest(
#         Scope(), "docs", source, command_id="ingest-first", expected_version=0)
```

可注入任何符合原同步解析契约的自定义 Parser，继续复用已有 Chunker 和 memory/SQLite/PostgreSQL 原子知识端口。
SDK 只借用存储，客户端由应用拥有。版本化原子回执保留解析器身份、原始字节 SHA256、解析后摘要、块 ID 和位置。
重复同一请求返回原回执，已提交的恢复不重新解析；新内容使用新 command_id 和当前 expected_version。

## 文本策略与边界

HTML 实体会解码；inline 标签不凭空插入空格，block 标签分隔为换行，pre 内保留代码／配置的换行和缩进，其他连续空白归一为空格并去除空行。
排除 head、script、style、template、iframe、object、noscript、注释及 hidden／aria-hidden=true 子树。
接受 HTML 片段和部分不完整标签，按标准库 HTMLParser 回调处理，不实现完整 HTML5 DOM 修复。
UTF-8 BOM 可以存在；其他编码或带 charset 参数的 media_type 需由应用先转换，内置仅接受 `text/html`。

这是一种确定性的纯文本提取策略，**不是浏览器渲染结果或 HTML 展示清洗器**。
不计算 CSS、页面可见性、JS、表单值、图片 OCR 或链接正文，不还原表格结构或计算 CSS white-space 样式。
`hidden` 是提取约定，不是资源访问权限；原 namespace／宿主授权仍负责限制数据范围。
原始 source_uri 只是来源标识，img/src、href、iframe、DOCTYPE 等不会触发联网或外部实体读取。

原始 SourceDocument 上限1MiB，解析文本上限1048576字符；另外限制256层未闭合元素和65536次实际解析回调（含标记声明、自闭合标签计一次）。
超限返回 ValidationError，不保存文档、块、词项或回执。结构限额不是浏览器标准兼容认证或宿主 CPU／内存配额。
回执位置单位是 **parsed_character**，指归一化后的文本，不对应原始 HTML 字节位置。

## 开箱即用

```sh
ralf init my-docs --template ingest
cd my-docs
python -m agent_app ingest /absolute/path/runbook.html --document-id runbook --command-id ingest-first --expected-version 0
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

模板显式读取 .txt/.md/.markdown/.html/.htm；dev52 另支持 .docx，先按原1MiB预算读取所选文件，再选择对应 Parser。
词法证据 Provider 仍为离线演示；不生成 Embedding 或证明真实模型质量。运行恢复与其他数据适配见[摄取指南](document-ingestion.md)。
DOCX 正文见[新指南](docx-ingestion.md)；PDF／其他 Office、网页连接器、CSS／语义解析、索引与来源生命周期仍见[剩余清单](remaining-work.md)。

文本型 PDF 可选适配器见[PDF 指南](pdf-ingestion.md)，原 HTML 默认保持。
