# dev16 异步交接、共享回执与默认服务审查

2026-10-07（Asia/Shanghai）。用户授权继续优化；保留工作区既有 dev12–15 增量，未提交、推送或发布。本轮完善异步执行接入和默认服务，未扩大 Temporal 编排能力子集。

## 交付与抽象

- SyncTaskControls/AsyncTaskControls 和 TaskControlBridge：结构化最小完成控制，无具体继承要求；同步调用留在协调线程，原生异步显式 await，不隐式 drive 或转移资源所有权。
- A2AApplication：同一 polling 协议可借用本地或 Temporal 权威，统一核验 DTO、有限 JSON、命令目标、可信 Scope 和注册绑定。Inbox I/O 后、wakeup 前复核；原 message ID 仍是恢复身份。
- PostgresInbox/PostgresOutbox：共享原子接收、完整消息身份、不可变完成和按 Scope 容量；事务级锁保护并发接收，发布网络调用在数据库事务之外。公开 AsyncInbox/AsyncOutbox 可替换；数据库不拥有执行状态。
- LocalA2AService 与 a2a starter：默认离线 Provider、真实 HTTP/SQLite Run/Inbox、显式本地凭据，单个 HTTP worker。跟踪 drive，关闭先取消、等待真实 handler，再分阶段关闭资源；取消关闭调用者仍保留真实清理任务。

配置、所有权及共享部署配方见[异步交接指南](../../docs/async-handoff.md)。

## 一次独立审查与修复

按 executing-plans/requesting-code-review 技能执行一次新上下文只读审查。审查者运行 44 项通过、3 项真实 PG 用例因无服务配置跳过；未独立验证进程和安装包，未将旧增量重新计作问题。

确认 **P2：callable instance 绑定漂移**。原检查只固定实例，替换其类的原生异步 `__call__` 后仍可执行替代实现。回归先 RED，随后同时固定实际入口与 Python code；RuntimeInstance 每次产生的合法 `@wraps` 委托保持可用。控制/A2A/本地关闭/交接相关 52 项通过。无第二审查者。

主任务全量测试另发现 **Temporal 首次控制初始化竞态**。真实双 HTTP 请求返回参数拒绝，诊断确认 registry Update 在 `run()` 前执行，命令登记器为 None。原生 Run Query 同样具有此窗口。改用 SDK `@workflow.init`，在控制接收前初始化状态；增加 run coroutine 尚未运行时的 Query/Update 回归（RED→GREEN）。纯状态/控制组合 51 项和实际双 HTTP 恢复 2 项通过。未增加外部重试或迁移调度权威。

## 实际运行证据

本机 Python3.12.7；Redis8.8.0/client8.1.0、PostgreSQL16.2/psycopg3.3.6、Qdrant1.19.2、Temporal SDK1.34.0/CLI1.9.1/Service1.32.0。使用任务自己的真实临时进程和持久 Temporal Service，没有 time-skipping server。

- PostgreSQL 双连接身份/不可变完成/容量竞争；Redis+PG 接收后、业务命令接受后或 broker 发布后实际 `os._exit(78)`。替换消费者使用原 message/command/broker ID 恢复，回执及单一执行保留。
- 两个 HTTP 进程、两个 Temporal Worker 与共享 PG Inbox 并发接收同消息，返回同一 Run；HTTP 在 authority 接收后、Inbox completion 前退出，替代进程修复原回执，只执行一次测试模型调用；实际 History 重放通过。
- 源码和 wheel 生成的 a2a starter 实际 HTTP 调用、重复请求、停止重启通过；缺少 token 在创建数据库前拒绝。真实线程尚未结束时仍占有本地 Coordinator；关闭等待被取消后清理继续，Inbox close 失败可重试。

最终全套 **1412 passed in305.70s**，warnings-as-errors、实际服务、无 skip。首轮全量 1409 通过/1 失败暴露上述初始化竞态，未计作全通过。修复后完整重跑。

仓库外最终安装 wheel 契约 **206 passed in53.82s**，包括真实 PG/Redis/HTTP/Temporal 和 SDK 来源检查。其他安装 starter 证据由全套的 source/installed 参数测试提供。基础包强制阻断可选 SDK 的组合 **146 passed、5 skipped**；缺少真实服务/Temporal SDK 的用例按预期跳过。195 个公共导入在阻断下仍可用。

实际 dev15 wheel 创建的 native/v3 graph、Team/flat Plan、DAG/nested 父子任务保留原记录与回执，在 dev16 批准、重复批准、恢复，业务写不重复。原十二种 starter 字典逐项完全一致，第十三种 a2a 为新增。

实际 dev15 wheel 创建的 Temporal Run/registry History 在安装 dev16 下重放，原 submit 返回同一 Run，终态控制保留原权威。基线旧版本有已确认的首次更新竞态，探针以同命令重提采集原 History；没有修改旧 SDK。探针曾因 SDK 导入位置和虚构 Workflow ID 失败，纠正脚本后实际原 ID 重放通过，不将脚本失败当作 SDK 通过证据。

源码/wheel/sdist/仓库外安装副本 **69 个 SDK 模块逐字节一致**；基础依赖仍只有 httpx/jsonschema，6 种 optional extras 不变。标准 wheel/sdist 构建、Ruff lint/format、Git 空白、pip check、本地文档链接与 Python/shell/TOML 片段校验通过，CI YAML 用 Ruby 解析。GitHub CI 作业和 Python3.11/3.13 未本机运行。验收后已关闭任务自己的 PostgreSQL、Qdrant 和 Temporal 临时服务。

## 保留边界

TaskControlBridge 借用组件，固定调用入口；隐藏捕获状态仍需显式版本配置。调用后拒绝不证明远端未接收，须恢复原命令。

PG 容量默认每 Scope/table 10000，可配置1..1000000，完成记录也计数；pending/flush 页面1..1000。容量满保留旧去重证据、拒绝新任务。backend_id 是部署身份，不是附加数据命名空间。尚无 retention/TTL/自动压缩，主机须约定容量并负责归档。

默认服务是单机单 Coordinator，认证映射可信 owner；共享网关需显式 Temporal/PG 和宿主资源生命周期。没有 OIDC/企业 ACL、全局配额、服务控制台或部署恢复验收。A2A 仍是固定0.3 polling 子集，无 SSE/push/gRPC/files/continuation。

Temporal 当前仍是 Agent/sequence、默认 Harness/History Context；DAG/Team/nesting/共享 Session/RAG/Memory/目录路由明确拒绝。初始化修复不等于完整分布式编排交付。

真实模型配置/调用预算尚未确定，质量报告保持 not_run/model_quality=null。离线测试和一次模型 fixture 执行不能推出真实 AI 质量或 AgentScope/LangChain/LangGraph 优势。完整 M1 与企业部署仍按独立门槛验收。
