# Temporal Coding 的部署准入

状态：dev120已完成所选公共Coding部署准入验收，普通v2与Coding v3边界分别保留。实际恢复、安装和原失败记录见[本批验收](../architecture/reviews/2026-10-15-temporal-deployment-coding.md)；SDK Session准入及第三阶段剩余工作见[支持矩阵](phase3-support-matrix.md)。本页不声明新增真实模型任务质量或性能SLO。

## 选择与容量

在已有 Temporal Coding Profile 上增加 `admission_policy/bounded`，或向 `TemporalRuntimeBuilder.abuild` 传入一个 `DeploymentAdmissionPolicy` 宿主参数。两处只能选一处，即使值相同也拒绝。显式 `coding_execution=True` 与公共策略共同选择 deployment v3；图、Team、Dynamic 与嵌套组合还需 `coding_composition=True`。保留 native6／binding22、composition7／binding23 的原工具授权、审批和资源约束，不手写或改动 Manifest。

Agent、顺序、所选 Agent 图、有限并行、Team、Dynamic 和有界递归的后代共享同一个原 root 槽。审批暂停、未知效果、未完成的实际调用和缺失 ACK 继续占用；零费用不意味着没有义务。Runner 的物理容量和原 Run 预算仍分别约束执行。

同一 namespace UUID 和完整部署策略使用一个固定 Registry。Registry3 支持当前 ordinary v2 与 Coding v3 共享根容量；v3 必须正向核对 Registry3。混合 Profile 应在同一 `TemporalProfileHost` 中声明，Host 在首次接受前按最大所需版本选择 Registry3，与 Profile 排列顺序无关。已有 Registry2 不会就地升级为3；恢复原任务不能换 deployment／Registry；宿主另建部署不解除原占用，也不能通过重置原 History 证明旧任务已退休。旧显式发布继续使用其匹配 Worker；不可假设 immutable dev119 客户端能连接新的 Registry3。

Scope 由可信宿主提供，不是配置文件自报的权限。部署总量跨 Scope 共享；每 Scope 上限单独应用。原命令、控制及关闭都核对 Scope、namespace UUID、首次请求／发布和实际 SDK epoch。

## 内置 Profile 与 SDK 装配

安装 `ralf-agent[temporal]`。应用提供 Temporal SDK Client、PostgreSQL 和既有 Docker 环境。以下变量是应用已核对的固定资源：`runner_root` 为当前用户拥有的0700非符号链接绝对目录；`docker_executable` 与 `docker_host` 为实际固定客户端及 Unix socket。长期恢复应使用保留的私有目录。环境准备遵循[固定环境指南](codex-coding-environment.md)与[检查指南](codex-coding-preflight.md)，不自动下载资产。

下例使用已经存在的 `postgres`、`codex-coding-postgres` 与 `bounded` 适配器。`APP_PG_DSN` 是环境变量名称，值由宿主管理，不写入 Profile。`offline-echo` 仅演示装配，不会请求 Coding 工具；它不证明原生认证、远端模型协议兼容或真实任务质量。需要显式模型连接时使用[连接指南](codex-model-connection.md)中已有的 connected-postgres 工厂，不从本例推断任何 endpoint／model 兼容。

