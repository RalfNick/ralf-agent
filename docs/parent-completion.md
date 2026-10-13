# Plan／Team 的业务完成验证

`completion_policy`把“成员已返回答案”和“父任务可以发布成功”之间的业务条件显式声明。它是可替换能力，复用原 Local Run／Temporal History 的执行权威。未选择政策的旧定义保持原行为。

政策包含纯 `ParentCompletionGate`，可以增加独立、受管理的 `ParentVerificationStage`。业务 gate 先检查真实子 Run、工具参数、回执和最终模型消费证据；只有 accept 才运行模型验证。模型可以拒绝或让 Plan 有界重规划，不能绕过 gate，也不能改写候选答案。

## 安装后的默认参考链路

安装本地构建的 wheel 后，以下命令可以在 checkout 外运行，无需模型密钥或远程服务：

```sh
python -m ralf_agent.parent_completion_starter --kind plan
python -m ralf_agent.parent_completion_starter --kind team --model-verification
python -m ralf_agent.parent_completion_starter --kind plan --task '{"dataset_id":"warehouse-a","target":null,"quantity":3}'
```

参考组合提供真实 Python 库存查询和整数计算工具、研究成员、写作成员及 `InventoryParentCompletionGate`。Plan 使用原 DAG，Team 使用原 Supervisor。默认三单位 wire 的总价为 1275 分；缺输入返回 needs_input，未知 SKU 返回 not_found，库存不足停止计算。报告包含原回执、gate/adopted 结论、子 Run 和额度。默认 Provider 是离线协议 fixture，`model_quality`始终为空；它验证链路和恢复，不代表模型质量。

`--db-path`可以保存运行证据。参考命令使用固定 command_id，同一输入重提取得原回执；更换输入时请使用新数据库，或在自己的 SDK 应用中为新请求提供新的 command_id。

```python
import asyncio
from ralf_agent.parent_completion_starter import run_reference

report = asyncio.run(run_reference("team", model_verification=True))
assert report["state"] == "succeeded"
assert report["result"] == {"status": "completed", "total": 1275}
assert report["gate_verdict"]["status"] == "accept"
assert report["model_quality"] is None
```

调用 `run_reference(..., business_provider=provider, verification_provider=reviewer)`可以分别替换两个模型，客户端由调用者拥有并关闭。模型阶段固定为无工具的一次决策，必须返回 `{status,feedback,evidence_ids}`。实际 Provider 配置仍遵循[模型工具指南](sdk-model-tools.md)与[原生续接](model-continuation.md)；思考 Provider 需要原 continuation/history 装配。参考函数没有自动开启这些能力，使用原生思考协议时应显式构造 Runtime/Profile。

## SDK 和 TOML：接入自己的工具

下面的完整离线例子使用一个真实计算工具。先把 TOML 保存为 `completion.toml`；两个 demo adapter 由应用显式注册，框架不会根据字符串导入任意模块。

```toml
schema_version = 1
[default]
name = "business"
version = "1"

[[profiles]]
name = "business"
version = "1"
[profiles.providers.default]
adapter = "demo-worker"
[profiles.components.tools]
adapter = "demo-tools"
[profiles.components.team_strategies]
adapter = "defaults"
[profiles.components.parent_completion_policies]
adapter = "configured"
[profiles.components.parent_completion_policies.config.policies.checked.gate]
adapter = "receipt-rules"
[[profiles.components.parent_completion_policies.config.policies.checked.gate.config.rules]]
id = "calculated-total"
member_path = ["worker"]
tool = "calculator"
[profiles.components.parent_completion_policies.config.policies.checked.gate.config.rules.argument_bindings.quantity]
source = "task"
pointer = "/quantity"
[profiles.components.parent_completion_policies.config.policies.checked.gate.config.rules.argument_bindings.unit_price_cents]
source = "task"
pointer = "/unit_price_cents"
[profiles.components.parent_completion_policies.config.policies.checked.gate.config.rules.output_bindings."/total"]
source = "candidate"
pointer = "/total"
```

将以下程序保存为 `completion_demo.py`，在相同目录执行 `python completion_demo.py`。输出为 `succeeded {'total': 1275}`。重复执行使用原持久化回执。

```python
import asyncio
import json
from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    ModelResponse,
    RuntimeBuilder,
    TeamSpec,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    load_catalog,
)


class DemoWorker:
    identity = {"kind": "demo-completion-worker", "version": "1"}

    async def complete(self, messages, tools):
        receipts = [m for m in messages if m["role"] == "tool"]
        if receipts:
            return ModelResponse(output=json.loads(receipts[-1]["content"]))
        task = json.loads(messages[1]["content"])["task"]
        return ModelResponse(tool_calls=(ToolCall("calculator", task),))


def business_tools(config, context):
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "calculator",
            "Multiply quantity by integer unit price.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["quantity", "unit_price_cents"],
                "properties": {
                    "quantity": {"type": "integer", "minimum": 1},
                    "unit_price_cents": {"type": "integer", "minimum": 0},
                },
            },
            effect="read_only",
        ),
        lambda args, context: {"total": args["quantity"] * args["unit_price_cents"]},
    )
    return registry


async def main():
    registry = ComponentRegistry()
    registry.register("provider", "demo-worker", lambda config, context: DemoWorker())
    registry.register("tools", "demo-tools", business_tools)
    profile = load_catalog("completion.toml").default
    definition = TeamSpec(
        "invoice",
        {
            "worker": AgentSpec(
                "worker",
                "Use calculator and return its actual result.",
                tools=("calculator",),
                max_decisions=2,
            )
        },
        completion_policy="checked",
        child_budget=4,
    )
    async with await RuntimeBuilder(registry).abuild(profile, "completion.sqlite") as runtime:
        handle = runtime.submit(
            definition, {"quantity": 3, "unit_price_cents": 425}, command_id="invoice:1", budget=5
        )
        result = await runtime.drive(handle.run_id)
        print(result.state, result.result)


asyncio.run(main())
```

