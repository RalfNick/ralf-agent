# Temporal Profile 配置装配

dev69 提供不可变 `TemporalProfile`、JSON／TOML Catalog 和异步
`TemporalRuntimeBuilder`。它们复用组件工厂、原 TemporalRuntime 与 History；
不创建 LocalEngine、执行数据库、Coordinator 或第三套调度状态机。
dev70 增加多版本 `TemporalProfileHost`，保留原队列并按原 Run／Session 绑定重连。
最终证据见[dev70 验收](../architecture/reviews/2026-10-11-temporal-profile-host.md)，
单版本历史证据见[dev69 验收](../architecture/reviews/2026-10-11-temporal-profile-assembly.md)。

## 安装与最小示例

```sh
pip install 'relf-agent[temporal]'
python -m ralf_agent.temporal_profile_example --data-dir ./profile-demo
# 启动自己的 Temporal 后，显式指定服务地址：
python -m ralf_agent.temporal_profile_example --data-dir ./profile-demo --address localhost:7233
```

第一条示例命令仅写 TOML，不调用 SDK、网络或模型。第二条以离线 Echo 模型运行图、
两轮持久会话和原生 Session 保存。Echo 只证明接入和执行，不代表真实模型质量。
重复运行使用相同命令身份和原回执；修改已接受版本需要保留原配置用于恢复。

```python
from ralf_agent import Scope, TemporalProfileCatalog, TemporalRuntimeBuilder

catalog = TemporalProfileCatalog.from_file("./profile-demo/temporal.toml")
assembly = await TemporalRuntimeBuilder(base_dir=catalog.base_dir).abuild(
    catalog.default_profile, scope=Scope("workspace", "operator")
)
try:
    await assembly.start_worker(client, task_queue="published-version-queue")
    engine = assembly.create_engine(client, task_queue="published-version-queue")
    # Runtime.from_temporal(engine)、Agent、Session、原编排 API 继续使用。
finally:
    await assembly.aclose(wait_timeout=30)
```

`client` 是宿主提供的 Temporal SDK Client。一个 Assembly 固定一个客户端对象和队列，
客户端始终 borrowed；多队列／版本可使用下面的 Host 管理独立 Assembly。Scope 由可信宿主提供，
不是配置文件中的认证信息。Catalog 的默认别名移动不改变已固定 Profile，
`resolve(original_identity)` 只接受原版本与原摘要。配置监听、在线代码更新和部署版本迁移仍未交付。

## 多版本 Host

```sh
python -m ralf_agent.temporal_catalog_example --data-dir ./catalog-demo
python -m ralf_agent.temporal_catalog_example --data-dir ./catalog-demo --address localhost:7233
```

第一条只写两版本 JSON，不需要 SDK 或连接服务。第二条显式启动两个版本的 Worker，
切换默认版本、重连原 Run，并验证重复命令返回原回执；重复运行仍沿用相同回执。
目录参与示例 Scope 身份，恢复时保留目录、Scope、服务 namespace 和队列前缀。
它使用离线模型，证明协议行为，不代表模型质量。

```python
catalog = TemporalProfileCatalog.from_file("./catalog-demo/temporal.json")
host = await TemporalRuntimeBuilder().abuild_catalog(
    catalog, scope=Scope("workspace", "operator"), data_path="./data/runtime.sqlite"
)
try:
    await host.start_workers(client, queue_prefix="my-agent")
    runtime = host.runtime()  # borrowed Facade，固定当前默认版本
    run = await runtime.submit(definition, "task", command_id="request-1")
    original_ref = run.ref
    host.select_default(catalog.profiles[1].identity)
    attached = await host.aattach(original_ref)  # 原版本，不能跟随新默认
    # await host.aattach_session(saved_session_ref) 复用原 Session/Turn 契约
finally:
    await host.aclose(wait_timeout=30)
```