```python
from ralf_agent import (
    AgentSpec, Scope, TemporalProfile, TemporalRuntimeBuilder,
)

scope = Scope("workspace", "operator")
profile = TemporalProfile(
    "coding-deployment", "1",
    {"default": {"adapter": "offline-echo"}},
    components={
        "effect_journal": {
            "adapter": "postgres",
            "config": {
                "dsn_env": "APP_PG_DSN",
                "backend_id": "coding-effects-v1",
                "initialize": True,
                "timeout": 10,
            },
        },
        "tools": {
            "adapter": "codex-coding-postgres",
            "config": {
                "name": "coding",
                "description": "Execute one approved contained Coding task.",
                "cost": 1,
                "runner_root": runner_root,
                "fixed_dependencies": {"deployment": "coding-effects-v1"},
                "docker_executable": docker_executable,
                "docker_host": docker_host,
                "request_timeout": 30,
            },
        },
        "admission_policy": {
            "adapter": "bounded",
            "config": {
                "deployment_id": "coding-deployment-v1",
                "max_active_root_runs": 4,
                "max_active_root_runs_per_scope": 2,
            },
        },
    },
    execution={"coding_execution": True, "coding_composition": True},
)

# 以下 await 放在应用自己的 async 入口；client 由宿主提供并保留。
assembly = await TemporalRuntimeBuilder().abuild(profile, scope=scope)
queue = "coding-deployment-v1"
await assembly.start_worker(client, task_queue=queue)
engine = assembly.create_engine(client, task_queue=queue, activity_timeout=80)
agent = AgentSpec("coder", "Handle the approved task.", tools=("coding",))
run = await engine.submit(agent, "bounded task", command_id="task-001", budget=8)
status = await engine.drive(run.run_id, wait_seconds=10)
admission = await engine.deployment_diagnostics()
print(status.state, admission["counts"]["held_root_runs_for_scope"])
```

本例的80秒是显式应用配置，不是框架吞吐或任务耗时承诺。实际工具调用仍要求原 Action 审批。应用取得审批决定后，使用 `status.pending` 中的原 `action_id`、`digest` 以及 `run_id`（缺省为根ID）调用 `engine.approve(..., command_id=稳定审批命令)`；父 Run 展示的审批可能属于后代，不能把它改投根 Run。公共控制会验证原祖先关系并固定目标 epoch，既不新增根槽也不绕过命令幂等。

JSON／TOML 使用相同的 `components.admission_policy` 和两个 `execution` 布尔字段，通过 `TemporalProfileCatalog.from_file` 加载。保持原 Catalog/Profile identity 恢复，不能因默认别名移动改写已接受任务。要让原 Profile 保持未添加准入组件的 identity，可以省略上例的该组件，改用：

```python
from ralf_agent import DeploymentAdmissionPolicy

policy = DeploymentAdmissionPolicy("coding-deployment-v1", max_active_root_runs=4)
assembly = await TemporalRuntimeBuilder().abuild(
    original_profile, scope=scope, admission_policy=policy,
)
```

这复用原 exact 策略 DTO，不是向已接受的旧 Coding History 回填新协议。自定义工厂继续使用 `ComponentRegistry` 的 `admission_policy` 槽并返回 exact `DeploymentAdmissionPolicy`。Runner journal 必须借用同一个具体 `PostgresEffectJournal`，相同 DSN 的另一对象不能替代它。多 Runner／per-Agent 绑定沿[原 Coding 装配](temporal-coding.md)和[所选编排](temporal-coding-orchestration.md)，不使用测试专用适配器。

SDK Session coordinator 与其 Turn 的部署准入尚未实现，`Runtime.from_temporal(engine)` 的 shared Session 入口继续明确拒绝；不能通过 `enable_sessions=True`、去掉元数据或直接启动 SDK child 绕过。普通受管理 Session 读写阶段与该 coordinator 能力不同。该项仍是阶段3批次2的后续必需工作。

## 首次接受、丢回复与恢复

Registry 首次接受固定原请求、Manifest、队列和 Activity timeout；重复提交先按原命令和请求找回首次信封／回执，再按原发布恢复，仍须宿主授权与实际身份核对。相同命令改变原逻辑输入仍拒绝。`CapacityExceeded` 表示新接受没有成立，可以在容量释放后用原命令重试；网络超时或丢回复不能当成该结论。

提交结果不确定时，恢复原服务、Scope、Profile／发布、queue 和 Worker，再用同一个命令和逻辑请求重试公共 `submit`。它查原 Registry／实际 SDK 执行，不另起根、换队列或更换容器。已接受但未确认启动的 claim 仍占用；SDK parent、原 first/current epoch 或 namespace UUID 不匹配会拒绝。保留原目录、PG dataset、Runner 和 Docker 物理身份；跨宿主／跨 daemon 接管未交付。

