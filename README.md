# Ralf-Agent

**Reliable Agent Lifecycle Framework — 从单个智能体到可靠的企业 AI。**

Ralf-Agent 是 Python 优先的开源 Agent 运行时。它把模型决策、工具动作、审批与结果保存为明确的执行步骤，让任务在重启后继续，并核验可能已经发生的业务操作。

当前版本：**0.1.0.dev12，M1 核心预览**。提供原生 Agent SDK、顺序 Workflow 与静态串行／有界并行图、SQLite 持久执行、可信 Python 工具、审批／取消、效果核验、记忆分页与本地 RAG。图支持依赖、条件、输入映射、纯变换、受管理 Tool 节点和可替换编译器／解释器／调度器；有独立 Graph／Parallel／MCP starter。MCP stdio 和自定义异步 ToolSource 接入同一审批／效果链路。模型层支持生成参数、能力预检、完整流式响应、原生 Anthropic/Gemini 文本和 DeepSeek 非思考模式适配。JSON／TOML 装配默认组件，历史任务按原配置版本恢复。完整 M1 尚未验收，适合开发者试点；支持范围见 [实现清单](docs/implementation-status.md)。预览 API 尚未稳定。

## 快速开始

Python 3.11+，Linux／macOS。本地模式无需 Redis、模型密钥或调度服务。从源码安装：

```bash
git clone https://github.com/RalfNick/ralf-agent.git
cd ralf-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ralf --db .ralf/demo.sqlite --format text demo --ticket INC-001
```

Demo 使用明确标注的离线脚本 Provider，读取工单、提出测试变更并停在 `waiting_approval`。可读输出包括工具参数、Action、摘要及可复制的批准／拒绝命令；测试业务服务使用独立 SQLite 保存真实效果回执。Demo 不调用付费模型或生产系统。

检查变更参数，复制输出中的批准命令后再运行恢复命令。也可以随时重新查看：

```bash
ralf --db .ralf/demo.sqlite --format text inspect RUN_ID
ralf --db .ralf/demo.sqlite --format text resume RUN_ID
ralf --db .ralf/demo.sqlite status RUN_ID
ralf --db .ralf/demo.sqlite events RUN_ID --after 0
```

省略 `--format text` 时保持 JSON 输出，便于脚本读取。重复同一 `command-id` 和内容返回原回执；同 ID 改内容返回冲突。审批回执 `applied` 表示审批决定已消费，执行结果由 `resume`／`status` 获取。`events` 每页最多 1000 项，下一页用已收到的最后 `seq`。

```bash
ralf --db .ralf/demo.sqlite cancel RUN_ID --command-id cancel-001
```

安装 wheel 后也能创建独立工程，无需源码或 `examples`：

```bash
ralf --format text init ../my-agent
cd ../my-agent
python -m agent_app --ticket INC-001
ralf --factory agent_app.runtime:create_engine --format text inspect RUN_ID
# 检查参数并运行 inspect 输出的批准命令
ralf --factory agent_app.runtime:create_engine --format text resume RUN_ID
```

生成的 `agent_app/runtime.py` 是可编辑的离线 Provider、Python 工具、业务回执和恢复工厂，默认数据库为 `.ralf/runs.sqlite`。`init` 拒绝覆盖非空目录。安装 wheel、接入自己的工具及真实 Provider 的步骤见 [首用教程](docs/getting-started.md)；wheel 不包含仓库示例。本轮未核验公开 PyPI／GitHub Release 状态。

知识问答也有独立模板，无需模型密钥：

```bash
ralf init ../my-knowledge-agent --template rag
cd ../my-knowledge-agent
python -m agent_app --query '缓存连接失败怎么恢复'
```

它从 SQLite 摄入文档检索证据并返回真实版本与原文引用；无相关证据时明确拒答。离线 Provider 用于验证检索链路。如何替换知识库、检索器、Embedding 和记忆策略见 [记忆与 RAG 教程](docs/recall-and-rag.md)。默认 `ralf init` 仍生成审批示例。

也可以从声明式配置开始：

```bash
ralf init ../my-config-agent --template config
cd ../my-config-agent
python -m agent_app --input hello
```

编辑 runtime.toml 的默认版本即可影响新任务；保留旧配置和适配器实现，旧任务会解析原版本。模板使用离线回显 Provider；配置与工厂扩展见 [运行装配教程](docs/runtime-assembly.md)。

