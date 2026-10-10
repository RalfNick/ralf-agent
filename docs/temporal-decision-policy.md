# Temporal DecisionPolicy — dev63

DecisionPolicy 复用公共纯 `Harness` 的 `prepare/propose`，与组合入口 `AgentHarness` 分工保持。
默认 `NativeHarness` 透明传递请求／响应；未配置额外策略时原发布与 History 身份保持。

```python
from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    BindingSelection,
    ModelRequest,
    NativeHarness,
)
from ralf_agent.temporal_activities import TemporalRuntime


class EvidencePolicy(NativeHarness):
    identity = {"kind": "evidence-policy", "version": "1"}

    def prepare(self, spec, messages, tools):
        prepared = super().prepare(spec, messages, tools)
        return ModelRequest(
            [*prepared.messages, {"role": "system", "content": "Use available evidence."}],
            prepared.tools,
        )


policy = EvidencePolicy()
catalog.register("decision_policy", "evidence", "1", policy)
execution = TemporalRuntime(providers=providers, tools=tools, binding_catalog=catalog)
definition = AgentDefinition(
    spec,
    AgentBindingDescriptor(decision_policy=BindingSelection.ref("evidence", "1")),
)
# 通过原 TemporalEngine／Runtime.from_temporal 运行；高级编排使用 orchestration_release。
```

`TemporalRuntime(..., harness=policy)` 设置宿主默认；`inherit` 继承，`ref` 替换。
该角色必需，`disabled` 和资源 selector 拒绝。当前支持原生／顺序／Graph／Team／动态／嵌套实际 Agent；
固定版本、原 Scope 和节点路径，不能通过策略增加宿主授权。
Worker 策略装配是显式 SDK 注册；完整 Temporal Worker Profile 工厂仍是后续能力。

`prepare` 只能返回具体 `ModelRequest`，`propose` 只能返回具体 `DecisionProposal`。
async、generator、字典和上下文管理器返回失败关闭；纯策略不能包含模型、工具、数据库或网络 I/O。
准备阶段可以裁剪／重排已授权的原工具描述，不能新增、修改或复制描述；执行提案仍按原 Agent 工具授权验证。
实际准备后的消息必须非空，并服从原字符／token／输出预留约束；mandatory Schema、审批、limits、预算和
CompletionVerifier 保持原采纳顺序。业务完成应使用可信回执规则，不能靠改写候选输出证明。

## 身份、证据与恢复

显式 `decision_protocol=1/temporal-3` 固定策略 JSON identity 及 prepare/propose 的可执行指纹。
只支持有限 JSON／纯函数闭包；零参数 `super()` 的编译器类闭包会固定 MRO／所调用的 Python 基类方法。
直接读取 `__class__`、显式携带类对象及其他 opaque 捕获拒绝。identity 必须覆盖影响行为的配置；引入未登记可变状态违反纯策略契约。全局依赖由宿主固定部署和配置版本；
指纹不是对任意 Python 代码进行隔离的沙箱。实例、方法、身份或所固定基类变更，在派发前／await 后拒绝。

指纹使用解释器字节码，不能保证跨 Python 版本相等；历史运行应保留原 Worker 代码与解释器。
Python 3.12/3.13 对零参数／双参数 super 的编译区别按官方
[LOAD_SUPER_ATTR 定义](https://docs.python.org/3.12/library/dis.html#opcode-LOAD_SUPER_ATTR)核对；
当前本机测试使用 Python 3.12，CI 的其他 Python 版本仍需分别运行。

派发前冻结实际准备请求；Provider 获得独立的可变数据，不能修改原证据。
模型 Activity 保存原 received_response／usage，以及所选注册、原请求摘要、prepared_request、
原响应摘要与提案摘要组成的 `decision_evidence`。原 Run History 独立验证一致性、原描述子集和额度后，
一次采纳工具／最终输出。新协议不接受旧格式成功响应作为兼容旁路；失败或取消后保留实际收到的响应，
不能推进业务。Worker 是可信部署，这些摘要不是不可信 Worker 的签名认证或外部业务真相证明。

纯准备／提案与业务模型同属原模型 Activity；已接受响应的 Worker 重启／History replay 不再次调用策略／模型。
未接受的外部响应仍可能无法找回，不保证任意供应商调用恰好一次或费用上限。此能力不增加第三套状态机。

验收和故障取舍见[dev63 记录](../architecture/reviews/2026-10-11-temporal-decision-policy.md)。
