# 审批、重启与未知效果恢复

适用版本：0.1.0.dev9／local-4。两个接收／采纳窗口已有本地真实进程回归证据，完整 M1 验收仍未完成。恢复使用原数据库、Scope 和工厂，包括原 Harness／ToolExecutor、可选 Recall／Knowledge／planner 身份。使用 --config 时保留原 profile 声明、适配器代码及数据，见 [运行装配](runtime-assembly.md)。执行日志与业务效果证据应一起保留；取消和关闭不会撤销远端操作。

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
