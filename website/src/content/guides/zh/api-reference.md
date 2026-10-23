---
title: API 与 CLI 参考
description: 查询常用 Local Agent、Runtime、Session 和 CLI 的签名、返回值与恢复契约。
locale: zh
slug: api-reference
sources: [docs/api-reference.md, docs/agent-api.md, docs/session-api.md, docs/user-input.md, docs/sdk-model-tools.md, docs/recovery-guide.md, docs/runtime-assembly.md, docs/getting-started.md]
---

本页精选常用 Local 入口，对照 SDK `0.1.0a6` 核验，不是完整的自动生成 API 列表。完整程序从[连续应用教程](/zh/docs/app-tutorial/)开始；Provider 装配见[模型与工具](/zh/docs/models-tools/)。Temporal 和可选后端的独立契约见[运行与部署](/zh/docs/operations/)。

## 定义和可运行入口

以下名称从 `relf_agent` 导入。

| 入口 | 常用签名或默认值 | 含义 |
| --- | --- | --- |
| `AgentSpec` | `AgentSpec(name, instructions, tools=(), provider="default", version="1", max_decisions=8, max_context_chars=32000, model_credits=1, output_schema=None)` | 不可变声明。工具名须在宿主注册；没有 `run` 或 `open_session` 方法。 |
| `Agent` | `Agent(*, model, tools=(), name="assistant", instructions="Answer the request", db_path=".ralf/runs.sqlite", definition=None)` | 显式传入 Provider 的独立异步 Facade，创建并拥有 Runtime。 |
| 共享宿主的 `Agent` | `Agent(runtime=runtime, definition=spec)` 或 `runtime.create_agent(spec)` | 借用已有 Runtime 及其固定组件，不再同时传 `model` 或 `tools`。 |
| `Runtime` | `Runtime(engine, *, owned=False, authority_locator=None, close_timeout=30, close_policy="drain")` | 在一个事件循环托管 Local 执行；默认借用注入的 engine。 |
| `LocalEngine` | `LocalEngine(store, providers=..., tools=..., ...)` | 底层执行权威。`submit` 记录意图，调用者显式推进。 |
| `ToolRegistry` | `tools.tool(effect="read_only", ...)` / `tools.register_function(function, effect=..., ...)` | 注册 Python 函数并从支持的类型生成参数 Schema；仍须明确效果分类和宿主授权。 |
| `ModelProvider` | 有限 JSON `identity` 字典；`async complete(messages, tools) -> ModelResponse` | 结构化协议，无须继承基类。Provider 提出输出或 `ToolCall`，引擎授权并执行工具。 |

建议定义命名为 `spec`，可运行入口命名为 `agent`。修改提交的声明（例如 `output_schema`）会改变请求摘要；工具和 Provider 注册身份固定在接受时的 release 中。变更组件用于新任务，恢复旧 Run 须保留原组件。

`Runtime.from_profile(profile, db_path, *, builder=None, scope=None, ...)` 拥有构建的组件装配；`await Runtime.afrom_profile(...)` 支持异步工厂。组件注册见[运行装配](repo:docs/runtime-assembly.md)，托管与关闭见 [Local Agent 契约（英文）](repo:docs/agent-api.md)。

## submit、run 与 wait

下表 Facade 方法均须 `await`；提交业务意图必须提供 `command_id`。

| 方法 | 返回值 | 默认值与行为 |
| --- | --- | --- |
| `agent.submit(input, *, command_id, budget=32)` | `AgentRun` | 持久提交并唤醒托管执行，保留 `.ref` 和 `.receipt`。 |
| `agent.run(input, *, command_id, wait_timeout=None, terminal_only=False, budget=32)` | `WaitResult` | submit 后 wait，不直接返回业务输出。 |
| `run.wait(*, wait_timeout=None, terminal_only=False)` | `WaitResult` | 观察已提交事实。默认无观察超时，遇终态或人工／恢复暂停即返回。 |
| `run.status()` | `RunSnapshot` | 只读观察：`state`、`result`、`error`、`pending`、`actions`、`state_revision`。 |
| `run.events(*, after=0, limit=1000)` | `RunEvent` 列表 | 有序事件；用最后一个 `seq` 继续翻页，`event_id` 为 `run_id:seq`。 |
| `run.diagnostics()` | `RunDiagnostics` | Snapshot、原 manifest、release digest、预算和可选工作流详情。 |

`WaitResult` 包含 `ref`、`snapshot`、`wait_reason`、`observed_at`。原因值为 `state_reached`、`control_available`、`observation_timeout`。读取 `observed.snapshot.result` 前先检查 `observed.snapshot.state`；暂停或观察超时不等于业务成功。`terminal_only=True` 会等待穿过暂停，通常需要明确的观察超时。

取消 wait 的 await 不会取消业务执行。明确取消须 `await run.cancel(command_id=...)`；取消也不回滚远端效果。

