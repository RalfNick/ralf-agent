# Ralf-Agent

dev98 已验收[自动 Facts 索引维护](docs/fact-index-maintenance.md)：原 Graph／Session 中先刷新索引再执行 Agent，提供 SDK／JSON／TOML、可编辑 `memory-index` 模板和原进程恢复。完整冻结源码 8298 passed／617 配置依赖跳过，两套安装各 163 项通过；[验收记录](architecture/reviews/2026-10-13-fact-index-maintenance.md)区分首期 SQLite／Hash 链路与未验收的语义质量、远程维护及完整能力。

dev96 已验收 [Facts 适配契约](docs/facts-adapter-contracts.md)：可编辑 SQLite 实现、SDK／JSON／TOML 替换及原记忆流程恢复。完整回归 7989 passed／617 配置依赖跳过；[验收记录](architecture/reviews/2026-10-13-facts-adapter-contracts.md)说明安装、兼容和恢复证据。完整能力、真实质量和独立采用继续验收。

dev97 已验收 [模型替换与业务组合](docs/model-adapter-contracts.md)：可编辑 Provider 与 Agent／RAG／Plan／Team、192 种安装配置组合和原恢复。完整回归 8183 passed／617 配置依赖跳过；边界见[验收记录](architecture/reviews/2026-10-13-model-adapter-contracts.md)。

dev95 已验收 [Session 适配契约](docs/session-adapter-contracts.md)：基础存储与准确回执分开，提供可编辑 SQLite 替换、安装后示例和原保存恢复。完整能力及真实质量仍按[剩余清单](docs/remaining-work.md)逐项验收。

dev94 已验收首个[知识适配契约套件](docs/adapter-contracts.md)：安装后可运行固定 K01–K12、编辑独立适配器并通过 JSON／TOML 接入 Agent／RAG／Plan／Team。保持原执行权威和旧默认；模型／语义质量、其他角色及完整能力继续验收。见[本批记录](architecture/reviews/2026-10-13-knowledge-adapter-contracts.md)。

dev93 增加显式[持久用户输入](docs/user-input.md)：Agent 提问、Plan 澄清及原 Run／Turn 续接，由原 Local／Temporal 执行权威保存问题、答案和控制回执。完整源码、实际 Worker 恢复、安装与旧版本兼容门槛已通过，见[本批验收](architecture/reviews/2026-10-13-durable-user-input.md)。完整能力与真实模型质量继续验收。

dev92 增加显式 [Plan／Team 业务完成验证](docs/parent-completion.md)：纯回执规则、独立受管理模型验证及安装后库存参考组合；模型不能绕过业务规则或替换候选。保留既有 [Responses 推理续接](docs/responses-reasoning.md)、原推荐默认及执行权威。真实模型质量和完整能力验收继续开放。

Dev83 已验收[原生 Sandbox](docs/sandbox.md)：可替换端口、显式本地 Docker 默认、
原工具审批和每 Agent 授权交集；六类 Local／Temporal 真实恢复、安装和旧82兼容通过。
完整能力继续建设，见[本批验收](architecture/reviews/2026-10-12-sandbox-native-tools.md)。

dev79 增加[每 Agent Skills选择](docs/skills-bindings.md)：原生目录工具的固定选择与禁用、审批及恢复；安装包、真实Temporal和旧78兼容通过。完整能力继续建设。

dev78 增加[可替换Skills目录与受管理加载](docs/skills.md)：Memory／File默认、固定内容、显式Scope和原审批恢复；安装包、真实Temporal及旧77兼容通过。完整能力继续建设。

dev77 增加[受管理Workspace写入](docs/workspace-writes.md)：可替换Memory／File、CAS、审批和恢复；安装包、真实Temporal／PG及旧76兼容通过。完整框架能力继续建设。

