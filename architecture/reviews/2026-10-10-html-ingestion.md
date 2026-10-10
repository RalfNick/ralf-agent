# dev51 H3 HTML 摄取验收

日期2026-10-10，基线3ceeca9/dev50。本轮沿已批准 R16/H3 继续开发，是现有解析端口与模板的有限扩展。
新增 HtmlDocumentParser，继续使用原 SourceDocument／ParsedDocument、Chunker、IngestionCoordinator、原子知识回执和数据后端。
不引入新执行权威、后台工作、依赖或联网行为。TextDocumentParser 与默认 pipeline 代码保持。

交付 UTF-8/BOM HTML 归一文本、实体、block/inline 边界、pre 代码缩进、指定元素／隐藏子树排除、结构预算及原始来源身份。
解析器身份含实际规则集合与辅助实现摘要，原注册契约在写入前拒绝变化。模板支持 .html/.htm，仍以离线词法证据演示引用。
分块位置对应解析文本；不声称原 HTML 字节映射、浏览器可见性或真实语义质量。

首次 SDK15项缺失 API 失败，随后 SDK／旧解析35项通过；模板 HTML 首用先因不支持扩展名失败，再通过。
实际 SQLite 在事务内与提交后退出两窗口，恢复验证文档、分块、词项和回执一起提交或一起回滚。
相关首轮73 passed／2未配置 PostgreSQL跳过。

独立只读审查发现4个 Important 与1个 Minor：pre 空白、辅助实现身份、异常声明、事件预算和孤立结束标签换行。
按实际代码证据／恢复身份／错误处理及预算影响维持分级；一轮修复全部完成，未延后 Minor，不做第二轮审查。
11个复现用例逐项 RED→GREEN（其中 CDATA 改用预算内源码重新确认失败，排除 SourceDocument 大小校验造成的假阳性）。
相邻摄取契约84 passed／2 skipped；受管限额异常保留原 ValidationError。

最终 wheel 在仓库外实际安装：82项解析／摄取契约通过，实际 __file__ 与 distribution metadata 确认为 site51/dev51。
188个 Python 模块在源码／wheel／sdist／安装包逐字节相同。
dev50↔51两组旧文本回执／默认 pipeline 精确恢复；dev51已提交 HTML 回执可被 dev50原接口重读，
不重新解析；dev50拒绝尚未提交 HTML，原知识文档／回执无写入。最终冻结回归3197 passed／92 skipped，533.12s；Ruff／格式／Git 空白检查通过，wheel／sdist 构建通过。

## 取舍及仍待验收

- 按用户持续开发与加速要求直接推进既有能力，不重复架构批准；代价是本轮聚焦 R16，不代表完整框架达标。
- 采用标准库回调文本策略，保留 pre；未实现 HTML5 DOM 修复／隐式闭合，代价是复杂破损网页应注入更完整 Parser。
- 不渲染 CSS／JS，不做显示清洗或抓取外链；代价是输入页面的浏览器可见性不等于提取文本，权限仍由宿主管理。
- PDF／Office／连接器／ACL与索引生命周期／语义质量保持待开发；代价是完整知识产品仍需后续链路。
- 作者完成最终回归、安装与跨版本工件验收，独立审查不认证这些后续运行；代价是依赖本记录的作者证据。

本轮未调用付费模型或重新认证真实 PostgreSQL／Temporal服务。完整 H3/M1 与企业验收仍未完成。
