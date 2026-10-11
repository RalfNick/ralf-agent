# Temporal Profile 与资源装配

状态：下一批实施设计；基线 ddb6dbb/dev68。属于已批准的 R04/H1/H5 与现有 Harness 目标；继续会话内实施，仅本地提交，不推送。

## 意图与选择

使用者以版本化 JSON/TOML 配置现有 Temporal 模型、上下文、Facts/Knowledge/Session、工具集合及十类 Agent 绑定；自定义适配器仍通过显式 ComponentRegistry 工厂注册。默认无远程依赖，显式远程配置复用现成端口。Worker 与客户端由可信宿主提供，不把连接凭据或 Scope 授权交给模型配置。

采用独立 TemporalProfile/TemporalRuntimeBuilder，复用 RuntimeProfile 数据声明、ComponentRegistry 和 BuildContext 的资源记录。没有选择构造 LocalEngine/CoordinatorLease 后换存储：Temporal History 仍是唯一执行权威。没有选择只包装配置而直接关闭工厂客户端：dev68 Context 排空不认证模型／工具／summary／write 全部停止，必须补机械实际调用责任。

完整 R01–R26、跨权威租约、企业身份、全局容量、自动进程监督、真实模型质量继续开放；该批不把所有配置或生产部署标为完成。

## 公开对象与配置

`TemporalProfile(name, version, providers, components=None, binding_components=None, execution=None)` 不可变有限 JSON，最多1MiB；复用 RuntimeProfile 的组件／绑定形状，拒绝 Local 专属 coordinator/conversation_resource/workflow_* 组件，而不是静默丢弃。

execution 仅允许严格 bool 的 enable_sessions/session_writes/composite_sessions/context_reads，默认均 False；composite_sessions 要求前两项 True，session_writes 要求实际 Session 数据声明。其他执行策略、SDK地址、Namespace、队列和凭据仍通过可信宿主明确 SDK 装配，不能偷偷变成新执行后端。

`profile.identity` 使用既有 runtime-profile kind/name/version/digest 形状，摘要包含全部 Temporal 声明与 execution。`TemporalProfileCatalog` 持久配置文档要求 `kind="temporal-profiles",schema_version=1,default={name,version},profiles=[...]`；JSON重复键、未知字段、重复版本不同内容、非法默认与超限拒绝。Local Catalog拒绝该 kind，不改已有 v1/v2 行为。

`TemporalRuntimeBuilder(registry=None, *, base_dir=None).abuild(profile, *, data_path=None, scope=None)` 创建固定组件和原 TemporalRuntime，返回 TemporalRuntimeAssembly，公开 profile/scope/release/capabilities；原 TemporalRuntime 由 Assembly 内部持有。Scope由可信宿主提供；默认仍为现有Scope默认。路径按base_dir固定。SQLite Memory显式 path；没有path时必须有data_path来形成独立数据路径，不能传 None 模拟执行Store。知识默认数据路径也固定；data_path不是执行权威文件。外置数据适配器自身内部表结构不构成 Local 调度权威。

支持现有 tools/session_store/memory_store/context_assembler/harness/tool_executor/recall_policy/recall_planner/knowledge/team_strategies/planners/plan_verifiers/verifier/limits/stage_policy：memory_store→facts，context_assembler→context_builder，其余采用原参数。十类 binding_components 使用既有角色到工厂映射和原 BindingCatalog。未支持组件、缺少所需路径和工厂在任何构造I/O前拒绝。context_execution 替换端口和其他环境角色保持显式SDK，不伪称本批已配置。

工厂在 BuildContext.store=None 下运行；不能创建 Engine、lease 或第三套 Run。own/own_async 的已登记资源由 Assembly 持有；未登记组件 borrowed。取消／构造失败在当前循环清理；关闭失败保留 RuntimeBuildError.cleanup 的可重试句柄。

