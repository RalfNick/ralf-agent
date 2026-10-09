# Agent 完成验证 — dev29 / Local H1e

模型给出合法 JSON，仅证明输出符合 Schema。业务完成条件需要读取执行证据。
`CompletionVerifier` 是纯同步策略；Engine 负责校验、记录结论、继续决策和提交结果。
它与动态流程的 `PlanVerifier` 是不同端口，本轮没有替换 `CompleteVerifier`。

## 默认与替换

默认继续使用强制 `final_output`／节点 Schema 校验。没有显式配置时，旧 Release
身份与行为保持兼容。`SchemaCompletionVerifier` 提供可注册的同等基线；它不判断业务正确性。
`ToolReceiptVerifier` 则检查当前 Agent 节点已经提交的工具回执，支持输出条件 Schema、
回执结果 Schema，以及从最终输出映射到工具参数的 JSON Pointer。

```python
from ralf_agent import ToolReceiptVerifier

verifier = ToolReceiptVerifier(
    "apply_fix",
    when={
        "type": "object",
        "required": ["status"],
        "properties": {"status": {"const": "resolved"}},
    },
    result_schema={
        "type": "object",
        "required": ["applied"],
        "properties": {"applied": {"const": True}},
    },
    argument_bindings={"ticket_id": "/ticket_id", "fix": "/fix"},
    on_missing="retry",  # 也可配置 reject，直接失败
)
# 交给已有 LocalEngine(..., verifier=verifier)
```

`when` 是 Schema 匹配条件；请用 `type`／`required` 表达完整条件。
没有 `when` 表示所有最终输出都要求回执。参数映射按 JSON 值比较，缺字段即不满足。规则使用不可联网的 Schema registry；内部 `$defs`／本地引用可用，无法在固定 Schema 内解析的引用会拒绝，不隐式下载远程规则。
`result_schema` 应要求真实成功标志；只有工具名而无结果约束，不足以区分业务失败。
同名工具的历史 Session 消息、模型声明、其他节点和兄弟 Agent 的回执都不参与。
回执证明的是 RALF 已采纳的结果；外部系统的实际正确性仍依赖可信 handler／核验接口。

## 自定义策略

```python
from ralf_agent import CompletionVerdict


class MyVerifier:
    identity = {"kind": "my-business-verifier", "version": "1"}

    def verify(self, request):
        # request.task / output / receipts 是脱离执行状态的 JSON 快照。
        if request.output == {"status": "needs_input"}:
            return CompletionVerdict("accept")
        return CompletionVerdict("reject", "缺少业务证据")
```

允许的返回值只有具体 `CompletionVerdict`：`accept`、`reject`、`retry`。
`retry` 必须有 1–4096 字符的非空反馈。async、generator、contextmanager 或字典返回会被拒绝。
策略不得执行模型、网络、数据库或工具 I/O；这些应通过受管理 Agent／Action 执行。
异步／模型 Verifier 的受管理阶段接入尚未交付。

## 绑定与配置

```python
from ralf_agent import AgentBindingDescriptor, AgentDefinition, BindingSelection

catalog.register("verifier", "business", "1", verifier)
definition = AgentDefinition(
    spec,
    AgentBindingDescriptor(verifier=BindingSelection.ref("business", "1")),
)
```

Local 的原生、顺序、Graph／并行、Team、Dynamic 和嵌套成员均支持 `inherit/ref/disabled`。
`disabled` 只关闭额外完成规则，不能跳过 Schema、授权或审批。该角色不接受 selector。
Profile 的 `components.verifier` 支持 `schema` 与 `tool-receipt` 适配器，后者 `config`
使用上例构造参数；`binding_components` 中的 role 为 `verifier`。
自定义适配器用 `ComponentRegistry.register`／`register_async` 注册同名 component kind。
异步工厂用于装配，实际 `verify` 仍是纯同步方法，资源所有权遵循现有 BuildContext。
Temporal 当前拒绝全部绑定声明，这一增量不扩大其支持矩阵。

## 执行与恢复

最终模型 Action 保存 `completion_verification`，包含请求、摘要和结论。task 保留当前节点的原始 JSON 类型；顺序后继节点读取前一节点经过 Schema 归一化的输出，不能把模型消息的序列化字符串误当作业务输入。
记录先于 Session 追加及节点终态提交；重启复用已提交结论，未提交的纯验证可重新运行。
`retry` 与反馈一次提交，下一轮新模型决策遵守既有 `max_decisions`／credits；拒绝以
`completion_rejected` 结束。取消仍由原执行权威处理。
注册身份或实际执行组件变化会阻止采纳；恢复必须重建原验证器。
没有新后台循环、执行权威或绕过审批的补写路径。

## 业务评测

```bash
ralf-evaluate-business --offline --receipt-gate
```

SDK 对应 `evaluate_business(..., completion_verifier=verifier)`。
启用后报告验证器摘要和各案例 accept/reject/retry 次数；业务成功仍由独立测试服务的
实际写入、参数、工具顺序、审批和恢复判定。任务／预期值保持冻结，历史 dev28 分数不改写。
离线试验只验证运行契约，不能当作真实模型质量。