所有参数及输出绑定都比较真实已采纳工具 Action 的值。仅返回正确总数、使用错误计算参数、引用另一 Run 的回执、或未把结果提供给最终模型，均不满足这条规则。规则可声明候选与工具结果 Schema、条件 `when`、必需成员和停止策略。

## 替换 gate 和模型阶段

SDK 直接注册 `parent_completion_policies={name: ParentCompletionPolicy(gate, ...)}`；Profile 使用 `configured`声明。gate 的 `verify(request)`是同步纯函数，返回 `ParentCompletionVerdict`。请求是脱离副本的有限 JSON，包含 task、candidate、已采纳 plan、业务子 Run、真实回执和剩余额度；验证器不能自己读取任意 Run。

`ModelParentVerificationStage(provider="reviewer")`提供默认无工具验证 Agent。将它放入 `ParentCompletionPolicy(..., model_stage=stage, verifier_budget=1)`，并注册 `reviewer` Provider 即可。Profile 的 `model_stage`使用 adapter `model`及对应构造配置。Provider/context ref 使用原 `AgentBindingDescriptor`，缺 alias/ref 或不合适的继承 context 会在 owned 资源创建前拒绝。默认模型阶段关闭 Session、事实、知识、自动记忆、Artifact、Workspace、Skills、Sandbox 和 leaf verifier，避免隐藏辅助调用；可以显式选择纯 context ref。

自定义 `ParentVerificationStage`提供固定 `agent`、纯 `prepare(request)`及纯 `interpret(request,output)`。Agent 必须 tool-free、一次有界决策并使用公共 Verdict Schema；实际模型 I/O、预算、取消及结束证据由原 child Run 承担。自定义阶段可以显式使用独立 Session／原生历史，仍需原绑定、宿主许可、预算和生命周期契约。任何 async、generator、惰性上下文管理器或非法返回值均拒绝。

验证阶段当前接受实际内建 ContextAssembler，或使用内建字符／UTF8估算 counter、WholeGroupBudgeter及可选Excerpt的 BudgetedContextAssembler。opaque自定义reader／counter／summarizer不能凭identity自报纯性；artifacts继承也不豁免。业务Agent的通用Context扩展端口保持，验证输入可用纯prepare独立定制。

`member_path`是两个后端一致的逻辑成员路径：根成员 `["worker"]`；嵌套成员追加名称；顺序步骤追加 `["steps","0"]`；图节点追加节点 ID。它与 AgentBinding 的配置地址分别定义。Local图直接工具节点没有最终模型 slot，真实回执可使用空 consumed_by；默认 `require_consumed=True`拒绝这种未消费证据，显式 False 可以验证纯工具链。Temporal图继续遵循现有仅Agent节点的支持范围，共享来源DTO不扩大执行器的节点类型。

## 恢复与运行限制

原权威分别保存 source、稳定 verifier child 意图、已接收 proposal 和已采纳 verdict；固定子调用为 `rN.verifier.verdict`。恢复采纳已保存响应，不重新执行已完成模型或工具。Verifier 不进入业务 DAG、Team 结果及会话业务聚合，其实际结束、额度及显式原生历史仍受管理。

Plan 的 replan 把有界 feedback 放进下一次真实 `PlanningRequest`，受 max_revisions、max_steps、host child/concurrency/depth 和原 credits 限制。Team 只支持 accept/reject，不自动重派成员。调用超时、unknown、审批未结束或 handler 仍活跃不能当成功证据；取消等待真实 child 停止，迟到响应保存并计量，不发布父成功。

source冻结期间外部DAG patch会拒绝，避免验证旧候选时悄悄改变业务计划；有界内部replan仍走原流程。needs_input／refused保留真实规划结论，不引用无关的旧工作。反馈只用于紧接的一轮规划，之后普通Verifier再次replan不会复用过期字段。采纳与最终发布会独立复核原计划和业务来源，合法的验证／Session结算不能掩盖其他预算变化。

新政策使用显式版本门槛：Local local-8／bound parent local-bindings-16；Temporal policy registry 发布 binding_protocol9、parent_completion_protocol1，由原 History 分支及纯 gate Activity 管理。旧 Worker 不执行新定义；未选中政策的旧 Local 定义和旧 History 保留原路径。

## 独立评测和能力边界

```sh
ralf-evaluate-orchestration --offline --kind plan-and-execute --completion-gate --repeats 3
ralf-evaluate-orchestration --offline --kind team --completion-gate --repeats 3
```

显式评测模式保留原业务 oracle、实际参数／结果／消费／停止检查，新增当前 revision lineage 和门禁采纳检查。旧报告默认不变化。历史修订的好回执不能替代当前任务证据；原错误尝试仍保存，不能删除以提高分数。

本批只验收有限 literal 工具证据及固定业务参考组合。摘要／Artifact 投影不作为完整 literal 消费证明；需要明确业务语义的查询、RAG答案和自由文本正确性仍应实现自己的 gate。离线 fixtures、MockTransport 和实际 Temporal 服务恢复均不证明真实模型质量或外部采用。完整 R10／H3／M1／R01–R26及对等框架比较继续开放。
