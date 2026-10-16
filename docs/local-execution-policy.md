# Local 持久执行期限

日期：2026-10-14。dev115 提供 `LocalExecutionPolicy`、Local Profile 策略声明和调用方 `deadline_at`，沿原 SQLite Run／Action 权威管理业务期限。本批最终源码、安装、冷恢复与兼容证据见[验收登记](../architecture/reviews/2026-10-14-local-deadlines.md)。dev116 已交付所选[Local 部署准入容量](deployment-admission.md)；第三阶段批次 2 仍未闭环；范围以[支持矩阵](phase3-support-matrix.md)为准。

## 策略与默认

| 字段 | 默认 | 行为 |
| --- | --- | --- |
| `version` | `"1"` | 非空版本文本，参与不可变策略身份 |
| `run_timeout_seconds` | `null` | 首次接受起的相对 Run 期限；有限正数，最多 86400 秒，拒绝 bool |
| `approval_timeout_seconds` | `null` | 首次等待审批起的相对期限；同样要求有限正数且最多 86400 秒 |

省略整个策略且未指定 `deadline_at`、未继承父期限时，保留旧提交请求、Profile、Manifest 和默认 Schema 1。显式选择 `LocalExecutionPolicy()` 仍固定策略身份并启用期限协议；两个时间字段为 `null` 表示不额外增加相对计时。策略不包含部署容量、调用者认证或费用上限，也不能代替工具授权、效果核验及真实处理器生命周期。

## SDK 与调用方时间

```python
import time
from ralf_agent import AgentSpec, LocalEngine, LocalExecutionPolicy, SQLiteStore

# providers、tools 由应用按原模型／工具端口装配。
engine = LocalEngine(
    SQLiteStore("runs.sqlite"),
    providers=providers,
    tools=tools,
    execution_policy=LocalExecutionPolicy(
        run_timeout_seconds=300,
        approval_timeout_seconds=120,
    ),
)
deadline = time.time() + 180
handle = engine.submit(
    AgentSpec("assistant", "Answer the request"),
    "task",
    command_id="task-001",
    deadline_at=deadline,
)
snapshot = await engine.drive(handle.run_id)
```

这段代码放在应用的异步入口中。`drive` 可返回审批／核验等稳定暂停状态；应用保持事件循环运行时，原 Engine 继续观察期限。退出前沿既有责任完成或取消已接受工作、排空真实线程，再关闭 Engine。

`deadline_at` 是有限正 UTC epoch 秒，拒绝 bool。过去时间可以接受并返回持久回执，但不能派发业务。有效 Run 期限取调用方时间、首次接受解析的相对时间与原父 Run 时间的最小值。Team／Dynamic 子 Run 继承原父绝对期限；并行图节点使用父 Run 的原权威，不创建另一份期限记录。

相对策略属于首次接受解析的发布；`deadline_at` 属于调用方请求身份。重试相同 `command_id` 时复用原 epoch 值，不能重新计算 `time.time() + duration`。同一请求先返回原回执，默认配置别名移动也不能重新计时；改变调用方时间属于不同请求，会产生幂等冲突。

Local Facade 的 `capabilities.deadline` 按原 Store 的可选期限能力声明；具备该能力时，stateless 提交接受 `deadline_at`，缺失能力时提前拒绝。配置的相对策略也适用于原 Session／Turn 创建的 Run，但 Session 的手动 `deadline_at` 输入不在本批新增范围。

Local Facade 同样接受 `deadline_at`：

```python
run = await runtime.create_agent(AgentSpec("assistant", "Answer")).submit(
    "task", command_id="task-001", deadline_at=deadline,
)
observation = await run.wait(wait_timeout=1)
```

`wait_timeout` 只结束本次观察；取消 `run.wait()` 的 await 也只取消观察。显式 `run.cancel(command_id=...)` 与业务期限才提出业务取消。直接取消低层 `engine.drive()` Task 保留原驱动取消语义，不能把它当作 Facade 的纯观察入口。

## JSON／TOML 与替换

Local Catalog 使用 `schema_version/default/profiles`，内置适配器为 `local-bounded`：

```json
{
  "schema_version": 1,
  "default": {"name": "governed", "version": "1"},
  "profiles": [{
    "name": "governed",
    "version": "1",
    "providers": {"default": {"adapter": "offline-echo"}},
    "components": {
      "execution_policy": {
        "adapter": "local-bounded",
        "config": {
          "run_timeout_seconds": 300,
          "approval_timeout_seconds": 120
        }
      }
    }
  }]
}
```

对应 TOML：

```toml
schema_version = 1

[default]
name = "governed"
version = "1"

[[profiles]]
name = "governed"
version = "1"

[profiles.providers.default]
adapter = "offline-echo"

[profiles.components.execution_policy]
adapter = "local-bounded"

[profiles.components.execution_policy.config]
run_timeout_seconds = 300
approval_timeout_seconds = 120
```