当前工作区 **0.1.0.dev98** 提供显式语义知识库、相关事实召回和 Plan／Team 默认组合，
复用原执行、审批和恢复协议。见[H3 使用与扩展指南](docs/h3-intelligent-combinations.md)。
dev48 增加[显式 HTTP 语义重排](docs/http-reranking.md)，保留原知识来源及旧默认配置。
dev49 增加[Query transform 与语义 Facts 召回](docs/query-and-semantic-recall.md)，支持显式语义记忆组合及保留语义顺序的上下文。候选窗口外事实和真实质量仍待完善。
dev50 增加[显式模型查询改写](docs/model-query-transform.md)，借用已配置 Provider，支持知识检索及 Local 语义 Facts；默认保留原查询，自动查询策略与完整质量仍待验收。
dev53 增加[可选文本 PDF 摄取](docs/pdf-ingestion.md)，与已有[DOCX 正文](docs/docx-ingestion.md)和[HTML 摄取](docs/html-ingestion.md)共用可安装 ingest 模板、原子知识回执、分块及来源引用。
dev54 增加[可替换 tokenizer、输出预留与 token 分块](docs/tokenization.md)，保持原字符默认；模型词表由宿主显式装配，纯计量不隐藏联网。
dev56 增加[全库事实索引](docs/fact-indexing.md)：有界扫描、独立可替换索引元数据、Embedding 回执与完整激活；memory／SQLite／Redis 来源与显式 Qdrant 配置。写后显式重建，Hash 默认为离线词项基线。dev57 补齐 PostgreSQL 原生扫描、连接重开、配置与进程恢复；dev58 增加 [Temporal Facts 绑定](docs/temporal-facts.md)和有界召回，复用原 History、每 Agent namespace 与纯 planner；dev59 补齐 [Temporal Knowledge namespace 绑定](docs/temporal-knowledge-bindings.md)，包括原始来源采纳和原生检索资源固定；真实语义质量仍待验收。

dev55 增加[文件 Artifact](docs/file-artifacts.md)：无需 extra，可通过 SDK 或 JSON/TOML 替换 SQLite，支持有界正文、作用域、TTL、原引用恢复和受管理卸载。POSIX 本地文件系统范围；孤儿清理、全局磁盘配额和 S3 继续待交付。
dev60 增加 [Temporal 持久会话／Turn](docs/temporal-sessions.md)：原 Namespace UUID 身份、串行占用、稳定拒绝与空闲重绑定；图／Team／动态／嵌套复用原执行 History，支持上下文和 Worker 恢复。外置 Session 数据和长期治理继续待交付。
dev61 增加 [Temporal 每 Agent 限制策略](docs/temporal-agent-limits.md)：可替换纯策略、强制宿主交集、逐节点固定及超限工具批次拒绝。
dev63 增加 [Temporal DecisionPolicy](docs/temporal-decision-policy.md)：宿主／每 Agent 纯 prepare/propose、自定义请求与原决策证据。
dev62 增加 [Temporal 完成验证](docs/temporal-completion-verification.md)：原节点工具回执、纯规则采纳、有界重试及完成前记忆门禁。
dev65 提供 [Temporal 固定 Session 有界读](docs/temporal-session-data-reads.md)。dev66 已交付 [原生／顺序的外置保存和持久 Turn](docs/temporal-session-data-writes.md)；dev67 已接通[高级根／成员会话树](docs/temporal-session-trees.md)，dev68 增加[真实 Context 读取生命周期](docs/temporal-context-read-lifetime.md)。
dev69 的[Temporal Profile 配置装配](docs/temporal-profiles.md)复用十类绑定与原 History；dev70 增加多版本 Host、原 Run／Session 路由、共享资源排空和声明 PostgreSQL EffectJournal。[本批验收](architecture/reviews/2026-10-11-temporal-profile-host.md)已通过本记录门槛；完整 R01–R26/H1–H5/M1 保持开放。

dev72 增加[固定命令 CLI 工具](docs/cli-tools.md)、异步声明工厂与 cli starter；本批验收已通过，完整工具与环境能力继续建设。

