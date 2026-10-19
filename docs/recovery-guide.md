# 审批、重启与未知效果恢复

本指南介绍当前 Local／SQLite 的基本观察、审批与恢复；各历史版本必须遵守其原执行协议，不保证任意旧 Run 都可由当前内核续跑。完整阶段验收状态见[实现清单](implementation-status.md)。恢复使用原数据库、Scope 和工厂，包括原 Harness／ToolExecutor、可选 Recall／Knowledge／planner 身份。使用 --config 时保留原 Profile 声明、适配器代码及数据，见[运行装配](runtime-assembly.md)；Temporal 使用其[独立执行指南](temporal-execution.md)。执行日志与业务效果证据应一起保留；取消和关闭不会撤销远端操作。

## 按现象定位下一步

CLI／示例会收敛输出公开错误码，避免泄露服务异常、凭据或业务正文。下面区分异常、等待结果和业务状态；它们不是同一种失败。

| 看到的结果 | 含义与下一步 |
| --- | --- |
| `validation_error` | 先核对必需参数、Schema 和扩展方法模式。真实模型必须显式选择 provider／model；异步专用端口使用 `async def` 或 `async __call__`，同步函数返回 coroutine 会被拒绝。按[扩展指南](extending.md#先选择扩展方式)检查当前支持入口 |
| `idempotency_conflict` | 同一 command_id 对应了不同请求。恢复时找回原输入、定义、budget 和 Session；确定是新任务时才使用新命令，不改旧回执 |
| `definition_mismatch` | 当前组件／Profile／来源与原 Run 不符。先观察原任务，再恢复原匹配配置和实现；模型别名、namespace 或新默认不能替代历史发布 |
| `session_busy` | 使用 SDK 异常 `SessionBusy.run_ref` 找回占用的原 Turn，先完成审批／核验；不用新 Run 绕过占用 |
| `session_binding_mismatch` | 当前 Session 绑定或引用不匹配，先恢复原绑定／引用；需要新绑定时按[Session API](session-api.md)在 idle 后显式 rebind。此错误本身不代表已有 Turn 占用 |
| `execution_host_failed` | 托管 drive 或期限观察器停止。保留原 Run；修复宿主后显式 resume。存储恢复、再次 wait 或查询状态不会自动重启执行 |
| `coordinator_busy`／`close_incomplete` | 原执行者或实际处理器仍有责任。检查原宿主与未完成调用，对原 Runtime 重试关闭；不要删除锁文件或强行释放租约 |
| `provider_error`／`memory_backend_error` | 检查原服务连接、授权、协议及后端可用性，保留原 command／Action。超时不证明下游未接受请求，避免以新命令重复业务写入 |
| `wait_reason=observation_timeout` | 只结束此次观察。用原 Run 继续查询／等待；只有显式 cancel 或业务期限才申请取消业务 |
| `waiting_approval`／`waiting_reconciliation` | 分别检查原审批内容或实际业务效果，按下文处理；等待本身不表示框架出错 |

排障记录保留包版本、绝对数据目录、Run／Action ID、command_id 和错误码。凭据留在环境或宿主管理中；不要把 API key、DSN 密码和完整客户上下文放进 issue、截图或恢复命令。

## 先观察，再继续

对生成项目，在项目根目录运行；这里 `RUN_ID` 为实际运行 ID：

```bash
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
ralf --db .ralf/runs.sqlite events RUN_ID --after 0 --limit 100
```

`inspect/status/events` 使用只读 SQLite，当前只观察默认本地 Scope。自定义 Scope／非 SQLite 存储需要使用原 SDK 配置；独立通用 Read API 尚未发布。观察命令不创建不存在的数据库，也不运行工厂代码。

| 状态 | 处理方式 |
| --- | --- |
| queued / running | 确认原执行者已经停止后，用原工厂 resume；另一个 Coordinator 仍占有租约时会拒绝接管 |
| waiting_approval | 核对 pending 的工具、参数和摘要，批准／拒绝；批准后 resume |
| waiting_reconciliation | 核验已派发尝试的实际效果；无法确认时保持等待 |
| failed，error 为 budget_exceeded | 当前额度无法支持下一次尝试；本版本没有 CLI 增加预算命令，终态不因恢复重新打开 |
| cancelling | 等待已派发调用结束；保留效果证据，再检查是否需要核验 |
| succeeded / failed / cancelled | 检查 actions 中是否仍有 outcome_unknown；Run 终态不代表所有外部效果已确定 |

`inspect` 的建议描述下一步；读取成功或 CLI 退出码 0 不代表 Run 已成功完成，应以 `state/result/error` 为准。

使用 Profile 配置时，观察命令不需要先装配模型；即使当前配置文件不可用，仍可用同一绝对 `--db` 执行 `status/inspect/events`。继续执行则必须恢复原 Run 对应的 Profile 和组件，不能拿新默认替代缺失的旧版本。示例：

```bash
ralf --db /ABSOLUTE/PATH/runs.sqlite --format text inspect RUN_ID
ralf --db /ABSOLUTE/PATH/runs.sqlite --config /ABSOLUTE/PATH/runtime.toml resume RUN_ID
```

持久 Session／Turn 的观察超时、忙碌状态及恢复见[Session 指南](session-api.md)；显式用户提问使用[原问题的输入控制](user-input.md)回答，重新提交一个任务不能代替回答原问题。

recorded_evidence 表示已收到、已耐久保存但尚未采纳的模型响应或工具观察，unresolved_effects 表示仍未确认的写。前者恢复时使用原证据，不重新调用原请求；后续活跃步骤可以继续执行。终态 Run 也可以采纳保存的证据与结算费用，终态保持不变。not_dispatched 则是本次调用在实际开始前被拒绝；它不抹掉历史 Attempt 的未知效果或额度。

## 持久审批与重复命令

进程在 `waiting_approval` 时可以正常关闭。新进程加载同一个工厂，针对原 Action 作出决定：

```bash
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine approve RUN_ID ACTION_ID --digest OPERATION_DIGEST --command-id approve-001
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

拒绝使用同一命令加 `--reject`，并使用该决定自己的 command_id。审批摘要必须来自原 pending；审批 `applied` 仅确认决定消费，恢复后才能知道业务结果。

同一个 Scope 内，相同 command_id 和请求内容返回原回执，内容改变则 `idempotency_conflict`。submit 身份由 definition、input、budget 和 session_id 决定；当前配置别名移动后重复请求仍返回最初 Run，但恢复仍要满足该 Run 的固定 Release。客户端网络或终端结果不确定时，重复原命令，不要直接生成新命令和新业务任务。

## 已收到证据先采纳；未知写效果先核验

工具派发前保存效果意图。收到完整模型响应后，先在独立事务保存 received_response，记录 model_response_recorded，Action 为 response_received；恢复调用原 Harness.propose 并验收，不重新问模型。DecisionCommit 后继续使用原稳定工具提案。

handler／执行器自动核验返回确认结果后，先独立保存 effect_observation，记录 tool_receipt_recorded，Action 为 receipt_received；恢复提交原 Action 的结果，不重新执行 handler 或 query。模型已知 credits 在接收时结算，工具 credits 在结果采纳时结算。

若业务已提交，但本地效果观察尚未保存，Action 仍可能 outcome_unknown；独立回执阶段不能追回未收到的响应。取消后已保存证据仍需结算与采纳，但不创建新提案／派发，不重新打开终态。操作员 reconcile 的人工结果仍与命令去重及 ResultCommit 共用同一原子事务，没有额外自动执行器接收窗口。实现与故障验证状态见 [组件指南](execution-components.md)。

恢复通过 `ToolExecutor.reconcile(envelope)` 按原 effect_key 查询业务记录，返回 EffectObservation，无法确定时返回 None。默认 PythonToolExecutor 转发 Registry 中的 `reconciler(arguments, context)`，该函数返回已确认结果的 JSON 或未知 None；自定义执行器可以独立提供查询，不要求重复注册 Python 核验函数。核验不应隐式重做写操作。缺少核验能力的未知写保持等待，相同工具／参数的未解决写也会阻止新的 Run 重新派发。

M1 尚未实现“已证明未执行／仍在处理中”的丰富核验结果。没有“未查到”就能安全重写的通用保证，也没有跨系统 exactly-once 保证。

若等待来自尚未耐久收到响应的模型尝试，下一次 resume 当前仍会发起新的模型 Attempt，旧未知额度继续占用；这可能产生新的供应商用量。先检查事件和 Action，区别于 response_received 或已经采纳的决策；显式可配置的未知模型重试策略仍待交付。`reconcile()` 仅确认工具效果，不能用于补交模型响应。

### 本地所有者提交人工核验证据

CLI 尚无 `reconcile` 子命令，使用 SDK，并加载原可信配置工厂：

```python
import asyncio
from agent_app.runtime import create_engine

with create_engine(".ralf/runs.sqlite") as engine:
    snapshot = engine.status("RUN_ID")
    # 先在原业务系统核对 Action 的 effect_key；不要猜测执行结果。
    unknown = next(
        action
        for action in snapshot.actions
        if action["kind"] == "tool" and action["status"] == "outcome_unknown"
    )
    confirmed_result = {"receipt_id": "ACTUAL_BUSINESS_RECEIPT", "applied": True}
    receipt = engine.reconcile(
        snapshot.run_id,
        unknown["id"],
        confirmed_result,
        command_id="reconcile-001",
    )
    print(receipt)
    print(asyncio.run(engine.drive(snapshot.run_id)))
```

此片段中的结果是占位示例，必须替换为原工具实际返回且已核实的业务 JSON。多个未知 Action 应逐一确认对应的业务凭据。Run 已经终止时，reconcile 仍可补充未知效果，但不重新打开终态或重新调度。

## 取消与服务关闭

取消是停止后续工作：

```bash
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine cancel RUN_ID --command-id cancel-001
```

同步 handler 的执行线程不能被 asyncio 强制停止。取消调用方 Task、取消整个事件循环或关闭循环，都不代表实际线程已退出；框架管理的工具、核验和 ThreadedMemoryAdapter 调用会继续持有执行归属。

自行管理服务的推荐顺序：停止接收请求；完成或取消并 await 自己的 drive Task；`await engine.wait_for_threads()`；最后 `engine.close()`。等待线程不会自动取消 Task。即使线程已结束，未采纳的业务回执仍需核验。使用者自己创建的后台线程／异步适配器内部线程必须自行满足真实完成契约。

Store 关闭失败会保留租约、停止旧 Engine 的其他操作；修正组件问题后重试 `close()`。存储已关闭但释放租约失败时，重试只释放租约。不要让新的 Engine 绕过旧持有者锁继续写。

## 默认本地项目的手工备份演练

以下仅适用于首用教程生成的默认离线 `oncall` 项目，POSIX 宿主与原版本工厂。先停止接收新请求，关闭并等待所有原进程／实际 handler 结束；备份及恢复期间不再运行任务。先在可丢弃的测试项目演练，保留原项目代码、安装包和配置。此流程不是在线多库事务备份、跨主机迁移或第三阶段 P3-5 的完整验收。

默认项目的会话／Facts 与执行事实共用 `runs.sqlite`，本地测试业务效果另存于 `runs.sqlite.business.sqlite`。在项目根目录执行以下 Python；目标目录必须不存在，并放在 `.ralf` 外。原工厂取得 Coordinator 后只做备份，不调用 `submit/drive`；其他执行者仍占有租约时拒绝。使用 SQLite backup API 读取包括 WAL 中已提交的数据，不能只复制仍在使用的主文件。

```python
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from agent_app.runtime import create_engine

db = Path(".ralf/runs.sqlite").resolve()
backup = Path("private-backup-001").resolve()
backup.mkdir(mode=0o700)  # 已有目录拒绝；失败／未完成的目录不能用于恢复。


def save(connection, target):
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(target)) as destination:
        connection.backup(destination)
        if destination.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError("Backup integrity check failed")


