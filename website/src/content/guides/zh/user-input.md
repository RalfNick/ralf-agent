---
title: 持久用户输入
description: 让原 Run 等待问题，提交带目标身份的 JSON 答案，并跨进程恢复执行。
locale: zh
slug: user-input
sources: [docs/user-input.md, docs/agent-api.md, docs/session-api.md, docs/recovery-guide.md]
---

应用缺少参数或需要澄清时，可以使用持久用户输入。显式注册的 `request_input` 工具让原 Run 停在 `waiting_input`，关闭和重启后仍保留同一个问题。业务审批、新的会话 Turn 与回答旧问题是不同操作。普通业务输出 `{"status":"needs_input"}` 不会自动创建持久问题。

以下流程使用已安装的 **0.1.0a1** Local SDK 和离线 Provider，不需要模型密钥或网络服务。请先完成[安装](/zh/docs/installation/)或[快速开始](/zh/docs/quickstart/)。

## 1. 生成已安装的输入 starter

在自己的工作目录中选择一个尚不存在的工程目录：

```bash
ralf --format text init input-app --template user-input
cd input-app
python -m agent_app run --command-id first-question
```

本模板使用上面的 `run` 子命令与生成的 README；`init` 的通用提示可能提到另一种 starter 的 `--ticket` 参数。

结果包含 `state: waiting_input`、`run_id`，以及 `pending` 中的一条 input。问题为 `Which environment should I use?`。保存原问题的 `run_id`、`pending_id` 和 `target_digest`，这些值由实际任务生成。完全重复这次提交会找回同一个 Run 和尚未回答的问题。

## 2. 检查问题与回复 Schema

把 `RUN_ID` 替换成保存的值。全局 CLI 参数放在子命令之前：

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  --format text inspect RUN_ID
```

应看到 `State: waiting_input`、问题、回复 Schema 与建议的 `send-input` 命令。默认策略接受非空白 JSON 字符串。pending 身份和 digest 必须取自原问题；审批 Action 的摘要对应另一类目标。

`inspect` 只读 SQLite，不加载工厂，也不取得执行租约。此处提供 factory，是为了让建议的继续执行命令指向正确应用。

## 3. 回答原问题

替换下面三个已保存的占位符。外层单引号是 shell 引号，内层双引号让 `production` 成为 JSON 字符串：

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  send-input RUN_ID PENDING_ID \
  --digest TARGET_DIGEST --value-json '"production"' \
  --command-id environment-answer
```

回执应包含 `kind: send_input`、`record_state: durably_recorded` 和 `apply_state: applied`，表示答案已被接受。原始 CLI **不会**驱动 Run，回执也不代表业务任务成功。

## 4. 恢复并检查结果

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine resume RUN_ID
ralf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

应看到 `State: succeeded` 和 `Result: {"environment": "production"}`。每条命令都可以运行在独立进程中；重启时保留相同数据库、原工厂、release 和策略配置。

再次执行第 3 步完全相同的 `send-input` 命令，包括 `environment-answer`，即使任务已经完成，也会返回原来的 applied 回执。它不会再提问、分配新的 Session Turn 或重置执行额度。离线替身验证持久执行流程，不代表模型推理质量。

## 命令身份、Schema 与被拒绝的答案

宿主在接受 Run 前固定策略与回复 Schema。`request_input` 的参数严格为 `{"prompt": "Which environment?"}`，并且必须是该次模型决策唯一的工具调用。注册框架标记不会自动扩展 Agent 的工具 allowlist；普通 Python 工具仅取名 `request_input` 也不会获得这项执行权限。

| 情况 | 结果与下一步 |
| --- | --- |
| 相同回复命令 ID、目标、值与前置条件 | 返回原回执；响应不确定时可以安全回读 |
| 相同命令 ID 改用了其他值或目标 | `idempotency_conflict`；保留原命令，新意图使用新 ID |
| 答案不满足固定 Schema | 回执拒绝，原因 `invalid_input`；问题仍开放，检查后用新命令 ID 提交有效值 |
| 新命令指向已消费或过期的问题 | `stale_pending_target`；检查当前 pending controls |
| owner 正在取消、已取消或已终结 | `target_closed`；新的迟到答案不能重新打开 Run |
| 可选 `--expected-state-revision` 已不匹配 | `version_conflict`；重新读取 owner，决定是否发出新命令 |
| JSON 格式错误、缺少必填字段或目标越权 | 接受前失败；修正命令或目标 |

如果 owner 已终结，同时问题也已消费，新命令可能返回 `target_closed`；原来已接受的命令仍回读原回执。检查 `apply_state` 和 `outcome`，不要仅凭 JSON 有效或退出码判断答案已经应用。

默认策略允许八个问题、4096 个问题字符和 65536 个回复 UTF-8 字节。可配置范围为 `max_requests` 1–32、`max_prompt_chars` 1–16384、`max_reply_bytes` 1–1048576。回复必须是有限普通 JSON，深度至多 32，并满足固定 Schema。Schema 只允许本地片段引用；远程与动态引用会在读取网络前被拒绝。