原始 engine 的返回类型与推进方式不同：

```python
# 位于 async 函数中；engine 和 spec 已装配。
handle = engine.submit(spec, "Check INC-001", command_id="request-001", budget=32)
snapshot = await engine.drive(handle.run_id)
print(snapshot.state, snapshot.result)
```

`engine.submit(...)` 同步返回 `RunHandle(run_id, receipt)`，不会开始执行；`await engine.drive(...)` 在完成或暂停时返回 `RunSnapshot`。不要混用 `RunHandle`、`AgentRun` 和 `WaitResult`。无状态 Facade 提交拒绝共享 `session_id` 和 `queue=True`，共享会话请使用显式 Session。

## 持久 Session

| 需 await 的方法 | 返回值／契约 |
| --- | --- |
| `agent.open_session(session_id, *, command_id)` | `AgentSession`，含 `.ref`（`SessionRef`）和开会话 `.receipt`。普通原生 Agent 路径不传 namespace；显式选择 namespace 属于独立的复合定义契约。 |
| `session.submit(input, *, command_id, budget=32)` | `AgentRun`，其 `.turn`（`TurnAdmission`）保留原 Turn／Run 身份。 |
| `session.run(input, *, command_id, wait_timeout=None, terminal_only=False, budget=32)` | `WaitResult`，观察语义与 Agent 相同。 |
| `session.status()` | `SessionSnapshot`，提交新 Turn 前检查 `.busy`。 |
| `session.turns(*, after=0, limit=100)` | 有序 Turn 记录，支持的 limit 最大为 1000。 |
| `session.rebind(definition, *, expected_binding_revision, command_id)` | 空闲状态下执行 CAS 后返回新 `AgentSession`；后续 Turn 使用其返回引用。 |
| `session.aclose()` | 只分离此入口，不关闭共享 Runtime。 |

Session 保留一个未完成 Turn，审批、用户输入和未知效果都可能占用它。仅有终态 Snapshot 不能证明会话空闲。向旧问题所属的原 Run 回答，再确认 Session 空闲，才提交新 Turn。完整用法见[会话与记忆](/zh/docs/sessions-memory/)、[持久用户输入](/zh/docs/user-input/)和 [Session 契约（英文）](repo:docs/session-api.md)。

## pending 与控制

`await run.pending()` 返回原始待处理证据，包括嵌套所有者。每项包含 `ref`；通过 `runtime.attach(RunRef.from_dict(item["ref"]))` 连接该所有者，先检查 `kind` 再选择控制。`auxiliary` 项可能是上下文、记忆或保存责任，不能当作审批请求处理。

| 对原所有者调用的 await 方法 | 返回值／契约 |
| --- | --- |
| `run.approve(action_id, target_digest, *, command_id, approved=True)` | `CommandReceipt`，将审阅决定绑定到原 Action 和 digest；`approved=False` 为拒绝。 |
| `run.send_input(pending_id, target_digest, value, *, command_id, expected_state_revision=None)` | `CommandReceipt`，value 必须符合原问题 Schema；可选 revision 增加状态检查。 |
| `run.reconcile(action_id, result, *, command_id)` | `CommandReceipt`，根据已核实业务证据确认未知效果，不得编造成功来解除阻塞。 |
| `run.cancel(*, command_id)` | `CommandReceipt`，记录明确停止决定。 |
| `run.resume()` | `AgentRun`，唤醒原托管执行，不产生新的提交或控制回执。 |

审批取待处理项的 `action_id` 和 `digest`；输入取 `pending_id` 和 `target_digest`。托管 Facade 控制会唤醒原根 Run，已应用的输入回复继续原 Run。原始 `engine.approve` / `engine.send_input` 和 CLI 控制仅记录决定，之后还需显式 drive／resume。闭环见[输入回复步骤](/zh/docs/user-input/)和[审批与恢复](/zh/docs/recovery/)。

## 身份、回执和重连

| 身份／记录 | 保留目的 |
| --- | --- |
| `command_id` | 可信 Scope 内的一次不可变请求或决定。同 ID、相同请求回读原回执；修改输入、定义、预算或决定会冲突。新意图使用新 ID。 |
| Run ID / `RunRef` | 原执行权威、Scope、release 上的一次执行。用 `run.ref.to_dict()` 保存，`RunRef.from_dict(...)` 重建。 |
| `SessionRef` / Turn | 原会话地址、绑定修订、Turn 顺序与其 Run；回复／控制不是新 Turn。 |
| `action_id` / digest | 被审阅或核验的精确操作提案。 |
| `InvocationContext.effect_key` | 宿主注入的稳定下游效果身份；下游须真正遵守幂等／查询契约。 |
| `CommandReceipt` | `command_id`、`run_id`、`kind`、`record_state`、`apply_state`、`outcome`。持久记录／应用不等于业务成功。 |

