---
title: 能力总览
description: 从业务目标选择 Agent、工具、记忆、知识与执行方式，逐步组合你的应用。
locale: zh
slug: overview
sources: [docs/basic-capabilities.md, docs/concepts.md, docs/support-journey.md, docs/releases/0.1.0a1.md]
---

## Relf-Agent 用来解决什么

Relf-Agent 是开源 Python Agent 框架。你定义模型、业务工具与任务结构，框架保存执行身份、模型响应、审批决定和工具回执，让任务能够被观察、控制，并在满足原配置与证据要求时恢复。

全称是 **Reliable and Extensible Lifecycle Framework for Intelligent Agents**，即**可靠、可扩展的智能体全生命周期框架**。定位是：**灵活构建智能体，可靠运行智能应用。** 模型推理、规划与成员协作提供智能能力，可替换组件支持业务定制，持久执行负责审批与恢复。

项目原名Ralf-Agent，仓库现为`RalfNick/relf-agent`。a6起公共入口统一为`relf-agent`、`relf_agent`、`relf`／`relf-*`；a5和更早包仍使用旧导入／命令。本站教程继续采用下方标注的SDK0.1.0a1固定基线，其历史例子使用`ralf_agent`／`ralf`；原公开版本见[0.1.0a2 Alpha](https://github.com/RalfNick/relf-agent/releases/tag/v0.1.0a2)。新版本的制品、平台及恢复资格独立验收。

一个典型工单流程是：读取工单 → 检索运维手册 → 提出变更 → 人工审批 → 执行工具 → 检查结果。可以先用一个 Agent 完成，再把固定步骤组合成 Workflow；需要成员协作时，再加入 Plan 或 Team。

先完成[离线快速开始](/zh/docs/quickstart/)。它使用 Python 3.11+ 与本地 SQLite，无需模型密钥、Redis、Temporal 或 Docker。

## 按任务选择能力

| 你的目标 | 使用的能力 | 从哪里开始 |
| --- | --- | --- |
| 让模型读取订单、处理工单或调用业务函数 | Provider、`AgentSpec`、`ToolRegistry`、参数与输出 Schema | [模型与工具](/zh/docs/models-tools/) |
| 关键写操作需要先确认，进程退出后还要继续 | Action、操作摘要、持久审批、业务回执与未知效果核验 | [审批与恢复](/zh/docs/recovery/) |
| 等待用户补充信息，随后继续原任务 | 持久问题、固定回复 Schema 与原 Run 续接 | [持久用户输入](/zh/docs/user-input/) |
| 同一用户连续对话，保留每轮任务和已知偏好 | Session / Turn、Facts、召回策略与 Context | [会话、记忆与 RAG](/zh/docs/sessions-memory/) |
| 根据手册或知识库回答，并保留来源 | 文档摄取、版本化 Knowledge、词法／向量／混合检索 | [会话、记忆与 RAG](/zh/docs/sessions-memory/) |
| 多个已知步骤依次或并行执行 | Workflow、静态依赖图、分支、输入映射与有界并行 | [工作流与多 Agent](/zh/docs/workflows/) |
| 在有限成员间规划、分工和检查结果 | Plan / Team、Planner、Verifier 与子 Run | [工作流与多 Agent](/zh/docs/workflows/) |
| 复用 MCP、HTTP 接口、固定 CLI 或文件资料 | ToolSource、Workspace、Skills 与显式策略 | [集成与扩展](/zh/docs/integrations/) |
| 用配置管理组件，按需接入独立 Worker | RuntimeProfile、版本化装配、Local／Temporal | [运行与部署](/zh/docs/operations/) |

## 能力如何一起工作

```text
用户输入 + Agent / Workflow 定义
                 ↓
Session + Facts + Knowledge → Context → Provider
                                          ↓ 提出响应／工具调用
                               执行校验与持久化
                                          ↓
                              需要审批？→ 等待人工决定
                                          ↓
                              Tool → 回执／效果核验
                                          ↓
                              保存结果，完成原 Run
```

Provider 负责提出响应和工具调用，执行权威由 Engine 或 Temporal History 持有。检索结果、Skills 文本、模型提案都不能自行扩大工具权限。纯 Transform 和决策策略不执行外部 I/O，真实业务调用放在受管理工具中。

## 默认起点与可选组件

**本地基础路径：** 一个 Python 进程、一个本地执行数据库、普通 Python 工具。按需加入 Session、Facts、本地词法 RAG、顺序或静态工作流。先验证任务与恢复流程，再替换组件。

**显式选择的扩展：** 真实模型、语义 Embedding、远程数据后端、MCP／HTTP／CLI、Sandbox、Coding 委托与 Temporal 分别有配置、资源和支持子集要求。当前 Alpha 中，远程及服务化等扩展按各自指南作为实验性能力使用；默认教程不依赖它们。当前支持和验收范围以[实现清单](repo:docs/implementation-status.md)为准。

有模型适配器，不表示所有线上型号兼容；有检索器，不表示语义质量已满足业务要求；一次 Local 成功，也不代表任意 Temporal 组合已验证。execution credits 是执行额度，不是货币、Token 或供应商费用硬上限。

## 三条学习路径

### 业务工具助手

[快速开始](/zh/docs/quickstart/) → [模型与工具](/zh/docs/models-tools/) → [审批与恢复](/zh/docs/recovery/)。先接只读查询，再为写工具配置正确的效果类别、幂等／核验契约和审批。

### 知识与多轮对话

[核心概念](/zh/docs/concepts/) → [会话、记忆与 RAG](/zh/docs/sessions-memory/) → [集成与扩展](/zh/docs/integrations/)。先区分会话历史、长期事实和知识文档，再选择来源、召回和上下文策略。

### 多步骤业务流程

[工作流与多 Agent](/zh/docs/workflows/) → [运行与部署](/zh/docs/operations/) → [审批与恢复](/zh/docs/recovery/)。固定步骤优先用静态图，需要规划时再明确允许成员、次数、并发与预算。

通过站内[连续应用教程](/zh/docs/app-tutorial/)，在同一个工单应用中加入模型、Session、RAG、Facts 和 Workflow。方法签名查 [API 与 CLI 参考](/zh/docs/api-reference/)，离线回归、模型兼容与真实质量边界见[测试与评估](/zh/docs/testing/)。
