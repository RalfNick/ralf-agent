# dev15 动态 DAG 与嵌套编排

用户要求继续实现动态 DAG、嵌套编排及后续远程执行链路。保留 dev14 合法 Agent/sequence/static graph/flat plan/team 定义与 Manifest；新能力显式启用。既有未提交增量不重置，也不发布。

## DAG

DynamicWorkflowSpec 增加显式 plan_mode="dag"。新增 DAGNode/DAGProposal，节点指定注册 member、依赖、已有 ValueRef/Literal/InputMap/BranchCondition，以及显式输出引用。依赖/循环/引用校验复用静态图纯逻辑；执行使用受管理子 Run，无第二状态存储。默认 RuleDAGPlanner、ModelDAGPlanner；模型通过固定 tool-free @planner 子调用产出 Schema 验证的计划或明确 refused/needs_input 结论。

提案接收先独立保存，再验证/采纳 DAG 与节点状态。节点输入只在依赖已确认后绑定并固定，条件未命中保存 skipped。并发由父容量限制；失败立即取消兄弟，真实在途调用保留执行归属。结果供纯 Verifier 决定完成/失败/有限重规划。旧提案、已派发调用与效果不能改写。

patch_plan 是去重控制命令，携带 expected_plan_revision；同一事务校验并替换尚未派发节点。已派发/完成/跳过节点及其定义不变，已派发节点依赖闭包不变。新图必须通过 allowlist、DAG、步骤额度及绑定校验。修订单调保存，计划补丁不能解除未知效果或取消。

## 嵌套

Team/Dynamic 注册成员支持 Agent、sequence、静态 Graph、Team、Dynamic；定义编解码独立到 spec_codec。有限 JSON，最多1 MiB/256结构节点/8层；可显式收紧 max_depth。原单 Agent 成员序列化保持原形。父 Manifest 新版固定所有嵌套组件及完整子定义；Graph 的 compiler/transform/scheduler 同样固定。

每层仍提交真正的子 Run，独立 Session、同宿主 Scope、稳定父子链接和 escrow。取消递归传播，未知预算自底向上保留；只在整个相关调用静止时结算。按根级深度限制准入，不可通过嵌套定义绕过。没有无限递归、跨 Scope 伪造权限或隐式队列执行。

## 验收

并行依赖/结果绑定/条件跳过/循环拒绝；proposal→adoption 两阶段崩溃；patch CAS/重放/已派发冻结/取消竞争；嵌套 Agent/Graph/Team/Plan 的审批重启、原回执、预算及真实线程关闭；旧dev14 原生/flat/team兼容。默认模板和公开 API/配置配套，真实模型质量另按冻结任务评测。