## 闭合、unknown 与原 ACK

业务结果采纳、native/container fence、原 Tool owner 结束、deployment 实际调用 end ACK、effect ACK 与 Registry 退休分别证明。一次 Activity 返回或进程消失不能代替这些证明；成功关闭组件也不等于未知业务效果已采纳。没有持久结果 candidate 的原执行不能凭物理停止重建成功结果，unknown 根及原恢复证据必须保留。

冷 Worker 死亡的有限 fence 仅适用于精确关联的原 Coding Tool Activity 第一 SDK attempt，且已有原 native owner、持久停止证明及原物理资源关联；不能推广到 Model／Context、另一 Worker 的 stop Activity 或无 owner 的调用。由固定 Worker／原 History 验证，不接受调用者自造证书或单独 PID-gone 声明。

`cancel` 回执中的 `remote_stop_confirmed=False` 表示真实后代尚未确认停止。观察超时不取消业务。已完成 Action 仅缺 effect ACK 时，恢复原 journal 路由后 `await engine.drive(run_id)` 继续原 ACK；`reconcile(..., query=True)` 查询未知效果证据，不是 ACK 重试或重发业务。已 seal 但 Registry 退休回执延后时，原 `drive` 用精确重复 seal Update 唤醒原 History；Facade 不直接释放额度，也不复活业务。

## owned close 与只读诊断

应用正常退出时调用 `await assembly.aclose(wait_timeout=30)`。它关闭新业务准入，并保留原 Worker／receiver、PG 与 Runtime，完成原 cancel/stop、实际调用和允许的清理／退休链，再关闭资源。`CloseIncomplete` 时保留同一个 Assembly、Client 和事件循环，修复原依赖后再次 `aclose`；不要先关 PG、杀 receiver 或改用另一 Assembly 假装原清理完成。期限是有界等待，不是强制终止许可。

恢复调用仍可能等待原先尚未结束的清理任务；修复依赖不会改变该任务已经产生的失败。消费这次 `CloseIncomplete` 后，可在原应用的总退出期限内再次显式关闭。每次失败继续保留原资源与未知效果；不保证修复依赖后的第一次调用就能完成，也不自动重发业务。

关闭会立即使 Assembly 创建的业务 Engine 不再接受调用，包括诊断；关闭期间需由独立的 borrowed Facade 查询相同原发布：

```python
from ralf_agent import TemporalEngine

observer = TemporalEngine(
    client, task_queue=queue, release=assembly.release, scope=scope,
)
try:
    info = await observer.deployment_diagnostics()
    held = info["held_roots"]  # 仅本 Scope；counts 同时提供部署／Scope 计数
    run_info = await observer.diagnostics(run.run_id)
finally:
    await observer.aclose()  # 只关闭该 Facade，不关闭借用的 SDK Client
```

这条路径只用于读原证据，不制造新提交或新的执行权威。`deployment_diagnostics()` 不启动缺失的 Registry／Workflow，不 query/stop 原生资源；缺失或读取失败不能转成“已退休”。原 root 不在 held 列表也不能单独证明其退休证书。真实未知效果存在时，物理资源可以关闭而额度继续 held；恢复资料仍需保留。不要删 ledger、清零保留或用 TTL/force release 释放未知义务。

Profile、组件和实现是固定发布身份。不要在运行中原位替换它们来改变权限。selected3 的原 Scope 只读证据读集在入口／出口完整检查 Runtime，中间保留固定传输、SDK身份与逐次读取；它不提供配置变更后的即时只读撤权，也不缓存可用业务权限。新的业务或原生请求仍须通过原阶段授权。

源码和安装后的实际服务、完整回归、最终默认／旧 History 兼容及 owned 清理，按本批登记逐项收口。结构化 peer 的原生提交、文件效果与实际 SDK／PG 证据不等于真实模型质量；真实 Docker 控制证据也不自动扩大该质量范围。批次2及Session后续项保持未关闭。