dev71 增加 Temporal Host 基础启动预检：无效参数在 RPC 与启动状态固定前拒绝，纠正后可重试；保留 SDK 合法零值。复杂 SDK 对象仍委托 SDK，极端数值尚有边界限制。[dev71 验收](architecture/reviews/2026-10-11-temporal-startup-preflight.md)本批门槛已通过，完整框架目标仍开放。
Local 与 Temporal 十一类每 Agent 绑定、自动上下文与来源化记忆已接通；完整 H3、
真实模型质量、H4 执行环境和 H5 企业治理仍待验收。当前适合开发者试点。

以下版本演进说明保留其发布时的边界；当前支持范围以[能力清单](docs/implementation-status.md)为准。

dev39 接通 Graph／并行图、Team、动态 Plan／DAG 和嵌套流程的远程根会话。复用 Redis／PostgreSQL 准确回执和原 Local 执行权威，丢失保存响应后直接恢复最终结果，不重跑编排决策或业务工具。见 [远程复合 Session 指南](docs/session-api.md#远程复合根会话dev39h2b4b)。

dev36 增加[授权根会话 namespace](docs/session-api.md)：
图／Team／动态／嵌套会话在宿主允许范围中选择 namespace，根资源与成员默认分离，
同名会话地址／历史独立，原资源在派发和最终保存前复核。配置此能力启用 schema4，
dev35旧代码在派发前拒绝；默认 schema1/2/3 兼容。SDK仍是开发者预览。

dev34 扩展[Temporal Agent 入口](docs/temporal-agent-api.md)：同一 Agent/AgentRun API 支持原生／顺序及已注册的 Graph、Team、动态 DAG 与嵌套流程；按实际子 Run 定位审批／核验，等待只观察，客户端 detach 保留服务端执行。Temporal 能力绑定、共享远程会话和完整 H2 仍待交付。

dev32 增加[持久 Local Session／Turn](docs/session-api.md)：原生 Agent／顺序 Workflow 的会话占用、原发布固定、稳定忙碌回执与空闲 CAS rebind；会话与执行事实同 SQLite 权威。开启会话后启用 schema2，旧 SDK 明确拒绝，远程／图／团队会话和完整 H2b 仍待交付。

dev29 增加[可替换完成验证](docs/completion-verification.md)：以已提交工具回执验证业务完成，有界反馈复用原预算和审批；支持 Local 每 Agent 绑定及 Profile 配置。dev62 已接通 Temporal 纯验证绑定；模型／异步验证阶段及完整 Facade 仍待完成。

**Reliable Agent Lifecycle Framework — 从单个智能体到可靠的企业 AI。**

dev28 的[Facts／Knowledge 范围绑定](docs/data-bindings.md)支持共享客户端下的独立 namespace 与来源校验；[DeepSeek 完整小试验](docs/live-model-quality-dev28.md)保留真实业务失败，Schema 合法仍不代表业务操作已完成。

Ralf-Agent 是 Python 优先的开源 Agent 运行时。它把模型决策、工具动作、审批与结果保存为明确的执行步骤，让任务在重启后继续，并核验可能已经发生的业务操作。

[推荐 Local Harness 组合](docs/recommended-harness.md)提供版本化 Basic／Knowledge／Managed Memory，支持自动历史摘要、引用摘录和大工具结果产物投影，沿用原 Run 恢复权威。

初次使用从[首用教程](docs/getting-started.md)开始；typed 工具与模型默认接入见[SDK 指南](docs/sdk-model-tools.md)，持久事件与调用中间件见[事件指南](docs/middleware-and-events.md)。[整体架构审查](architecture/reviews/2026-10-08-agent-framework-alignment.md)区分已有组件、默认组合、尚未实现的能力和三项已在dev24修复的问题与后续架构门槛。

dev44 接通[高级编排与 Temporal 自动上下文](docs/composite-temporal-context.md)：图／Team／动态／嵌套实际 Agent 的历史压缩与产物卸载，保留原 Run／History 阶段证据；高级自动记忆写入、语义质量与完整 H3 仍待完成。

dev45 增加[Local 高级编排自动记忆](docs/composite-memory-stages.md)：原规则／模型字段选择、并行节点事实隔离、推荐 managed-memory 默认组合及终态根／子 Run 的证据恢复。Temporal 自动记忆写入、语义默认与完整 H3 质量仍待完成。

dev46 增加[Temporal 自动记忆与每 Agent 绑定](docs/temporal-memory-bindings.md)：显式 temporal-3 发布支持五类版本化选择、实际子 Run 路径、History 记忆阶段及只读证据恢复。其他 Temporal 绑定角色、共享 Session 与完整 H3 质量仍待完成。

dev46 发布时范围（历史）：**0.1.0.dev46，M1 核心预览**。提供原生 Agent SDK、顺序 Workflow、静态串行／有界并行图，以及有限动态规划与多 Agent 团队。SQLite 持久执行统一管理模型、工具、审批／取消、预算和未知效果恢复。模型层提供 Chat Completions、Anthropic、Gemini 文本及 DeepSeek 非思考模式适配；工具支持可信 Python、异步 ToolSource 和 MCP stdio。JSON／TOML 装配版本化组件，历史任务按原配置恢复。

dev14 增加真实 **Redis Session/Facts、PostgreSQL Memory/Knowledge 和 Qdrant VectorIndex**，通过[异步装配](docs/async-assembly.md)接入原有记忆／RAG 端口；提供默认规则 Planner、受管理 ModelPlanner、Verifier，以及 Sequential／Router／Supervisor 团队和独立 Plan／Team 模板。接入方式见[远程数据指南](docs/remote-data.md)与[规划及多 Agent 指南](docs/orchestration.md)。完整 M1 尚未验收，适合开发者试点；[实现清单](docs/implementation-status.md)记录支持边界。预览 API 尚未稳定。

dev86 提供安装后可用的 [RAG 与 Plan／Team 完整任务评测](docs/task-evaluation.md)：实际摄取、检索、答案引用、原受管理成员与工具回执、重复评分和观察式恢复。默认离线仅验证运行协议，真实质量及外部采用仍需独立证据。

dev15 增加[动态 DAG、计划补丁和嵌套编排](docs/dynamic-dag.md)、可替换的[MQ／A2A 交接层](docs/remote-handoff.md)，以及以 History 为执行权威的[Temporal 预览后端](docs/temporal-execution.md)。dev15 的 Temporal 子集仅支持原生 Agent／顺序 Workflow；dev17 已扩展，见下文。新增 20 个冻结任务的[规划质量评测入口](docs/planning-evaluation.md)，真实模型质量仍需实际配置与运行，离线分数不代表 AI 能力。

```bash
ralf init my-dag --template dag
# 或：ralf init my-nested --template nested
cd my-dag
python -m agent_app --input hello --command-id first
```

dev16 将 A2A 接到原生异步执行权威，新增共享 PostgreSQL Inbox／Outbox 和默认 `a2a` HTTP 模板。单机默认服务负责执行跟踪与安全关闭；多进程网关可共用 Temporal 和 PostgreSQL。配置与所有权见[异步交接指南](docs/async-handoff.md)。

dev17 增加 [Temporal 分布式图／团队／动态规划与嵌套编排](docs/temporal-composition.md)，复用真实 PostgreSQL／Qdrant RAG；支持固定执行额度、并发／深度限制、任务期限和审批过期。组件通过显式注册替换，父子执行事实归 History 管理。新增安装包内 `temporal` 模板和 [业务任务评测](docs/business-evaluation.md)。企业身份、全局容量、生命周期治理和真实模型质量仍需后续验收。

dev21 新增[自动来源记忆与受管理模型摘要](docs/managed-memory.md)、[Temporal 自定义上下文](docs/temporal-custom-context.md)和第十八种 memory starter。已完成一轮[真实 DeepSeek 试验](docs/live-model-quality.md)，保留初次失败和不同配置的后续成绩；不代表完整 M1 或跨框架能力对齐。

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

真实模型有独立可编辑入口：`ralf init my-model-agent --template model`。先在 runtime.toml 替换模型占位、选择协议与凭据环境变量，再运行应用。协议、参数、流式和支持边界见[模型接入指南](docs/model-adapters.md)。Gemini 文本模式保持原行为，函数工具使用显式 `gemini-functions`；DeepSeek 非思考 preset 保持，思考工具循环使用[deepseek-thinking](docs/deepseek-thinking.md)。原生模式需显式启用续接，完整历史按需要配置；本地协议测试不证明线上型号兼容或模型质量。

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

前一步通过输出验收后，结果成为下一步输入。需要依赖、条件分支和输入映射时，使用 `GraphWorkflowSpec`，默认串行，显式 max_concurrency 启用有界并行。图计划及节点状态持久保存。动态规划使用 `DynamicWorkflowSpec`，团队使用 `TeamSpec`；两者通过子 Run 复用相同的 Agent 与业务执行协议。

```sh
ralf init my-graph --template graph
cd my-graph
python -m agent_app --input urgent --command-id first-graph
```

Python 图定义、自定义纯变换、编译器／解释器、分支合并与恢复见[静态 Workflow 教程](docs/static-workflows.md)。

无需模型密钥也能运行规划与团队链路：

```shell
ralf init my-plan --template plan
cd my-plan
python -m agent_app --input hello --command-id first-plan
```

`--template team` 生成 Supervisor／Workers 项目。规则与离线模型仅验证运行时链路；真实模型规划需要配置 Provider。父子审批、预算、取消、恢复和自定义策略见[编排指南](docs/orchestration.md)。

## 扩展与替换

- **图编排：** `WorkflowCompiler`／`WorkflowInterpreter` 与 `NodeTransform` 是同步纯端口，默认有静态编译／解释和复制输入实现。可直接注入或用显式工厂注册；输入、跳过集合与结束结果仍由公共边界校验。
- **模型：** 实现 `ModelProvider.identity` 与异步 `complete(messages, tools) -> ModelResponse`，通过 `providers` 注入。Provider 只产生决策，不自行执行工具。
- **Agent 策略：** 默认 `NativeHarness`；自定义同步 `prepare(spec, messages, tools) -> ModelRequest` 与 `propose(spec, response) -> DecisionProposal`，通过 `harness` 注入。可以按 AgentSpec 选择策略；内核继续验收工具白名单、参数和最终输出。
- **工具：** `ToolRegistry.register(ToolSpec, handler, reconciler=...)`。handler 接收 JSON 参数和可信 `InvocationContext`，支持普通同步／异步函数、实例、绑定方法和 `functools.partial`。状态、绑定参数和依赖变更应更新 `ToolSpec.version/config`，不要把秘密写入配置；代码摘要和配置一起绑定运行。Registry／policy 返回的描述是独立副本。
- **工具执行器：** 默认 `PythonToolExecutor`；自定义异步 `execute(DispatchEnvelope) -> EffectObservation` 与 `reconcile(DispatchEnvelope) -> EffectObservation | None`，通过 `tool_executor` 注入。审批、预算、派发意图和结果提交由内核负责；执行器复用固定的参数、摘要与 effect_key。
- **记忆：** `SessionStore`／`LongTermMemoryStore` 及对应异步 Protocol 通过 `session_store`／`memory_store` 独立注入。SQLite 和内存后端留在创建线程；远程后端优先实现异步方法。线程安全的同步远程客户端可用 `ThreadedMemoryAdapter` 显式桥接。`backend_id` 必须识别后端／配置／版本，已有 Run 不静默切换后端。
- **远程数据与 RAG：** Redis／PostgreSQL 提供会话和事实默认适配器；PG 文档权威与 Qdrant 派生索引可独立替换，通过 EmbeddingProvider／VectorRetriever 组合。可选客户端使用 `.[remote]` 安装，工厂通过 abuild 创建并管理关闭。
- **规划与团队：** 替换 Planner、纯 PlanVerifier 或 TeamStrategy，注册有限成员即可组合业务 Agent。策略提出计划，Engine 管理子调用与执行事实；父级统一限制成员、修订、步骤、并发和 credits。
- **执行与上下文：** `ExecutionStore` 不暴露 SQL／连接，`CoordinatorLease` 负责执行权归属；自定义存储需显式提供租约和记忆组件。`context_assembler` 接收具有版本身份的 `ContextBuilder`，内核仍检查上下文额度和实际快照摘要。这些是 Local 的同步组件端口；独立 History 权威与支持范围见 [Temporal 编排](docs/temporal-composition.md)。
- **治理：** 本版本为可信宿主配置的本地所有者模式。可注入同步 `policy(scope, tool_spec, arguments) -> None`，拒绝时抛 `AuthorizationDenied`；其他返回值一律拒绝；每次工具执行／恢复重新检查。企业 OIDC、资源 ACL 和凭据代理尚未交付。

```python
from ralf_agent import InMemoryMemory

sessions = InMemoryMemory(backend_id="demo-sessions:v1")
facts = InMemoryMemory(backend_id="demo-facts:v1")
# LocalEngine(..., session_store=sessions, memory_store=facts)
# facts.put_fact(scope, "assistant", "language", "中文", expected_version=0)
```

短期消息和长期事实使用作用域及 CAS 版本。本地向量索引、Hash Embedding 离线基线、混合检索和来源版本校验已有实现；[可选记忆 pipeline](docs/managed-memory.md)提供规则／模型字段选择与有来源的观察记录。观察记录不等于已经确认的事实。dev40–42 已提供 Local 原生／顺序的[自动规则记忆](docs/managed-memory-stages.md)、[自动模型字段选择](docs/managed-model-memory-stages.md)与[受管理规则／模型摘要](docs/managed-context-stages.md)，默认关闭并可按 Agent 绑定。高级及 Temporal 自动记忆、摘要和大结果卸载已有显式原 Run 阶段；完整 Session／RAG 语义管理、语义修订／撤回、线上质量和企业知识源撤权体系仍待完善。

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
- [当前剩余能力清单](docs/remaining-work.md)：逐层区分已交付子集、尚未实现与待验收能力，按 H1–H5 继续建设。
- [Local Agent API](docs/agent-api.md)：dev31 H2a 的统一入口、独立执行托管、纯观察等待与可重试关闭；dev32 补齐同库原生／顺序 Session/Turn 子集。
- [Temporal Profile 配置装配](docs/temporal-profiles.md)：JSON／TOML、十类绑定工厂与真实 Worker 资源排空；安装包提供离线起步模块，完整路由／治理仍待完善。
- [Temporal Context read lifetime](docs/temporal-context-read-lifetime.md)：显式托管 Context 读取与准确结束通知，关闭和恢复责任独立；[dev68 子集验收](architecture/reviews/2026-10-11-temporal-context-read-lifetime.md)已通过。
- [Temporal Agent API](docs/temporal-agent-api.md)：高级编排入口、实际子 Run 控制引用、异步重连与客户端 detach；已有版本化绑定、History Session 与原生／顺序外置保存；高级根／成员私有数据见[Temporal 会话树](docs/temporal-session-trees.md)。其余环境角色、配置及完整验收仍待完善。
- [AgentHarness目标架构](architecture/viewpoints/harness-runtime.md)：广义Harness/Core、每Agent绑定、统一入口、受管理默认链路与H1–H5开发门槛；首期见[能力绑定契约](architecture/specs/agent-capability-binding-contract.md)，H2见[Facade／Session／关闭契约](architecture/specs/agent-facade-session-contract.md)。H1a–H1f 与入口子集已交付；完整 H1/H2、Temporal 其余角色、其他资源选择／环境角色及完整智能默认链路仍待实现。
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

[并行 Workflow Review](architecture/reviews/2026-10-06-parallel-workflow.md)记录 dev12 的执行隔离、资源静止、回调核验修复和独立审查证据。

### 用户文档摄取（dev18）

`ralf init my-doc-agent --template ingest` 提供第十五种包内 starter。显式 UTF-8 文本／Markdown → 可替换 Parser／Chunker → 原子知识回执 → 默认词法证据 Agent 查询；SQLite 默认无需外部服务，PostgreSQL 支持同一摄取契约。重复请求返回历史回执，`knowledge_committed` 不代表向量索引就绪。替换组件、更新／恢复及边界见[文档摄取指南](docs/document-ingestion.md)。dev19 已交付显式 HTTP Embedding／混合检索／基础重排，dev21 已交付显式模型摘要与来源提炼；运行内自动链路及完整语义质量仍待验收。

### 混合检索（dev19）

`ralf init my-hybrid-agent --template hybrid` 提供第十六种包内模板：用户文档摄取、显式向量索引、词法／向量并行召回和引用恢复。默认 HashEmbedding 无需服务；显式 OpenAIEmbeddingProvider 和 SQLite／PostgreSQL/Qdrant 的新装配入口可替换这一层。融合与同步／异步重排仅提出排名和候选 ID，由知识权威复核来源。完整示例、预算、生命周期与语义质量边界见[混合检索指南](docs/hybrid-retrieval.md)。

### 上下文与大结果（dev20）

`ralf init my-context-agent --template context` 提供第十七种离线模板，显式存储大工具结果并读取有界样本，支持提交后恢复。MessageCounter、ContextBudgeter、ContextSummarizer 可分别替换，BudgetedContextAssembler 提供字符／token 估算、完整消息组裁剪与显式历史摘录，实际 Harness 请求也受预算约束。ArtifactStore 有内存／SQLite 默认及 opt-in 文件后端，实现 Scope、字节、TTL、摘要与事务容量；应用工具选择引用契约。旧默认保持。自动规则记忆和 Local 原生／顺序模型摘要已有 opt-in 原 Run 阶段；显式提炼／模型摘要及 Temporal 纯自定义上下文已有实现。自由合成、剩余环境角色、完整智能默认链路和企业治理仍待完善，见 [上下文与 Artifact 指南](docs/context-artifacts.md)及[自动上下文接入](docs/managed-context-stages.md)。

Native Responses, keyword Python tools and managed compatibility scenarios: [dev22 guide](docs/sdk-model-tools.md). The [ordered alignment roadmap](docs/agentscope-alignment.md) tracks subsequent sandbox/interaction, semantic data, services and enterprise gates.

The dev23 [middleware and event guide](docs/middleware-and-events.md) covers
opt-in observers, resumable persisted-event streaming, ralf-watch-events and the
twentieth observable starter. [Alignment order](docs/agentscope-alignment.md)
retains separate input/Workspace/Sandbox and production acceptance gates.

Dev73提供[固定目标HTTP JSON工具](docs/http-tools.md)，完善[CLI](docs/cli-tools.md)读取／规划／审批示例；最终门槛见[记录](architecture/reviews/2026-10-11-fixed-business-tools.md)。

Dev74增加[MCP HTTP JSON／POST SSE](docs/mcp-http.md)，接入原ToolSource与async声明；[子集验收](architecture/reviews/2026-10-11-mcp-http.md)通过，持久Session／GET恢复／OAuth仍待实现。

Dev75增加[只读Workspace Port与文件／内存默认实现](docs/workspace.md)，沿原工具与async装配接入；[子集验收](architecture/reviews/2026-10-11-workspace-read.md)通过。环境绑定与Sandbox仍开放。

Dev76子集已验收接通[每Agent只读Workspace绑定](docs/workspace.md)：复用原工具授权和资源，不增加执行权威；[安装与最终验收](architecture/reviews/2026-10-11-workspace-bindings.md)已通过；后续写入、Skills和本地Sandbox子集按各批验收记录交付，完整环境能力仍开放。
