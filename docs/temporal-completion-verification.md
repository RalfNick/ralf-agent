# Temporal CompletionVerifier — dev62

复用公共 `CompletionRequest` / `CompletionVerdict` / `CompletionVerifier`。
默认强制 `final_output` Schema 校验；没有配置 verifier 时保持原发布和完成行为。
`SchemaCompletionVerifier` 是可替换的 Schema 基线；`ToolReceiptVerifier` 可要求真实已提交的工具结果。

```python
from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    BindingSelection,
    ToolReceiptVerifier,
)
from relf_agent.temporal_activities import TemporalRuntime

rule = ToolReceiptVerifier(
    "apply_fix",
    argument_bindings={"ticket_id": "/ticket_id"},
    result_schema={
        "type": "object",
        "required": ["applied"],
        "properties": {"applied": {"const": True}},
    },
    on_missing="retry",
)
catalog.register("verifier", "business", "1", rule)
execution = TemporalRuntime(providers=providers, tools=tools, binding_catalog=catalog)
definition = AgentDefinition(
    spec, AgentBindingDescriptor(verifier=BindingSelection.ref("business", "1"))
)
# 原 TemporalEngine / Runtime.from_temporal；高级编排使用 orchestration_release。
```

`TemporalRuntime(..., verifier=rule)` 配置宿主默认补充规则。`inherit` 继承；`ref` 替换；
`disabled` 关闭额外规则，不能删除 Schema、授权、审批、LimitsPolicy 或预算。
该角色不接受资源 selector；目录版本和 Scope 由宿主验证。支持原生／顺序／Graph／Team／动态 DAG／嵌套实际 Agent。
补充完成规则与强制 limits 的交集语义不同，也与 Parent 的 `PlanVerifier` 不同。

## 唯一采纳权威与恢复

显式 `completion_protocol=1/temporal-3` 固定登记、实际方法和对象。策略必须同步、纯、确定性地
返回具体 `CompletionVerdict`。只允许有限 JSON 闭包配置；推荐模块级导入公共类型。
不能包含模型、网络、数据库或工具 I/O。async、generator、上下文管理器及字典返回失败关闭。

原模型输出通过公共 Schema 边界后，原 Run History 固定当前节点原类型输入、归一化输出、
该节点已提交的工具回执和原模型响应摘要；旧 Session／兄弟／前节点回执不参与。
Worker Activity 只提出 verdict；History 校验原请求摘要和严格结论后一次采纳。
采纳前安全纯 Activity 可重试；采纳后 Worker 重启／History replay 不再次验证该候选。

- `accept` 才进入原自动记忆和节点终态链路。
- `reject` 保存证据，以 `completion_rejected` 失败，不能先写记忆或推进后继。
- `retry` 原子追加候选输出及 1–4096 字符反馈，再按原决定数和 credits 继续模型循环。
  决定数耗尽为 `decision_limit`，不会重置 LimitsPolicy、预算或审批。
- 取消后的迟到结论仅保存证据，不写记忆、不重新开启 Run。已发出的验证 Activity 尚未返回时，
  原 Run 未静默，Session 保持占用。

默认／budgeted／managed 上下文把最新候选＋`Completion verification: ...` 反馈及其后工具证据
作为一个必须保留的尾组。不能拆开或静默丢弃；必要内容超过预算时在派发前失败。
默认有效的无反馈历史保持原输出／身份；显式自定义 Context 的可执行指纹变化仍须保留原 Worker 代码或升级发布，不能绕过原身份检查。其他普通 user 续接和 `needs_input` 仍是独立契约。

模型 Action 的 `completion_verification` 保存采纳请求和结论。使用
`await engine.completion_stages(run_id)` 只读原 History 的阶段证据，不执行策略或推进任务。
高级子 Run 控制按包含原 `agent_bindings` 的原发布摘要生成 RunRef，不能丢失绑定身份。

规则只证明回执满足配置，外部业务真相依赖可信 handler／核验接口。此能力没有交付模型 Verifier、
真实质量证明、全局容量、隐藏 I/O 的隔离执行或新的服务部署配置。
验收见[dev62 记录](../architecture/reviews/2026-10-11-temporal-completion-verification.md)。
