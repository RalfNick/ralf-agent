# Local 持久期限契约

第三阶段批次 2 的期限部分沿原 SQLite Run／Action 权威实施，容量准入继续作为同批次的下一交付，不因此关闭批次 2 或 R21。宿主、编排和数据范围沿 `docs/phase3-support-matrix.md`。

## 接口与默认

`LocalExecutionPolicy(version="1", run_timeout_seconds=None, approval_timeout_seconds=None)` 是不可变值；相对秒数须为有限正数且不超过 86400，拒绝 bool。`LocalEngine(execution_policy=policy)` 和 Local Profile 的 `components.execution_policy={adapter:"local-bounded",config:{...}}` 选择原策略。默认省略保持旧 Profile、Manifest、提交请求与 Schema 字节。

`LocalEngine.submit(..., deadline_at=None)` 接受有限正 UTC epoch 秒，拒绝 bool；显式过去时间允许接受但不能派发业务。省略不增加请求字段。Facade 沿原受管理提交传递该字段；观察 wait 超时与取消仍只结束观察。相对策略属于首次解析的发布，调用方 deadline_at 属于请求身份，重复 command 先返回原回执，不重新计时。

## 原接受与持久事实

首次接受事务创建原 Run、预算、事件、策略发布及 `local_deadlines` 事实：协议版本、accepted_at、requested_deadline_at、run_expires_at、parent_run_expires_at。有效期限取已选择相对期限、显式时间与原父期限的最小值。Team／Dynamic 和普通／图接受路径共用采纳函数；根时间不能由子提交重置。

Manifest 显式记录 `local_deadline_protocol=1` 与已配置 Local 策略 identity（只有调用方时间／继承父时间时为 null）。原 `_check_release` 重建这些扩展后要求完整发布相等；不得由当前配置覆盖原策略。保持已有 Coding／绑定 kernel，扩展字段与 opt-in Schema 15 拒绝旧 Reader。历史已接受的无期限 Run 不获得新的期限。

可选公开 `LocalDeadlineExecutionStore` 为 `local_deadline_version=1` 和同步 `prepare_local_deadlines()->None`；mandatory ExecutionStore v1 不变。方法绑定、原 Store 与 backend_id 固定。显式启用在业务 I/O 前拒绝缺失／惰性能力；准备只在原接受事务内执行，失败回滚全部接受状态。SQLite Schema 15 保留 native publications 和 Session/Turn，默认仍为 Schema 1。

## 审批、计时与业务边界

第一次将 ToolAction 持久化为 waiting_approval 时，在同一事务写 approval_requested_at／approval_expires_at 与原时间摘要，恢复和审批采纳均校验有限类型、摘要与原策略公式。审批时间取其相对期限与 Run 期限的较早值；重复 drive 与重启不刷新。审批命令先查原回执，再在 apply 内复核原时间；第一次晚到审批返回持久拒绝回执，不能写 ready。

Engine 对开始／恢复 drive、开始业务派发、推进下一步和最终完成执行期限 checkpoint。活跃 drive 与暂停 Run 使用原 Engine 所有的纯计时任务；计时任务只能调用原事务采纳期限／取消，不能自己保存结果或调度业务。暂停后仍在同一宿主事件循环计时；宿主关闭撤销计时任务，保留数据库绝对时间，原配置 resume 时先处理到期。无可运行宿主期间不承诺后台执行；重启不能得到新时长。计时任务失效不改写业务终态；通过原 Run 及创建时固定的祖先宿主 locator 提供 `workflow.local_deadlines.host_failure` 与 Facade `ExecutionHostFailed`。回调不得查询已变化的 Store 来寻找父级；resume 复核原发布与恢复绑定后才能清除诊断。

到期复用原 cancel 和后代传播。Run 期限的最终状态为 cancelled／deadline_exceeded；审批期限最终 failed／approval_expired。实际 handler 未结束时保持 cancelling／原操作所有权，既有后代及 Coding stop 门槛仍生效。不得用 wait_for 取消底层模型／工具 Task；保留原 `_inflight`、真实线程 tracker、预算和 unknown。并行图由原父 Engine 管理期限，节点 frame 不创建另一套期限权威。

晚到模型／效果回执继续原记录与结算，禁止采纳新工具提案、后继或成功终态；晚到错误不能覆盖已采纳的 deadline 原因。到期不等于效果未发生或实际进程已经结束。owned 关闭遵循实际排空和 Coordinator 门槛；未知效果不允许危险重试。

## 本批验收

SDK／JSON／TOML／替换、默认字节、Schema 1 与原 14→15、只读及旧 Reader 拒绝；真实进程冷恢复审批期限；活跃异步模型与真实同步线程；晚到成功／失败与预算；顺序／串并行图／Team／动态／嵌套；Facade 纯观察与 owned 关闭；原 Store 代理不暴露 SQL。源码、固定 wheel 安装及匹配版本恢复分别登记，模型夹具不替代真实模型质量。
