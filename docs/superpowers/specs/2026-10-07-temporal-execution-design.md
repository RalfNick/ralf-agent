# dev15 Temporal 独立执行后端

分布式参考后端使用真正 Temporal Service/Workflow/Activities；Workflow History 是命令、状态、决策、预算与终态权威。不得在 Activity 内运行 LocalEngine/SQLiteRun 来伪装分布式，也不把 Redis 消费组/TTL 锁当执行权。第一支持矩阵明确原生 Agent 与顺序 Workflow；其他定义在创建 Workflow 前拒绝，未来按共同契约扩展。

网络控制需要新增独立 AsyncExecutionEngine 端口，submit/status/events/approve/cancel/reconcile/diagnostics/drive 均异步；旧同步 ExecutionEngine 不变。TemporalEngine facade 绑定 namespace/task_queue/Scope/固定运行发布；可选 temporalio 依赖，不影响基础安装。Worker 装配显式 Provider/ToolRegistry/Policy/ToolExecutor，注册版本固定，变更应换队列/发布并拒绝不匹配。

Workflow 确定性更新并保存 CommandReceipt、单调状态/事件、Action 身份、credits、审批摘要及未知效果。命令先进入 History，再由 Workflow 应用；Update 接受不冒充业务完成。submit 的 command identity 固定 Workflow ID，重复同摘要原 Run，不同摘要冲突；提交与控制均 scope 隔离，终态不重开。原始调用请求与首次固定 Release 分离。

模型/工具/核验在 Activity；Activity 最大尝试1，不自动盲重做未知写。每次派发先预留额度/保存意图；正常 ActivityCompleted 证据沿 History 采纳。失败/超时/Worker 丢失保持原 Action/effect_key 与未知额度。PostgresEffectJournal 可独立记录真实业务工具的 received 观察与跨 Run 未核验写保护，不参与 Run 状态/计划推进。工具必须重新核验固定 Manifest、Schema、同步 None-return Policy，并由稳定 InvocationContext 派发。

取消是 Workflow 更新，先停止后续调度，晚到观察仍记录/结算、不覆盖终态。业务终态与真实远端停止分别说明；不能因 Activity 超时推断 handler/外部请求已结束。核验恢复使用固定动作身份，明确人工 evidence 与 queryable 核验，不以新 Workflow ID绕过未知效果。

真实验收：两个独立 Worker 进程；审批后 Worker 中断与重启、提交/审批/取消去重冲突、Activity业务提交后丢失响应、原键核验、一条业务写、取消竞争、History Replay 与版本拒绝。仅 Mock/时间跳跃不算服务验收。最小探针每例20次按 M1协议，完整企业分布式规模/部署/认证/History保留仍单独验收。
