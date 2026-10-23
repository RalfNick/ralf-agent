# 每 Agent 执行限制 — Local H1f / Temporal dev61

`AgentLimitsPolicy` 是纯同步扩展端口，宿主与每 Agent 选择的策略共同约束执行。
默认继续使用 `AgentSpec` 的决策次数／上下文上限和原 Run credits；没有配置策略时，
旧 Manifest 和恢复行为保持兼容。

```python
from relf_agent import FixedAgentLimits, LocalEngine

# 传入现有 store/providers/tools；这是宿主强制上限。
engine = LocalEngine(
    store,
    providers=providers,
    tools=tools,
    limits=FixedAgentLimits(
        max_decisions=4,
        max_context_chars=16000,
        max_tool_actions=3,
    ),
)
```

| 上限 | 范围 | 合法值 |
| --- | --- | --- |
| max_decisions | 当前 Agent 节点的新模型决策次数 | 整数≥1，或 None |
| max_context_chars | 准入／构建／实际模型请求的字符上限 | 整数≥256，或 None |
| max_tool_actions | 当前 Agent 节点已采纳的独立工具 Action 数量 | 整数≥0，或 None |

None 不增加额外上限；决策与上下文始终受 AgentSpec 约束。bool、浮点数和非法下限被拒绝。
有效值取 AgentSpec、宿主与所选 Agent 策略的最小值。
审批、unknown、已完成动作都占用工具动作额度；已存在 Action 的恢复／核验／重试不另占一个槽位。
这一额度不是 handler 调用次数或速率限制，也不是并发、token、时间或真实费用控制。
model_credits／工具成本／父子预算保持原契约，策略不能改变计价或授权。

## 选择与扩展

```python
from relf_agent import AgentBindingDescriptor, AgentDefinition, BindingSelection

catalog.register("limits", "business", "1", FixedAgentLimits(max_tool_actions=1))
definition = AgentDefinition(
    spec,
    AgentBindingDescriptor(limits=BindingSelection.ref("business", "1")),
)
```

`inherit` 使用宿主上限；`ref` 在宿主限制上叠加所选策略；`disabled` 只关闭额外 Agent 策略，
不能删除宿主限制、Spec 限制、预算或权限。limits 不接受资源 selector。
Local 原生、顺序、Graph／并行、Team、动态 flat/DAG 和嵌套成员均支持，
稳定成员路径沿用[绑定教程](agent-bindings.md)。每个 Agent 调用独立计数，父级预算仍约束整体消费。
直接 Tool／Transform 图节点属于 Workflow 的执行链路，不算某个 Agent 的动作。
Temporal dev61 支持宿主及每 Agent limits 策略，范围、History 采纳时机与恢复见
[Temporal 限制指南](temporal-agent-limits.md)。下文 Manifest、配置和父级固定投影说明为 Local 契约。

```python
from relf_agent import AgentLimitProposal


class MyLimits:
    identity = {"kind": "my-agent-limits", "version": "1"}

    def propose(self, spec):
        return AgentLimitProposal(max_decisions=2 if spec.name == "reviewer" else 4)
```

策略接收脱离共享状态的 AgentSpec，必须同步、确定性地返回具体 `AgentLimitProposal`。
不能执行模型／存储／网络 I/O，也不能修改共享定义、工具、Schema、身份或权限。
async／generator／上下文管理器／字典返回被拒绝；实际调用对象身份变化也会阻止采纳。
纯策略的结果在首次接受时固定，执行读取 Manifest 中的 caps，重新检查配置不会更新旧上限。
不确定性策略或缺失原版本会被拒绝，不能让审批续接悄悄换成宽松配置。
并行节点读取父 Run 已接受的上限；Team／动态规划的子 Run 也必须与父级固定的成员
上限一致，包含模型 Planner、绑定与嵌套成员。首次创建子 Run 和后续恢复都会检查，
不能借重新调用策略接受更宽松的配置；漂移按 `definition_mismatch` 拒绝。

## 声明式配置

默认适配器名为 `fixed`；JSON 对应 `components.limits` 和 `binding_components`。

```toml
schema_version = 2
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.limits]
adapter = "fixed"
[profiles.components.limits.config]
max_decisions = 4
max_tool_actions = 3
[[profiles.binding_components]]
role = "limits"
component_id = "business"
version = "1"
[profiles.binding_components.component]
adapter = "fixed"
[profiles.binding_components.component.config]
max_tool_actions = 1
```

自定义适配器用 `ComponentRegistry.register("limits", ...)` 或 `register_async` 装配；
异步工厂不意味着策略可以异步执行。资源 owned/borrowed 和关闭责任沿用 BuildContext。

## 证据与超限

`diagnostics(...).manifest` 的 `agent_limits` 保存策略身份和每个原有效 Agent step 的摘要／caps。
显式 limits 选择使用 `local-bindings-6`；旧 wheel 会拒绝新的发布，原旧任务继续按旧发布恢复。
工具批次超过余量时，模型响应仍保留，但整个批次不生成可执行 Action，Run 以
`agent_limit_exceeded` 失败。决策和上下文超限沿用既有 `validation_error`；预算不足为 `budget_exceeded`。
已经发生的工具效果不会回滚，也不能通过重提相同命令、改默认配置或重新审批绕过原限制。

此增量没有交付全局并发、工作区共享额度、分布式容量、Local deadline 或自动清理。
