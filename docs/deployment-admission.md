# 部署内 root 准入与容量

日期：2026-10-15。Local／SQLite 已有持久部署准入，沿原命令、Run、预算和 Coordinator 管理占用，证据见[Local 验收登记](../architecture/reviews/2026-10-14-local-admission.md)。Temporal dev118 的内部 Worker SDK 门禁保留为私有 v1，只持有占位；dev119 已实现普通公共 v2 Engine／Profile、原接受信封恢复及原树校验后安全退休，冻结源码与独立安装均已通过受影响、实际服务及原版本兼容验收，见[公共验收记录](../architecture/reviews/2026-10-15-temporal-deployment-public.md)。所选 Coding 与 SDK Session coordinator 尚未接入，仍明确拒绝。当前阶段范围见[支持矩阵](phase3-support-matrix.md)，批次 2 未关闭。

## 策略与占用单位

`DeploymentAdmissionPolicy` 独立于 `LocalExecutionPolicy`／`TemporalExecutionPolicy`。它不改变后两者的期限、子调用并发或 identity：

| 字段 | 默认 | 行为 |
| --- | --- | --- |
| `deployment_id` | 必填 | 非空文本；固定在原执行数据库，不能通过配置别名或换 principal 移动 |
| `version` | `"1"` | 非空文本，参与完整不可变策略身份 |
| `max_active_root_runs` | `32` | 整个原 SQLite 数据库的 root 占用上限；exact int，1–10000，拒绝 bool |
| `max_active_root_runs_per_scope` | `null` | 可选 Scope 占用上限；同样要求 exact int，且不能超过部署上限 |

占用单位是受管理 root Run。Agent、顺序、图、Team、Dynamic 和嵌套子 Run 沿原根身份共享一个额度；模型／工具预算、每 Run 的并发与 Runner 物理容量仍分别管理。审批／输入暂停继续占用。已终态但有未知效果、未结算保留或实际工作未结束的 root 也继续占用。

一个物理 SQLite 执行数据库是一个部署容量权威。多个 Scope 共享部署总量，同时使用自己的 Scope 上限；多个 SQLite 数据库不共享额度。这里不提供队列、公平调度、TTL 逐出或强制释放。

## 可运行 SDK 示例

```python
import asyncio
from ralf_agent import (
    AgentSpec, DeploymentAdmissionPolicy, LocalEngine, ModelResponse,
    SQLiteStore, ToolRegistry,
)

class Provider:
    identity = {"kind": "application-example", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output="completed")

async def main():
    with LocalEngine(
        SQLiteStore("runs.sqlite"),
        providers={"default": Provider()},
        tools=ToolRegistry(),
        admission_policy=DeploymentAdmissionPolicy(
            "personal-assistant",
            max_active_root_runs=4,
            max_active_root_runs_per_scope=2,
        ),
    ) as engine:
        run = engine.submit(AgentSpec("assistant", "Answer"), "task", command_id="task-001")
        result = await engine.drive(run.run_id)
        admission = engine.diagnostics(run.run_id).workflow["local_admission"]
        print(result.state, admission["held"])

asyncio.run(main())
```

示例 Provider 是确定性入口演示，不是模型业务质量证据。真实应用替换 Provider／工具时沿原版本、授权、审批和效果契约装配。

`CapacityExceeded` 是瞬时拒绝：没有接受新的 Run、命令回执、预算或事件，额度安全释放后可用同一请求和 `command_id` 重试。已经接受的重复命令先返回原回执，即使部署当前满额也不重新占位。同一已接受命令改变输入或目标仍按原幂等冲突拒绝。

## Profile、JSON／TOML 与替换

Local 内置组件为 `admission_policy`，适配器为 `bounded`：

```json
{
  "schema_version": 1,
  "default": {"name": "governed", "version": "1"},
  "profiles": [{
    "name": "governed",
    "version": "1",
    "providers": {"default": {"adapter": "offline-echo"}},
    "components": {
      "admission_policy": {
        "adapter": "bounded",
        "config": {
          "deployment_id": "personal-assistant",
          "max_active_root_runs": 4,
          "max_active_root_runs_per_scope": 2
        }
      }
    }
  }]
}
```

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

