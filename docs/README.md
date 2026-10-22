# Ralf-Agent 文档

[项目首页](../README.md) · [示例目录](../examples/README.md) · [贡献指南](../CONTRIBUTING.md)

第一次使用按“安装 → 首用教程 → 核心概念 → 选择功能指南”阅读。这里按使用任务组织现有文档；出现某项功能的链接表示有对应指南，支持范围仍以[实现清单](implementation-status.md)及各指南为准。

## 开始使用

| 文档 | 解决的问题 |
| --- | --- |
| [0.1.0a2 Alpha 范围与候选](releases/0.1.0a2.md) | 首版范围、已测平台、实验性能力及本地制品／公开发行边界 |
| [可复现发布门禁](release-gate.md) | 固定制品、离线依赖、精确测试集合、平台矩阵及失败证据 |
| [安装与环境](installation.md) | 源码／wheel 安装、可选依赖和安装排障 |
| [第一次使用](getting-started.md) | 生成独立工程，完成提交、审批、跨进程恢复 |
| [一个工单逐步加入能力](support-journey.md) | 同一应用接模型、Session、RAG、Facts 和 Workflow |
| [核心概念](concepts.md) | 理解 Agent、Run、Action、Session、记忆和执行权威 |
| [基础能力](basic-capabilities.md) | 默认组件及定制路径、基础交付边界 |
| [模型与 Python 工具 SDK](sdk-model-tools.md) | 接入真实模型，注册自己的函数工具 |
| [示例与 starter](../examples/README.md) | 选择离线示例和安装包内工程模板 |
| [恢复与排障](recovery-guide.md) | 按错误码／状态定位；审批、配置不匹配、未知写效果和关闭失败 |

## Agent、模型与工具

- **应用入口：** [Local Agent API](agent-api.md)、[持久用户输入](user-input.md)、[每 Agent 限制](agent-limits.md)、[完成验证](completion-verification.md)。
- **模型协议：** [模型适配与流式](model-adapters.md)、[原生函数与续接](model-continuation.md)、[完整模型历史](model-history.md)、[DeepSeek 思考模式](deepseek-thinking.md)、[Responses 推理](responses-reasoning.md)。
- **工具接入：** [受管理工具与 MCP stdio](managed-tools.md)、[MCP HTTP](mcp-http.md)、[HTTP JSON 工具](http-tools.md)、[固定命令 CLI 工具](cli-tools.md)。
- **运行组件：** [Harness 与工具执行器](execution-components.md)、[调用中间件与持久事件](middleware-and-events.md)。
- **Workspace 与 Skills：** [只读 Workspace](workspace.md)、[Workspace 写入](workspace-writes.md)、[Skills 目录](skills.md)、[Skill 文档格式](skill-documents.md)、[自动发现](skill-discovery.md)、[每 Agent Skills 绑定](skills-bindings.md)、[原生 Sandbox](sandbox.md)。

## 工作流与多 Agent

- [静态 Workflow](static-workflows.md)：顺序步骤、依赖、分支与输入映射。
- [有界并行 Workflow](parallel-workflows.md)：并行节点、共享预算与分支恢复。
- [动态规划与团队](orchestration.md)：Plan／Team 入口及可替换策略。
- [动态 DAG 与嵌套编排](dynamic-dag.md)：计划补丁、依赖图及复合成员。
- [Plan／Team 业务完成验证](parent-completion.md)：以工具回执和规则验证业务结果。
- [知识、召回与 Plan／Team 组合](h3-intelligent-combinations.md)：显式语义能力组合及边界。

## 会话、上下文、记忆与 RAG

- **Session：** [Local Session／Turn](session-api.md)、[精确消息回执](session-receipts.md)、[每 Agent Session 绑定](session-bindings.md)。
- **上下文：** [推荐 Harness](recommended-harness.md)、[上下文预算与 Artifact](context-artifacts.md)、[自动上下文阶段](managed-context-stages.md)、[复合编排上下文](composite-temporal-context.md)、[共享模型上下文契约](shared-model-context-contracts.md)、[Token 计量与分块](tokenization.md)。
- **产物：** [文件 Artifact](file-artifacts.md)、[每 Agent Artifact 绑定](artifact-bindings.md)、[绑定配置示例](artifact-binding-examples.md)。
- **记忆：** [记忆与 RAG 起步](recall-and-rag.md)、[受管理记忆](managed-memory.md)、[自动规则记忆](managed-memory-stages.md)、[自动模型字段选择](managed-model-memory-stages.md)、[复合编排记忆](composite-memory-stages.md)、[Facts／Knowledge 范围绑定](data-bindings.md)。
- **文档摄取：** [解析、分块与摄取](document-ingestion.md)、[HTML](html-ingestion.md)、[DOCX](docx-ingestion.md)、[PDF](pdf-ingestion.md)。
- **检索：** [Embedding 与混合检索](hybrid-retrieval.md)、[HTTP 重排](http-reranking.md)、[查询变换与语义 Facts](query-and-semantic-recall.md)、[模型查询改写](model-query-transform.md)、[全库 Facts 索引](fact-indexing.md)、[自动索引维护](fact-index-maintenance.md)、[语义 RAG 参考应用](phase1-semantic-rag.md)。
- **远程数据：** [Redis／PostgreSQL／Qdrant](remote-data.md)、[异步装配与资源生命周期](async-assembly.md)。

