# dev18 文档摄取与扩展边界

日期：2026-10-07。用户授权继续优化；本轮落实[智能数据链路](../viewpoints/intelligent-data-pipeline.md)的 D1。实际兼容基线为 dev17 wheel，旧 HEAD 不代表上一轮完整实现。已有工作区增量保持，未发布、提交或推送。

## 交付与架构

解析器、分块器、摄取协调和存储事务各自独立。SourceDocument／ParsedDocument／ChunkSpan 记录原字节摘要、解析正文及字符范围，PreparedIngestion 冻结首次采纳配置；同步／异步 IngestionKnowledgeStore 负责文档 CAS、完整块集、词项与回执的同一事务。Coordinator 借用资源，在解析前后和 awaited I/O 后检查固定注册，没有第二 Run 权威。

默认 TextDocumentParser 严格处理 UTF-8 text/plain／text/markdown；CharacterChunker 保留原文本切片、块 ID 和元数据，默认继承 Store 的 chunk_size／overlap；ParagraphChunker 显式可选。内存、SQLite、真实 PostgreSQL 提供原子实现，legacy put 路径保持。新增第十五种包内 ingest 模板，空知识库起步，读取用户有界文件、词法证据回答与引用、跨进程恢复无需仓库导入。

调用方请求身份不包含首次解析／分块配置。重复 command 返回原历史回执，更新、删除、过期及有效 pipeline 移动不重新执行；内容变化冲突。SQLite 摄取拒绝未提交外部事务，避免提前确认；PostgreSQL 文档锁与 namespace 接收锁兼容原 put/delete 并控制回执容量。中途异常／进程退出回滚整个文档提交；提交后回复丢失可由原请求恢复回执。

knowledge_committed 仅确认知识权威。向量索引显式独立，真实 PostgreSQL/Qdrant 组合验证索引前空结果、索引后正确来源、跨 Scope 隔离和源更新后旧命中拒绝。HashEmbedding 是离线词项散列基线，没有语义质量证据或分布式事务承诺。

## 审查与修复

一次独立最终审查报告 1 个 Important/P2，无 P1。make_receipt 在每块循环内读取冻结 JSON 属性，导致完整快照反复解码并持锁阻塞。16／128 块复现分别产生 72／520 次解码，回归先失败；修复改为一次解码、复用块 ID。相同合法上限输入（1MiB／4096 块／每块 800 字符元数据）由约 64.539 秒降至 0.0269 秒，仅为本机该例性能观察，不能作为数据库吞吐基准。最终本地 50 项测试通过。

另外已补充 SQLite 默认后端身份包含路径／Store 分块设置的说明，建议用显式 Chunker 修改新策略并保留原 Store 身份。非阻断建议：公开扩展回执未来可增加块 ID 与 locator 的自洽检查；内置实现已正确产生这些值。不能直接用当前 pipeline 校验历史回执，因为并发相同请求可能返回另一有效 pipeline 的先提交回执。

写入前还补了可执行 PreparedIngestion 子类拒绝、注册方法消失的类型化错误、篡改快照的字段／布尔版本／覆盖／展开元数据／键冲突校验。所有修复保留 RED→GREEN 记录。插件代码和来源 I/O 不在存储事务中运行。

## 验证记录

| 检查 | 结果 |
| --- | --- |
| 首轮完整实际服务套件 | 1520 passed／360.33s；随后增加性能回归 |
| 修复后最终完整套件 | 1521 passed／374.81s；真实 PostgreSQL／Qdrant／Redis／Temporal，warnings as errors |
| 工作区外 dev18 wheel 契约 | 303 passed／124.69s，包括新增数据链路及远程执行 |
| 屏蔽可选 SDK 的安装包默认能力 | 240 passed／7 expected skips／10.55s；跳过为被明确禁用的外部服务 |
| 实际 PG／SQLite 摄取与故障窗口 | 独立连接并发去重、不同内容冲突、CAS、容量、事务中退出／提交后退出及回执恢复通过 |
| 实际 PG／Qdrant 组合 | 显式索引、权威回读与旧版本／跨 Scope 拒绝通过 |
| 实际 dev17 → dev18 安装兼容 | 原十四份模板逐字不变；native／graph／Team／flat／DAG／嵌套历史回执与恢复通过 |
| 实际 Temporal 旧 History | dev17 wheel 创建原生 Run／registry History；dev18 重放、原提交与控制回执、继续执行通过 |
| 包与依赖 | 84 SDK 模块在源码／wheel／sdist／安装目录逐字节一致，211 公开导出可用；基础依赖及 6 extras 保持 |
| 静态检查 | Ruff lint／format、Git 空白、9 份指南相对链接、CI YAML 与依赖检查通过 |

测试于 Python 3.12.7 本机运行；其他声明 Python 版本由现有 CI 矩阵覆盖，本轮没有本机多版本认证。CI 已增加安装后 ingest 模板及真实 PG 摄取／崩溃测试。任务临时 PostgreSQL/Qdrant/Temporal 服务在全部核验后关闭，最终状态记录于实现进度。

真实业务模型未配置：安装包离线 business fixture 8/8、15 调用；未配置模型入口明确 not_run、0 调用、model_quality=null。未执行真实模型或跨框架对等实验。

## 尚未交付

本轮完成 D1。D2 语义 HTTP Embedding／混合召回与重排，D3 token 上下文／大结果卸载／摘要与长期记忆提炼，D4 真实质量和外部采用仍待交付。高级解析／连接器、后台索引、源 ACL、清理迁移、全局配额、企业身份、沙箱和远程 stop 管理继续作为独立门槛。本轮不表示完整 M1、企业可用或整体能力超过 AgentScope／LangGraph。