[profiles.components.admission_policy]
adapter = "bounded"

[profiles.components.admission_policy.config]
deployment_id = "personal-assistant"
max_active_root_runs = 4
max_active_root_runs_per_scope = 2
```

```python
from ralf_agent import RuntimeBuilder, load_catalog

catalog = load_catalog("runtime.toml")
instance = RuntimeBuilder(base_dir=catalog.base_dir).build(catalog.default, "runs.sqlite")
```

异步组件使用 `await builder.abuild(...)`，退出使用 `await instance.aclose()`。内置字段在 Store／Provider 构造前校验。未知字段、错误类型、非法额度及 Scope 上限超过部署上限均拒绝。

注册自定义工厂时使用 `ComponentRegistry.register("admission_policy", ...)` 或 `register_async`：

```python
from ralf_agent import ComponentRegistry, DeploymentAdmissionPolicy

registry = ComponentRegistry()

def validate(config):
    DeploymentAdmissionPolicy(**config)

def factory(config, context):
    return DeploymentAdmissionPolicy(**config)

registry.register("admission_policy", "business-capacity", factory, validator=validate)
```

工厂必须返回 exact `DeploymentAdmissionPolicy`，不能返回子类、字典、`None`、执行期限策略或惰性对象。同步工厂返回 coroutine、generator 或上下文管理器也不能成为已经完成的配置。附属客户端沿 `BuildContext.own/own_async` 声明；错误装配必须完成 owned 清理，借用资源仍由应用负责。

## 原 Profile 的历史恢复

不要为了给旧 Run 增加部署治理而改写它的 Profile。Builder 提供宿主参数，允许原无准入组件的 Profile 保持完整 identity：

```python
from ralf_agent import DeploymentAdmissionPolicy, RuntimeBuilder, load_catalog

