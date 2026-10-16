# 基础能力：先跑通，再定制

当前优先保障个人开发者能安装、完成任务、接入自己的模型与工具，并在重启后继续运行。复用已有接口与默认实现；不为起步链路新增抽象、适配器或部署服务。

## 起步顺序

1. 按[首用教程](getting-started.md)生成独立项目，跑通提交、审批、恢复与重复提交。
2. 按[模型与工具 SDK](sdk-model-tools.md)接入真实模型和自己的 Python 工具。
3. 按业务需要选择[基础 Harness](recommended-harness.md)、[Workflow](static-workflows.md)或[RAG 模板](recall-and-rag.md)。

离线 Provider 用于验证框架装配与执行行为；真实任务效果按模型、工具和业务数据单独验证。已有真实参考任务的冻结证据继续按[验收清单](remaining-work.md)记录的范围引用。

## 默认实现与替换入口

| 基础能力 | 起步实现 | 定制方式与说明 |
| --- | --- | --- |
| 模型 | 离线 Provider；明确配置后使用真实模型 Provider | 替换异步 `complete` 端口，或选择已有协议适配器；[模型接入](model-adapters.md)、[模型替换](model-adapter-contracts.md) |
| 单 Agent | `AgentSpec`、`Agent` 与 Local 执行 | 自定义指令、输出 Schema、工具集合与预算；[Agent API](agent-api.md) |
| 基础 Workflow | 顺序执行与静态图 | 自定义步骤、依赖、条件与输入绑定；[Workflow](static-workflows.md) |
| 工具 | Python 工具与默认执行器 | 注册自己的函数、Schema、读写效果和必要审批；[SDK 指南](sdk-model-tools.md)、[执行组件](execution-components.md) |
| 上下文 | 默认 ContextAssembler；可选现有 managed-data 组合 | 替换上下文策略，按需开启摘要和工具大结果投影；[推荐组合](recommended-harness.md) |
| 短期与长期记忆 | 内存／SQLite 会话与 Facts | 分开替换会话和事实存储，显式配置 namespace；[记忆扩展](extending.md)、[Session 适配](session-adapter-contracts.md)、[Facts 适配](facts-adapter-contracts.md) |
| RAG | 本地词法知识检索与现有 RAG 模板 | 替换摄取、Embedding、向量检索和重排组件；[检索与 RAG](recall-and-rag.md)、[知识适配](adapter-contracts.md) |
| 配置与恢复 | SDK、JSON／TOML Profile，本地 SQLite 执行记录 | 自定义工厂与组件所有权；按原配置恢复任务；[运行装配](runtime-assembly.md)、[恢复指南](recovery-guide.md) |

内存、SQLite 和词法检索是低依赖起点，不代表分布式存储或语义质量。Redis、PostgreSQL、向量数据库、MCP、CLI、沙箱、Plan／Team 和 Temporal 已有不同范围的实现，按需要使用对应指南；它们不成为所有基础应用的前置条件。

## 当前开发边界

先修复基础链路中可复现的失败、接入障碍和文档错误；执行相关回归与必要的安装后验证。已有接口能满足的需求，优先补示例和修复，不再增加一层通用封装。

Temporal Coding Session 的原360秒验收仍未通过，保留为后续收尾项；当前停止围绕它追加性能原型和专项，不把未通过改写为支持完成。其他阶段与R01–R26长期路线图仍保留，见[阶段矩阵](phase3-support-matrix.md)。

2026-10-16 基础回归：现有9个模块214项通过，包括单Agent推荐组合、Harness替换、静态图审批与恢复、模型协议模拟、内存／SQLite记忆与召回，以及独立wheel安装后的starter审批／崩溃恢复和RAG运行。该结果不代表所有模型协议、远程后端或真实语义质量均完成验收；本批没有调用真实模型或外部数据服务。
