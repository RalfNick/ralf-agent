# 原生执行组件与接收阶段 Review

日期：2026-10-06；基线：`2aacaee`／0.1.0.dev5；修订：0.1.0.dev6／local-4。

## 已交付边界

| 边界 | 默认实现与扩展 | 内核保留的权威 |
| --- | --- | --- |
| Harness | NativeHarness；同步 prepare 返回 ModelRequest，propose 返回 DecisionProposal；可按 AgentSpec 选择策略 | 实际请求验收、允许工具、参数／输出 Schema、稳定 Action ID、决策采纳 |
| ToolExecutor | PythonToolExecutor；异步 execute／reconcile 返回 EffectObservation；固定 DispatchEnvelope | 当前授权、审批、额度预留、派发意图、证据接收、结果采纳与流程推进 |
| 模型接收 → 决策 | 原始 received_response 先耐久；随后解释／验收并原子保存 response 与工具清单 | 接收后的恢复不重新请求 Provider；提案尚未采纳不提前暴露执行 Action |
| 工具接收 → 结果 | effect_observation 先耐久；随后原子保存结果、消息与费用 | 已保存观察恢复不重新执行／查询；首次提交结果不可被晚到证据覆盖 |

这是原生 Agent／顺序 Workflow 的组件边界。Workspace、Skills、外部 Coding Harness、RAG、分支并行和独立 Temporal 权威仍未实现。任意自定义 Python 属于可信宿主代码，接口不是沙箱。

## 独立复核与修复

1. 真正调用的 Provider 在 await 中改变身份，再将注册表替换为原身份实例，原校验会确认错误来源。现在捕获实际对象，派发意图后、调用前复核，完整响应先保存再复核来源；已收到事实与费用不变成 unknown。
2. 意图提交后的身份校验／取消可以阻止真实调用，原异常处理仍误记 unknown。现在本次 Attempt 标记 not_dispatched，记录派发拒绝并以零实际 credits 释放预留；真实组件调用已经开始才进入未知效果路径。
3. 拒绝新重试曾覆盖历史未知 Action，并把人工核验结算到已归零的未派发 Attempt。现在旧未知效果仍阻断跨 Run 同操作写入；核验上下文、回执状态和费用使用最后真正派发 Attempt，旧预留保留至确认。

[独立回归](../../tests/test_review_component_boundaries.py)包含 13 项用例，覆盖以上问题、非法核验 DTO、执行器换源、无 Registry reconciler 的自定义核验与原终态保持。第二次独立核对修正了文档：最终输出验收针对 Harness 提出的 DecisionProposal；默认 NativeHarness 透明转交原响应。

## 故障与采用证据

- [接收窗口回归](../../tests/test_receipt_process_recovery.py)：10 项真实进程／取消用例；在最外层接收事务实际 commit 后退出，恢复检查独立模型、handler、query 次数及业务账本、原 Action、事件顺序和预算。
- [组件示例](../../examples/execution_components.py)与[测试](../../tests/test_component_example.py)：单 Agent／顺序 Workflow、自定义 Harness 变换、自定义执行器审批前零调用、效果键去重，以及业务提交后崩溃查询恢复。
- [只读诊断回归](../../tests/test_receipt_inspection.py)：活跃／已取消 Run 的耐久证据可见，观察不执行外部请求，提示不会将已保存回执误报为未知写。
- 安装包核对必须在仓库外运行，确认实际导入 site-packages；源码示例不打入 wheel，独立 starter 打入 wheel。第三方依赖复用已安装环境，不冒充全新网络依赖解析验证。

模型已知 execution credits 在接收阶段结算；工具 credits 在结果采纳阶段结算。未知 Token／用量仍标未知。取消后可以保存／结算收到的事实，不创建新提案或调用，不重新打开终态。人工 reconcile 的证据与命令回执／结果继续同事务。

## 兼容及剩余验收

local-4 固定 Harness／Executor 身份并改变 Action 阶段；不静默迁移 dev3–dev5 的 local-3 Run。旧 Run 可观察、取消和人工核验，继续执行要求原版本与配置；dev3 起的提交请求身份不变，因此找回原回执与新内核能继续执行是两件事。SQLite Schema／ExecutionStore 保持 v1。

此轮关闭两处本地接收窗口及组件可替换边界。M1 的成组故障报告、真实模型质量、Temporal 最小探针和外部开发者采用仍需独立证据；不能以专项测试或版本升级声明通过。端口/API 与下一步见[组件指南](../../docs/execution-components.md)、[支持状态](../../docs/implementation-status.md)及[M1 验收](../../docs/m1-acceptance.md)。
