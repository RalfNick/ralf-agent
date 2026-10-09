# dev14 真实数据与本地编排审查

日期：2026-10-07。范围为本次工作区增量，保留此前 dev12 契约修复和 dev13 异步装配；版本 0.1.0.dev14，尚未提交或公开发布。规格：[远程数据](../../docs/superpowers/specs/2026-10-07-remote-data-design.md)、[规划与团队](../../docs/superpowers/specs/2026-10-07-orchestration-design.md)；[实施计划](../../docs/superpowers/plans/2026-10-07-data-orchestration.md)。

## 实际交付与架构边界

RedisMemory/PostgresMemory 实现异步 Session、Facts、分页及当前事实校验，保留范围、CAS、消息去重和逻辑 TTL。PostgresKnowledgeStore 保存文档/Chunk 权威，QdrantVectorIndex 只保存派生向量和来源身份；VectorRetriever 回读版本/摘要和有效原文。可选客户端与 async 默认工厂不改变基础安装依赖。HashEmbeddingProvider 提供确定性词项散列基线，可以替换，不作为语义模型质量证明。

TeamSpec/DynamicWorkflowSpec 有独立不可变定义和有限组件映射，成员仍为 AgentSpec。TeamStrategy/PlanVerifier 保持纯同步，Planner 提出计划；ModelPlanner 的固定 tool-free Agent 进入相同子 Run 执行协议。父级通过一笔事务接受子 Run、固定 parent_call/link 和 escrow；隔离 Session，稳定调用 ID，接收提案与采纳修订分阶段保存。并发、成员、步骤、修订和总 credits 均有界。

单独加入 Redis/PG/Qdrant 不产生分布式执行权。新编排是有限委派计划和本地团队，不等于动态 DAG、嵌套流程、远程 A2A/MQ 或企业资源权限。

## 一次独立只读审查与修复

审查覆盖新适配器、编排及共享 Engine/配置边界；没有 Critical 发现，三项 Important 均由独立探针确认，并在一次修复中补 RED→GREEN 回归。没有第二轮审查。

| 发现 | 复现与影响 | 修复及验证 |
| --- | --- | --- |
| 并行子失败延迟取消 | gather 等全部子 Run 完成后才检查失败；慢兄弟仍可运行后续工具 | 分别观察完成，立即保存父失败/取消兄弟，继续排空已开始调用；阻断后续工具，释放静止后 escrow，原父取消回归保持无错误 |
| Qdrant 关闭失败无法重试 | 提前设置 closed 导致再次 aclose 无操作，owned HTTP client 仍未关闭 | 关闭操作门禁和成功清理状态分离；并发清理串行；异常/取消后重试关闭，borrowed 归属保持 |
| Planner 绕过父并发额度 | 自定义 Planner gather 两个 @planner 调用，max_concurrency=1 实际峰值2 | caller admission 按父限额排队，耐久 pending 子 Run 仍占容量，采纳后禁止追加规划调用；峰值1/2分别验证，预算准确结算 |

修复前完整 suite 1218 项通过，说明旧测试没有覆盖这些边界；新增五个测试参数用例使最终总数为1223。修复后原取消、未知效果、真实线程归属和崩溃用例继续通过。

## 已完成验证

- 项目 Python3.12/macOS，完整 suite **1223 passed in114.86s**，warnings-as-errors；实际服务全部启用，没有 skip。最终只对测试观察方式/fixture做格式修正，相关25项再通过，产品代码未再变化。
- 实际 Redis8.8.0/redis-py8.1.0、PostgreSQL16.2/psycopg3.3.6、Qdrant1.19.2。覆盖 CAS 竞争、Scope、TTL、分页、删除/失效引用、PG/Qdrant 实际 RAG、owned/borrowed 清理与 RuntimeBuilder.abuild。服务在本机临时目录隔离运行。
- 五个真实进程 os._exit 窗口：提案接收、修订采纳、子提交、子完成、Verify。恢复复用已保存证据，保持一个计划调用、一个 Worker 模型调用及一个子 Run；这不包含真实模型智能评分。
- 仓库外实际安装 wheel，**293 passed in7.73s**；数据、规划、团队、五个崩溃窗口和旧异步/租约契约均使用安装副本，导入来源检查通过。Source/installed Plan、Team starter 四项已通过。
- 实际 dev13→dev14：原生完成/排队任务、v3 并行图、原始记录和回执保留，续跑成功；原八种 starter 字典完全一致。全部142公共导出可导入；安装 Async starter 的 run/replay/resume 和 owned HTTP 关闭通过。
- 新父/子兼容：实际 dev13 对 dev14 Team/Plan 父和审批等待中的子 Run 均在派发前拒绝，记录不变、零写入；dev14 通过真实子审批/回执重放恢复父，每个场景恰好一次测试业务写入，父 held 归零。

49个 SDK 模块与 source/wheel/sdist/安装内容逐字节相同，基础依赖保持 httpx/jsonschema；阻断 redis/psycopg 导入时142个公开名称仍可加载。Ruff、196文件格式、Git 空白、YAML、pip check 通过；59份文档的324本地链接及 Python32/shell39/TOML2片段通过。离线回归3/3，每例一次业务写入。项目 editable metadata 已更新 dev14，任务临时 PG/Qdrant 服务已停止。详情见[实施进度](../../docs/implementation-progress.md)。没有 PyPI/GitHub 发布，没有执行真实付费模型或竞品对等 benchmark。

## 未验收项

Redis Cluster/failover、完整客户端/服务版本矩阵、生产拓扑/性能、自动迁移/清理/备份；pgvector、托管语义 Embedding、混合重排、独立 Parser/Chunker、智能记忆提炼；动态 DAG、异步模型 Verifier、递归 Team/Graph、全局容量、deadline、MQ/A2A、独立 Temporal/分布式权威与企业身份仍未交付。

新增远程服务 CI job 声明 PostgreSQL16、Qdrant1.19.2 和 Redis，可运行相关四套契约；该 GitHub job、Python3.11/3.13 矩阵本轮未在远端执行。默认本地仍能无服务运行。完整 M1、外部开发者采用、真实模型任务质量以及与 AgentScope/LangChain/LangGraph 的对等比较仍按独立验收协议处理。
