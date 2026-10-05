# Ralf-Agent

**Reliable Agent Lifecycle Framework — 从单个智能体到可靠的企业 AI。**

Ralf-Agent 是 Python 优先的开源 Agent 运行时。它把模型决策、工具动作、审批与结果保存为明确的执行步骤，让任务在重启后继续，并核验可能已经发生的业务操作。

当前版本：**0.1.0.dev4，M1 核心预览**。已经提供原生 Agent SDK、顺序 Workflow、SQLite 持久执行、可信 Python 工具、审批／取消、效果核验、事件分页、独立可替换的会话与长期记忆，以及 Chat Completions 模型 Provider。执行存储、协调器、上下文装配和异步记忆可显式接入。完整支持状态和剩余工作见 [实现清单](docs/implementation-status.md)。预览 API 尚未稳定。

## 快速开始

Python 3.11+，Linux／macOS。本地模式无需 Redis、模型密钥或调度服务。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ralf --db .ralf/demo.sqlite demo --ticket INC-001
```

Demo 使用明确标注的离线脚本 Provider，读取工单、提出测试变更并停在 `waiting_approval`。输出包括 `run_id` 和 `pending`；测试业务服务使用独立 SQLite 保存真实效果回执。Demo 不调用付费模型或生产系统。

复制输出中的 Run、Action 和摘要，显式批准后继续：

```bash
ralf --db .ralf/demo.sqlite approve RUN_ID ACTION_ID --digest OPERATION_DIGEST --command-id approve-001
ralf --db .ralf/demo.sqlite resume RUN_ID
ralf --db .ralf/demo.sqlite status RUN_ID
ralf --db .ralf/demo.sqlite events RUN_ID --after 0
```

重复同一 `command-id` 和内容返回原回执；同 ID 改内容返回冲突。审批回执 `applied` 表示审批决定已消费，执行结果由 `resume`／`status` 获取。`events` 每页最多 1000 项，下一页用已收到的最后 `seq`。

```bash
ralf --db .ralf/demo.sqlite cancel RUN_ID --command-id cancel-001
```

SDK 示例：`python examples/oncall.py`。它等待用户输入 `APPROVE`，不会自动批准。

自建 Agent 的 CLI 恢复使用原配置工厂，不能用 Demo 配置代替。仓库内提供可运行示例：

```bash
python -m examples.custom_runtime --db .ralf/custom.sqlite
# 复制输出中的 run_id；PYTHONPATH=. 使 examples 工厂可导入
PYTHONPATH=. ralf --db .ralf/custom.sqlite --factory examples.custom_runtime:create_engine resume RUN_ID
ralf --db .ralf/custom.sqlite status RUN_ID
```

工厂是使用者显式指定的可信本地 Python 代码，接收数据库路径并返回 `LocalEngine`。审批和取消也可以使用同一 `--factory`。`status/events` 使用只读 SQLite 观察模式，不取得执行租约，不创建缺失的数据库。CLI 观察当前限定默认本地 Scope。

## 编写自己的 Agent

```python
import asyncio
import os

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    OpenAIChatProvider,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
)

tools = ToolRegistry()


def lookup(arguments, context):
    return {"ticket": arguments["ticket"], "status": "open"}


tools.register(
    ToolSpec(
        "lookup",
        "Read a test ticket",
        {
            "type": "object",
            "properties": {"ticket": {"type": "string"}},
            "required": ["ticket"],
            "additionalProperties": False,
        },
        effect="read_only",
    ),
    lookup,
)

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

设置 `OPENAI_API_KEY` 和 `RALF_MODEL` 后运行；真实模型调用产生对应供应商的用量。Provider 支持配置 `base_url` 和 `token_parameter="max_tokens"`，用于符合相同响应／工具调用契约的服务；每个具体服务仍需验证。默认 `max_completion_tokens`，每次只发一次请求，不隐藏重试。

顺序工作流使用同一执行引擎：

```python
from ralf_agent import WorkflowSpec

flow = WorkflowSpec(
    "incident",
    (
        AgentSpec("diagnose", "Return a diagnosis from the supplied evidence."),
        AgentSpec("plan", "Produce a change plan from the diagnosis."),
    ),
)
# engine.submit(flow, input, command_id="workflow-001")
```

前一步通过输出验收后，结果成为下一步输入。分支、并行、动态计划及子 Agent 属于后续阶段。

## 扩展与替换

