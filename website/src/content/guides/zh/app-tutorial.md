---
title: 用一个工单开发应用
description: 用同一份应用源码，逐步跑通离线 Agent、Session、RAG、显式 Facts 与顺序 Workflow。
locale: zh
slug: app-tutorial
sources: [docs/support-journey.md, docs/installation.md, docs/agent-api.md, docs/session-api.md, docs/recall-and-rag.md, docs/managed-memory.md, docs/orchestration.md, docs/recovery-guide.md]
---

围绕工单 `INC-001`，在同一份应用文件中完成五个阶段：带只读工具的 Agent、持久 Session、本地 RAG、长期 Facts 和顺序 Workflow。每个阶段组合现有 SDK 组件。默认 Provider 是离线替身，无需模型凭据与网络服务，用于验证执行流程与证据传递。

本教程面向发布提交 `0b9b6c9682c40285d91994cd831aa93d7e814bf1` 的 **0.1.0a1 Local SDK**。先完成[安装](/zh/docs/installation/)和[审批首用教程](/zh/docs/quickstart/)。以下阶段不需要 Temporal、Docker、Embedding 或外部数据库。线上模型兼容性与任务质量需要另外进行[测试与评估](/zh/docs/testing/)。

## 1. 准备应用文件

使用已发布源码中的 [support_journey.py](repo:examples/support_journey.py)。它只导入已安装 SDK 与 Python 标准库，不导入仓库 `examples` 包。wheel 安装 SDK，但不包含该示例文件；源码包中包含它。

如果按源码方式安装，在虚拟环境已激活的**框架仓库根目录**执行，目标目录应尚不存在：

```bash
mkdir ../support-app
git show 0b9b6c9682c40285d91994cd831aa93d7e814bf1:examples/support_journey.py \
  > ../support-app/support_journey.py
cd ../support-app
python support_journey.py --help
```

如果仅安装了 wheel、没有检出仓库，打开上面的源码链接，选择 raw 文件，保存到新工作目录，命名为 `support_journey.py`。保存 Python 源码而非 GitHub HTML 页面，激活安装 SDK 的环境，在该目录执行同样的 `--help` 命令。帮助中应列出 `agent`、`session`、`rag`、`memory`、`workflow`。

后续命令都在这个文件所在目录执行。默认 `.ralf/support-journey/` 下有五个独立阶段数据库，分别保存执行记录、Session、Knowledge 与 Facts。各阶段用同一源码装配自己的数据，不会迁移或共享前一阶段的 Run／Session。

| 阶段 | 增加的组件 | 主要定制位置 | 数据库 |
| --- | --- | --- | --- |
| `agent` | Provider、Python 工具、`AgentSpec` | `provider_for`、`tools_for` | `agent.sqlite` |
| `session` | 持久会话与 Turn | `run` 中的 `agent.open_session`、`session.submit` | `session.sqlite` |
| `rag` | SQLite 文档与词法检索 | `run` 中的 `Document`、`KnowledgeContext` | `rag.sqlite` |
| `memory` | 显式、带版本 Facts | `run` 中的 `memory.put_fact`、`MemoryRecallPolicy` | `memory.sqlite` |
| `workflow` | 两步顺序 Agent 编排 | `run` 中的 `WorkflowSpec` | `workflow.sqlite` |

## 2. 执行 Agent 并回读原结果

```bash
python support_journey.py agent --command-id agent-1
python support_journey.py agent --command-id agent-1
```

第一次 JSON 输出应包含下列字段；实际 `run_id` 由任务生成：

```json
{
  "stage": "agent",
  "state": "succeeded",
  "model_calls": 2,
  "result": {
    "ticket": {"ticket_id": "INC-001", "service": "cache", "status": "connection-error"},
    "advice": "Check cache health and connectivity; do not restart without approval.",
    "knowledge": [],
    "facts": {},
    "session_records": 0
  }
}
```

替身先请求 `lookup_ticket`，再把工具观察复制到答案。第二条命令保持不变，回读**相同 `run_id` 与已保存结果**，`model_calls: 0`。这些数字是离线 Provider 调用次数，不是付费模型用量或质量评分。

相同定义的新请求使用新的 `--command-id`。复用 `agent-1` 却改变输入、budget 或定义可能冲突。响应不确定时保留原 ID 查找原请求，不要删库绕过身份校验。

## 3. 可选：显式选择真实模型