每个 Run／Action／digest／决定使用独立、稳定的控制 ID；重试同一决定时重用该 ID。不能用固定的 `approve-1` 批准后续所有动作。`Scope(workspace="default", principal="local-owner")` 来自可信宿主，不提供企业身份认证。

关闭后，按原 engine、组件、数据库重建 Runtime，再 `runtime.attach(saved_ref)`（或 `await runtime.aattach(saved_ref)`）。Attach／status／events 只观察；继续执行须显式 `await run.resume()` 或应用所需控制。`RunRef` 不包含客户端或凭据，也不是执行权威或数据库备份。

## 资源归属和错误

Agent／Runtime 使用 `async with`。独立 Agent 关闭自己创建的 Runtime；借用 Agent 的关闭只分离入口。Runtime 排空托管工作，仅 `owned=True` 才关闭 engine；`LocalEngine` 拥有 Store／Coordinator。直接注入的 Provider、客户端及其他借用组件仍由原所有者关闭；Profile Builder 可以显式拥有资源。

关闭默认 `drain`，超时为 30 秒。`aclose()` 返回 `CloseReport(state, parked, owned)`。`CloseIncomplete` 保留报告和关闭责任，应保留资源并重试 `aclose()`。`close_policy="cancel"` 提交取消并等待实际受管理工作收尾；两种策略都不证明远端写已回滚。

| 信号 | 下一步 |
| --- | --- |
| `ValidationError` | 修正 Schema、选项或不支持的组合后再试。 |
| `IdempotencyConflict` | 回放原请求，或为真正的新意图使用新命令 ID。 |
| `DefinitionMismatch` | 恢复原组件／配置发布和执行权威。 |
| `BudgetExceeded` / `AgentLimitExceeded` / `CapacityExceeded` | 查看原账本和执行／准入上限；执行 credits 不代表货币。 |
| `AuthorizationDenied` / `NotFound` | 检查可信 Scope 和原 Run／引用，不绕过执行权威。 |
| `SessionBusy` | 沿 `.run_ref` 找原 Turn；拒绝有 `.receipt`。完成原 Turn，确认 idle 后用新 ID 发起新尝试。 |
| `SessionBindingMismatch` | 恢复原绑定，或空闲时显式 rebind。 |
| `RuntimeClosed` / `ExecutionHostFailed` | 重连，或修复原宿主后显式 resume；查询不会重启执行。 |
| `snapshot.error` / 暂停状态 | 查看持久失败／pending 证据。成功返回的观察也可能描述失败的业务任务，不一定抛 SDK 异常。 |

类型化异常继承 `RalfError`，通过 `.code` 识别。CLI 错误默认以 JSON 输出到 stderr，退出码为 2。业务结果仍以 Snapshot 为准，CLI 调用成功不等于任务成功。

## CLI 查询和控制

全局选项放在子命令前：`--db` 默认为 `.ralf/runs.sqlite`，`--format` 默认为 `json`，`--format text` 输出可读视图。`--config runtime.toml` 与 `--factory module:callable` 是互斥的可信装配选择；修改／恢复命令必须保留同一数据库和原装配。

```bash
relf --version
relf --help
relf run --help
relf send-input --help
```

| `relf [全局选项]` 后的命令 | 结果／推进方式 |
| --- | --- |
| `init my-agent --template config` | 在新目录创建离线 starter，随后按其 README 运行。 |
| `run --spec agent.toml --input hello --command-id hello-1 --budget 32` | 须提供 `--config` 或 `--factory`；提交并推进到完成／暂停。JSON 输入改用 `--input-json`。 |
| `run ... --submit-only` | 返回序列化 `RunHandle`，不推进。 |
| `status RUN_ID` | 只读 JSON Snapshot；text 格式改为检查摘要。 |
| `inspect RUN_ID` | 只读发布、预算、待处理证据和操作提示。 |
| `events RUN_ID --after 0 --limit 1000` | 只读有序事件页，下一页从最后 `seq` 继续。 |
| `approve RUN_ID ACTION_ID --digest DIGEST --command-id DECISION_ID` | 记录审批回执；`--reject` 记录拒绝。随后显式 `resume RUN_ID`。 |
| `send-input RUN_ID PENDING_ID --digest DIGEST --value-json '"answer"' --command-id REPLY_ID` | 记录符合 Schema 的回复；可加 `--expected-state-revision N`，随后显式 resume。 |
| `resume RUN_ID` | 按原装配推进原 Run。 |
| `cancel RUN_ID --command-id CANCEL_ID` | 记录停止决定，不回滚效果。 |

`status`／`inspect`／`events` 直接只读本地 SQLite 权威，不导入工厂，也不是通用 Temporal 检查入口。完整 CLI 操作见[用户输入](/zh/docs/user-input/)或[快速开始](/zh/docs/quickstart/)，回归和协议命令见[测试与评估](/zh/docs/testing/)。更广的可选查询见[仓库 API 索引](repo:docs/api-reference.md)。
