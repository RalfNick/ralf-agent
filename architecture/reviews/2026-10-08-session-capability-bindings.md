# dev27 Local H1c — Session 能力绑定

日期：2026-10-08。基线为本轮开始时保存的 dev26 实现快照；Git HEAD 2de767c 不包含全部历史增量。继续既有 H1 设计，代码、安装包及验证证据保留本地。

## 实现与架构边界

Session 成为第七种 Local 可选择能力。原生 Agent、顺序、Graph、Team、Dynamic 和嵌套成员可使用原有同步／异步 SessionStore；SQLite、内存、Redis、PostgreSQL 和自定义后端继续遵循原 CAS、消息去重及分页端口。事实记忆、知识库、向量索引和执行事实的职责不变。

SessionBindingResource 保存宿主允许的 namespace 与默认选择；不可变 SessionView 固定 Scope、后端身份及实际键投影，并在异步调用前后复核。目录别名不成为新的存储身份；已选择的视图不能再次登记，也不能作为宿主默认 Session 后端，避免执行权威漏记存储键投影。

SQLite 在既有命令接受事务中检查实际资源地址，保存 Session refs 的 session_resources 和旧 reader 可见的物理键别名；无需新 SQL 表或第三套状态机。顺序步骤一次固定全部可能资源；并行节点和受管理子 Run 保留原隔离会话。图／团队父协调会话仍由宿主固定。审批、未知效果及尚未静止的线程／后代保持原占用。

自定义执行 Store 通过可选 SessionResourceAdmission 提供同步准入；没有该能力时明确拒绝 refs，原未绑定行为保持。标准 ThreadedMemoryAdapter 解包实际存储身份，旧 threaded: 身份按已知别名保守匹配；两个独立不相关后端若故意使用仅相差该前缀的 ID，可能收到保守 busy 拒绝。宿主需提供稳定、如实描述存储的身份；这里不推断任意客户端或 DNS 别名。

新 Session refs 固定 local-bindings-3；未使用 ref 的原生 local-4、H1a kernel1 和 H1b kernel2 发布身份保持。JSON／TOML session-resource 包装复用原工厂、async 装配和 owned/borrowed 生命周期；不增加基础依赖。首期没有 Session 自动迁移或嵌套视图装配。

## 验证证据

新增资源／执行／装配专项修复后 **39 passed**。覆盖 namespace／Scope／分页／CAS、目录和默认别名、直接物理键、不同后端、重启与审批、未来顺序步骤、并行图、团队、动态 DAG、嵌套、回执重放、异步身份漂移、工厂配置冻结以及实际执行权威能力声明。

最终 wheel 在独立安装目录通过 **155 项原有及新增绑定契约**；测试复制到源码 checkout 之外，SDK 来自安装目录，子进程使用安装环境 Python。实际安装包 Redis Session 隔离／CAS／重启通过 **1 项**，PostgreSQL 因未配置真实服务跳过 **1 项**；不把接口测试当作 PostgreSQL 服务认证。

实际 dev26 wheel 创建 8 个待审批任务：原生、H1a Agent／顺序、H1b Graph／Team／Dynamic／嵌套，以及 1.1 MB 有效原生 Schema。最终 dev27 wheel 返回原提交回执，保持原 Manifest，重复审批返回同一控制回执，每个任务产生一次业务写入。新 Session ref 任务在 dev26 下以 ValidationError 拒绝推进，Run 与零业务写入保持；dev27 接受原审批后写入一次。证据使用真实安装包与私有 SQLite 业务幂等键，不能推出任意外部操作恰好一次。

修复后完整回归：**1998 passed、43 skipped，335.12 秒**。修复前回归为 1993 passed／43 skipped；配置依赖的 PostgreSQL／Qdrant／Temporal 等跳过项不计为通过。Ruff／格式／Git 空白检查已通过；130 个 SDK 模块与 wheel／sdist／安装目录逐字节一致，包内排除私有验证目录、凭据文件和测试数据库。

## 独立审查与处置

一次独立上下文审查发现两个 P2 和一个 P3；本轮一次修复完成：

1. 已选择的 SessionView 再登记或作为宿主默认后端，会丢失投影信息。明确拒绝这两种装配，保留原始后端／SessionBindingResource 入口。
2. 无效准入返回值原先可能调用任意对象 close，关闭借用对象或掩盖契约错误。仅对识别的 coroutine／generator 做惰性对象清理，其他无效值直接 ValidationError，不调用资源生命周期。
3. resource_selectors=false 与 Session namespace 角色表矛盾。实现阶段按影响能力探测的 P2 处理，声明依据实际 Store 能力一致返回；无准入端口时同时撤销 Session ref、selector 标志和角色表。

六项专项先复现 **6 failed**，修复后包含其余新契约的 **39 passed**。没有第二轮审查；以实际安装包、旧版本兼容与完整回归验证修复结果。审查关注本轮 dev26→dev27 增量，不替代历史设计或生产认证。

审查未裁定的事项分别保留边界：H2 Facade／持久 Turn／rebind／关闭协议未交付；Temporal 绑定及其他角色 selector 仍拒绝；任意自定义存储别名的真实性由宿主负责；完整／安装／旧 wheel 结果由本轮实际验证给出，不能称为审查者独立重跑；Redis 已实测，PostgreSQL／Qdrant／Temporal 服务配置门槛仍各自存在。

## 后续与使用

[Session 教程](../../docs/session-bindings.md)提供离线最小示例、允许 namespace、JSON／TOML 配置、异步客户端生命周期和准入边界；[剩余能力](../../docs/remaining-work.md)移除已交付的 Local Session 后端／namespace 子集。

下一步继续完整 H1 的其他资源角色及 Temporal 绑定，再实现 H2 独立任务托管与统一入口。本轮没有跨独立执行权威共享 Session 的分布式租约，也未交付 AgentHarness 默认组合、企业 ACL 或完整 AgentScope 对齐。未读取模型凭据、调用真实模型、提交、推送或发布。
