# Temporal Profile 配置装配

dev69 提供不可变 `TemporalProfile`、JSON／TOML Catalog 和异步
`TemporalRuntimeBuilder`。它们复用组件工厂、原 TemporalRuntime 与 History；
不创建 LocalEngine、执行数据库、Coordinator 或第三套调度状态机。
本批发布验收记录见[dev69 验收](../architecture/reviews/2026-10-11-temporal-profile-assembly.md)。

## 安装与最小示例

```sh
pip install 'ralf-agent[temporal]'
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
客户端始终 borrowed；多队列／版本使用独立 Assembly。Scope 由可信宿主提供，
不是配置文件中的认证信息。Catalog 的默认别名移动不改变已固定 Profile，
`resolve(original_identity)` 只接受原版本与原摘要；本批没有多版本路由或热更新服务。

## 声明与扩展

Catalog 必须显式使用 `kind="temporal-profiles"`、`schema_version=1`、
`default={name,version}` 和 `profiles`。旧 Local Catalog 拒绝此种类；重复键、
未知字段、不兼容版本、超限和同版本冲突拒绝。

复用现有 Provider 工厂，包括离线 Echo、Chat Completions／Responses、Anthropic、Gemini。
线上协议质量仍需要单独测试。SDK endpoint、namespace、queue、授权策略与凭据由宿主
明确提供；配置远程连接只引用环境变量名称，不写密钥。

支持的组件包括 tools、session_store、memory_store、context_assembler、harness、
tool_executor、recall_policy、recall_planner、knowledge、team_strategies、planners、
plan_verifiers、verifier、limits、stage_policy；`memory_store` 接到 Facts，
`context_assembler` 接到纯 ContextBuilder。十类 `binding_components` 使用原 BindingCatalog，
包括 Provider、决策、上下文、Session、Facts、Knowledge、工具集合、Verifier、Limits、Stage。
使用原 AgentBindingDescriptor／BindingSelection 和 namespace allowlist 选择。

使用 `ComponentRegistry.register/register_async` 注册自己的工厂。工厂的
`BuildContext.store` 是 `None`，显式登记 `own/own_async` 才由 Assembly 清理；
未登记组件 borrowed。未支持的 Local 调度组件和未知工厂在构造前拒绝。
默认 Python 工具可用；业务写工具仍要求原耐久 EffectJournal，本批没有其声明工厂，
高级宿主需显式移交后装配已有写入契约，不应把写工具改标为只读。

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

应用正常退出应先等待业务 Run 和 Session 空闲，再关闭 Assembly。开始关闭后后续 Activity
可能因停止准入而失败或需要恢复；关闭不是业务 Run 全部完成、主动取消、外部效果停止或
整个部署停机的证明。SDK 停止后，运行中 Workflow 的查询仍需可处理该版本的 Worker；
服务 History 本身仍可读取。其他 Worker／历史版本由宿主治理。

只有在尚未启动 Worker、未创建 Engine、未开始关闭时才能 `detach_components()`，
取得原 Runtime 与清理句柄，并显式接管全部资源责任。移交后 Assembly 不再执行或清理；
宿主必须在真实工作停止后调用 cleanup.cleanup_async()。没有“已停止”布尔断言绕过保护。

R04/H1/H3/H5 仍未整体完成：多版本恢复路由、剩余环境角色、分布式租约、长期容量／保留、
企业 IAM、线上质量与外部开发者采用继续按能力清单验收。
