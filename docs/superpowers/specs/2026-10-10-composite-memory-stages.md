# H3 Local 高级编排的受管理长期记忆

## 用户目标与范围

继续既有能力清单 R15／H3，默认组合与自定义 Agent 能力应能在图、Team、动态 DAG 和嵌套编排中工作。本轮将现有规则／模型字段选择记忆阶段扩展到 Local 高级编排的实际 Agent；纯 Planner、Transform、Tool 节点和父路由不隐式提炼事实；显式代理化 Planner 按其已固定的 Agent 策略与额度执行。Temporal 写阶段留作后续独立 History 增量，不将 Local 执行库视为分布式执行权威。

## 架构

复用 ManagedMemoryPolicy／ManagedModelMemoryPolicy、原来源／提案／意图／回执协议、原执行额度及宿主授权的写后端。串行图使用原 Run 节点；并行 Agent 使用原 Run 内的 execution 投影，不另建任务、调度器或日志权威。Team／动态／嵌套使用已有真实子 Run。

并行记录必须固定 workflow_node，并与 NodeEngine 的原节点对应；同一根 Run 下两个逻辑 node=0 的帧，其事实键不可碰撞。模型只选宿主 allowlist 字段，事实值来自已采纳完成结果；来源、Policy、Provider 和写目标在每次 await 后复核。现有原生／顺序策略类与已接受记忆键、额度、发布身份保持。

## 持久化与生命周期

高级记忆准入显式要求 ExecutionStore 的 composite_memory_stage_version=1 和同步 prepare_composite_memory_stages()，在原接受事务启用 Schema12；dev44 及以前代码明确拒绝。普通原生／顺序仍启用原 Schema7/9；无新能力的原库不升级。

独立预算证据属于原根 Run；并行节点的事实／selector 预留不能串扰。阶段失败不凭空宣称业务失败；未知写入保留额度，父子额度只有子 Run 已无 held 额度与活跃处理器时才结算。

memory_stages 纯查询验证原来源、记录与独立预算，对并行记录附 workflow_node，不读取真实记忆后端。整个 execution 投影丢失但原 Action 留有记忆 marker 时拒绝恢复／查询。

成功、取消或失败后显式恢复只检查已派发事实和采纳已持久回执，不新增 CAS 或 selector 模型。未派发事实跳过；未知且无准确事实证据继续保留。父级查询不自动遍历真实子 Run；显式根 resume 可沿已固定的原父子归属恢复已结束、未结算且无活跃操作的子 Run，使用子 Run 原 drive 锁与终态协议，再结算父额度。借用写后端由宿主关闭。

## 验收

规则／模型选择 × 串行图／并行图／Team／动态 flat/DAG／嵌套执行；同名字段的并行事实和预算隔离；每成员绑定不同宿主授权 target／namespace。内存与 SQLite 后端、sync/async 工厂、推荐 managed-memory 统一入口与重启均验证。

真实进程在来源、selector 响应、CAS 提交、准确回执和阶段完成窗口退出，重启不重复已确认模型或 CAS。未知写、取消、缺失／篡改来源／投影、写目标漂移和不足额度有拒绝或保留证据。实际 dev44↔dev45 wheel 原生／顺序审批与记忆兼容；旧 wheel 拒绝 Schema12。

更新能力矩阵、教程、版本和审查记录，完整回归／静态与格式检查、构建安装后本地提交，不推送；本轮不用真实模型成绩代替协议证据。
