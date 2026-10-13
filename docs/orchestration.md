# 动态规划与多 Agent

`TeamSpec`／`DynamicWorkflowSpec`可以显式设置 `completion_policy="name"`。原父权威冻结业务子Run和回执，再采纳纯gate及可选受管理模型验证；模型验证不能放宽gate或替换候选结果。Plan反馈进入下一次实际规划，Team仅accept/reject。接口、默认参考链路、配置与恢复边界见[业务完成验证](parent-completion.md)。未选中政策的旧定义保持。

dev14 的 TeamSpec 和 DynamicWorkflowSpec 使用受管理父子 Run。各成员仍是 AgentSpec，使用同一 Harness、模型、工具、上下文、记忆、审批及效果恢复。父级保存委派与 PlanRevision；策略只提出方案，LocalEngine 提交执行事实。

## 从安装包开始

```shell
ralf --format text init my-team --template team
cd my-team
python -m agent_app --input hello --command-id first
```

`--template plan` 创建规则规划项目。两个模板都包含可编辑 workflow.json/runtime.toml，默认离线 Echo；支持 --submit-only、--resume 和命令重放。它们证明运行链路，不能作为真实 AI 能力评分。

```python
import asyncio

from ralf_agent import AgentSpec, RuntimeBuilder, RuntimeProfile, TeamSpec


profile = RuntimeProfile("team", "1", {"default": {"adapter": "offline-echo"}})
team = TeamSpec(
    "review-team",
    {"research": AgentSpec("research", "Research"), "review": AgentSpec("review", "Review")},
    child_budget=4,
)
with RuntimeBuilder().build(profile, ".ralf/team.sqlite") as runtime:
    handle = runtime.submit(team, "task", command_id="first", budget=8)
    print(asyncio.run(runtime.drive(handle.run_id)))
```

成员可分别配置国内外 Provider、工具、Schema 和版本；异步记忆/RAG 组合通过 abuild 创建同一个 LocalEngine。JSON/TOML load_spec 支持 team/dynamic，并保留显式 member_order。

## 三种默认团队策略

| strategy | 调度与输入 | 汇总 |
| --- | --- | --- |
| sequential | 按成员顺序执行；输入为 task + 已保存 results | 最后成员结果 |
| router | strategy_config.routes 根据 task 中 route_field 选择注册成员 | 选中成员结果 |
| supervisor | 有限并行 workers；其输入为原任务，supervisor 输入为 task + worker results | supervisor 结果 |

Supervisor 由 strategy_config.supervisor 显式命名；Router 的路由必须命中注册成员，无默认越权 fallback。max_concurrency=1..64，每个成员只能委派一次。当前成员限定为原生 AgentSpec，不支持递归团队、远程 A2A 或 MQ 广播。

TeamStrategy 是纯同步 `select(TeamRequest) -> TeamSelection`，identity 必须版本化。TeamSelection 提出 ChildCall 或最终 JSON，不执行业务工具。自定义策略通过 LocalEngine(team_strategies={"custom": strategy})，或 ComponentRegistry 工厂返回同名映射；SDK 不要求继承 SequentialTeam。

## Plan → Execute → Verify → Replan

DynamicWorkflowSpec 限定 members、planner、verifier、child_budget、max_revisions=1..32、max_steps=1..256 和 max_concurrency。默认 RulePlanner 生成成员列表，CompleteVerifier 取最后结果；本增量是有限委派计划，不是动态 DAG/任意图热改。

```python
from ralf_agent import AgentSpec, DynamicWorkflowSpec, PlanProposal, PlanStep, Verification


class Planner:
    identity = {"kind": "business-planner", "version": "1"}

    async def plan(self, request, caller):
        return PlanProposal([PlanStep("research", "research", request.task)])


class Verifier:
    identity = {"kind": "business-verifier", "version": "1"}

    def verify(self, request):
        return Verification("succeeded", request.results[-1]["result"])


spec = DynamicWorkflowSpec(
    "business",
    {"research": AgentSpec("research", "Research")},
    planner="custom",
    verifier="custom",
    max_revisions=2,
)
# 注入 LocalEngine(planners={"custom": Planner()}, plan_verifiers={"custom": Verifier()})。
```

