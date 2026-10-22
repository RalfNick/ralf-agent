---
title: 测试与评估
description: 运行离线应用回归、检查模型协议，并区分固定样例结果与真实任务质量。
locale: zh
slug: testing
sources: [docs/sdk-model-tools.md, docs/business-evaluation.md, docs/task-evaluation.md, docs/planning-evaluation.md, docs/agent-api.md, docs/completion-verification.md]
---

先按[快速开始](/zh/docs/quickstart/)安装 SDK `0.1.0a1` 并激活 Python 环境。下面的离线路径不需要模型密钥、网络服务或 pytest，已对照发布的 SDK 基线验证。

## 先选择需要的证据

| 检查 | 回答什么问题 | 通过不能证明什么 |
| --- | --- | --- |
| 应用回归 | 在受控响应下，工具、输出断言、身份和恢复规则是否符合预期？ | 真实模型推理或任务质量。 |
| 模型协议兼容 | 此 Provider／端点是否正确处理本次文本、Schema、工具和流式契约？ | 通用智能或你的业务任务成功率。 |
| 任务评估 | 实际配置的模型／工具执行是否满足独立任务 oracle？ | 冻结任务之外的质量，或无关集成的生产验收。 |

日常检查保留确定性回归；切换 Adapter／端点时做协议检查；判断模型行为时，针对版本化业务案例运行真实任务评估。离线评估即使满分也保留 `model_quality: null`；模型兼容探针的离线和在线报告均保持该字段为 null。

## 一个完整的离线应用测试

创建新的工作目录：

```bash
mkdir ralf-offline-tests
cd ralf-offline-tests
```

将以下内容保存为 `test_app.py`。它使用自定义的结构化 `ModelProvider` 执行真正的受管理 Agent／工具循环，不调用外部模型。`complete` 先提出工具调用，再返回工具的真实结果。测试覆盖业务输出、持久工具完成证据和相同命令回放。

```python
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from ralf_agent import Agent, ModelResponse, ToolCall, ToolRegistry


class OfflineProvider:
    identity = {"kind": "offline-application-test", "version": "1"}

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        receipts = [m for m in messages if m["role"] == "tool"]
        if not receipts:
            return ModelResponse(
                tool_calls=(ToolCall("lookup", {"ticket": "INC-001"}, "lookup-1"),)
            )
        return ModelResponse(output=json.loads(receipts[-1]["content"]))


async def main():
    provider = OfflineProvider()
    tools = ToolRegistry()
    lookups = []

    @tools.tool(effect="read_only", description="Read a test ticket")
    def lookup(ticket: str):
        lookups.append(ticket)
        return {"ticket": ticket, "status": "open"}

    with TemporaryDirectory() as directory:
        async with Agent(
            model=provider,
            tools=tools,
            instructions="Read the ticket and return its status.",
            db_path=Path(directory) / "runs.sqlite",
        ) as agent:
            run = await agent.submit("Check INC-001", command_id="test-001")
            observed = await run.wait(wait_timeout=5)
            assert observed.snapshot.state == "succeeded", observed.snapshot.error
            assert observed.snapshot.result == {"ticket": "INC-001", "status": "open"}
            actions = [a for a in observed.snapshot.actions if a["kind"] == "tool"]
            assert len(actions) == 1 and actions[0]["status"] == "completed"
            replay = await agent.submit("Check INC-001", command_id="test-001")
            repeated = await replay.wait(wait_timeout=5)
            assert replay.ref == run.ref and replay.receipt == run.receipt
            assert repeated.snapshot.result == observed.snapshot.result
            assert provider.calls == 2 and lookups == ["INC-001"]
    print("PASS: tool result, durable completion, command replay; model calls=2")


asyncio.run(main())
```

在已激活的环境运行：

```bash
python test_app.py
```

预期退出码为 0，输出：

```text
PASS: tool result, durable completion, command replay; model calls=2
```