要让整个教程保持离线，跳过本步。显式接入时，通过自己的凭据管理方式提供 `DEEPSEEK_API_KEY`，将 `YOUR_MODEL` 替换为账户支持的实际型号：

```bash
python support_journey.py agent \
  --provider deepseek-chat --model YOUR_MODEL \
  --data-dir .ralf/support-live --command-id live-1
```

也可以选择 `--provider chat-completions`，提供 `OPENAI_API_KEY` 与适用的明确型号。`provider_for` 选择 `DeepSeekChatProvider` 或 `OpenAIChatProvider`。缺少配置时明确失败，不降级为离线替身。真实请求可能产生供应商费用；示例没有统计其用量，`model_calls` 为 `null`。

离线固定答案不是对真实模型结果的预期。应使用自己的任务样例检查工具调用、证据使用与业务结果。[模型与工具](/zh/docs/models-tools/)介绍 Provider 配置，[测试](/zh/docs/testing/)介绍兼容与质量检查。本教程的验证没有调用在线模型。

真实与离线数据使用不同目录。修改模型、指令、工具或策略后，使用新请求身份，以及新数据目录或按新配置创建的 Session；历史恢复仍需原配置。后续命令默认使用离线 Provider，不会继承这条命令的真实模型选择。

## 4. 跨进程继续同一 Session

```bash
python support_journey.py session --command-id turn-1
python support_journey.py session --command-id turn-2 \
  --input 'What should we check next?'
python support_journey.py session --command-id turn-2 \
  --input 'What should we check next?'
```

每次调用都是新进程。应用在 `session.sqlite` 中打开同一 `INC-001` Session；前两条命令分别创建不同 Turn 和 Run，均应成功。第二次输出的 `result.session_records` 应大于零，干净目录中为 `1`，表示保存的上一 Turn 进入了当前上下文。第三条命令回读第二个 Run，`model_calls: 0`。

`Runtime.create_agent(definition)` 创建可运行的 `agent`，`AgentSpec` 只是定义。该文件包含完整异步入口和资源生命周期，可以独立执行，无需依赖[会话指南](/zh/docs/sessions-memory/)中的代码变量。

提交下一 Turn 前，先完成或处理原 Turn。开放审批、输入问题或未结束执行会让 Session 保持 busy。处理原 Run 后等待 idle。回答已有问题使用[持久用户输入](/zh/docs/user-input/)，不能调用 `session.submit()` 再发一条消息。观察 Run 超时不会释放 Session。已保存的 busy 拒绝仍绑定原命令 ID；阻塞解决后，新的提交尝试使用新 ID。

## 5. 加入本地 RAG

```bash
python support_journey.py rag --command-id rag-1
```

应得到 `state: succeeded`，且 `result.knowledge` 中包含：

```json
{"document_id": "cache-recovery", "version": 1, "source_uri": "local://runbooks/cache-recovery"}
```

应用向 `runbooks` namespace 导入一条缓存恢复手册，再用 `KnowledgeContext(LexicalRetriever(...))` 检索。`local://...` 是保存在 SQLite 中的来源标识，不是远程请求。创建使用 `expected_version=0`；重启不会覆盖已有版本或复活已删除文档。

接入自己的文档时，在新应用数据目录中修改 `run` 的 `Document` 内容、身份和 source URI。更新已保存文档时，读取当前版本并进行版本检查更新；仅修改启动时的 seed 文本不会更新持久 Knowledge。预期来源更新后，以新命令 ID 发起新查询；旧请求继续展示原记录答案。

此阶段使用词法检索，不下载 Embedding 模型。命中证明来源检索与引用传递，不代表语义相关性或回答质量。[会话、记忆与 RAG](/zh/docs/sessions-memory/)提供摄取与混合检索装配；可选的仓库[混合检索规格](repo:docs/hybrid-retrieval.md)提供更多技术细节。

## 6. 加入显式长期 Facts

```bash
python support_journey.py memory --command-id memory-1
python support_journey.py memory --command-id memory-2
```

两次都应成功，包含 `result.facts: {"response-style": "concise"}`。可信宿主首次以 `expected_version=0` 将 Fact 写入 `support` namespace。第二个进程保留已保存值并再次召回，也会得到上一条 Session 记录。此阶段在自己的 `memory.sqlite` 中初始化手册，所以结果同时含有 Knowledge。

Fact namespace 与 `support` Agent 对应。替换存储时保留 Scope 与 namespace 边界。更新现有 Fact 需要当前版本；修改初始 seed 值不会替换已保存的 Facts。