## 一个完整离线 SDK 示例

在已安装 SDK 的另一个目录中保存为 `input_sdk.py`，执行 `python input_sdk.py`。它使用新的 `.ralf/sdk-input.sqlite`、显式枚举 Schema 和拥有 Engine 的 Runtime。保持文件不变再次执行，会找回原来已完成的 Run。

```python
import asyncio
import json

from ralf_agent import (
    AgentSpec, LocalEngine, ModelResponse, Runtime, SQLiteStore,
    ToolCall, ToolRegistry, UserInputPolicy, register_user_input,
)


class OfflineInputProvider:
    identity = {"kind": "docs-input-sdk", "version": "1"}

    async def complete(self, messages, tools):
        replies = [m for m in messages if m["role"] == "tool"]
        if replies:
            return ModelResponse(output={
                "environment": json.loads(replies[-1]["content"]),
            })
        return ModelResponse(tool_calls=(ToolCall(
            "request_input", {"prompt": "Which environment?"},
            call_id="environment",
        ),))


async def main():
    tools = ToolRegistry()
    ask = register_user_input(tools, policy=UserInputPolicy(
        reply_schema={"type": "string", "enum": ["production", "staging"]},
    ))
    spec = AgentSpec("assistant", "Ask for the environment.", tools=(ask,))
    engine = LocalEngine(
        SQLiteStore(".ralf/sdk-input.sqlite"),
        providers={"default": OfflineInputProvider()}, tools=tools,
    )
    async with Runtime(engine, owned=True) as runtime:
        agent = runtime.create_agent(spec)
        run = await agent.submit("Check deployment", command_id="sdk-request-1")
        observed = await run.wait()
        print(observed.snapshot.state)
        question = next((q for q in await run.pending() if q["kind"] == "input"), None)
        if question is not None:
            receipt = await run.send_input(
                question["pending_id"], question["target_digest"], "production",
                command_id="sdk-answer-1",
            )
            if receipt.apply_state != "applied":
                raise RuntimeError(receipt)
            print(receipt.apply_state)
        result = await run.wait(terminal_only=True)
        print(result.snapshot.state, result.snapshot.result)


asyncio.run(main())
```

首次执行应依次得到 `waiting_input`、`applied` 和 `succeeded {'environment': 'production'}`。Facade 中已应用的 `run.send_input()` 自动唤醒原受管理根任务；原始 `engine.send_input(...)` 与 CLI `send-input` 需要显式 drive/resume。答案成为原工具调用的结果，剩余决策／工具次数限制与执行额度继续沿用。

替换模型时，按[模型与工具](/zh/docs/models-tools/)把 `OfflineInputProvider` 改为配置好的 Provider。修改回复结构时，同时修改 `UserInputPolicy` 与 Provider 的输出处理。新的定义和策略需要新请求身份以及适当的新数据存储或 Session；恢复旧 Run 时保留旧配置。

## Session 与子任务 owner

开放问题让 Session 保持 busy。`Session.submit()` 和 `Session.run()` 请求的是**新 Turn**，可能抛出 `SessionBusy`，不能用来回答上一 Turn。应调用原 Run 的 `send_input()`，完成或显式取消该 Turn，再等待 Session idle；rebind 同样要求 idle。

在 Team、图或嵌套子任务中，`root.pending()` 的 `ref` 包含问题原 owner 的 RunRef。下面是已有 Runtime 和 `root` handle 中的**用法片段**，不是独立程序：

```python
from ralf_agent import RunRef

question = next(q for q in await root.pending() if q["kind"] == "input")
owner = await runtime.aattach(RunRef.from_dict(question["ref"]))
receipt = await owner.send_input(
    question["pending_id"], question["target_digest"], "production",
    command_id="child-answer-1",
)
print(receipt.apply_state)
```

向该 owner 回答并保留其 target digest。兄弟任务仍在执行时，根任务 `wait()` 可以返回 `wait_reason="control_available"`，而权威快照依旧为 `running`。读取 `pending()` 找到实际 owner；这一观察不代表所有 handler 已停止。兄弟任务的审批或未知效果仍须分别处理。`terminal_only=True` 会继续等待终态，不适合发现尚未回答的问题。

Local owned Runtime 在实际兄弟 handler 完成后，可以关闭并停放稳定的输入等待。保留原 RunRef、数据库与 release，在匹配 Runtime 中 attach 后检查 pending controls，再回答实际 owner。观察超时、取消 `wait()` 或连接断开不会回答或取消 Run。`CloseIncomplete` 要求先处理原来的未释放资源，再正常重试关闭，不能删除租约来强行重启。

继续阅读[连续应用教程](/zh/docs/app-tutorial/)、[审批与恢复](/zh/docs/recovery/)或[API 与 CLI 参考](/zh/docs/api-reference/)。可选的仓库[输入协议指南](repo:docs/user-input.md)还介绍 Profile 策略声明、动态规划澄清与显式启用的 A2A 扩展。