原 TemporalRuntime 新增显式 runtime_profile=None 参数；None的旧Manifest逐字兼容，有值时严格验证既有身份并加入固定Manifest。选中视图继承原身份；Scope/版本/实际组件仍按原协议校验。Profile不是运行权威，复用原请求去重／Release，不改旧AgentSpec。新Catalog不能由旧Local装配器隐式执行；不声称旧Worker能执行含新增注册的发布。

## 实际资源生命周期

新增 WorkerExecutionOwner 为机械 Activity Task/明确桥接线程责任，可复用既有 ContextExecutionOwner 的实际托管逻辑，但无 History end callback、无业务状态或控制命令。原Context/Session所有者仍各自负责准确通知；本Owner不得代替它们的证据。

Assembly创建的Worker包装原已注册Activity，使用实际SDK Workflow UUID/Activity ID/attempt和固定请求摘要形成内部拥有关系；原SDKActivity上下文继承，异步客户端不搬循环。包装保留实际Activity注册名／声明；原Workflow／审批／预算／模型与工具效果协议不变。只跟踪原实际调用，不调度新Run或重试模型。

`assembly.start_worker(client, *, task_queue, **worker_options)` 托管一个原Worker；SDK client borrowed。Assembly自行持有原Worker，不在 CloseIncomplete 时自动退出SDK context。`assembly.create_engine(client, *, task_queue, **engine_options)` 使用固定Scope及发布，客户端借用；不创造执行Store。单Assembly首期一个Worker；多版本／多队列保留各自实例／原Workers，不暗改原CommandRegistry队列。

`assembly.aclose(wait_timeout=30)` 首先拒绝新装配／Worker操作和新Activity进入，保持Worker接收原结束Update；等待WorkerExecutionOwner、ContextExecutionOwner、SessionExecutionOwner实际结束，再正常关闭Worker，再逆序清理已登记资源。任一排空失败抛CloseIncomplete并保留Worker／客户端／资源／重试句柄。观察取消不取消实际清理责任；关闭不自动取消业务Run，不认证外部系统效果或整个部署无运行任务。

没有Worker的Assembly在组件尚未对外执行时可以关闭。高级宿主可在未启动Worker／未开始操作时显式 detach_components()，取得原 TemporalRuntime 和资源清理句柄，所有工厂资源的拥有关系一并移交；Assembly 此后不再创建Worker／Engine、不再关闭已移交资源。此路径与现有 borrowed SDK 合同相同，由宿主在实际执行停止后释放资源。普通入口不直接暴露可执行 runtime，避免通过裸Worker绕过自动排空；该移交不得发生在启动或关闭等待中。

模型/工具端口依然不得私下脱离托管启动未声明后台工作。取消的HTTP调用无法证明下游服务器停止／账单确定；原未知效果和预算恢复规则保留。容量仅每Assembly Owner有界，不是集群全局限额。

## 验收

1. 纯Profile/Catalog读写、不变身份、重复键／未知组件、旧Local拒绝、无SDK核心导入；默认不构造网络模型。
2. 工厂角色与源路径、十类绑定、sync/async资源、取消/失败清理、关闭重试、真实线程与全循环取消；没有LocalEngine/lease。
3. SDK实际Activity包装、模型／工具／summary／write阻塞窗口、拒绝早关、Context/Session结束通知仍可达原History；原发布审批／跨Turn／图／Team／DAG／嵌套恢复。
4. 真实Redis/PG／配置模型协议以已有工厂验收；离线Provider不作为真实智能质量。
5. 一次fresh-context整批只读review；重要问题一轮RED→GREEN；完整回归、安装/core/文档及旧68兼容；实际服务停止后只本地提交。

## 实施自查

没有配置热改运行发布、没有I/O藏入纯Harness，没有把Worker任务done当线程结束；原History业务权威不变。裸Runtime借出与关闭门禁是本批必须落实的行为契约；不以只读Context排空或文档免责声明替代实际拥有关系。
