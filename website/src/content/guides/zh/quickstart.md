---
title: 快速开始
description: 无需模型密钥，生成自己的离线 Agent，体验提交、审批与跨进程恢复。
locale: zh
slug: quickstart
sources: [docs/installation.md, docs/getting-started.md, docs/recovery-guide.md]
---

本页包含从安装到完成任务的完整本地流程，需要 **Python 3.11+**。使用 SQLite 和离线 Provider，无需模型密钥、Redis、Temporal 或 Docker。已安装 SDK 时，可直接从第 2 步继续。

## 1. 从源码安装

在终端中创建独立虚拟环境并安装：

```bash
git clone https://github.com/RalfNick/ralf-agent.git
cd ralf-agent
git checkout 0b9b6c9682c40285d91994cd831aa93d7e814bf1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ralf --version
```

> 本指南使用源码安装。核对实际检出的版本；Relf-Agent 处于 Alpha，API 与部署组合仍在演进。公开 PyPI 发行包尚未作为本指南核验的安装方式。

checkout 固定文档基线 **0.1.0a1**，验证日期为 2026-10-21；继续前确认该版本。版本不同先查[安装与环境](/zh/docs/installation/)。

## 2. 创建离线工单项目

继续在源码仓库根目录执行，选择一个尚不存在的目标目录：

```bash
ralf --format text init ../my-agent
cd ../my-agent
python -m agent_app --db .ralf/runs.sqlite --ticket INC-001
```

生成的 `agent_app/runtime.py` 包含工具、离线 Provider 与 `create_engine(db_path)` 工厂。工程使用已安装的 SDK，自身不依赖框架仓库。

离线 Provider 生成固定提案，用来理解执行协议。它不会调用真实模型，也不代表模型任务质量。

## 3. 观察待批操作

首次运行会停在 `waiting_approval`。输出中包含 `run_id`、`pending` 与提交回执。将以下占位符替换成实际 ID：

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  --format text inspect RUN_ID
```

`inspect` 展示原工具、参数、操作摘要与可复制的下一步命令。只读 SQLite 检查不加载工厂，也不取得执行租约。

> `--db`、`--factory`、`--format` 是全局参数，放在子命令之前。默认输出 JSON；`--format text` 用于人工阅读。

## 4. 批准并恢复原任务

核对操作后，优先执行 `inspect` 给出的实际命令。手工填写时，`ACTION_ID` 与 `OPERATION_DIGEST` 必须取自原 pending：

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  approve RUN_ID ACTION_ID \
  --digest OPERATION_DIGEST --command-id approve-001
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  --format text resume RUN_ID
ralf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

批准回执的 `applied` 表示决定已保存。`resume` 才推进工具执行与结果采纳。流程完成后检查 `state` 是否为 `succeeded`，不要仅凭进程退出码判断业务成功。

这些命令可以运行在不同进程中。保留同一数据库、原工厂与原配置，才能继续原 Run。

## 5. 检查结果并找回原任务

检查 `inspect` 输出中的 `state: succeeded` 和实际结果。随后重复原工单入口，观察它是否仍指向同一个 `run_id`：

```bash
python -m agent_app --db .ralf/runs.sqlite --ticket INC-001
```

再次运行相同工单，默认 `command_id` 为 `starter:INC-001`，会找回原提交。相同 ID 对应不同定义、输入、budget 或 Session 时会冲突。新任务使用新 ID；结果不确定时先找回原命令。

## 6. 接入自己的业务

本地流程跑通后，在[核心概念](/zh/docs/concepts/)中理解 Run、Action 与命令身份；在[模型与工具](/zh/docs/models-tools/)中换成自己的业务函数与真实模型。真实模型需要配置凭据和型号，并产生供应商用量。

可选依赖和安装排障见[安装与环境](/zh/docs/installation/)；未知写效果、重启与取消的边界见[审批与恢复](/zh/docs/recovery/)。