每次执行都创建新的临时数据库，并在删除前关闭 Agent。修改输入或定义须使用新命令 ID，不能删除生产数据库来绕过身份冲突。断言失败时进程返回非零，应先检查 `snapshot.state`、`.error`、`.actions` 和 `await run.pending()`，再判断是否修改预期。本例不实例化 HTTP Provider；下一步添加你自己的拒绝、审批、输入、取消和重启案例，操作闭环见[用户输入](/zh/docs/user-input/)和[恢复指南](/zh/docs/recovery/)。

## 检查模型适配器协议

在 `ralf-offline-tests` 中执行：

```bash
ralf-check-model
ralf-check-model --offline > compatibility.json
python - <<'PY'
import json
with open("compatibility.json") as file:
    r = json.load(file)
print(r["status"], r["passed"], r["total"], r["calls"], r["model_quality"])
PY
```

第一个命令输出 `status: "not_run"`、`reason: "provider_not_configured"`、`calls: 0`，不读取模型密钥、不发请求。第二次的摘要为：

```text
completed 5 5 6 None
```

五个案例为 `text`、`structured`、`tool`、`stream`、`stream_close`，可用 `--cases text,tool` 选择子集。工具案例校验精确参数及持久的只读 echo 结果。提前关闭流的案例会有意留下 `waiting_reconciliation` Run，模型结果／用量未知；清理探针通过只证明消费者已关闭，不证明供应商已停止工作或退回用量。

需要可编辑的安装后项目时：

```bash
ralf init my-model-check --template model-check
cd my-model-check
python -m agent_app
cd ..
```

该 starter 运行相同五项离线检查，将私有证据保存在 `my-model-check/.ralf/model-check`。重复运行须使用新证据位置，例如在 starter 内执行 `python -m agent_app --evidence-dir .ralf/model-check-2`。这是兼容检查程序，不提供应用 Engine 工厂。

真实兼容检查须另外显式启用，可能产生供应商费用。私下设置 `MY_MODEL_KEY`，将占位模型换成账号实际可用型号：

```bash
ralf-check-model --adapter openai-responses --model YOUR_ACTUAL_MODEL \
  --api-key-env MY_MODEL_KEY --max-calls 6 --max-output-tokens 1024 \
  --timeout 30 --evidence-dir .ralf/private-live-compatibility-1
```

