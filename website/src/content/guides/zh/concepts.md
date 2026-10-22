---
title: 核心概念
description: 将 Agent 定义、持久执行事实与外部业务效果分开理解。
locale: zh
slug: concepts
sources: [docs/concepts.md, docs/recovery-guide.md, docs/agent-api.md, docs/completion-verification.md]
---

## 一次任务如何执行

`AgentSpec` 定义指令、允许的工具、模型选择与输出约束。Provider 接收消息与工具描述，返回响应或工具提案；引擎校验提案、保存事实并控制实际执行。

```text
AgentSpec + input
      ↓ submit(command_id)
     Run
      ↓ drive
Model → Decision → Tool / Approval → Result
      ↳ execution facts saved in the store
```

| 概念 | 职责 |
| --- | --- |
| `AgentSpec` | Agent 的声明式定义 |
| Provider | 调用模型，返回响应或工具提案 |
| Tool | 带参数 Schema、版本和效果类别的业务能力 |
| Run | 一次已接受任务的持久身份、状态、预算和事件 |
| Action | Run 中的具体动作，关联审批、回执与效果核验 |
| Engine / Runtime | 执行托管、持久化、观察与控制命令 |

`LocalEngine.submit` 返回 Run 引用，`drive` 推进原任务，`status` 与 `events` 观察执行。等待超时不等于取消业务任务。

## 选择 SDK 入口

| 入口 | 适合什么时候用 |
| --- | --- |
| `Agent` | 从一个已配置模型和工具集合开始，使用 submit／wait 与持久会话 |
| `Runtime` | 多个 Agent 或复合定义共享执行托管、观察与资源生命周期 |
| `LocalEngine` | 直接控制本地提交、drive、审批、核验及底层组件装配 |
| Runtime Profile | 用 JSON／TOML 选择注册组件，保留版本与恢复身份 |

这些入口复用原执行权威，不会各自创建一套审批或预算日志。`Agent.run` 是提交并等待，返回的 `WaitResult.snapshot` 才包含实际业务状态；等待成功返回也可能表示正在等待审批。

## 命令与执行身份

`command_id` 表达调用方的一次意图。同一作用域内，相同 ID 与相同请求返回原回执；相同 ID 改内容会产生 `idempotency_conflict`。审批、取消等控制操作也有各自的命令 ID。

恢复需要原数据库或 History、匹配的组件身份与原业务证据。调整配置创建新任务；不要用一个新默认配置强行续跑旧 Run。

| 身份 | 用来关联什么 |
| --- | --- |
| `command_id` | 一次提交或控制意图及其原回执 |
| Run ID | 一次已接受任务；重新提交同一意图可回到它 |
| Action ID / 操作摘要 | 一项具体动作及其原参数、审批与执行证据 |
| `effect_key` | 原业务效果的幂等／查询身份，由宿主执行上下文提供 |
| Session / Turn | 连续会话及其中每一轮任务，与单个 Run 区分 |

例如一个工单有多轮对话、多项工具动作和多个控制命令。不要把工单号同时当作这些身份，也不要仅靠工具名称判断某次批准是否适用于另一项操作。

## 审批与未知效果

需要人工确认时，任务停在 `waiting_approval`。批准绑定到具体 Action 与操作摘要，继续执行后才能知道实际业务结果。

已派发写入的结果不明确时，任务可能进入 `waiting_reconciliation`。先查询业务效果，确认后再采纳结果。不要因为超时就直接重做写入。

> 已保存的模型响应和工具观察，可以在恢复时继续采纳。未收到证据的外部操作需要按效果类别处理；框架不提供跨第三方系统的 exactly-once 保证。

## 会话、记忆与知识

Session / Turn 保存多轮会话身份；Facts 保存有作用域、版本与来源的长期事实；Knowledge / RAG 保存文档、检索候选与引用；Context 是某次模型请求真正采用的内容。

这些组件可以独立选择与替换。Scope 由可信宿主提供，不能单独代替身份认证。详见[会话、记忆与 RAG](/zh/docs/sessions-memory/)。

## 输出合法与业务完成

输出 Schema 检查 JSON 的字段和结构，不能证明业务已经完成。需要确认变更生效时，可配置完成验证器，检查当前 Agent 节点已采纳的工具回执和结果约束。

模型说“已修复”、历史聊天中的成功描述或另一个成员的回执，都不能自动替代当前操作证据。业务校验调用本身通过受管理工具完成，纯 Verifier 只检查提供给它的事实。继续阅读[模型与工具](/zh/docs/models-tools/)。

## 从本地到编排

本地入口使用 SQLite。Workflow、静态图与 Plan / Team 让多个步骤或 Agent 协作；子 Run 仍遵循工具、审批和恢复协议。Temporal 后端需要显式配置，其权威记录来自原 Workflow History。

`budget` 使用整数 **execution credits**，对执行尝试预留与结算；它不是货币预算，也不是供应商的硬 Token 上限。继续阅读[工作流与多 Agent](/zh/docs/workflows/)。
