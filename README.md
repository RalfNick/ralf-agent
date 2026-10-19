# Ralf-Agent

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**可持久化审批与恢复的 Python Agent 框架。**

Ralf-Agent 把模型决策、工具调用、人工审批和业务结果保存为明确的执行步骤，让 Agent 任务在进程重启后继续。模型、工具、上下文、记忆和检索组件可以独立替换，从本地 SQLite 的单 Agent 逐步组合到 Workflow、Plan／Team 与 Temporal 执行。

[快速开始](#快速开始) · [文档目录](docs/README.md) · [示例](examples/README.md) · [贡献指南](CONTRIBUTING.md) · [更新记录](CHANGELOG.md)

> 当前为 **0.1.0a1 Alpha 本地候选**，API 与部署能力仍在演进。使用范围以[实现清单](docs/implementation-status.md)为准；不同后端与组合的验证范围分别记录。首版冻结范围、平台及未验收项见[Alpha说明](docs/releases/0.1.0a1.md)，本候选尚未公开发布。默认本地入门无需模型密钥、Redis、Temporal 或 Docker。

## 为什么使用 Ralf-Agent

- **审批后再执行：** 写工具声明效果类别和审批要求，批准绑定到具体操作与参数。
- **保留任务进度：** 已保存的模型响应、工具回执和命令身份用于恢复原 Run，避免从头重跑整个任务。
- **处理未知效果：** 写操作结果不明时暂停核验，保留原 Action 和业务证据。
- **按需组合组件：** Python 工具、模型 Provider、Session、Facts、知识库与上下文都有显式替换入口。
- **从单 Agent 到编排：** 顺序工作流、静态图、有界并行、动态规划和团队复用执行协议。

## 快速开始

需要 Python 3.11+，本地开发使用 Linux 或 macOS。从源码安装：

```bash
git clone https://github.com/RalfNick/ralf-agent.git
cd ralf-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ralf --db .ralf/demo.sqlite --format text demo --ticket INC-001
```

Demo 使用离线脚本 Provider 和本地测试业务，停在 `waiting_approval`。检查输出中的工具与参数，执行输出给出的批准命令，再执行恢复命令；完成后状态为 `succeeded`。可随时查看原任务：

```bash
ralf --db .ralf/demo.sqlite --format text inspect RUN_ID
ralf --db .ralf/demo.sqlite --format text resume RUN_ID
ralf --db .ralf/demo.sqlite status RUN_ID
```

将 `RUN_ID` 替换为实际值。`--db`、`--factory`、`--format` 是全局参数，放在子命令前；默认输出 JSON。审批回执表示决定已保存，任务结果通过 `resume`／`status` 获取。

创建可编辑的独立工程：

```bash
ralf --format text init ../my-agent
cd ../my-agent
python -m agent_app --ticket INC-001
ralf --factory agent_app.runtime:create_engine --format text inspect RUN_ID
```

生成的 `agent_app/runtime.py` 包含 Provider、Python 工具、业务回执和恢复工厂。检查操作后按 `inspect` 输出审批与恢复；自定义工程使用自己的原工厂。完整步骤见[首用教程](docs/getting-started.md)，wheel 与可选依赖见[安装指南](docs/installation.md)。

## 编写自己的 Agent

下面的例子使用真实模型和一个只读 Python 工具。先通过环境变量设置 `OPENAI_API_KEY` 与 `RALF_MODEL`，然后保存为 `my_agent.py` 并运行 `python my_agent.py`。调用会产生对应供应商用量。

```python
import asyncio
import os

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    OpenAIChatProvider,
    SQLiteStore,
    ToolRegistry,
)

tools = ToolRegistry()


@tools.tool(effect="read_only", description="Read a test ticket")
def lookup(ticket: str):
    return {"ticket": ticket, "status": "open"}


provider = OpenAIChatProvider(model=os.environ["RALF_MODEL"])
spec = AgentSpec("assistant", "Read the ticket and summarize its status.", ("lookup",))


async def main():
    with LocalEngine(
        SQLiteStore(".ralf/my-agent.sqlite"), providers={"default": provider}, tools=tools
    ) as engine:
        run = engine.submit(spec, "Check INC-001", command_id="request-001", budget=16)
        print(await engine.drive(run.run_id))


asyncio.run(main())
```

函数类型注解生成输入 Schema。写工具还需声明效果类别、审批及幂等／核验方式，详见[模型与工具 SDK](docs/sdk-model-tools.md)。相同 `command_id` 与相同请求找回原回执；请求内容变化时为新任务使用新 ID。模型协议与配置见[模型接入指南](docs/model-adapters.md)。

## 按任务选择入口

| 你想做什么 | 从这里开始 |
| --- | --- |
| 理解 Run、Action、Session 和恢复 | [核心概念](docs/concepts.md)、[恢复指南](docs/recovery-guide.md) |
| 在同一应用中逐步加入能力 | [连续工单教程](docs/support-journey.md) |
| 接入模型与自己的工具 | [SDK 指南](docs/sdk-model-tools.md)、[模型适配](docs/model-adapters.md)、[MCP 工具](docs/managed-tools.md) |
| 配置多轮会话、记忆与知识问答 | [Session](docs/session-api.md)、[记忆与 RAG](docs/recall-and-rag.md)、[推荐 Harness](docs/recommended-harness.md) |
| 组合工作流与多个 Agent | [静态图](docs/static-workflows.md)、[并行工作流](docs/parallel-workflows.md)、[Plan／Team](docs/orchestration.md) |
| 用 JSON／TOML 配置与替换组件 | [运行装配](docs/runtime-assembly.md)、[扩展指南](docs/extending.md) |
| 使用 Workspace、Skills 或沙箱 | [Workspace](docs/workspace.md)、[Skills](docs/skills.md)、[Sandbox](docs/sandbox.md) |
| 接入 Temporal、服务或 Coding 执行 | [完整文档目录](docs/README.md#部署服务与-coding)及各指南的支持边界 |
| 查 SDK、CLI 与支持范围 | [API 参考](docs/api-reference.md)、[实现清单](docs/implementation-status.md) |

## 执行与恢复保证

Local 使用持久执行记录，Temporal 使用原 History 作为各自执行权威。恢复继续使用原定义、配置身份和已采纳证据；已保存响应不重新询问模型，已保存工具观察用于推进结果。

工具声明 `read_only`、`idempotent_write`、`queryable_write` 或 `unqueryable_write`。未知写效果可能停在 `waiting_reconciliation`，需要核验后继续；框架不承诺外部系统 exactly-once。取消停止后续调度，不撤销已发出的业务操作。预算单位是整数 execution credits，不是金额或供应商 Token 硬限额。

Python 工具与配置工厂属于可信宿主代码。沙箱与服务身份需要显式配置；安全及部署边界见[安全说明](SECURITY.md)，排障见[恢复指南](docs/recovery-guide.md)。

## 参与贡献

欢迎提交问题复现、文档改进、示例和修复。开发环境、测试要求及 PR 说明见[贡献指南](CONTRIBUTING.md)；文档分类与维护约定见[文档维护指南](docs/documentation-guide.md)。

[架构设计](architecture/design.md) · [剩余能力与路线](docs/remaining-work.md) · [发布流程](docs/releasing.md) · [历史记录入口](docs/project-history.md)

## 开源协议

Ralf-Agent 采用 [Apache License 2.0](LICENSE)，第三方归属信息见 [NOTICE](NOTICE)。再分发与修改请遵循许可证要求；外部模型服务、模型权重和第三方依赖适用各自的许可或服务条款。贡献许可见 [CONTRIBUTING.md](CONTRIBUTING.md#license)。
