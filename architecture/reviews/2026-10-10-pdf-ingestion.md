# dev53 H3 可选文本 PDF 摄取验收

日期2026-10-10，基线0395c1c/dev52。沿既有 R16/H3 扩展原同步 DocumentParser 与安装模板，不新增知识协议、执行权威或后台任务。
采用懒加载可选 pypdf>=6.20,<7，实际6.20.0；核心 SDK 仍只有原两项依赖。原 Text/HTML/DOCX 模块与默认 pipeline 保持。
固定依赖版本／入口与调用内完整 Configuration，严格非加密 plain 页序文本；原始来源、分块位置与原子知识回执复用。
格式与限额依据见[PDF 指南](../../docs/pdf-ingestion.md)，不声明 OCR／布局／复杂语料质量或硬宿主资源隔离。

11项首次因缺少 API 失败，随后89项解析相邻契约通过；模板实际 PDF 首用先因不支持扩展名失败。
注册 helper 变化和写入等待期间依赖变化两项复现先 RED，再完成拒绝确认／原回执恢复。
手写 ASCII／Flate PDF+xref 独立 fixture，未用生产解析器生成期望；仅加密测试使用实际 pypdf Writer。
真实 SQLite 事务内／提交后 os._exit(79) 两个窗口，文档、块、词项与回执整体提交／回滚，恢复不增加文档版本。
当前相关132 passed，含完整模板 ingest→重复回执→查询来源、缺 extra、加密／无文本／超限及调用配置恢复。
CI 声明显式安装 pdf extra，避免新适配器测试因缺可选依赖长期跳过；本轮未运行远端 CI Python3.11/3.13。

独立只读审查发现两项 Important：P1 的 Form 限额／解码异常被 pypdf catch-and-skip 后仍提交部分文本；P2 的宿主 custom RTL 设置变化未固定身份。保持其实际影响分级。七项复现先 RED，修复递归预检／预算／循环／引用与 RTL 注册及提交窗口核验；作者追加畸形 Form 文本吞错的一项 RED，随后增加逐 Form 直接验证。小型正常 Form 另有独立文字完整性测试。

## 审查暂不判断项及取舍

- OCR／图像文本：接受延期，代价是无文本扫描件被明确拒绝，OCR 文本层质量仍依赖输入。
- 布局、字体与视觉顺序：接受范围排除，代价是不能承诺提取结果等于渲染页；可注入更完整 Parser。
- 真实 Office PDF 语料：接受未认证，代价是目前仅手写及真实库加密 fixture，不能标记普遍兼容。
- 宿主 CPU／内存隔离与 deadline：接受后续执行环境责任，代价是有界策略不替代硬资源沙箱。
- 声明绑定外的任意进程内库代码替换：接受可信宿主边界；代价是版本／入口固定不归档完整库代码。
- 文档与冻结验收：由作者完成并分开记录；代价是审查不认证后续安装／全量／跨版本结果。

一轮修复完成，八项复现 RED→GREEN；相邻契约141 passed，实际仓库外 site53 安装包同141 passed，13.15s，__file__／distribution metadata 确认为 dev53。190个 Python 模块在源码／wheel／sdist／安装包逐字节一致。

独立 core venv 实际不含 pypdf，仅复用 HTTPX／jsonschema 及12项实际传递依赖；SDK 冷导入、真实模板 text ingest／重复回执／query 成功。缺 extra 的 PDF 构造／模板返回 typed ValidationError，知识无写入；原默认 Coordinator 在无 pypdf 环境重读已提交 PDF 回执成功。

dev52↔53 的 text／HTML／DOCX 各双向精确回执恢复，三种新库 pipeline／内容摘要／块身份保持。dev53已提交 PDF 可被 dev52原默认接口重读；dev52未提交 PDF 拒绝且无知识写入。原文本／HTML／DOCX 适配器不改代码或默认。

完整冻结回归3256 passed／92 skipped，547.10s；外部服务配置跳过保持，未重新验收线上服务或模型。Ruff／格式／Git 空白／依赖检查与 wheel／sdist 构建通过。12份相关文档、391个本地链接及9个 Python 代码块检查通过。完整 H3/M1 和企业验收仍未达标。

本轮只本地提交，不推送；未调用付费模型或重新认证 PostgreSQL／Temporal。完整 H3/M1 和企业验收仍待完成。
