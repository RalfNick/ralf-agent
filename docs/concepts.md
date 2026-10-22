# 核心概念与执行模型

[文档目录](README.md) · [首用教程](getting-started.md) · [API 参考](api-reference.md)

Relf-Agent 将 Agent 定义、执行事实与业务效果分开保存。先用 Local 与 SQLite 理解下面的概念，再按需要选择编排和部署方式。

## 从定义到一次执行

| 概念 | 含义 | 使用入口 |
| --- | --- | --- |
| `AgentSpec` | Agent 的指令、允许工具、模型选择、输出约束及限制 | [模型与工具 SDK](sdk-model-tools.md) |
| Provider | 接收消息和工具描述，返回模型响应或工具提案；不自行执行工具 | [模型接入](model-adapters.md) |
| Harness／DecisionPolicy | 准备模型请求、解释响应并提出决策；引擎继续校验与采纳 | [执行组件](execution-components.md) |
| Tool | 具有参数 Schema、版本和效果类别的业务能力 | [受管理工具](managed-tools.md) |
| Run | 一次已接受任务的持久执行身份，包含配置、状态、预算和事件 | [Agent API](agent-api.md) |
| Action | Run 内的具体执行动作；审批、效果回执和核验关联到原动作 | [恢复指南](recovery-guide.md) |
| Runtime／Engine | 托管执行、保存与观察任务、处理控制命令和资源生命周期 | [运行装配](runtime-assembly.md) |

`submit` 接受任务并返回原 Run 引用。LocalEngine 的 `drive` 推进执行；`status`／`events` 观察状态。使用更高层的 `Agent`／`Runtime` 时，执行托管和等待方式见[Agent API](agent-api.md)。等待超时或取消等待不等于取消业务任务。

## 命令、审批与恢复

`command_id` 标识一次调用方意图。相同 ID 和相同请求找回原回执；同 ID 改内容产生冲突。新任务使用新 ID，审批、取消等控制命令也需要自己的 ID。

工具需要审批时，Run 停在 `waiting_approval`。批准绑定到原 Action 和操作摘要，批准回执表示决定已保存；继续执行后才能确认业务结果。写操作结果不明时可能停在 `waiting_reconciliation`，应先核验原业务效果。常用状态、诊断与操作步骤见[恢复指南](recovery-guide.md)。

恢复依赖原数据库或 History、原配置身份和原业务证据。已保存的模型响应和工具观察可继续采纳；缺失证据的外部操作需要按效果类别处理。取消不撤销外部写入，框架也不保证第三方系统 exactly-once。

## 会话、记忆、知识与产物

| 概念 | 保存什么 | 使用入口 |
| --- | --- | --- |
| Session／Turn | 多轮会话身份、每轮执行及相关消息；与单次 Run 区分 | [Session API](session-api.md) |
| Facts／长期记忆 | 有作用域、版本与来源的长期事实及观察 | [记忆召回](recall-and-rag.md)、[受管理记忆](managed-memory.md) |
| Knowledge／RAG | 文档、分块、检索候选、来源与引用；向量索引可独立替换 | [文档摄取](document-ingestion.md)、[混合检索](hybrid-retrieval.md) |
| Context | 本次模型请求实际采用的消息、事实与知识片段 | [推荐 Harness](recommended-harness.md) |
| Artifact | 大工具结果或正文的显式产物引用、读取与卸载 | [上下文与产物](context-artifacts.md) |
| Scope／Binding | 宿主授权的作用域，以及每 Agent 选择的版本化资源 | [能力绑定](agent-bindings.md) |

Scope 由可信宿主提供，不能单独替代身份认证。记忆写入、摘要与语义召回按指南显式启用；离线 Hash／词法检索结果不代表真实语义质量。

## 编排与执行后端

`WorkflowSpec` 表达顺序步骤，静态图表达依赖与分支；Plan／Team 则通过受限制的规划或团队策略委派子任务。子 Run 继续使用工具、审批、预算与恢复协议。见[静态工作流](static-workflows.md)和[编排指南](orchestration.md)。

Local 以本地执行存储为权威；Temporal 以原 Workflow History 为权威，需要显式 Worker 与发布配置。两者的已支持组合与限制分别说明，不能从单 Agent 的验证结果推断所有后端和嵌套组合可用，见[Temporal 指南](temporal-execution.md)与[实现清单](implementation-status.md)。

预算使用整数 execution credits，对真实尝试预留和结算；供应商 Token 用量另行记录。它不提供货币预算或供应商硬停止保证。