Host 在构造前固定整个 Catalog，最多32个版本；所有工厂声明在第一次 I/O 前校验。
dev71 的 `engine_options` 只接受 activity_timeout／drive_timeout，使用原 Engine 的
(0,86400] 秒规则；Host 只接受原生 int/float，拒绝 bool、非有限值与惰性数值子类。
`worker_options` 字段按已安装 SDK 的明确签名检查；client/task_queue/runtime/activity_owner/
workflows/activities 由 Host 固定。基础容量整数、bool 开关、有限 rate/ratio（Worker rate 为正，队列 rate 和 poll ratio 可为零）、nullable 字符串 identity、非负
原生 timedelta、tuner/slot 冲突与缓存/工作流 slots/polls 的约束，在服务 I/O 前校验。
显式 build_id 必须匹配全部版本；多版本通常保留原默认，不设置共用 build_id。
拒绝不会固定 Client 或启动 Task，纠正后可重试。极端整数宽度或非正规浮点 rate 仍可能由 SDK 构造拒绝。只复制选项字典，复杂 SDK 对象借用；
其语义仍由 SDK 构造校验，可能在 namespace 查询后失败，不承诺任意插件对象的无 I/O 验证。
[本批记录](../architecture/reviews/2026-10-11-temporal-startup-preflight.md)区分实际验收与剩余边界。
外部 Catalog 默认或注册变化不会改变已构造 Host。新 `runtime()` 选择当前默认，
已经取得的 Facade 仍使用原版本。`select_default` 只选择已声明且已启动的版本。
队列由 namespace UUID、可信 Scope、解析后的原 Release 与显式前缀确定；
重启必须保留原 Profile、资源身份和前缀。原 command Registry 若属于未声明队列，
启动在业务派发前明确拒绝，不能把原注册表迁到新队列。

重连先读 SDK 的原 Workflow 队列元数据，再验证原 History 的 Profile/Manifest/Scope。
普通 Facade 的重复提交、Session open、查询和 Update 也保留原 Host 身份，
并检查目标原队列／类型；不能通过返回的 Facade 重新建立对漂移配置的信任。
Session 同时验证原 Coordinator 队列、准确 SessionRef 与当前已接受绑定。
默认变化不自动 rebind；仍需空闲 Session 的明确 `rebind(expected_binding_revision=...)`。
缺失版本、未知队列或过期引用拒绝；不存在的 Workflow 返回原 SDK NOT_FOUND。
恢复需要原队列持续有相应 Worker，Host 不自动下载或恢复旧代码、迁移数据、确认外部效果。

## 声明与扩展

Catalog 必须显式使用 `kind="temporal-profiles"`、`schema_version=1`、
`default={name,version}` 和 `profiles`。旧 Local Catalog 拒绝此种类；重复键、
未知字段、不兼容版本、超限和同版本冲突拒绝。

复用现有 Provider 工厂，包括离线 Echo、Chat Completions／Responses、Anthropic、Gemini。
线上协议质量仍需要单独测试。SDK endpoint、namespace、queue、授权策略与凭据由宿主
明确提供；配置远程连接只引用环境变量名称，不写密钥。

支持的组件包括 tools、session_store、memory_store、context_assembler、harness、effect_journal、
tool_executor、recall_policy、recall_planner、knowledge、team_strategies、planners、
plan_verifiers、verifier、limits、stage_policy；`memory_store` 接到 Facts，
`context_assembler` 接到纯 ContextBuilder。十一类 `binding_components` 使用原 BindingCatalog，
包括 Provider、决策、上下文、Session、Facts、Knowledge、工具集合、Verifier、Limits、Stage、只读 Workspace。Workspace 复用已注册 tools，声明方式与 protocol1 opt-in 见[Workspace 指南](workspace.md)。
使用原 AgentBindingDescriptor／BindingSelection 和 namespace allowlist 选择。

使用 `ComponentRegistry.register/register_async` 注册自己的工厂。工厂的
`BuildContext.store` 是 `None`，显式登记 `own/own_async` 才由 Assembly 清理；
未登记组件 borrowed。未支持的 Local 调度组件和未知工厂在构造前拒绝。
默认 Python 工具可用；业务写工具仍要求原耐久 EffectJournal。Temporal 专用组件声明可使用：

```json
"effect_journal": {
  "adapter": "postgres",
  "config": {
    "dsn_env": "RALF_EFFECT_DSN",
    "backend_id": "business-effects",
    "initialize": true
  }
}
```

只引用环境变量名，后端身份固定，`initialize` 默认 false，
`timeout` 默认10秒、上限300秒。它复用原 PostgreSQL EffectJournal 与核验契约，
不是 ExecutionStore。旧 dev69 和 Local Profile 拒绝这个新声明；不应把写工具改标为只读。

