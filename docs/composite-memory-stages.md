# Local 图、Team、动态编排的自动长期记忆（dev45）

复用已有 `ManagedMemoryPolicy`／`ManagedModelMemoryPolicy`、写后端、额度和固定成员绑定。
实际 Agent 的结果通过完成验证与必要 Session 保存后，才准备观察来源和记忆提案。
不增加后台任务或执行权威；Temporal 自动记忆写入仍未交付。

| 组合 | 规则字段提炼 | 模型字段选择 | 证据与预算归属 |
| --- | --- | --- | --- |
| 原生 Agent／顺序 | 原有支持 | 原有支持 | 原 Run，Schema7/9 |
| 串行图 | 支持 | 支持 | 原 Run 的原节点 |
| 有界并行图 | 支持 | 支持 | 原 Run，节点 execution 投影 |
| Team／动态 Plan／DAG／嵌套 | 支持 | 支持 | 原真实 Agent 子 Run |
| Temporal | 未交付 | 未交付 | 后续需独立 History 阶段 |

## 默认使用

```python
import asyncio
from ralf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    Runtime,
    RuntimeBuilder,
    recommended_profile,
)


async def main():
    profile = recommended_profile("managed-memory", agent_name="observations")
    instance = await RuntimeBuilder().abuild(profile, "runs.sqlite")
    flow = GraphWorkflowSpec(
        "research",
        [
            GraphNode("draft", agent=AgentSpec("draft", "Draft a response")),
            GraphNode("check", agent=AgentSpec("check", "Check the evidence")),
        ],
        max_concurrency=2,
    )
    async with Runtime(instance, owned=True) as runtime:
        run = await runtime.submit(flow, "hello", command_id="hello-1")
        print((await run.wait()).snapshot)
        print(await run.memory_stages())


asyncio.run(main())
```

默认 `offline-echo` 验证装配；这不是真实任务质量证明。该 Profile 默认把每个已完成
Agent 结果作为来源观察，写入明确的 `agent_name` namespace；所有成员继承相同写目标。
它不会按成员名字偷偷切换 namespace，也不自动扩大召回范围。

业务应用覆盖 `stage_policy.config.fields` allowlist，只存需要的字段。
`mode="model"` 配合明确的 selector Provider；模型只能选 allowlist 键，值从原结果回取，
不能自由合成事实。完整来源、策略、模型响应与 CAS 回执保留在原执行权威。
纯 Planner／Transform／Tool 节点和父路由没有隐式记忆写；明确代理化的 Planner
仍是实际 Agent，按其已固定的策略与额度执行。

## 自定义成员

每 Agent 的 `stage_policy` 继续支持 inherit/ref/disabled；Graph 用 `graph/nodes/<id>`，
Team／Dynamic 用原成员声明路径，嵌套延续完整路径。参见[绑定指南](agent-bindings.md)。

在可信 `BindingCatalog(scope=scope)` 注册两个不同 Policy，即可让成员写入不同后端或 namespace：
`ManagedMemoryPolicy(memory_a, namespace="customer", scope=scope)` 与
`ManagedModelMemoryPolicy(memory_b, namespace="project", scope=scope, provider="selector")`。
再用原 `AgentBindingDescriptor(stage_policy=BindingSelection.ref(...))` 选择。
JSON/TOML 的 sourced-memory／sourced-memory-async 工厂与 sync/async 装配继续复用。

SQLite／内存及已有 Redis／PostgreSQL CAS、精确 inspection 或有界 recall 端口均按原契约接入；
Facts 只读绑定不能授权写入。借用资源由宿主关闭，owned 工厂资源随 Runtime 关闭。
写后 await 的实际后端／方法／Policy 身份变化不能静默确认原发布。

## 并行与恢复

并行帧仍以逻辑 node=0 执行；来源和事实元数据额外固定原 `workflow_node`。
事实键纳入该节点身份，同名字段不互相覆盖或共用额度。root `memory_stages()`
附加 workflow_node，核对原 Action marker、阶段和独立预算，纯查询不读取写后端。
丢失整个帧或改变来源节点时拒绝查询／恢复。

成功的辅助响应分别持久化和采纳；收到 selector 响应后重启不会再次调用模型。
CAS 已提交但本地丢回执时只读取原精确事实；事实缺失、冲突或不可核验时保持 unknown，
不盲目重写。阶段来源已保存而纯规则提案未采纳时，保持原协议的保守辅助失败，不重做纯提案。
每事实预留 1 execution credit，模型选择另外 1；这不是实际费用上限。

子 Run 的 unknown 额度持续占用父 allowance。`wait`／`status`／`pending` 是观察，
不会恢复写入。显式 `await run.resume()` 对已结束根 Run，沿原父子归属恢复已结束、
未结算且无活跃处理器的子 Run，使用它们原 drive 锁与终态协议，再观察父额度。
仅核验已派发事实、采纳晚到回执、跳过未派发事实；不启动 selector、CAS 或新业务调用。
仍在执行或缺乏证据的子 Run 保持占用，需要等待后再次显式恢复。

高级记忆首次准入原子启用 **Schema12**；dev44 及以前拒绝该库。
自定义 ExecutionStore 显式提供 `composite_memory_stage_version=1`、同步
`prepare_composite_memory_stages()->None` 及原独立额度查询。普通原生／顺序保持原语义，
旧库 1–11 可由新代码读取，不可手工改版本号绕过门槛。

本轮真实退出测试固定依赖以隔离已持久窗口，另用自由并行测试覆盖取消、额度及目标漂移。
这些证据不证明所有同时崩溃交错，也不保证任意外部调用恰好一次。
观察不是信念修订；Temporal 记忆写、语义冲突／撤回／遗忘、远程保留和真实记忆利用质量仍待验收。
