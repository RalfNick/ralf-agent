# 可选文本 PDF 摄取 — dev53

`PdfDocumentParser` 实现原同步 `DocumentParser`，读取应用提供的 `application/pdf` 字节，并复用原知识、Chunker 和原子回执。
核心 SDK 不导入或要求 pypdf；只有构造此适配器时加载可选依赖。

```sh
# 源码安装
python -m pip install -e '.[pdf]'
# 或安装本地构建的 wheel
python -m pip install 'dist/ralf_agent-0.1.0.dev53-py3-none-any.whl[pdf]'
```

未安装或不支持的 pypdf 版本返回 `ValidationError`，提示 `relf-agent[pdf]`。
支持 pypdf>=6.20,<7；实际验收版本6.20.0。原文本／HTML／DOCX 和 Agent 使用不需要此 extra。
适配器身份固定实际依赖版本、完整配置、宿主 RTL 设置、策略和自身辅助实现；注册后的版本、入口、配置、RTL 或 helper 变化会拒绝继续确认原 pipeline。
该身份不归档依赖代码，也不认证任意库内部运行时猴子补丁；保留原发布环境仍是应用责任。

```python
from ralf_agent import (
    PdfDocumentParser,
    IngestionCoordinator,
    Scope,
    SourceDocument,
    SQLiteKnowledgeStore,
)

source = SourceDocument("runbook", pdf_bytes, "application/pdf", "book://runbook")
# 在应用自己的 async 函数中：
# with SQLiteKnowledgeStore("knowledge.sqlite") as store:
#     receipt = await IngestionCoordinator(store, parser=PdfDocumentParser()).ingest(
#         Scope(), "docs", source, command_id="first", expected_version=0)
```

适配器将原字节交给 `BytesIO`，使用严格模式和 plain 提取，按页序连接文本，页间加入换行。
不读取应用未提供的文件、不跟随 source_uri 或 PDF 链接，不执行 JavaScript、打开附件、渲染图片或启动 OCR。
加密 PDF 全部拒绝，不接受密码；没有可提取文本时明确拒绝，避免扫描件被静默当成已摄取正文。
已有 OCR 文本层可被提取，但正确性仍由输入质量决定；多栏、表格、字体编码、阅读顺序和排版没有通用质量保证。
这些限制与 [pypdf 官方提取说明](https://pypdf.readthedocs.io/en/latest/user/extract-text.html)一致；真实复杂 PDF 语料仍未验收。

## 限额与来源

原始 SourceDocument 仍最大1MiB；最多64页、页面与被调用 Form 的内容工作累计8MiB、最终1048576字符。
另外通过 [pypdf 调用内 Configuration](https://pypdf.readthedocs.io/en/latest/modules/configuration.html)限制声明流长、选定解码输出与工作量、页面树深度／条目和 Form 调用次数；禁用外部 jbig2dec。
Form 在父页面提取前递归预检；每页最多128次调用、32层，循环／失效引用／无显式资源／解码超限拒绝。每个 Form 另行验证提取，避免上游吞掉错误后保存不完整页面。
RTL 参数按宿主当前设置绑定，注册后变化拒绝；适配器不重置宿主 RTL 全局值。
配置在调用结束或异常时恢复，不修改应用的全局默认配置或旧式常量。
这不是所有 PDF 对象／Form 的全局内存限额，也不是宿主 CPU、硬内存配额或沙箱。
提取器可能先解析内容，再检查输出字符数；对不可信资料有硬隔离要求时，宿主仍需在受控执行环境运行解析。

无效、超限、加密或无文本文件返回 `ValidationError`，不提交文档、块、词项或回执。
原始 document_id、SHA256、source_uri 和 metadata 保留；块位置沿原 **parsed_character** 单位，不是 PDF 页号／坐标或字节偏移。
已提交请求由原知识权威返回原回执，不重解析；换解析策略和新内容仍使用新 command_id／当前 expected_version。
提交后发现组件变化不静默确认成功；已写入回执仍可重连，不能撤回已经完成的原子提交。
SDK 借用 Store，不负责关闭共享客户端。

## 模板使用

```sh
ralf init my-docs --template ingest
cd my-docs
python -m agent_app ingest /absolute/path/runbook.pdf --document-id runbook --command-id first --expected-version 0
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

新模板需要 dev53；使用 PDF 时安装 pdf extra，其余格式无需。
模板显式读取所选文件，先按原1MiB预算限制输入，再选择对应 Parser。
离线词法 Provider 演示真实知识查询／引用，不代表真实模型质量或向量索引就绪。
其他适配和恢复见[摄取指南](document-ingestion.md)，完整待交付能力见[清单](remaining-work.md)。