- **模型：** 实现 `ModelProvider.identity` 与异步 `complete(messages, tools) -> ModelResponse`，通过 `providers` 注入。Provider 只产生决策，不自行执行工具。
- **工具：** `ToolRegistry.register(ToolSpec, handler, reconciler=...)`。handler 接收 JSON 参数和可信 `InvocationContext`，支持普通同步／异步函数、实例、绑定方法和 `functools.partial`。状态、绑定参数和依赖变更应更新 `ToolSpec.version/config`，不要把秘密写入配置；代码摘要和配置一起绑定运行。Registry／policy 返回的描述是独立副本。
- **记忆：** `SessionStore`／`LongTermMemoryStore` 及对应异步 Protocol 通过 `session_store`／`memory_store` 独立注入。SQLite 和内存后端留在创建线程；远程后端优先实现异步方法。线程安全的同步远程客户端可用 `ThreadedMemoryAdapter` 显式桥接。`backend_id` 必须识别后端／配置／版本，已有 Run 不静默切换后端。
- **执行与上下文：** `ExecutionStore` 不暴露 SQL／连接，`CoordinatorLease` 负责执行权归属；自定义存储需显式提供租约和记忆组件。`context_assembler` 接收具有版本身份的 `ContextBuilder`，内核仍检查上下文额度和实际快照摘要。这些是 Local 的组件端口，多进程和 Temporal 尚未实现。
- **治理：** 本版本为可信宿主配置的本地所有者模式。可注入同步 `policy(scope, tool_spec, arguments) -> None`，拒绝时抛 `AuthorizationDenied`；其他返回值一律拒绝；每次工具执行／恢复重新检查。企业 OIDC、资源 ACL 和凭据代理尚未交付。

```python
from ralf_agent import InMemoryMemory

sessions = InMemoryMemory(backend_id="demo-sessions:v1")
facts = InMemoryMemory(backend_id="demo-facts:v1")
# LocalEngine(..., session_store=sessions, memory_store=facts)
# facts.put_fact(scope, "assistant", "language", "中文", expected_version=0)
```

短期消息和长期事实使用作用域及 CAS 版本；长期记忆是显式确认的数据。自动记忆提取、向量索引和知识源撤权链路尚未交付。

更多接入约束、组件生命周期和测试方法见 [扩展指南](docs/extending.md)。

## 执行与恢复保证

模型响应和稳定工具清单在同一 SQLite 事务采纳，之后才调度工具。已采纳决策不重新问模型。工具执行前保存效果意图，结果提交后才能推进下一步。

工具声明 `read_only`、`idempotent_write`、`queryable_write` 或 `unqueryable_write`。`reconciler` 返回已确认效果的 JSON 结果，无法确定时返回 `None`。不可核验写停在 `waiting_reconciliation`；本地所有者可用 SDK `reconcile()` 提交已完成效果的人工证据。新的 Run 也不能重新提交同一工具／参数对应的未解决写效果。

每个文件数据库只有一个 Coordinator。操作系统锁阻止第二个进程接管；等待审批时可以关闭／重启进程。取消停止后续调度，保留已发出操作及晚到效果。它不撤销远端业务效果；仍在执行的 Python handler 会保留 Coordinator，直到调用结束，不能以取消调用方 Task 释放其归属。

核验结果只采纳一次，晚到的核验证据不会覆盖原结果或重复插入工具消息。运行终态也不会被晚到异常重新打开。可选记忆按上下文额度选择，保留当前任务及完整的最新工具结果；Manifest 记录真正选入的事实版本。

预算单位为整数 **execution credits**：模型／工具每次真实尝试分别原子预留与结算。未知尝试继续占用额度，实际 Token 报告独立保存，缺失明确标记未知。这里没有硬货币预算、实际 Token 计费或外部硬停止的保证。

## 开发与验证

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m build
python examples/evaluate.py
```

测试包括真实进程在业务提交后 `os._exit`、跨进程审批恢复、未确认写不重跑、预算竞争和取消竞态。离线评测输出运行成功、实际写入数、工具顺序、预算和延迟；真实模型的任务质量、事实保留和多次采样基线仍待完成。

## 架构与路线

- [完整设计](architecture/design.md)与 [review 取舍](architecture/review-resolution.md)。
- [Run 命令](architecture/specs/run-command-contract.md)、[Action 恢复](architecture/specs/action-recovery-contract.md)、[Runner 能力](architecture/specs/runner-capability-contract.md)。
- [实现状态与下一步](docs/implementation-status.md)。M1 后续完成更完整的命令／等待契约、模型质量基线及 Temporal 内部验证；v0.2 验证 Codex、并行和多进程；v1.0 完成企业私有部署目标。
- [本轮授权与关闭 Review](architecture/reviews/2026-10-05-authorization-shutdown.md)、[可靠性与架构门槛](architecture/reviews/2026-10-05-reliability-boundaries.md)、[扩展性 Review](architecture/reviews/2026-10-05-runtime-extensibility.md)。dev4 保留 `local-3` 固定发布身份及 dev3 提交摘要，与合法 dev3 Run／回执兼容；dev1／dev2 Run 可按 ID 观察、取消及人工核验，继续执行和历史提交重放需要原版本。运行及命令摘要尚不支持自动迁移。

SDK、运行时和基础治理按 [Apache-2.0](LICENSE) 开源。外部模型／Harness 的服务和许可独立适用。
