# dev16 async execution handoff

用户授权继续优化；本轮原地保留既有增量，不提交/发布。目标是在保持执行权威与传输分离的前提下，让同一 A2A 接口接入本地同步控制或 Temporal 原生异步控制，并提供共享耐久交接默认实现和可安装服务模板。

## Controls boundary

新增公共 SyncTaskControls/AsyncTaskControls 结构化最小端口及 TaskControlBridge。submit/status/cancel 必须全部同步或全部原生异步，固定可信 Scope。桥接在协调线程完成同步调用，在同一循环 await 异步调用；不搬运 LocalEngine 到线程。调用前后复核 Scope/模式/绑定方法；拒绝 lazy 内层返回，核验 RunHandle/RunSnapshot/CommandReceipt 类型、JSON、请求目标/命令身份。桥接借用 Engine，不拥有关闭，不 drive。

A2AApplication 保留同步 host factory，返回一个支持任一模式的 Engine；改为 await 桥接三个控制，保持认证、wire request 身份、Inbox 完成先于回执与 wakeup 分离。调用超时或连接断开不推定远端未接受，按原 messageId 重新核验。

## Shared PostgreSQL handoff

PostgresInbox/PostgresOutbox 实现 AsyncInbox/AsyncOutbox，无继承要求。可选 postgres 依赖，连接显式拥有/借用，initialize 显式建表。按类别+workspace+principal 的事务级 advisory lock 实现跨连接/进程接收、容量和不可变完成，身份覆盖完整 message envelope。记录有 BIGSERIAL 排序，pending 有界、完成证据单调；容量每Scope最多10000（可配置1..1000000），不自动清理/删除 dedup。

Outbox flush 不跨网络保持数据库事务，只发布已提交记录，在稳定 broker 回执后完成。并发 publisher 允许 at-least-once 请求，要求 MessageBus.publish 稳定去重；崩溃后沿用相同 message_id，不生成新身份。SQL错误脱敏为 HandoffError。自定义或默认适配器需遵循完成None、有限JSON及真实耐久契约。

## Default service starter and validation

新增 a2a starter，基础模式用离线 Echo、LocalEngine、SQLiteInbox 和真实 loopback HTTP；显式 server extra。用户本机提供 bearer 环境变量（无默认令牌）；认证映射固定 host Scope，不接收请求选择身份。应用 lifespan 跟踪真实 drive Tasks，shutdown 先取消/等待/排空真实线程，再关闭 Engine 和 Inbox；宿主关闭失败不释放仍活跃的执行权。默认单个服务 worker，禁止误用多worker共享 LocalEngine。

共享部署示例使用 TemporalEngine + PostgresInbox，每个 HTTP进程借用自己的 Client/连接，共享 History/Inbox；不赋予 HTTP进程新的调度权。真实服务验证两个 HTTP进程接收同消息，恢复 Inbox 完成前进程退出，原Run/回执无重复；MQ原 publish identity/ack 契约保持。Temporal DAG/Team/RAG支持仍独立待交付。

验收：测试先RED→GREEN；第三方 sync/async控制组合、Scope漂移/内层lazy/错误DTO、真实PG双连接容量/CAS/不可变回执和真实进程丢失窗口、A2A+Temporal双进程；源码/安装 starter运行、重复请求、重启恢复、排空。原12模板/Run identity/基础依赖不变；新SDK仅增加可选和公共端口。真实模型质量不从Echo/fixture推断。