```python
from ralf_agent import RuntimeBuilder, load_catalog

catalog = load_catalog("runtime.toml")
builder = RuntimeBuilder(base_dir=catalog.base_dir)
instance = builder.build(catalog.default, "runs.sqlite")
```

异步组件沿原 `abuild`／`aclose` 装配；CLI 的 Catalog 入口见[配置装配](runtime-assembly.md)。Echo 仅验证入口，不证明模型业务质量。内置工厂在组件构造前校验未知字段和非法时间；Local 策略与 Temporal 的 `bounded`／`TemporalExecutionPolicy` 不互换。

应用可以注册自己的同步或异步策略工厂：

```python
from ralf_agent import ComponentRegistry, LocalExecutionPolicy

registry = ComponentRegistry()

def validate(config):
    LocalExecutionPolicy(**config)

def factory(config, context):
    return LocalExecutionPolicy(**config)

registry.register("execution_policy", "business-deadline", factory, validator=validate)
```

配置改用 `adapter="business-deadline"`。工厂必须返回具体 `LocalExecutionPolicy`；显式 `None`、字典、Temporal 策略或惰性返回值不会降级为省略声明。策略自身没有客户端；工厂附属资源仍通过 `BuildContext.own/own_async` 登记，借用资源由应用负责。修改策略使用新的 Profile 版本，原 Run 恢复时保留原策略和组件发布。

## 存储与 Schema

替换执行存储沿原 mandatory `ExecutionStore` v1，并为期限显式实现可选 `ralf_agent.ports.LocalDeadlineExecutionStore`：

```python
local_deadline_version = 1

def prepare_local_deadlines(self) -> None:
    # 在当前原接受事务内准备持久期限和旧 Reader 拒绝门槛。
    # 真实完成后返回 None；不得创建另一套调度权威。
    ...
```

Engine 固定原 Store、`backend_id` 与方法绑定。缺失、异步、generator 或其他未完成能力在期限链路使用前拒绝；代理无需暴露 SQL，但必须完成原事务责任。准备失败回滚接受，不能留下半个 Run、命令回执或预算。

SQLite 仅在显式期限的原接受事务内升级到 Schema 15，保留已有 Session／Turn 与 native history publications；构造 Engine／加载配置本身不升级 Schema。旧 Reader 对 15 明确拒绝。省略期限的默认库保留 1；已有高版本库保留其原门槛，不自动降级。不要修改 schema metadata 绕过 Reader，Schema 15 不承诺旧二进制读写或自动回退。

## 到期、暂停、晚到证据与关闭

首次审批等待在同一事务记录原 `approval_requested_at`、`approval_expires_at` 及固定摘要，审批截止被原 Run 期限上限约束。重复 drive、暂停和重启不刷新时间；字段损坏或原绑定变化明确拒绝。第一次晚批准返回持久拒绝回执；此前已批准的相同命令仍返回原回执。Run 与审批在同一时间到期时，采用 Run 的 `deadline_exceeded`。

Run 到期最终为 `cancelled/deadline_exceeded`；审批到期最终为 `failed/approval_expired`。实际工作未结束时保持 `cancelling` 和原所有权。子审批到期沿原受管理父链传播，原 child escrow 按原证据结算；未知效果或实际未结束工作继续保留义务。

Engine 的计时任务只唤醒原事务检查／取消，不保存另一份 Run 状态、不调度新业务。模型、Harness、完成策略、会话写入与后继采纳边界均复核原时间。到期不会用 `wait_for` 取消底层模型／工具 Task，也不把超时当作业务未发生。晚到模型或效果证据继续原 Action 记录与预算结算；禁止新增工具提案、后继派发或成功终态，晚到错误保留已采纳的期限原因。

宿主关闭撤销计时任务，数据库原绝对时间保留。没有运行宿主时不承诺后台计时动作；使用原 Scope、数据库、Profile 和匹配组件重启／resume 时，先检查到期，不能获得新时长。真实同步线程、delegated work 或 owned 资源未结束时，沿原 `CloseIncomplete`／Coordinator 拒绝门槛保留关闭责任；Run 的终态、预算结算和真实处理器结束分别检查。

计时宿主失败可通过 `diagnostics().workflow["local_deadlines"]["host_failure"]` 查看；Facade 等待会报告 `ExecutionHostFailed`，不能把原仍暂停状态当作期限仍正常。恢复原 Store 方法、策略／组件发布后显式 `runtime.resume(run.ref)`，原绑定重新校验，已到期 Run 按原时间处理。计时失败不允许清账、改时间、替换陌生后端或重发可能重复写入的任务。

本批恢复测试覆盖范围与最终证据见[验收登记](../architecture/reviews/2026-10-14-local-deadlines.md)。容量、托管 HTTP 管理、身份 ACL、保留清理及框架备份恢复仍按第三阶段后续门槛推进；本地重启与期限测试不能代替这些能力，也不构成真实模型质量或外部采用结论。
