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
| 短期与长期记忆 | 内存／SQLite 会话与 Facts | 从[Session API](session-api.md)与[记忆召回](recall-and-rag.md)开始；按需使用[Session 适配](session-adapter-contracts.md)、[Facts 适配](facts-adapter-contracts.md) |
| RAG | 本地词法知识检索与现有 RAG 模板 | 替换摄取、Embedding、向量检索和重排组件；[检索与 RAG](recall-and-rag.md)、[知识适配](adapter-contracts.md) |
| 配置与恢复 | SDK、JSON／TOML Profile，本地 SQLite 执行记录 | 自定义工厂与组件所有权；按原配置恢复任务；[运行装配](runtime-assembly.md)、[恢复指南](recovery-guide.md) |

内存、SQLite 和词法检索是低依赖起点，不代表分布式存储或语义质量。Redis、PostgreSQL、向量数据库、MCP、CLI、沙箱、Plan／Team 和 Temporal 已有不同范围的实现，按需要使用对应指南；它们不成为所有基础应用的前置条件。

## 当前开发边界

先修复基础链路中可复现的失败、接入障碍和文档错误；执行相关回归与必要的安装后验证。已有接口能满足的需求，优先补示例和修复，不再增加一层通用封装。

Temporal Coding Session 的原360秒验收仍未通过，保留为后续收尾项；当前停止围绕它追加性能原型和专项，不把未通过改写为支持完成。其他阶段与R01–R26长期路线图仍保留，见[阶段矩阵](phase3-support-matrix.md)。

## 基础用法检查记录（2026-10-16）

| 范围 | 验证结果 |
| --- | --- |
| 默认SDK、工具、Workflow、记忆与starter | 9个现有模块214项通过，包含独立wheel安装后的审批、进程崩溃恢复和RAG运行 |
| 模型与Python工具接入 | 3个现有模块54项通过；README示例在独立安装包中执行两次，Schema、工具往返与原回执复用通过 |
| Local Session与审批 | 4个安装用法场景确认观察超时、持久busy拒绝、继续原Run及跨Turn审批；修正用法下每Turn仅一次SQLite业务写入，重复批准返回原回执 |
| RAG文档更新 | 6个独立进程确认CAS更新后相同命令复用版本1响应、新命令获取版本2 |
| 配置与恢复 | 2个现有模块23项通过；安装包11个独立进程确认新默认／原Profile恢复、回执重放、缺失原版本拒绝和坏配置下的只读观察 |

各行记录不同验证范围，不相加为全量回归。所选基础用法检查已收口，修正了首用文档、等待／审批示例及配置说明；产品代码与原接口未变。没有调用真实模型或外部数据服务，不代表所有模型、后端、真实质量或阶段门槛均已完成。后续以具体使用缺口驱动修复，不为延长本轮排查增加组件或抽象。

### 后续修复：自定义工具 Schema 缺少必填约束

2026-10-16 复现：Python 函数需要参数，但显式 Schema 漏写 `required` 时，Local 会生成无法执行的审批请求，Temporal 模型 Activity 也会采纳该缺参提案。现于原 `RegisteredTool.resolve_arguments` 边界，在 Schema／默认值解析后拒绝缺少函数必填参数的输入；不修改用户 Schema、工具身份或执行权威。默认值、宿主 context、bound method 和 keyword-only 参数保留原语义，接入说明见[工具 SDK](sdk-model-tools.md)。

新增12项回归覆盖缺参拒绝、合法顶层／组合 Schema 原身份、默认值及原审批关闭重开恢复；原命令／批准回读后只发生一次业务写入。源码10模块178项通过，wheel 安装后5模块86项通过，产品425文件与源码逐项一致；安装检查在 checkout 外执行，无源码导入路径，复用现有依赖。Ruff、格式和空白检查通过。Temporal 证据仅为模型 Activity 的公共参数采纳，不是实际 Service／History 验收；本批未调用真实模型或外部服务，也不关闭新的阶段门槛。
