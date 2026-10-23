# Temporal 每 Agent 执行限制 — dev61

复用公共 `AgentLimitsPolicy` / `AgentLimitProposal` / `FixedAgentLimits`。
策略是同步纯函数；可按 AgentSpec 给出不同限制，不限于固定数值适配器。

```python
from relf_agent import AgentBindingDescriptor, AgentDefinition, BindingSelection, FixedAgentLimits
from relf_agent.temporal_activities import TemporalRuntime

catalog.register("limits", "review", "1", FixedAgentLimits(max_decisions=2, max_tool_actions=1))
execution = TemporalRuntime(
    providers=providers,
    tools=tools,
    binding_catalog=catalog,
    limits=FixedAgentLimits(max_context_chars=16000, max_tool_actions=4),
)
definition = AgentDefinition(
    spec,
    AgentBindingDescriptor(limits=BindingSelection.ref("review", "1")),
)
# 原 TemporalEngine / Runtime.from_temporal 入口；高级编排使用 orchestration_release。
```

`inherit` 使用宿主策略；`ref` 叠加 Agent 策略；`disabled` 只能关闭额外 Agent 策略。
Scope 由宿主验证，limits 不接受资源 selector。有效决定数、上下文字符数取
AgentSpec、host、agent 的最小值；工具数取非空策略值的最小值。
具体合法值沿用[公共限制契约](agent-limits.md)。没有额外限制时保持旧发布身份与行为。

配置限制或注册 limits 目录时显式增加 `limits_protocol=1` 和 History 派发准入。
每 Agent 绑定沿原 `temporal-3` 路径，覆盖 Agent／顺序／Graph／Team／动态 DAG／嵌套。
宿主与 Agent 策略注册包含显式 JSON 身份、Python 方法指纹；对象和实际方法必须保持。
方法注册沿已有纯 Python 指纹规则，闭包配置必须是有限 JSON；推荐模块级定义策略并导入公共提案类型。
策略对象、方法或身份漂移被拒绝，不回退到新的宽松默认值。

## 采纳与恢复

Run 首次接受固定的是策略注册和声明。每个实际 Agent 节点第一次推进时，原 Run
History 记录 limits Activity 意图；Worker 返回原始 host/agent 提案，History 独立校验
原请求摘要、严格字段和值类型后计算交集。尚未采纳时，安全纯策略 Activity 可以重试。
采纳后原值成为 `diagnostics` 的 `limits_stages` 证据；Worker 重启和 History replay
不再次调用该节点的策略。相同定义的不同序列节点各自保存上限；嵌套选择沿固定声明子树传递。
不能在策略中调用模型、存储、网络或业务工具，异步、generator、上下文管理器及字典返回被拒绝。

既有 Context／managed 压缩／卸载／模型链路使用采纳后的字符上限。
决定数耗尽为 `decision_limit`。工具动作按当前节点累计计数，包括等待审批、已完成和
未知效果；核验和恢复同一 Action 不新增额度。新提案批次超限时全部拒绝，保留模型响应
和已发生的计费证据，不创建部分 Action，错误为 `agent_limit_exceeded`。
取消先于限制采纳时只保存迟到证据，不启动后续模型或工具。

此能力不提供父级共享工具额度、全局并发、rate limit、货币费用保证或新增执行权威。
模型 Planner 自身仍走宿主注册 Agent 槽位；不是动态选择新的 limits 组件。
声明式 Profile／工厂继续负责既有组件装配；此页使用显式 TemporalRuntime 注入，
不声称新的配置文件即可创建 Temporal 服务部署。

验收见[dev61 记录](../architecture/reviews/2026-10-11-temporal-agent-limits.md)。