本命令至多允许六次模型调用尝试，并声明每次输出／await 上限；它不是金额硬上限，也不证明上游取消。其他适配器见 `ralf-check-model --help`。通过只适用于所选端点、型号、适配器和案例，本页离线检查不代表已有在线验收。SDK 可 `await evaluate_model_compatibility(provider, cases=[...], limits=EvaluationLimits(...), evidence_dir=...)`，注入的 Provider 为借用资源。更多细节见 [SDK 兼容检查（中英混排）](repo:docs/sdk-model-tools.md#bounded-compatibility-checks)。

## 验证业务、RAG、Plan 和 Team 行为

在 `ralf-offline-tests` 中运行以下安装后命令。它们以确定性离线 Provider 执行真实受管理循环，并用独立任务 oracle 验证结果：

```bash
ralf-evaluate-business --offline --max-calls 16 \
  --evidence-dir .ralf/business-1 --report business.json
ralf-evaluate-rag --offline \
  --evidence-dir .ralf/rag-1 --report rag.json
ralf-evaluate-orchestration --offline --kind plan-and-execute --max-calls 32 \
  --evidence-dir .ralf/plan-1 --report plan.json
ralf-evaluate-orchestration --offline --kind team --max-calls 32 \
  --evidence-dir .ralf/team-1 --report team.json
python - <<'PY'
import json
for name in ("business", "rag", "plan", "team"):
    with open(name + ".json") as file:
        r = json.load(file)
    print(f"{name}: {r['status']} {r['passed']}/{r['total']} "
          f"calls={r['calls']} model_quality={r['model_quality']}")
PY
```

各命令输出 JSON 报告，最后的摘要为：

```text
business: completed 8/8 calls=15 model_quality=None
rag: completed 8/8 calls=8 model_quality=None
plan: completed 5/5 calls=17 model_quality=None
team: completed 5/5 calls=17 model_quality=None
```

| 评估组 | 证据和边界 |
| --- | --- |
| Business | 八个工单服务案例校验独立业务状态、工具参数、审批／拒绝、停止、回放和终态重建。离线规则只提供回归证据。 |
| RAG | 八个案例校验答案、实际展示的来源／版本／正文支撑、停止和终态重连。离线散列 Embedding 是词项基线，`semantic_quality` 保持 null。 |
| Plan / Team | 各五个案例执行受管理 researcher／writer 子 Run，校验库存／计算器工具回执、参数、金额、先后证据和停止。离线 Plan 使用规则 DAG，Team 使用固定 Supervisor，不测量自主规划质量。 |

`--report` 必须是新文件，每批证据位置须是新的，重跑请更换路径。公开 JSON 不含原始提示／答案；私有 SQLite 证据包含原文并使用受限文件权限。离线失败应作为应用／协议／oracle 回归调查，不应因此直接启用付费模型；先查看各案例 checks／metrics 和原 Run 证据。

未传 `--offline` 或显式 Provider 时，这些评估器报告 `not_run`，不调用模型。任务评估退出码：全部通过或无配置默认展示为 0，案例未通过为 1，已配置但缺失／非法输入为 2。除退出码外还须检查 `status`，`not_run` 不是通过。

## 单独评估规划提案

`ralf-evaluate-planning` 通过受管理 `ModelDAGPlanner` 子 Run 对提案评分，不执行被提议的业务 Worker。默认冻结套件有 20 个案例，仓库提供的离线响应 fixture 只覆盖三个。

安装后的安全默认命令为：

```bash
ralf-evaluate-planning
```

它报告 `not_run`、20 个总案例、零调用及 `model_quality: null`。执行源码 fixture 时，先回到安装所用的已发布仓库 checkout 根目录（测试目录不会生成此文件）：

```bash
ralf-evaluate-planning --fixture evals/planning-fixtures.json \
  --max-cases 3 --max-calls 3 \
  --evidence-dir .ralf/planning-1 --report planning.json
```

预期字段为 `status: "completed"`、`passed: 3`、`total: 3`、`calls: 3`、`model_quality: null`，退出码 0。提案语义和 Schema 通过不能证明拟执行的 Worker 或最终答案成功。评分与分母规则见[规划评估（英文）](repo:docs/planning-evaluation.md)。

## 显式验收真实任务质量

协议检查通过后，再明确配置端点、模型、密钥与独立的新证据批次。例如下面是显式启用的有界真实业务评估，本指南没有运行它：

```bash
ralf-evaluate-business --provider openai --model-env RALF_EVAL_MODEL \
  --base-url-env RALF_EVAL_BASE_URL --key-env RALF_EVAL_KEY \
  --max-cases 8 --max-calls 32 --max-output-tokens 2048 --timeout 60 \
  --evidence-dir .ralf/private-live-business-1 --report live-business.json
```

这些环境变量在本地设置，凭据不进入源码或报告。`--max-calls` 包含失败／未知结果的尝试；`--timeout` 限制客户端 await，可信代码和供应商执行须另有控制。执行 credits 不是货币。`--max-cost-usd` 会保守返回 `not_run`，因为通用契约不能保证计费硬上限。未知用量／费用保持 null。

重复业务测量可用 `--offline --repeats 3 --max-calls 48` 将同样八个样例运行三次；真实重复运行须另行明确调用额度。失败和未尝试项保留在分母中。重复只是同一任务的描述性测量，不是独立任务样本。对外声明质量前，应扩展你自己的版本化案例和独立业务 oracle。

继续阅读[业务评估（英文）](repo:docs/business-evaluation.md)、[完整任务评测](repo:docs/task-evaluation.md)和[完成验证](repo:docs/completion-verification.md)；或回到[连续应用教程](/zh/docs/app-tutorial/)，用 [API／CLI 参考](/zh/docs/api-reference/)定位失败。
