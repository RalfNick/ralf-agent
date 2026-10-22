---
title: 安装与环境
description: 从源码准备一个轻量的 Python 环境，先在本地跑通 Relf-Agent。
locale: zh
slug: installation
sources: [docs/installation.md, docs/getting-started.md]
---

## 环境要求

准备 **Python 3.11 或更新版本**。本地入门使用 SQLite 与离线 Provider，无需模型密钥、Redis、Temporal 或 Docker。建议在 Linux 或 macOS 上使用独立虚拟环境。

Relf-Agent 处于 Alpha 阶段，API 和部署组合仍在演进。各组合的实际验证范围以仓库的[实现清单](repo:docs/implementation-status.md)为准。

展示名称已由 Ralf-Agent 更新为 Relf-Agent。安装包 `ralf-agent`、导入路径 `ralf_agent`、CLI `ralf` 与仓库地址保持；不使用 `pip install relf-agent`、`import relf_agent` 或 `relf` 命令。旧版 `ralf --version` 显示 Ralf-Agent 属于原 SDK 输出。

## 从源码安装

```bash
git clone https://github.com/RalfNick/ralf-agent.git
cd ralf-agent
git checkout 0b9b6c9682c40285d91994cd831aa93d7e814bf1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ralf --version
```

文档基线为 SDK **0.1.0a1**，提交 `0b9b6c9682c40285d91994cd831aa93d7e814bf1`，验证日期为 2026-10-21。checkout 命令固定此版本，`ralf --version` 应显示 `0.1.0a1`。基础依赖含 `httpx` 和 `jsonschema`。更新源码后行为可能变化；为旧 Run 保留原 SDK 和配置。

> 当前指南固定原 a1 源码，不把它描述成公开发行包。最新 [0.1.0a2 Alpha](https://github.com/RalfNick/ralf-agent/releases/tag/v0.1.0a2) 已通过 GitHub Release 公开交付，安装命令见其发布说明；PyPI 尚未发布，`pip install ralf-agent` 不是本指南的已验证入口。

如果已经获得本地 wheel，可以在虚拟环境中用 `python -m pip install /实际路径/包名.whl` 安装，并核对制品来源与版本。

## 先完成一个本地任务

安装完成后，进入[完整离线快速开始](/zh/docs/quickstart/)，在一页中完成创建项目、审批、恢复与结果检查。这个流程无需任何可选依赖或模型密钥。

## 按需要添加依赖

以下命令在源码仓库、已激活的虚拟环境中执行。安装客户端依赖不会创建外部服务。

| 用途 | 命令 |
| --- | --- |
| 开发与测试 | `python -m pip install -e '.[dev]'` |
| 读取 Skill 文档 | `python -m pip install -e '.[skills]'` |
| 文本 PDF 摄取 | `python -m pip install -e '.[pdf]'` |
| Redis 客户端 | `python -m pip install -e '.[redis]'` |
| PostgreSQL 客户端 | `python -m pip install -e '.[postgres]'` |
| Temporal 客户端与相关依赖 | `python -m pip install -e '.[temporal]'` |

完整 extra 声明以 [pyproject.toml](repo:pyproject.toml) 为准。模型凭据通过进程环境配置，不写入代码或版本库。

## 确认安装

```bash
ralf --help
ralf --version
```

找不到 `ralf` 时，先确认虚拟环境已经激活，再运行 `python -m pip show ralf-agent` 检查安装位置。接下来阅读[快速开始](/zh/docs/quickstart/)，完成一次本地审批与跨进程恢复。