真实模型有独立可编辑入口：`ralf init my-model-agent --template model`。先在 runtime.toml 替换模型占位、选择协议与凭据环境变量，再运行应用。三种原生/兼容协议的参数、流式和明确限制见 [模型接入指南](docs/model-adapters.md)。Gemini 当前不支持工具，DeepSeek preset 固定关闭思考模式；本地协议测试不证明线上型号兼容或模型质量。

MCP 与无模型业务图也有独立入口：`ralf init my-mcp-agent --template mcp`。工具源、明确的效果策略、幂等键注入和进程管理见 [受管理工具指南](docs/managed-tools.md)。

源码中的 SDK 示例：`python examples/oncall.py`。它等待用户输入 `APPROVE`，不会自动批准。

自建 Agent 的 CLI 恢复使用原配置工厂，不能用 Demo 配置代替。仓库内提供可运行示例：

```bash
python -m examples.custom_runtime --db .ralf/custom.sqlite
# 复制输出中的 run_id，从仓库目录导入原工厂
ralf --db .ralf/custom.sqlite --factory examples.custom_runtime:create_engine resume RUN_ID
ralf --db .ralf/custom.sqlite status RUN_ID
```

工厂是使用者显式指定的可信本地 Python 代码，接收数据库路径并返回符合 `ExecutionEngine` 契约的对象。审批和取消也可以使用同一 `--factory`；从工程目录执行即可导入本地工厂。`status/inspect/events` 使用只读 SQLite 观察模式，不取得执行租约，不执行工厂，不创建缺失的数据库。CLI 观察当前限定默认本地 Scope。

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

前一步通过输出验收后，结果成为下一步输入。需要依赖、条件分支和输入映射时，使用 `GraphWorkflowSpec`。默认串行调度，图计划及节点状态持久保存；并行、动态计划与子 Agent 尚未交付。

```sh
ralf init my-graph --template graph
cd my-graph
python -m agent_app --input urgent --command-id first-graph
```

Python 图定义、自定义纯变换、编译器／解释器、分支合并与恢复见[静态 Workflow 教程](docs/static-workflows.md)。

## 扩展与替换

- **图编排：** `WorkflowCompiler`／`WorkflowInterpreter` 与 `NodeTransform` 是同步纯端口，默认有静态编译／解释和复制输入实现。可直接注入或用显式工厂注册；输入、跳过集合与结束结果仍由公共边界校验。
- **模型：** 实现 `ModelProvider.identity` 与异步 `complete(messages, tools) -> ModelResponse`，通过 `providers` 注入。Provider 只产生决策，不自行执行工具。
- **Agent 策略：** 默认 `NativeHarness`；自定义同步 `prepare(spec, messages, tools) -> ModelRequest` 与 `propose(spec, response) -> DecisionProposal`，通过 `harness` 注入。可以按 AgentSpec 选择策略；内核继续验收工具白名单、参数和最终输出。
- **工具：** `ToolRegistry.register(ToolSpec, handler, reconciler=...)`。handler 接收 JSON 参数和可信 `InvocationContext`，支持普通同步／异步函数、实例、绑定方法和 `functools.partial`。状态、绑定参数和依赖变更应更新 `ToolSpec.version/config`，不要把秘密写入配置；代码摘要和配置一起绑定运行。Registry／policy 返回的描述是独立副本。
- **工具执行器：** 默认 `PythonToolExecutor`；自定义异步 `execute(DispatchEnvelope) -> EffectObservation` 与 `reconcile(DispatchEnvelope) -> EffectObservation | None`，通过 `tool_executor` 注入。审批、预算、派发意图和结果提交由内核负责；执行器复用固定的参数、摘要与 effect_key。
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

短期消息和长期事实使用作用域及 CAS 版本；长期记忆是显式确认的数据。本地向量索引、注入式向量检索与来源版本校验已交付；默认 Embedding、自动记忆提取和企业知识源撤权体系尚未交付。

常用 SDK 和 CLI 见 [API 指引](docs/api-reference.md)；更多接入约束、组件生命周期和测试方法见 [扩展指南](docs/extending.md)。

[组件接入指南](docs/execution-components.md)提供完整契约。源码示例 `python -m examples.execution_components --db .ralf/components.sqlite` 使用自定义 Harness 和业务执行器，停在人工审批；加 `--workflow` 使用同一组件运行顺序工作流。示例使用独立业务账本，模型为离线脚本。

## 执行与恢复保证