## 配置、扩展与 API 参考

- **配置与扩展：** [JSON／TOML 运行装配](runtime-assembly.md)、[每 Agent 能力绑定](agent-bindings.md)、[扩展端口与生命周期](extending.md)。
- **API：** [常用 SDK 与 CLI](api-reference.md)、[Session 适配契约](session-adapter-contracts.md)、[Facts 适配契约](facts-adapter-contracts.md)、[知识适配契约](adapter-contracts.md)、[模型替换契约](model-adapter-contracts.md)。
- **契约与设计：** [整体架构](../architecture/design.md)、[Run 命令](../architecture/specs/run-command-contract.md)、[Action 恢复](../architecture/specs/action-recovery-contract.md)、[Runner 能力](../architecture/specs/runner-capability-contract.md)。

## 部署、服务与 Coding

这些能力按各自的依赖、组合和证据范围使用。开始部署前先读[支持状态](implementation-status.md)、[安全说明](../SECURITY.md)与对应专题的限制。

### Local 与服务

- [Local 执行期限](local-execution-policy.md)、[部署准入与容量](deployment-admission.md)。
- [异步执行交接](async-handoff.md)、[消息传输与 A2A](remote-handoff.md)。
- [HTTP 事件](http-events.md)、[HTTP Run 控制](http-run-controls.md)、[服务身份与脱敏审计](service-audit.md)。
- [Local 数据保留](local-retention.md)、[备份、恢复与版本回退](framework-backup-restore.md)。

### Temporal

- **起步与装配：** [独立执行](temporal-execution.md)、[分布式编排](temporal-composition.md)、[Agent API](temporal-agent-api.md)、[Profile／Host](temporal-profiles.md)、[执行期限与策略](temporal-execution-policy.md)。
- **策略与生命周期：** [执行限制](temporal-agent-limits.md)、[完成验证](temporal-completion-verification.md)、[DecisionPolicy](temporal-decision-policy.md)、[工具真实执行生命周期](temporal-tool-execution.md)。
- **记忆与知识：** [自动记忆绑定](temporal-memory-bindings.md)、[Facts 召回](temporal-facts.md)、[Knowledge namespace](temporal-knowledge-bindings.md)。
- **会话：** [Session／Turn](temporal-sessions.md)、[固定会话读取](temporal-session-data-reads.md)、[外置会话保存](temporal-session-data-writes.md)、[根／成员会话树](temporal-session-trees.md)。
- **上下文与保留：** [自定义 Context](temporal-custom-context.md)、[Context 读取生命周期](temporal-context-read-lifetime.md)、[Temporal／PG 冗余副本清理](temporal-retention.md)。

### Coding 委托

- **Local：** [Coding 委托](local-coding-delegation.md)、[Profile 配置](coding-profiles.md)、[图与父子编排](coding-composition.md)、[容量与 create 恢复](coding-resource-recovery.md)。
- **Runner 环境：** [协议与启动证据](codex-runner-foundation.md)、[配置预检](codex-coding-preflight.md)、[保留环境与启动日志](codex-coding-environment.md)、[模型连接](codex-model-connection.md)。
- **Temporal：** [Coding 委托](temporal-coding.md)、[串行图](temporal-coding-composition.md)、[有界并行图](temporal-parallel-coding.md)、[Team／动态规划](temporal-coding-orchestration.md)、[部署准入](temporal-deployment-coding.md)。

## 评测、支持状态与贡献

- **评测方法：** [业务任务](business-evaluation.md)、[规划质量](planning-evaluation.md)、[RAG 与编排完整任务](task-evaluation.md)。离线运行协议、真实模型质量和实际外部服务验证分别报告。
- **当前支持：** [实现清单](implementation-status.md)、[剩余能力](remaining-work.md)、[阶段二矩阵](phase2-support-matrix.md)、[阶段三矩阵](phase3-support-matrix.md)。
- **开发路线与门槛：** [能力对齐路线](agentscope-alignment.md)、[持续开发队列](continuous-development.md)、[交付门槛](delivery-gates.md)、[M1 验收协议](m1-acceptance.md)。
- **参与项目：** [贡献指南](../CONTRIBUTING.md)、[文档维护约定](documentation-guide.md)、[发布指南](releasing.md)、[安全报告](../SECURITY.md)。
- **历史证据：** [版本、设计与验收记录索引](project-history.md)。
