# dev13 异步组件装配与资源生命周期

日期：2026-10-06。状态：dev13 已实现并完成本地验证；继续用户已授权的通用 SDK 建设。
依据：[框架能力审查](../../../architecture/reviews/2026-10-06-framework-parity.md)第 4/7 节及[公共生命周期目标](../../../architecture/viewpoints/framework-capabilities.md)。

## 目标与范围

远程模型、Redis/数据库客户端通常需要异步创建和关闭。目前 BuildContext.own 只管理同步 close，使用者必须在框架外管理客户端。本增量给现有版本化装配增加显式异步入口，保持默认同步路径、执行权威与发布身份兼容。

交付 AsyncLifecycle、显式异步组件工厂、RuntimeBuilder.abuild、BuildContext.own_async、RuntimeInstance.aclose/async with、包内 async starter 和失败/取消/事件循环测试。不交付真实 Redis/PostgreSQL 适配器、异步 ProfiledEngine、CLI 的异步运行路由或分布式权威；这些独立交付。

Python >=3.11；无新增运行依赖。包版本为 0.1.0.dev13，仍是预览；local-4、SQLite/ExecutionStore v1 和合法请求摘要不变。

## 公共接口

- `AsyncLifecycle`：`async def aclose(self) -> None`。真实清理完成后返回 None；不得把 coroutine/上下文管理器作为完成值返回。
- `ComponentRegistry.register_async(kind, name, factory, *, validator=None)`：factory 必须是 async 函数或 async callable；validator 仍同步且返回 None。名称、配置与重复注册规则共用原注册机制。
- `RuntimeBuilder.abuild(profile, db_path, *, scope=None) -> RuntimeInstance`：async 方法；同步/异步组件工厂按原顺序执行。Store/Engine 工厂和事务仍同步。同步工厂返回 awaitable 明确拒绝，不隐式等待。
- `BuildContext.own_async(resource) -> resource`：只能在 abuild 的上下文注册；resource 必须有 async aclose。同对象同模式注册去重；同对象不同关闭模式拒绝。Store 的关闭权属于 Engine，不能 own_async(Store)。
- `RuntimeInstance.aclose() -> None`、`__aenter__/__aexit__`：异步清理入口；同步默认实例同样可使用。同步 close/with 在仍拥有异步资源时提前拒绝，不能先关闭一部分后才发现需要 await。

原 BuildContext/RuntimeInstance 的导入路径保持；内部生命周期逻辑独立到 runtime_lifecycle.py。原配置声明不新增隐式标记，SDK 注入与 JSON/TOML 选择共用 Registry。

## 清理与执行权

调用方先完成或取消并 await 驱动 Task。aclose 在关闭执行器前等待框架管理的真实同步线程，Engine.close 仍验证活跃 drive/调用；不自动取消驱动，不把取消等待当成实际工作退出。

异步关闭开始后拒绝新的运行入口，已缓存的公开方法也检查实例状态。旧驱动可完成；需要取消时调用方取消自己的驱动 Task。执行未退出或 Store 关闭失败时保留原执行权，仅允许关闭重试。

Engine.close 同步完成后，按注册逆序清理附属资源。已完成的资源移除，失败的资源保留，不重新关闭已完成资源。附属客户端清理不能发起新业务操作；应用自建后台任务必须满足资源的真实完成/安全重试契约。

异步 aclose 由实例保留的 Task 执行。取消外层清理等待不会取消该 Task；再次 aclose 等待同一个在途关闭，不重复启动。若底层 Task 自身取消/失败，保留资源供幂等重试。完成值无效视为失败。并发或重入 aclose 拒绝；不隐式使用 asyncio.run、不在线程里关闭 loop-bound 客户端。

第一次 own_async 绑定正在运行的事件循环。仍有异步资源时，在其他循环 aclose 必须在关闭 Engine 前拒绝；创建循环停止前应完成清理。无异步资源的同步实例继续允许跨循环 wait_for_threads/关闭。资源全部确认完成后重复关闭不执行 I/O。

同样在 drive 等异步运行入口预检该循环，包含预先缓存的方法；不能先派发模型或预留预算，再让客户端报跨循环错误。同步只读诊断不访问异步客户端，不受该限制。

## 构造失败与取消

abuild 预检全部注册与配置，然后才创建 Store。build 遇异步工厂在创建 Store 前拒绝，提示使用 abuild。

构造失败或被取消，清理已声明 owned 的资源；未注册资源仍属工厂。candidate 如有 close，按原所有权关闭；否则关闭刚创建的 Store。清理成功后传播原 RalfError/CancelledError；其他异常使用现有 RuntimeBuildError。清理失败或等待再次取消时，RuntimeBuildError.cleanup 保留 RuntimeInstance，可 await cleanup.aclose 重试；同步句柄继续支持 cleanup.close。

## 验收

1. 默认同步 build、旧 profile/原回执、native/v1/v2/v3 恢复不变；abuild 默认可运行。
2. 同步/异步工厂、async callable、配置 validator、未知工厂在正确边界拒绝。
3. 混合资源逆序、去重、重复关闭、失败重试、无效完成值；实际 Store/租约所有权证据。
4. 活跃驱动/线程、已缓存入口、并发关闭、关闭等待取消后实际 Task 完成。
5. 原/其他事件循环、构造取消与清理失败的保留句柄。
6. 安装包内 async starter：无需网络，运行、恢复、重复命令和客户端关闭；原 starter 文件不改变。
7. 完整测试、Ruff/文档/构建、仓库外 wheel 与旧 dev12 兼容证据。此验收不代表真实远程适配器或竞品优势。