模型完整响应先在接收事务保存，再由 Harness 提案并在另一事务采纳稳定工具清单，之后才调度工具。已保存响应恢复时不重新问模型；已采纳决策不重新生成。工具执行前保存效果意图，收到的确认观察先独立保存，再提交结果推进下一步；恢复已保存观察不重新执行或查询业务工具。CLI `inspect` 区分待采纳证据与未知写效果。

工具声明 `read_only`、`idempotent_write`、`queryable_write` 或 `unqueryable_write`。`reconciler` 返回已确认效果的 JSON 结果，无法确定时返回 `None`。不可核验写停在 `waiting_reconciliation`；本地所有者可用 SDK `reconcile()` 提交已完成效果的人工证据。新的 Run 也不能重新提交同一工具／参数对应的未解决写效果。

每个文件数据库只有一个 Coordinator。操作系统锁阻止第二个进程接管；等待审批时可以关闭／重启进程。取消停止后续调度，保留已发出操作及晚到效果。它不撤销远端业务效果；仍在执行的 Python handler 会保留 Coordinator，直到调用结束，不能以取消调用方 Task 释放其归属。

核验结果只采纳一次，晚到的核验证据不会覆盖原结果或重复插入工具消息。运行终态也不会被晚到异常重新打开。可选记忆按上下文额度选择，保留当前任务及完整的最新工具结果；Manifest 记录真正选入的事实版本。

预算单位为整数 **execution credits**：模型／工具每次真实尝试分别原子预留与结算。未知尝试继续占用额度，实际 Token 报告独立保存，缺失明确标记未知。这里没有硬货币预算、实际 Token 计费或外部硬停止的保证。

遇到审批、配置不匹配、未知效果或关闭失败时，按 [恢复与排障教程](docs/recovery-guide.md) 处理，保留原 Run、Action 和业务证据。

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
- [通用框架能力与扩展验收](architecture/viewpoints/framework-capabilities.md)：每层的契约、默认实现、替换入口和验收矩阵；覆盖 Pipeline／Graph／流式编排、动态 Plan、多 Agent 和可替换数据链路，按固定版本与场景对标 AgentScope。
- [Run 命令](architecture/specs/run-command-contract.md)、[Action 恢复](architecture/specs/action-recovery-contract.md)、[Runner 能力](architecture/specs/runner-capability-contract.md)。
- [实现状态与下一步](docs/implementation-status.md)。M1 继续完成命令／等待、质量和最小 Temporal 门槛；通用 SDK 先推进静态图、工具、规划／团队和数据适配，之后扩展流式编排及企业执行模式；v1.0 完成企业私有部署验收。
- [M1 验收与对等比较协议](docs/m1-acceptance.md)：真实模型任务集、故障窗口、Temporal 和外部开发者首用门槛；未执行的实验不记为通过。
- [执行组件与接收阶段 Review](architecture/reviews/2026-10-06-execution-components.md)：dev6 的扩展边界、独立复核修复和真实崩溃证据。
- [记忆与知识来源 Review](architecture/reviews/2026-10-06-recall-rag.md)：dev7 的分页、引用校验、快照恢复和规模边界。
- [受管理工具与 MCP Review](architecture/reviews/2026-10-06-managed-tools.md)：dev11 的会话游标、幂等参数提前验收、修复与资源归属证据。
- [静态 Workflow Review](architecture/reviews/2026-10-06-static-workflow.md)：dev10 的纯编排边界、真实进程恢复、安装升级和独立审查证据。
- [授权与关闭 Review](architecture/reviews/2026-10-05-authorization-shutdown.md)、[可靠性与架构门槛](architecture/reviews/2026-10-05-reliability-boundaries.md)、[扩展性 Review](architecture/reviews/2026-10-05-runtime-extensibility.md)。dev6 使用 `local-4`，Manifest 增加 Harness／Executor 身份；dev3–dev5 的 `local-3` Run 可观察、取消及人工核验，继续执行需要原版本与原配置。dev3 起的提交请求摘要未变，相同请求可以找回原回执；这不表示可以用新内核执行旧 Run。dev1／dev2 的历史提交重放需要原版本。运行及命令摘要尚不支持自动迁移。
- [变更记录](CHANGELOG.md)、[贡献说明](CONTRIBUTING.md)、[发布流程](docs/releasing.md)和[安全反馈](SECURITY.md)。

SDK、运行时和基础治理按 [Apache-2.0](LICENSE) 开源。外部模型／Harness 的服务和许可独立适用。

并行节点隔离上下文、共享预算与分支审批／恢复见[有界并行 Workflow](docs/parallel-workflows.md)。
