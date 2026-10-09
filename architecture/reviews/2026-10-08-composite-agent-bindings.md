# dev26 Local H1b — 复合编排能力绑定

日期：2026-10-08。基线为 dev25 的未提交实现快照；Git HEAD 2de767c 不包含全部历史增量。本次继续既有 H1 设计，改动和证据保留本地。

## 实现与架构边界

原生 Agent／顺序流程的六种能力选择扩展到 Local Graph、Team、Dynamic 和嵌套成员：provider、decision_policy、context、facts、knowledge、tool_set。绑定仍是独立声明包装，不重写原 AgentSpec 或原父定义；解析器只提供组件视图，执行权威仍是 LocalEngine／ExecutionStore。

- 图用 `graph/nodes/ID`，团队／动态流程用声明 member 路径，嵌套逐层投影。图的持久 node_paths 关联真实计划索引；自定义编译器可以重排节点，但不能更换声明 Agent 身份。
- 父发布固定全部成员，包括 Router 未选中的成员。受管理子 Run 保存对应绑定声明并校验祖先发布；并行节点持有自己的解析器视图，不依赖全局 current_agent，也不切换宿主组件。
- 直接 Tool／Transform 图节点保留宿主治理。工具绑定只能缩小原工具集合；模型 Planner 继续固定宿主槽位，`@planner` 不是新的绑定入口。
- Session inherit 保留既有串行共享／并行隔离语义；disabled 关闭消息读写。含 disabled 叶子的受管理子定义省略生成的显式会话请求，父子／call 身份与额度／取消传播仍持久。Team／Dynamic 父 Session 只用于协调。
- 原生／顺序包装保留 local-bindings-1，原未绑定任务保留 local-4。新的复合包装使用 local-bindings-2，记录叶子发布、图索引和编排身份。

完整 H1 尚未完成：规范资源 selector／Session 后端选择、其余环境与阶段角色、Temporal 绑定仍拒绝；H2 的 Facade、Turn 准入、仅观察等待及新关闭协议未实现。本次不改变旧 drive／close 行为，不交付新的调度器或智能数据默认组合。

## 验证证据

新增 57 项契约覆盖声明、串行／并行隔离、工具授权与直接节点审批、响应接收后身份变化、团队策略、动态 DAG、嵌套投影、回执重放、恢复／取消／预算、宿主 Planner 及 JSON／TOML 配置。

六项实际进程故障覆盖并行图与 Team 内嵌并行图的模型响应接收、工具回执接收和业务提交后崩溃。恢复固定原模型，两个业务效果各出现一次；已收到的模型响应被复用，未收到响应的窗口允许再次调用。此证据依赖测试下游幂等键和核验器，不保证任意外部操作恰好一次。

实际 wheel 在独立安装环境执行绑定契约：**117 passed**。测试复制到 checkout 之外，以安装目录为 SDK 来源，并复用现有第三方测试依赖；子进程使用该安装环境的 Python，未使用源码的 pytest pythonpath。最终安装包回归关闭非必需的 Pytest 缓存写入，无警告。

实际 dev25 wheel 创建原生／H1a Agent／H1a 顺序审批任务，dev26 返回原 submit 回执及相同 Manifest，重复审批返回同一控制回执，另外覆盖 530 KB、1.1 MB 原生 Schema 与 900 KB 顺序 Schema；共六个旧任务各产生一次业务写入。dev26 复合图审批任务在 dev25 下以 DefinitionMismatch 拒绝推进，Run 记录和零业务写入保持；dev26 继续原审批后写入一次。

修复后完整回归：**1959 passed、42 skipped，344.59 秒**。修复前回归为 1956 passed／42 skipped。跳过项仍依赖额外的 PostgreSQL／Qdrant／Temporal 服务配置，不计为通过。Ruff、格式、Git 空白检查已通过；wheel／sdist 已构建，128 个 SDK 模块与源码逐字节一致，包内不含私有验证目录或测试数据库。

未调用真实模型；未重跑依赖配置的远程 PostgreSQL／Qdrant／Temporal 验收；未提交、推送或发布。完整 M1、AgentScope 对齐、模型质量和企业正式可用仍各需验收。

## 独立审查与修复

一次独立上下文审查发现一个 P2：新的图／嵌套定义遍历对 H1a 原生执行包装执行 1 MiB 校验，原 spec 又在包装内重复，导致 dev25 已接受的大 Schema 定义无法继续。修复直接枚举原生 spec，并保留原生历史准入限制；顺序及复合定义仍保留原 Codec 限制。

专项回归先复现两种原生大小拒绝（2 failed／1 passed），修复后 **3 passed**；实际 dev25→dev26 wheel 升级进一步验证大原生／顺序定义保持原 Manifest、审批回执和一次效果。原始失败与修复记录均保留本地。审查未发现其他 Critical／Important／Minor 问题；最终修复只做一次测试验证，不以第二轮审查代替回归。

审查排除项继续按明确边界处理：Temporal 绑定、Session 后端／selector／环境角色／H2、真实模型／远程服务／企业 ACL 没有本轮交付或质量声明；串行共享 Session、waiting_approval 聚合与预派发 mismatch 维持原行为。审查范围为 dev25 快照到 dev26 增量，完整回归也不等于重新证明全部历史设计或生产条件。

## 使用与后续

[绑定教程](../../docs/agent-bindings.md)提供默认／注册工厂／Python 注入／复合路径／生命周期／拒绝矩阵；[剩余能力清单](../../docs/remaining-work.md)保留 R01–R26，并从 R01/R11 的缺口中移除已交付的 Local 复合绑定。

下一步继续 H1 的规范资源身份与 Session 组合，再落实已定义的 H2 统一入口及独立任务托管；不把本轮六类 Local 选择视为完整 AgentHarness。