示例执行显式写入与持久召回，不执行自动提炼、冲突修订或遗忘。若显式选择受管理提炼，应配置来源字段 allowlist，并检查其独立完成证据；模型陈述不会自动成为已核验 Fact。参阅[记忆配置](/zh/docs/sessions-memory/)与可选的仓库[受管理记忆规格](repo:docs/managed-memory.md)。

## 7. 组成顺序 Workflow

```bash
python support_journey.py workflow --command-id workflow-1
```

应得到 `state: succeeded`、`model_calls: 4`、手册引用和 `response-style: concise`。`WorkflowSpec` 先运行 `triage`，再运行 `support`，前一步输出成为后一步输入。Workflow 阶段复用前面的组件选择，在自己的数据库中装配 Knowledge 与 Facts。业务工具仍全部只读。

这是两个 Agent 定义的固定顺序。离线结果证明两个步骤能够执行，不代表规划、Team 协作或通用工单准确性。修改 `run` 中的 `WorkflowSpec` 可定制顺序或定义；图、Plan、Team 等选择见[工作流与协作](/zh/docs/workflows/)。

## 8. 检查与恢复原任务

每次输出都有 `run_id`。例如，用 Session 阶段自己的数据库检查其 Run：

```bash
ralf --db .ralf/support-journey/session.sqlite --format text inspect RUN_ID
ralf --db .ralf/support-journey/session.sqlite events RUN_ID --after 0 --limit 100
```

其他阶段分别使用 `agent.sqlite`、`rag.sqlite`、`memory.sqlite`、`workflow.sqlite`。如果使用了 `--data-dir`，相应替换目录。这些命令观察默认 Local Scope；检查本身不会恢复执行。本例没有暴露 `module:create_engine` CLI 工厂。

进程已停止后，用同一文件、阶段、Provider、型号、数据目录、输入和命令 ID 再次执行原应用命令。其 submit 路径找回原 Run 并托管继续执行，已经完成的请求返回保存结果。旧执行器仍拥有活动工作时，不要再启动另一进程；正常租约检查会阻止接管。

| 现象 | 下一步 |
| --- | --- |
| `ModuleNotFoundError: ralf_agent` | 激活安装 SDK 的环境，核对[安装](/zh/docs/installation/) |
| Python 找不到文件，或报告 HTML 语法错误 | 准备 raw `support_journey.py` 源码，在该文件目录运行 |
| JSON `{"error":"validation_error"}` | 检查参数与配置；真实模式需明确型号和凭据，离线工单只支持 `INC-001` |
| `idempotency_conflict` | 原请求保持不变进行恢复；新意图使用新 ID |
| `definition_mismatch` | 恢复原模型、文件和组件配置；变更后的应用使用新数据 |
| `session_busy` | 检查并处理原 Turn，等待 idle；原 busy 拒绝保存后，新尝试使用新 ID |
| `coordinator_busy` 或活动租约 | 找到原执行器，让它完成或正常关闭 |
| `close_incomplete` | 保留原资源，处理实际未完成调用／效果，再正常重试关闭 |

示例共用一个 SQLite 连接：Knowledge 和 Memory 借用连接，拥有 Engine 的 Runtime 负责排空后关闭。不能强制关闭借用资源或删除租约。未知效果见[审批与恢复](/zh/docs/recovery/)，资源所有权见[运行与部署](/zh/docs/operations/)。

## 9. 定制与验证应用

- 在 `provider_for` 替换模型；维护离线回归替身时同步调整 `OfflineSupportProvider`。
- 在 `tools_for` 替换只读业务查询。更换工单还需修改离线替身中写死的工具调用，以及 `run` 中的指令和 Session ID；只改变 `--input` 不会让该替身变成通用工单服务。
- 在 `run` 替换 Knowledge、Memory 端口，保留 Scope、namespace、来源校验与版本检查写入。新定义使用新数据，历史恢复保留原文件与配置。
- 新增写操作时，按[模型与工具](/zh/docs/models-tools/)及[首用教程](/zh/docs/quickstart/)使用适当的效果类别、审批和核验契约。只读声明必须符合工具的实际行为。
- 通过[测试与评估](/zh/docs/testing/)建立离线回归、模型协议检查与任务质量样例；在[API 与 CLI 参考](/zh/docs/api-reference/)查询签名和控制语义。

可选的仓库[原始连续工单教程](repo:docs/support-journey.md)使用同一源码文件。Temporal／Coding 组合及生产服务集成不在本 Local 教程的验证范围内。
