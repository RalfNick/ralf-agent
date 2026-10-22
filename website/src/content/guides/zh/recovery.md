---
title: 审批与恢复
description: 检查原操作、保存人工决定，并根据真实业务证据恢复原 Run。
locale: zh
slug: recovery
sources: [docs/recovery-guide.md, docs/getting-started.md, docs/concepts.md]
---

## 先观察原任务

以下命令在快速开始生成的项目根目录执行。保留原数据库、Scope、工厂与组件身份，把占位符替换为实际值：

```bash
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
ralf --db .ralf/runs.sqlite events RUN_ID --after 0 --limit 100
```

`inspect`、`status`、`events` 使用只读 SQLite，当前观察默认本地 Scope。查询不会重新调度任务；CLI 返回成功也不表示 Run 已完成。

| 状态 | 下一步 |
| --- | --- |
| `waiting_approval` | 核对工具、参数与操作摘要，批准或拒绝，再恢复 |
| `waiting_input` | 检查原问题／Schema／摘要，向问题所属 Run 回复，再恢复；见[持久输入](/zh/docs/user-input/) |
| `waiting_reconciliation` | 核验已派发操作的真实效果，无法确认就保持等待 |
| `queued` / `running` | 确认原执行者已停止，使用原工厂恢复；活跃租约会阻止接管 |
| `succeeded` / `failed` / `cancelled` | 查看是否仍有未知效果；终态不等于外部效果全部确定 |

## 审批绑定到原操作

进程可以在等待审批时正常关闭。新进程加载同一工厂，对原 Action 与原操作摘要作出决定：

```bash
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine approve RUN_ID ACTION_ID --digest OPERATION_DIGEST --command-id approve-001
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text resume RUN_ID
```

拒绝时在批准命令中加 `--reject`，并使用该决定自己的 `command_id`。摘要取自原 pending；批准回执表示决定已保存，恢复后才确认实际业务结果。

同一命令与相同请求可以找回原回执。网络结果不确定时重用原命令，不要直接创建新的业务写入。

## 进程重启后继续

恢复使用原数据库与匹配的配置身份。已完整接收并耐久保存的模型响应、工具观察与节点结果，会按各自的采纳边界继续。

这与“所有外部请求都不会重试”不同。模型尝试的响应若尚未被耐久收到，后续恢复仍可能创建新尝试，并产生新的供应商用量。先查看 Action 和事件，区分已保存的证据与未知结果。

`definition_mismatch` 表示当前配置或实现与原 Run 不匹配。恢复原版本与配置，而不是改默认别名去覆盖历史身份。各历史执行协议也不保证任意旧 Run 都能由当前内核续跑。

## 未知写效果先核验

超时不证明远端没有执行。写效果不明确时，使用原 `effect_key` 查询业务系统。

- 默认 Python 执行器可以调用注册的 `reconciler(arguments, context)`，返回已确认的业务 JSON；无法确认返回 `None`。
- 核验不得隐式重新执行写操作。“没查到”不自动等于“可以重写”。
- CLI 当前没有通用 `reconcile` 子命令；人工补交真实证据使用 SDK。

```python
import asyncio
from agent_app.runtime import create_engine

with create_engine(".ralf/runs.sqlite") as engine:
    # confirmed_result must come from the real business system.
    confirmed_result = {"receipt_id": "ACTUAL_RECEIPT", "applied": True}
    engine.reconcile(
        "RUN_ID", "ACTION_ID", confirmed_result,
        command_id="reconcile-001",
    )
    print(asyncio.run(engine.drive("RUN_ID")))
```

上面是操作模板。替换 Run、Action 和已核验的实际结果，不能把占位数据作为业务证据。无法确认时保持等待。框架不承诺跨系统 exactly-once。

## 取消与关闭

```bash
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine cancel RUN_ID --command-id cancel-001
```

取消停止后续调度，不撤销已经发出的业务操作。应用关闭前完成或取消并等待自己的驱动任务，等待真实线程调用结束，再关闭 Engine。不要删除租约或数据库来绕过仍然活跃的执行者。

## 按现象定位下一步

| 现象 | 先确认什么 | 下一步 |
| --- | --- | --- |
| `idempotency_conflict` | 是否复用 ID 却改变输入、定义、预算或审批决定 | 回到原请求；新意图使用新 ID |
| `definition_mismatch` | 原工厂、工具、模型、Profile 或数据身份是否改变 | 恢复原版本与配置，保留执行记录 |
| `session_busy` | 哪一轮仍占用会话 | 找到 `SessionBusy.run_ref`，处理原 Turn 并等待空闲 |
| `coordinator_busy` | 是否有同库 Engine 或实际调用仍存活 | 检查原宿主和处理器，完成正常关闭 |
| `close_incomplete` | 哪个工具、线程、连接或效果仍未收尾 | 排除故障后重试原对象的关闭，不强删租约 |
| RAG 更新后仍返回旧答案 | 是否重复原查询命令 | 原结果保持；新查询使用新命令 ID |

记录原 Run／Action、状态、事件游标、非秘密配置版本与错误码，便于重现同一个故障窗口。诊断资料不应包含密钥或敏感业务正文。

完整状态、备份与故障窗口处理见仓库[恢复指南](repo:docs/recovery-guide.md)。多轮会话详见[会话、记忆与 RAG](/zh/docs/sessions-memory/)，配置与后端选择见[运行与部署](/zh/docs/operations/)。

回复回执只记录回答，不表示业务完成。子任务的问题应从 pending 记录定位实际所属 Run；不要通过新建 Run 或 Session Turn 回答。控制返回值见 [API 与 CLI 参考](/zh/docs/api-reference/)，回归检查见[测试与评估](/zh/docs/testing/)。
