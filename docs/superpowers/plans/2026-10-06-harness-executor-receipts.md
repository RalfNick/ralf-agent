# Harness、Executor 与回执阶段实现计划

> **For agentic workers:** Use the existing delegated component tasks and root integration task. Steps use checkbox syntax to track verified deliverables.

**Goal:** 提供可替换的原生决策策略与工具执行器，并补齐已收到模型响应／效果回执到正式采纳之间的 Local 崩溃恢复窗口。

**Architecture:** Harness 只准备模型请求和提出 DecisionProposal；ToolExecutor 只执行已获准的 DispatchEnvelope 并返回 EffectObservation。LocalEngine 保留唯一执行权威，在独立事务中记录原始响应／效果观察，再原子采纳决策／结果；恢复消费耐久证据，不重新调用已经完成的外部请求。

**Tech Stack:** Python 3.11+、现有 asyncio／线程追踪、SQLite Schema v1／ExecutionStore v1；无新增运行依赖。

**Spec:** [Action 恢复契约](../../../architecture/specs/action-recovery-contract.md)、[可靠性门槛](../../../architecture/reviews/2026-10-05-reliability-boundaries.md)、[总设计](../../../architecture/design.md)。

## Global Constraints

- 单 Coordinator；现有审批摘要、Action／Attempt／effect_key、授权、预算和取消语义继续由内核负责。
- Harness prepare/propose 必须同步；Executor execute/reconcile 必须异步，框架默认同步 Python 调用仍追踪真实工作线程。
- 已确认业务效果不能因取消或错误被丢弃；未知费用不按零处理；任何阶段不隐式授予工具权限。
- 新运行身份为 local-4、包版本 dev6；不静默改写 local-3 已有 Run。旧 Run 可观察／取消／人工核验，继续执行需要原版本与配置。
- 本轮不实现 RAG、模型供应商适配、多进程、并行 Workflow、沙箱或 Temporal；默认组件与独立自定义策略必须实际可运行。

## Review Focus

- 自定义 Harness 返回非法／异步提案或扩大工具白名单：在派发前明确拒绝。
- 模型响应已耐久但提案尚未采纳：恢复不调用 Provider，固定已派发请求，不重新检索。
- 效果观察已耐久但结果尚未采纳：恢复不执行 handler 或 reconciler，预算及消息只合并一次。
- 取消发生在接收与采纳之间：保存效果／用量，终态保持取消，不派发后续工具。
- 组件在回调／await 期间改变身份、线程仍运行或晚到结果：保留事实，不确认符合另一固定配置，不提前释放 Coordinator。

## Task 1: 纯 Harness 提案

**Files:** 新增 src/ralf_agent/harness.py、tests/test_harness.py。

**Interfaces:** ModelRequest(messages, tools)、DecisionProposal(output=None, tool_calls=())；Harness.identity、prepare(spec, messages, tools)、propose(spec, response)；NativeHarness 默认实现。输入输出均为分离的有限 JSON；Engine 再验提案、Schema 与白名单。

- [x] RED：输入／输出隔离、有限 JSON、ToolCall 结构、自定义准备与解释；原生策略不执行工具。
- [x] GREEN：实现 DTO、Protocol 和默认策略；定向验证。

## Task 2: 受控工具执行组件

**Files:** 新增 src/ralf_agent/executors.py、tests/test_tool_executors.py。

**Interfaces:** DispatchEnvelope(context, tool_manifest, arguments, operation_digest)，属性提供分离的描述／参数；EffectObservation(result, source="tool-handler")；ToolExecutor.identity、async execute(envelope)、async reconcile(envelope)。PythonToolExecutor(registry) 复核实际 manifest，再调用现有 invoke，不拥有调度／审批／预算。

- [x] RED：同步／异步调用、查询、manifest 不符、JSON 隔离、取消时真实线程仍保留归属。
- [x] GREEN：默认 Python 执行器及公开协议。

## Task 3: 内核装配与独立接收阶段

**Files:** 修改 engine.py、__init__.py；新增 tests/test_execution_components.py。

**Interfaces:** LocalEngine(..., harness=None, tool_executor=None)；Manifest 固定两种组件身份。模型 Action 保存实际请求及 received_response，status=response_received；工具 Action 保存 effect_observation，status=receipt_received。接收事件为 model_response_recorded／tool_receipt_recorded，正式采纳保留 decision_adopted／tool_result_committed。

- [x] RED：默认／自定义组件跑通 Agent 与顺序 Workflow；非法组件和扩权提案拒绝；组件身份变化阻断续跑。
- [x] GREEN：将准备／解释／调用分离，持久接收先于原子采纳，恢复优先处理已有证据；原生行为保留。

## Task 4: 真实故障窗口

**Files:** 新增 tests/receipt_runtime.py、tests/test_receipt_process_recovery.py。

- [x] RED：在接收事务实际 commit 后 os._exit(77)，独立业务库记录 Provider／handler／reconciler 调用计数。
- [x] GREEN：重启仅采纳已有回复／观察，Action、预算和工具消息唯一；取消后仍保留／结算已收到事实，不开启下一步骤。
- [x] 定向 review：晚到结果、当前授权、固定组件和真实线程生命周期。

## Task 5: 文档、包装与交付验证

**Files:** 更新 README、扩展／API／恢复／支持／进度／变更文档及版本；提供自定义 Harness／Executor 示例，更新 CLI 对已保存回执的观察。

- [x] 全套 pytest -q -W error、Ruff lint/format、git diff --check。
- [x] 源码与 wheel 独立安装，原生 starter 审批／恢复、两个故障窗口和自定义策略实际运行。
- [x] 独立实现 review，修复阻断并完成本地交付；没有真实模型质量或外部框架比较成绩时继续明确标为未运行。

## Verification evidence

- `pytest -q -W error`: 376 passed，Python 3.12.7；新增 102 项，含独立 review 13 项。
- 两个接收 commit 后真实退出／取消窗口 10 项通过；自定义组件／顺序 Workflow 与只读证据诊断通过。
- 仓库外安装 dev6 wheel：组件工作流、原生 starter、响应／回执崩溃恢复；旧 dev5 原提交回执重放、观察／取消／人工核验通过，续跑明确拒绝。
- Ruff、Git 空白检查与文档／制品检查通过；无真实模型、Temporal 或对等框架 benchmark，M1 仍未完成。
