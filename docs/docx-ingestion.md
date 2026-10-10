# DOCX 正文摄取 — dev52

`DocxDocumentParser` 是现有同步 `DocumentParser` 的显式适配器，以标准库 ZIP/XML 解析应用提供的 DOCX 字节。
无需新增依赖，不读取文件或访问 URL。原 `TextDocumentParser` 和 `HtmlDocumentParser` 策略保持。

```python
from ralf_agent import (
    DocxDocumentParser,
    IngestionCoordinator,
    Scope,
    SourceDocument,
    SQLiteKnowledgeStore,
)

# docx_bytes 由应用读取，最大 1MiB；source_uri 只作为来源标识。
source = SourceDocument(
    "runbook",
    docx_bytes,
    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    source_uri="book://runbook",
)
# 在应用自己的 async 函数中：
# with SQLiteKnowledgeStore("knowledge.sqlite") as store:
#     receipt = await IngestionCoordinator(store, parser=DocxDocumentParser()).ingest(
#         Scope(), "docs", source, command_id="ingest-first", expected_version=0)
```

正文结构按 WordprocessingML 的 document/body/p/r/t 与表格行／单元格提取，依据
[Microsoft 文档结构](https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document)和
[表格说明](https://learn.microsoft.com/en-us/office/open-xml/word/working-with-wordprocessingml-tables)。
适配器只接受 canonical `word/document.xml`、内部主关系及 DOCX 主内容类型；XML 必须为 UTF-8，可带 BOM。
支持 transitional／strict Word 正文 namespace，不代表完整 OOXML 标准认证。

## 提取策略与限制

段落以换行分隔，正文文本保留空白，tab 转制表符，br/cr 转换行；显式 nonbreaking/soft hyphen 保留对应 Unicode 字符；表格行以换行、单元格以制表符分隔，单元格段落仍按顺序保留。
支持正文与表格行／单元格的内容控件及 customXml 等有限 Word 包装，不实现完整布局或隐式结构修复。
忽略删除修订、moveFrom 移动源内容、直接标记为隐藏的 run、域指令、绘图／嵌入对象文本；保留 moveTo 的行内目标文本、域已保存的显示文本和超链接文本。
不计算继承样式可见性或执行 Office 域，也不跟随关系目标和超链接。
隐藏排除是提取规则，不是源访问权限；Scope／namespace／宿主授权仍限制知识范围。

不支持页眉、页脚、脚注、图片／OCR、文本框、样式、编号／布局还原、完整修订视图或其他 Office 格式。
未完成真实 Microsoft Word／LibreOffice 导出语料兼容认证；当前测试使用独立手写 OOXML 包。
未知附件不执行、不加载；主内容类型校验不证明整个包不存在宏附件。

原始输入最大1MiB，ZIP 最多256成员、声明解压总量8MiB；主 XML 最大4MiB，两个元数据 XML 各64KiB。
解析的三个 XML 部件各最多65536元素、256层，最终文本最多1048576字符。
拒绝重复／不安全路径、加密／不支持压缩／符号链接成员、外部主关系、所解析 XML 中的 DTD／实体声明及坏包。
实际读取 XML 另有字节界限；ZIP 声明限额依据 [Python zipfile 接口](https://docs.python.org/3.11/library/zipfile.html)，不是宿主 CPU／内存或全包解压的硬配额。
没有解压到文件系统。无效或超限输入返回 `ValidationError`，不提交知识文档、块、词项或回执。

解析器身份固定实际策略和辅助实现摘要，注册后变化在提交前拒绝。
原始字节 SHA256、document_id、source_uri、metadata 沿原协议保存；块位置是 **parsed_character**，不对应 Word 页码或 XML 字节。
同一已提交请求重连返回原回执，不重解析。SDK 借用 Store，由应用负责关闭。

## 模板使用

```sh
ralf init my-docs --template ingest
cd my-docs
python -m agent_app ingest /absolute/path/runbook.docx --document-id runbook --command-id ingest-first --expected-version 0
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

新生成的模板需要 dev52 或后续 SDK；旧版重读已提交回执，不代表旧版能解析 DOCX 或运行新模板。
模板明确读取所选文件，再按扩展名选择 text/Markdown、HTML 或 DOCX Parser。
其离线词法证据 Provider 展示查询和来源引用，不生成向量、不证明真实模型答案质量。
原 memory/SQLite/PostgreSQL 原子知识端口与自定义 Chunker 继续适用；本轮恢复测试使用 SQLite。
其余后端接入见[摄取指南](document-ingestion.md)，完整待交付能力见[清单](remaining-work.md)。

文本型 PDF 的独立可选适配器见[PDF 指南](pdf-ingestion.md)，不改变此 DOCX 的版本化提取规则。
