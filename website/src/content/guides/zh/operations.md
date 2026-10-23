---
title: 运行与部署
description: 选择 Local 或 Temporal，管理版本化配置、执行额度、观察与资源生命周期。
locale: zh
slug: operations
sources: [docs/runtime-assembly.md, docs/agent-api.md, docs/agent-limits.md, docs/temporal-execution.md, docs/recovery-guide.md, docs/releases/0.1.0a6.md]
---

## 先选择执行后端

| 维度 | Local | Temporal |
| --- | --- | --- |
| 执行权威 | 原本地执行存储与 Coordinator | 原 Workflow History |
| 起步依赖 | Python、本地 SQLite 与应用工厂 | 显式 Temporal Service、Worker、任务队列与发布配置 |
| 推进方式 | `drive` 或托管 Runtime 推进原 Run | Service／Worker 执行；Facade 发送控制并观察进度 |
| 恢复依据 | 原数据库、工厂、组件版本与业务证据 | 原 History、匹配发布、队列及业务效果证据 |
| 适用起点 | 本地工具助手、开发试点和低依赖流程 | 需要独立 Worker 的所选分布式组合 |

Local 不会自动变成分布式调度器；Temporal 也不是把 LocalEngine 放进 Activity。两者共享部分公共概念，但功能、会话、工具节点及嵌套组合并不完全对等。Temporal 在当前 Alpha 中按实验性范围显式配置，使用前阅读[Temporal 指南](repo:docs/temporal-execution.md)和[当前支持状态](repo:docs/implementation-status.md)。

官网是静态网站，可以由 Cloudflare 托管；Python Agent 应用需要自己的 Python 执行环境或 Worker。托管官网不会启动 Python Agent 或提供 Temporal Service。

## 用一个 Profile 管理组件

已经完成源码安装后，在新目录生成离线配置项目：

```bash
relf init my-config-agent --template config
cd my-config-agent
python -m agent_app --input hello --command-id hello-1
python -m agent_app --input pending --command-id pending-1 --submit-only
relf --config runtime.toml --format text inspect RUN_ID
relf --config runtime.toml resume RUN_ID
```

将 `RUN_ID` 换成第二次提交返回值。`runtime.toml` 定义运行组件，`agent.toml` 定义 Agent。模板 Provider 为 `offline-echo`，只验证装配与执行。

一个基础 Profile 的形状如下；模板已经包含可编辑的完整配置：

```toml
schema_version = 1
[default]
name = "assistant"
version = "1"

[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "example"
```

配置只选择已注册组件，不执行 Python 或动态导入任意插件。相对资源路径以配置文件目录解析；跨目录恢复时保留同一绝对数据库与配置路径，并确保原工厂可导入。需要异步资源构造时使用对应异步装配入口。

## 改配置与恢复旧任务

Profile 的 `name/version` 对应不可覆盖的配置身份。切换 default 只影响新任务；旧 Run 按原 Profile 解析。保留原声明、适配器实现与数据，Catalog 不会替你归档代码或迁移数据库。

同一命令 ID 与相同请求回读原任务；相同 ID 改输入产生冲突。想用新配置执行新任务，使用新命令 ID。`definition_mismatch` 应恢复原版本，不能通过宽松默认值或改别名绕过。

## 额度、限制与完成验证

| 机制 | 控制什么 | 不能由此推断什么 |
| --- | --- | --- |
| Run `budget` | 以整数 execution credits 预留、结算执行尝试 | 货币预算、精确 Token 或供应商费用硬上限 |
| Agent 限制 | 决策数、上下文字符、独立工具 Action 数等上限 | 整个宿主的 CPU、并发、速率或实际远端停止 |
| 图／Plan 限制 | 步骤、修订、并发与子预算 | 任意规模都能执行或一定规划正确 |
| 输出 Schema / Verifier | 输出结构及显式业务完成条件 | 模型文本天然真实、工具回包等于业务成功 |

有效 Agent 上限取 Spec、宿主与所选策略的约束。纯限制策略不能做 I/O 或扩大权限；恢复既有 Action 也不代表创建新的独立工具动作槽位。限制身份与原任务一起固定。

## 观察、控制与服务关闭

`status`、`events`、`inspect` 和 `attach` 用于观察。等待结束可能是暂停或观察超时，先检查 snapshot 的实际状态；需要恢复时显式 `resume`，需要取消时提交独立取消命令。

关闭应用时，先停止新任务准入，完成或取消并等待自己的执行任务，再关闭自己拥有的客户端和数据连接。直接注入的借用组件由其所有者关闭；不能在工具线程、子进程或远端写效果仍未知时，假设 Python await 取消已经完成资源收尾。

备份要覆盖执行记录、所选 Session／Facts／Knowledge／Artifact 数据，以及业务效果证据；只复制一个空闲数据库文件不等于完整应用恢复。具体步骤见[恢复指南](repo:docs/recovery-guide.md)。

## 从本地试点继续

先验证一个离线任务、真实工具和审批恢复，再为实际模型、外部数据、MCP 或 Temporal 添加所需依赖与服务。Temporal 可选依赖从源码仓库根目录安装 `python -m pip install -e '.[temporal]'`，随后自行配置 Service、Worker 与匹配发布；本指南不会隐式启动服务。

API 和部分组合仍在 Alpha 阶段。部署判断使用你的实际组件与故障场景证据，当前资格见[实现清单](repo:docs/implementation-status.md)。遇到执行问题，从[审批与恢复](/zh/docs/recovery/)按状态定位下一步。

## 验证基线与支持边界

本站基于页首所示固定源码提交的 SDK **0.1.0a6 候选版本**，验证日期 **2026-10-23**。日期记录这些教程的验证，不表示每种部署或线上型号均获保证。

| 组合 | 文档状态 | 使用前继续验证 |
| --- | --- | --- |
| Local＋SQLite＋离线模型／工具 | 教程基线 | 运行快速开始和应用测试 |
| Local Session、持久输入、词法／混合检索、显式 Facts | 提供离线操作路径 | 使用自己的案例运行连续应用和输入教程 |
| 真实模型、Embedding 和外部工具 | 显式适配器与配置 | 检查具体端点、权限、错误、关闭与业务结果 |
| 远程存储或 Temporal Worker／Release | 实验性支持子集 | 按所选后端指南逐项验收；本站教程未验证这些服务组合 |

方法签名查 [API 与 CLI 参考](/zh/docs/api-reference/)，暂停交互看[持久用户输入](/zh/docs/user-input/)，切换 Provider 或部署前运行[测试与评估](/zh/docs/testing/)。固定技术源说明该快照的范围；仓库后续开发不会改变旧 Run 恢复所需的原配置。