SQLite Session／Facts 缺省路径需要 `abuild(data_path=...)`，分别生成独立数据文件；
显式相对路径按 base_dir 固定。自动记忆 Stage 必须声明 `memory`，可选显式 in-memory、
SQLite 或远程目标，不能依赖 Local 执行 Store 的隐式默认。
开启 `session_writes` 时装配器初始化原远程 Session 数据集身份；PostgreSQL 表初始化
仍由其显式 `initialize` 声明控制。Redis、PostgreSQL、知识与向量的工厂继续复用原数据契约。
长时间阻塞的同步自定义数据处理器必须通过明确的 ThreadedMemoryAdapter 等桥接端口托管；
异步客户端留在创建循环，不能私下派发未登记后台工作。
构建取消会取消协作式工厂，但仍持有明确桥接的实际线程。无法立即排空或清理失败时，
`RuntimeBuildError.cleanup` 保留重试责任；调用 `await error.cleanup.aclose(wait_timeout=30)`，
实际工作停止后才释放资源。并发清理明确拒绝，取消清理等待不会重复关闭同一资源。

四个 execution 开关默认全部 false：enable_sessions、session_writes、composite_sessions、
context_reads。复合 Session 要求前三项开启并有明确 host Session source；Context 读取
持有和原 end Update 见[读取生命周期](temporal-context-read-lifetime.md)。

## 关闭与恢复责任

Assembly 包装每个原 Activity，保留 SDK 注册名、参数和原 Workflow UUID／attempt／namespace。
它只托管实际调用及明确桥接线程；业务审批、预算、效果、Session 与 Context end proof
仍由原 History 和对应 Owner 管理。SDK Worker 的 hosting Task 保持存活，致命取消后拒绝新入口。
SDK 致命错误在实际 Worker 停止且 owned 资源清理完成后由 `aclose` 传出；
资源清理失败时仍可重试，不能将致命故障当成成功关闭。

`aclose` 拒绝新 Activity 和新 Facade 操作，并关闭已创建 Engine 入口，保留 Worker
处理原结束 Update；实际处理器、Context／Session 通知排空后关闭 Worker，再逆序释放
工厂资源。超时抛 `CloseIncomplete`，保留 Worker、真实处理器和重试责任；调用方取消等待
不会丢弃正在进行的启动／关闭。资源关闭失败可在原创建循环重试。
SDK Client 不由 Assembly 关闭；当前 wait_timeout 分别作用于各排空阶段，
不是整个关闭操作的总 deadline，也不限制用户自定义资源 close 的时长。

Host 管理的子 Assembly 不可独立清理共享 ledger。同一对象按相同 owned 模式登记时只关闭一次；
相互冲突的同步／异步拥有方式拒绝。Host 关闭先停止所有版本与 Facade 准入，
保留全部 Worker 处理原结束通知，等待所有实际处理器、桥接线程和 Context／Session Owner；
随后关闭全部 Worker，最后清理共享资源。一个版本排空超时不会提前释放其他版本的资源。
启动等待被取消仍保留真实启动 Task；失败后仍须 `aclose` 排空部分启动。
SDK 致命退出停止全 Host 准入，清理完后传出原错误；普通取消或关闭不是业务取消。
客户端或 Engine 配置漂移会拒绝新操作，但关闭仍在原创建循环排空原 RPC 责任；
只有真实排空后才停止 Worker 和清理资源。Session attach 若最终 status 已观察到更高绑定版本，
旧引用立即拒绝；返回的是最后校验的快照，之后其他调用方仍可显式 rebind。
借用 Facade 可先自行关闭；Host 关闭完成后必须通过仍托管原队列的新 Host 重连。

应用正常退出应先等待业务 Run 和 Session 空闲，再关闭 Assembly。开始关闭后后续 Activity
可能因停止准入而失败或需要恢复；关闭不是业务 Run 全部完成、主动取消、外部效果停止或
整个部署停机的证明。SDK 停止后，运行中 Workflow 的查询仍需可处理该版本的 Worker；
服务 History 本身仍可读取。其他 Worker／历史版本由宿主治理。

只有在尚未启动 Worker、未创建 Engine、未开始关闭时才能 `detach_components()`，
取得原 Runtime 与清理句柄，并显式接管全部资源责任。移交后 Assembly 不再执行或清理；
宿主必须在真实工作停止后调用 cleanup.cleanup_async()。没有“已停止”布尔断言绕过保护。

R04/H1/H3/H5 仍未整体完成：配置迁移、剩余环境角色、分布式租约、长期容量／保留、
企业 IAM、线上质量与外部开发者采用继续按能力清单验收。