business = Path(str(db) + ".business.sqlite")
for source_path in (db, business):
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
with create_engine(str(db)) as engine:
    save(engine.store.conn, backup / db.name)
    with closing(sqlite3.connect(business.as_uri() + "?mode=ro", uri=True)) as source:
        save(source, backup / business.name)
print("Both databases backed up:", backup)
```

恢复须保持原绝对路径、Scope、代码和配置。确认所有原进程已退出后，保留整个旧 `.ralf` 目录供调查，再把两个备份数据库放回原 `.ralf` 路径的新空目录；不要把旧 WAL／SHM 混入恢复目录，不使用硬链接，不在原执行者仍活跃时移动数据库或锁文件。先 `inspect`，再按原 Action／digest 批准或核验并 `resume`。恢复目录不同会改变后端和业务服务身份，备份副本可只读观察，不能当成第二个可同时执行的部署。

这两个数据库仅覆盖默认本地示例。替换 Session/Facts、知识库、Artifact、Workspace 或真实业务服务后，必须另行保留其数据、原身份及一致性责任。尤其不能用旧业务备份覆盖备份后已发生的真实效果；外部系统仍以实际记录为准，缺失本地回执时使用原 effect_key 核验，不能凭旧快照重做写。保留 unknown、原额度及效果证据；完整框架备份、升级与恢复管理仍按[阶段矩阵](phase3-support-matrix.md)验收。

## 常见拒绝及升级

| 错误 code | 检查方向 |
| --- | --- |
| coordinator_busy | 同一数据库是否还有 Engine、drive 或未结束的真实线程；先完成其关闭 |
| definition_mismatch | 原内核版本、工具模块、version/config、Provider、Harness、ToolExecutor、记忆 backend_id 或 ContextBuilder 是否改变；恢复原版本／配置 |
| idempotency_conflict | 是否复用了命令 ID，但改变定义／输入／预算／Session／审批决定 |
| authorization_denied | 原 Scope 或宿主 policy 是否拒绝该操作；审批不能代替授权 |
| validation_error | 参数／输出 Schema、policy 返回值、CAS 或生命周期是否违反契约 |

整数 credits 的未知预留保持占用；缺失 Token 用量不会被认定为零。credits 不是供应商费用或外部调用硬限制。

dev6 使用 `local-4`，dev3–dev5 的 local-3 Run 不能由新内核默认续跑，需原版本和原配置；观察、取消与人工核验仍可进行。SQLite Schema v1、dev3 起调用方摘要保持不变，重复原请求仍能找回旧 Run／回执，但不能据此绕过版本检查。dev1／dev2 的旧 submit 重放需原版本。自动迁移尚未实现，详情见 [扩展指南](extending.md)。

dev7 未启用 Recall／Knowledge 时保留 dev6 默认 Manifest，可用原配置继续。新知识任务恢复也必须保留原知识库与检索器。未知模型 Attempt 重试沿用保存的引用和快照；原知识删除／改版／过期或事实变更将阻止新派发，原未知预算仍保留。已有独立 received_response 时直接采纳，不重取来源。来源校验不把旧快照当成当前有效知识，也不追回已经发送的内容。具体接入见 [召回与 RAG](recall-and-rag.md)。
