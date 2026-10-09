# dev14 远程数据、规划与多 Agent 实施计划

依据：[远程数据设计](../specs/2026-10-07-remote-data-design.md)、[编排设计](../specs/2026-10-07-orchestration-design.md)。保留 dev12/dev13 未提交改动；不重置工作区，不推送/发布。用户已明确要求这几项继续实现。

## 约束与审查重点

Python >=3.11；基础运行依赖不变，可选 redis/psycopg；版本 dev14。所有适配器都维护 scope、CAS、过期版本和来源有效性。父子提交原子，预算不越过总额；旧声明与默认 Manifest 不变。新增组件不能隐藏业务写入。取消和未知结果不能释放实际调用归属。

审查重点：并发首次 CAS、密钥/错误泄漏、分页快照、向量跨 scope；Planner 提案持久化与重放；子 Run 链接/预算原子性、取消传播和未知 held；实际线程与关闭；旧包恢复/模板兼容。

## 1. Redis

创建 redis_memory.py 与独立契约测试；直接构造/async connect/close；Session/Facts CAS、Lua、分页与验证。先运行缺失 API 测试，再实现并使用本地 Redis 实例验证。

## 2. PostgreSQL

创建 postgres.py 和独立测试；PostgresMemory/PostgresKnowledgeStore、initialize/connect/aclose、固定 SQL 参数/事务并发；真实服务套件可通过显式 DSN 执行。先 RED，后协议/服务 GREEN。

## 3. Qdrant

创建 qdrant.py 和独立测试；HTTP Cosine index、初始化/过滤/稳定 UUID/完成状态/关闭；通过 VectorRetriever 回读来源。先 RED，后 HTTP fixture 和真实服务验证。

## 4. 父子 Run 与 Team

创建 orchestration_types.py、orchestration.py、teams.py 及测试；修改 LocalEngine/types/workflow diagnostics 的新定义入口。稳定 ChildCall/链接、escrow、三种纯策略、恢复、并发、取消、审批与未知效果。默认同步内核身份保持兼容。

## 5. 动态规划

创建 planning.py、提案/修订持久化和纯 verifier；接入父子运行；RulePlanner 与受管理 ModelPlanner，受限重规划。收到提案后崩溃恢复不再调用 Planner。

## 6. 配置、首用与验收

公共导出、abuild 默认 remote 工厂、Planner/Team 配置、包内 plan/team starter、教程、状态/变更记录、可复现服务测试入口。完整测试/一次独立审查并修复；构建和仓库外安装、dev13 升级；真实服务与模拟/未验证项分别记录。

适配器域不编辑共享内核文件，可在独立缺失契约测试确认后使用 dispatching-parallel-agents 技能处理；主线程完成父子/规划和集中集成，避免同文件竞争。每项记录 RED→GREEN 与完成证据。

## 完成记录 — 2026-10-07

任务1–6的限定范围已实现，真实 Redis/PG/Qdrant 与组合装配已验证。一次独立审查发现的三项 Important 均以五个 RED→GREEN 用例修复；最终完整1223项通过，仓库外 wheel 契约293项通过。实际 dev13 升级、原八种模板、旧内核拒绝新父子链路、安装模板与五个真实进程窗口验证完成。49个 SDK 模块的 source/wheel/sdist/安装内容相同。

当前保持本地单 Coordinator、有限 AgentSpec 成员和委派计划。模型任务质量、生产远程服务矩阵、动态 DAG/嵌套工作流、MQ/A2A、分布式和完整 M1 留待独立交付。[审查记录](../../../architecture/reviews/2026-10-07-data-orchestration.md)与[实施进度](../../implementation-progress.md)区分已验证行为和边界。
