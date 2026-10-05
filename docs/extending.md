# Ralf-Agent 扩展指南

版本：0.1.0.dev2；日期：2026-10-05。面向 SDK／适配器开发者。本指南描述已经运行的 Local 端口；企业适配仍按 [实现清单](implementation-status.md) 分期。

## 1. 装配组件

| 扩展点 | 注入位置 | 必须满足的约束 |
| --- | --- | --- |
| ModelProvider | `providers={name: provider}` | `identity` 非空有限 JSON；`async complete` 返回 ModelResponse；不执行工具 |
| 工具与核验 | `tools=ToolRegistry()` | 参数 Schema、效果类别、version/config、稳定幂等键；单次调用不隐藏业务重试 |
| SessionStore／AsyncSessionStore | `session_store=` | `backend_id`、read、append；CAS 与 message_id 去重同时成立 |
| LongTermMemoryStore／AsyncLongTermMemoryStore | `memory_store=` | `backend_id`、facts、put_fact；范围、版本及到期语义一致 |
| ContextBuilder | `context_assembler=` | identity 与确定性 assemble；返回实际消息和 JSON Manifest |
| ExecutionStore v1 | 第一个构造参数 | 原子命令／事务、Run CAS、事件、预算、活跃 Session 和未知效果查询；不另建调度器 |
| CoordinatorLease | `coordinator=` | 同一执行权威只允许一个持有者，活跃调用结束前不能交出归属 |
| 当前工具授权 | `policy=` | 可信宿主同步授权函数；失败抛 AuthorizationDenied，不自行提交运行状态 |

默认 `LocalEngine(SQLiteStore(path), ...)` 会创建 POSIX 文件租约和共享 SQLite 记忆。自定义存储通过端口接入，不需要 `.conn`／`.path`；同时显式注入 `coordinator`、`session_store`、`memory_store`。当前 ExecutionStore 方法是 Coordinator 线程内的同步事务操作；远程数据库需单独验证延迟、原子性和失败语义。

## 2. 远程记忆

远程后端优先使用对应的异步 Protocol，方法名称及返回结构与同步后端一致；引擎会等待返回。同步 SQLite／内存接口用于本地快速操作，不能把阻塞网络请求直接写进同步 `read/facts`。

对于已存在且线程安全的同步客户端，可显式桥接：

```python
from ralf_agent import ThreadedMemoryAdapter

# 使用者自己的后端，先通过范围/CAS/去重/TTL 契约测试。
# redis_sessions = MyRedisSessions(...)
# sql_facts = MySqlFacts(...)
# sessions = ThreadedMemoryAdapter(redis_sessions)
# facts = ThreadedMemoryAdapter(sql_facts)
# LocalEngine(..., session_store=sessions, memory_store=facts)
```

桥接器不能包装 SQLiteMemory 或原生异步后端。其底层客户端必须支持工作线程调用；客户端由使用者关闭。原生异步组件直接注入，不需要桥接。

`read(scope, session_id)` 返回 `(revision, messages)`；`append(..., expected_revision, message_id)` 使用比较交换，并在重复 message_id 时返回原提交，不同内容则冲突。会话消息、长期事实与执行状态分别存储，替换记忆不会替换审批／效果／预算日志。

`facts(scope, namespace)` 只返回当前 Scope 下未过期的已确认事实；`put_fact(..., expected_version)` 不静默覆盖其他写入。当前是全量 namespace／会话读取，下一步需要预算化 RecallQuery／分页；向量检索和来源授权尚未作为代码端口发布。Redis、PostgreSQL、向量数据库不因接口存在就被列为已支持。

## 3. 身份与不可变发布

identity／backend_id 表达端点、数据库／namespace、模型、版本及影响行为的非秘密配置。不要存入 API key、连接凭据或用户隐私。独立内存实例默认具有不同身份；人为指定同一身份时，使用者负责后端语义保持一致。

工具实例状态、partial 绑定参数、闭包和外部依赖不会自动序列化；改变它们时同步更新 `ToolSpec.version/config` 并构造新的 Registry。Provider／ContextBuilder／记忆的 identity 应反映实际当前配置。内核在恢复、异步装配后的派发、模型响应采纳及工具授权后复核固定发布。

Registry 的 Schema/config 描述是独立副本，policy 可以读取它们；修改副本不会改变登记的工具或原审批。核验历史未知效果使用原 Manifest 成本，不要求当前工具仍注册。

## 4. 存储及租约

ExecutionStore 的 `run()` 返回与底层记录分离的 JSON 快照；`save_run()` 原子比较 revision，只在成功时更新传入 revision。`command()` 的 apply、Run／事件／预算及回执在同一原子事务中提交。事务中不能 await 外部 I/O。

`session_owner()` 和 `unresolved_effect()` 必须按可信 Scope 查询当前权威事实，在同一事务内与提交保持一致。当前 SQLite 实现扫描聚合记录；企业实现需要索引、保留与数据迁移方案，这仍是后续工作。

`FileCoordinator` 使用数据库解析后的实际路径获取 OS 锁。自定义 lease 必须协调同一存储的所有使用者；只有 TTL 的 Redis 锁不满足“旧执行者仍能提交时不能交接”的约束。多进程／分布式需要执行 epoch、Worker 交接和独立能力验收。

这些是 Local 的存储与所有权端口。TemporalEngine 会以 Workflow／History 作为执行权威，需实现独立后端及相同外部契约，不能仅把 SQLiteStore 换成远程数据库就宣称支持分布式执行。

## 5. 生命周期与 CLI

Engine 成功构造后拥有 execution store 与 coordinator；`close()` 等待条件由调用者满足，活跃工具／记忆调用尚未结束时会拒绝关闭。传入的 Provider、HTTP client、session_store、memory_store 由调用者管理，Engine 不隐式关闭它们。构造失败会释放已获得租约，直接传入的 store 仍由调用者关闭。

自建 Agent 的跨进程控制使用 `--factory module:callable`。同步工厂接收 db_path，返回相同固定配置的 LocalEngine；工厂应放在可导入包中，或在仓库目录使用 `PYTHONPATH=.`。完整可运行示例见 [custom_runtime.py](../examples/custom_runtime.py)。

SDK 入口程序应导入同一个配置模块，工具实现保留稳定的包／模块名。示例入口已经这样装配；在 `__main__` 重新定义工具后，再从其他模块加载同名函数，属于不同的发布身份。

CLI 的 `status/events` 使用只读 SQLite 和默认 Scope；不载入工厂、不取得执行租约。自定义 Scope／非 SQLite 的观察可使用 SDK `engine.status/events`，独立 Read API 尚未发布。

## 6. 接入验收与升级

新的适配器至少覆盖：隔离 Scope、重启后稳定身份、CAS 冲突、重复请求去重、未知成本保留、已确认效果不重跑、取消期间不新增后续调用、晚到证据不覆盖原结果、组件变化拒绝恢复。参考 `tests/test_memory.py`、`tests/test_extension_contracts.py`、`tests/test_engine.py` 中的真实数据库和异步测试。

dev2 内核固定身份为 `local-2`，SQLite Schema 仍为 v1。dev1 的记录可以观察、取消及人工核验；继续执行须使用原版本和原配置。自动 Run 迁移尚未实现。未知效果应先在原执行日志里核验，不能通过创建新日志或新 Run 绕过恢复约束。