PlanningRequest 是脱离执行记录的不可变 JSON 快照；results 包含已完成 worker 的 id/member/result。PlanProposal 仅能调用 allowlist 中的成员，id 不能重复，输入为有限 JSON。每次修订创建新的逻辑调用，不能改写旧结果、效果或批准；Verifier 可返回 replan，达到次数/步骤/预算上限就失败。

ModelPlanner 注册固定 tool-free planner Agent，通过 AgentCaller 调用受管理子 Run，返回 steps JSON 后做同一校验。它不另写 Provider 循环，工具提案也不能被采纳为业务执行。planner 与 worker 的调用命名空间分离；模型规划同样占用步骤额度和父预算。要使用真实模型，配置 Provider，再注入 planners={"model": ModelPlanner(provider="alias")}；规则/fixture 测试不能证明模型规划质量。

自定义 async Planner 应只提出方案；caller 仅允许它声明的 @planner Agent，不允许提前执行业务 worker。并发 caller.call 也按父 max_concurrency 排队；已有未知/待恢复子调用占据耐久容量，不能改用另一个 ID 绕过上限。采纳计划后不能追加规划调用。外部副作用应由受管理 Agent/工具执行。纯 Verifier 不进行 I/O；通用异步/模型 Verifier 是后续独立能力。

## 父子身份、预算与控制

委派在同一 ExecutionStore 事务中预留父额度、提交子 Run、保存 parent_id/call_id 与父子链接；重放不创建第二个孩子。父 budget 为总上限，每个 child_budget 先整体 escrow，子预算只能花费该 cap。终态且实际调用静止后按已花费结算；未知 held 保留父预留。并发不足或某个 cap 大于剩余额度时保守拒绝，不能当作完整可嵌套账户体系。

子 Session 派生自父 Session/稳定 call ID，Scope 与父一致。子 Release 从首次接受就绑定 parent_call，直接继续子 Run 同样核验原父配置和链接；老于 dev14 的内核不能继续新的父/子 Run。原生 Agent/sequence/static graph 的旧请求/Manifest 不变；无自动迁移。

父 diagnostics 的 workflow.children 包含子快照；CLI inspect 显示子 Run 的观察命令。对实际子 Run 使用 approve/reconcile，然后 drive 原父 Run。父 pending 不伪造子批准对象。任一并行子 Run 失败时立即标记父失败并取消兄弟，阻止它们派发后续工具；驱动仍等待已开始调用结束，保留 Coordinator 与证据。父取消同样传播；不能用新 Run 替代未知业务写入。

保存的 received proposal 先于 PlanRevision 采纳；恢复消费已保存提案，ModelPlanner 的已完成子响应不重新调用模型。五个真实进程窗口验证提案接收、修订采纳、子提交、子完成和 Verify 后恢复，保持一个计划调用、一个 worker 调用和一个子 Run。

关闭时先完成/取消并 await 自己的驱动；真实线程未结束仍占有 Coordinator。取消等待不代表业务操作撤销，也不保证外部系统恰好一次。本地长期运行的全局容量、deadline 与企业 Scope 收窄仍待交付。嵌套编排、消息交接与 Temporal 在后续增量扩展，见下文。

## dev15 extension

The original flat mode and serialized members remain compatible. Explicit plan_mode=dag supports dependencies, conditions, bindings and durable CAS plan patches. Team/Dynamic members now accept Agent, sequence, graph, team and dynamic definitions with finite recursion, ancestor releases and budget settlement. See [DAG/nesting](dynamic-dag.md). MQ/A2A composition and the independently limited Temporal backend are documented in [handoff](remote-handoff.md) and [Temporal](temporal-execution.md); local orchestration is not silently moved to another authority.

## dev17 distributed composition

The explicit Temporal orchestration_release supports Agent-node Graph, Team, Dynamic flat/DAG and nested definitions, with registered strategies/planners/verifiers, RAG snapshots and immutable execution limits. See [distributed composition](temporal-composition.md); direct Tool/Transform graph nodes and shared Sessions remain refused.