catalog = load_catalog("original-runtime.toml")
policy = DeploymentAdmissionPolicy("personal-assistant", max_active_root_runs=4)
instance = RuntimeBuilder(base_dir=catalog.base_dir).build(
    catalog.default, "original-runs.sqlite", admission_policy=policy,
)
# async 组件对应 await builder.abuild(..., admission_policy=policy)。
```

宿主参数和 Profile 的 `components.admission_policy` 只能选一个，即使两者内容相同也提前拒绝，避免隐式覆盖。宿主参数必须是 exact DTO，在资源构造前校验。

首次激活在取得原 Coordinator 后、服务新提交前，用独立原 Store 事务固定部署策略并登记仍占用的 legacy roots。旧 Run 的 Profile、Manifest、release digest 不改写，不添加新准入标记；原 Scope 可以继续恢复。legacy 占用超过新额度时，激活仍持久完成，原工作可恢复，新 root 拒绝，不能通过一次失败提交回滚治理安装。

已配置数据库要求完整原策略。省略、改部署 ID、版本或额度不能绕过占用，也不是在线修改容量的入口。新 Run 选择 `local_admission_protocol=1` 和完整策略 identity，并持久引用原 root。

## 替换执行存储

mandatory `ExecutionStore` v1 不变。选择 Local 准入的适配器另外实现 `ralf_agent.ports.LocalAdmissionExecutionStore`：

| 可选能力 | 完成返回契约 |
| --- | --- |
| `local_admission_version` | exact `1` |
| `local_capacity_policy()` | 完整 detached 策略 identity，未激活为 `None` |
| `prepare_local_capacity(policy)` | 原事务内固定策略、种入 legacy 占用；完成后返回 `None` |
| `local_capacity_acquire(scope, root_run_id)` | 原接受事务内原子占位；完成后返回 `None`，满额抛 `CapacityExceeded` |
| `local_capacity_release(scope, root_run_id)` | 原事务内检查持久树义务；返回 exact bool，False 保留占用 |
| `local_capacity_holders(scope)` | 仅此 Scope 的 detached、唯一、有界 tuple root locators |

适配器无需暴露 `conn/path`。Engine 固定原对象、backend identity 和五个方法绑定；方法／后端漂移、未完成返回和外 Scope locator 都拒绝。适配器承担原子性及真实完成责任，不能用错误布尔回执证明释放。

SQLite 在准入激活事务进入 Schema 16，保留原 Session／Turn、native publications 和期限数据。旧 dev115 Reader 必须拒绝 Schema 16。未配置库且省略准入时，默认 Profile、请求、Manifest 与 Schema 1 保持原兼容；已有高版本不降级。隐藏可选端口也不能绕过已激活数据库的原 `insert_run` 校验。不要改 schema metadata 强行使用旧 Reader。

## 释放、诊断与恢复

原终态、效果回执、预算结算及处理器实际结束分别检查。Store 要求原 root 树无持久义务，包含金额为零但仍 reserved／unknown 的预算记录；Engine 还检查原 drive、并行任务和真实线程。完成的记忆、摘要、Artifact 和 native history 写入按原回执验证，未知写入与 delegated stop 保留。`cancel`、业务期限、观察等待超时和 `close` 都不能独立腾出额度。

暂停后正常关闭保留持久 claim，重启取得原 Coordinator 也不会清除未知效果。已知效果但实际线程尚在执行时仍占位；只取消 asyncio Task 不能证明线程结束。真实工作未结束时沿原 `CloseIncomplete`／Coordinator 门槛保留 owned 关闭责任。

公开诊断通过原 SDK 查询：

```python
info = engine.diagnostics(run_id)
admission = info.workflow["local_admission"]
# root_run_id、policy、held、host_failure
```

`held=True` 表示仍占用，False 表示已释放；无法确认原绑定时为 `None` 并报告固定 `host_failure` 代码。诊断只展示本 Scope 的原身份，不暴露其他调用者的占用 ID。它不构成强制释放权限。

绑定故障先恢复原 Store 方法、后端、策略对象及匹配组件，再对原 Run 执行原恢复／核验。等待实际工作结束后，`await engine.wait_for_threads()` 会沿原事实刷新准入；新提交前也会刷新可安全释放的原 claims。未知效果需要原核验／停止证据或明确人工处置，不能删除 ledger、清零保留、重标未执行或重新派发业务。

当前不提供 force release、TTL 逐出、队列或跨 SQLite 数据库共享额度。Temporal 普通公共 v2 的安全退休由原 CommandRegistry／Run／Parent History 管理：真实 Activity 结束与持久 end ACK、原树义务闭合及 SDK 固定身份核对缺一不可，EffectJournal 不能成为另一套执行权威；私有 v1 登记或 SDK 派发证明本身仍不能释放占位。Local 与本批有限 Temporal 已交付范围不关闭第三阶段批次 2，也不代表 R21–R26、企业平台或真实模型质量已验收。

已结束验证子 Run 的父阶段可沿原 journal 退休；收到的不合法 evidence 提案仍保留，不采纳晚到 verdict。此 closed＋received 变体仅用于已安装治理的失败／取消根，旧未治理记录不新增该语义。未知验证请求、预算或实际工作未闭合时继续占位；原版本与原 Profile 恢复仍是必要条件。

## Temporal 公共 v2 的原恢复入口

已终态或已 seal 不等于额度已退休。若原 History 因 Registry 退休 RPC 不可用登记 `deployment_retirement_deferred` 后静止，先恢复原服务／Worker 路由，再调用 `await engine.drive(run_id)`。Engine 核对原 Scope、namespace UUID、Registry v2 策略、首个完整接受信封、原 SDK epoch 与原证书；已有退休记录时只读返回，否则向固定 epoch 的原 root 发送精确重复 seal payload 的新 SDK Update，唤醒原 History 重试释放。该 Update 不改变证书、不复活业务、不发送新的业务 drive command，也不由 Facade 直接退休 Registry。别名变化仍沿首个接受信封恢复；内部恢复 helper 不作为公共 API 暴露。

`drive` 可以先返回原终态，释放验证仍异步进行；用 `await engine.deployment_diagnostics()` 查看原 held／retired 根。Parent 的 `cancel` 回执中 `remote_stop_confirmed=False` 表示尚未确认真实后代停止，不能根据取消回执或父终态认定容量已释放；等待原后代及当前诊断确认结束。若 Action 已完成但 effect ACK 延后，修复原 journal 路由后用原 `drive` 继续 ACK。`reconcile(query=True)` 用于未知效果证据，不是已完成 Action 的 ACK 重试或再次执行工具。该恢复 P2 的实际失败、目标重试和最终公共矩阵通过证据见[验收登记](../architecture/reviews/2026-10-15-temporal-deployment-public.md)。本批真实零费用写／ACK 恢复窗口使用测试专用 SQLite 效果证据适配器，其他确定性用例使用默认组件，未调用 PostgreSQL；第三阶段所选 Temporal＋PG 服务组合仍需另行验收。

## Temporal 内部 Worker 的原 SDK 门禁

dev117 的[Registry 基础](../architecture/specs/temporal-deployment-admission-contract.md)继续在原 History 持有根占位。dev118 的[调度契约](../architecture/specs/temporal-deployment-dispatch-contract.md)通过内部 `TemporalRuntime(_deployment_admission_policy=policy)` 固定 exact 策略对象，发布完整策略、稳定 Registry 地址和固定源码清单。原 SDK 接受数据在 `request` 旁携带根预留及有界祖先链；原请求、命令和子投影 SHA 不改变。

Worker 核对实际 Activity Workflow ID、namespace 名称／UUID、current 与 original epoch、原 Registry held claim 和每条原 Parent 子意图。Run／Parent 先采纳该证明，才允许业务 Activity、选择、预算产生操作及 SDK 子派发。子 Run 沿原 Parent 记录继承同一根，固定 metadata 和原子 SDK epoch；注册子意图不新增 Registry 槽位。所有业务 Activity 均经过门禁，机械 carrier 在验证后还原原 handler 请求，保留 managed Context、limits、completion 和 Session 写入的原 SHA 与阶段准入。

内部所选范围覆盖普通 Agent、顺序、已注册 Agent 图、Team、Dynamic 与嵌套后代。实际源码 Service 17 项验证派发／祖先共享槽位、审批／取消保留 claim、Worker 缺席／重启、原 History 重放和身份拒绝；冻结源码受影响检查 814 项通过。独立安装与最终出处以[本批登记](../architecture/reviews/2026-10-14-temporal-deployment-dispatch.md)单独记录。省略内部策略保持默认发布兼容，旧实验发布仍须匹配其固定 Worker／源码。

上述内部参数不是公共装配入口，仍发布 v1 且不提供退休。dev119 普通公共入口使用 `TemporalRuntime(admission_policy=policy)`，或 Profile 的 `components.admission_policy`／`bounded`，再把所选 Runtime 发布传给 Engine；同步／异步工厂与 Builder 宿主策略复用原 exact DTO，宿主与 Profile 策略不能共存。公共 Engine 只接受 v2，遇到已有同地址 v1 Registry 明确拒绝，不替换或自动升级。原接受信封／回执先于当前发布检查恢复，原树物理义务闭合后由 Registry 自身 SDK 校验 Activity 幂等退休，详见[公共契约](../architecture/specs/temporal-deployment-public-contract.md)与[执行指南](temporal-execution.md)。冻结源码与独立安装各通过 953 项受影响检查、27 项公共实际服务与 17 项私有 v1 服务，零失败／错误／跳过；默认发布和原 dev118 History 重放／续接兼容通过，owned 资源已清理。所选 Coding 物理关闭及 SDK Session coordinator Turns 继续拒绝且保留为必需后续项。登记和 SDK 派发证据不能自行解除 claim，也不证明完整批次 2、阶段全量回归或新模型质量通过。随本地提交交付，不推送远端。
