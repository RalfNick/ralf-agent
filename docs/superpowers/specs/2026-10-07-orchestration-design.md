# dev14 动态规划与多 Agent

目标：新增 DynamicWorkflowSpec、TeamSpec 与可替换 Planner/PlanVerifier/TeamStrategy，LocalEngine 接受和恢复它们。原 Agent/sequence/static graph 保持原声明与 local-4，只有新定义增加 orchestration Manifest。它们是受管理父 Run，不另起执行日志或审批循环。

父子调用：每次委派固定调用 ID、AgentSpec/Graph、输入、Session 和预算上限；在同一个 ExecutionStore 事务中预留父预算、submit 子 Run、提交父子链接。子调用重复不创建第二个 Run。子 Run 的 parent_id/call_id 为观察链接，子消息不作为完成证据。成员只允许 AgentSpec，避免无界递归。派生 Session 独立，Scope 固定为同一 trusted host Scope。

预算：父 budget 为总上限。每个子 Run 先按独立上限 escrow 预留，子预算不能超过额度；完成且实际调用静止后结算已花费，未知 held 保留父 reservation。完成子 Run 不重复结算，异常/未知预算保守占有。并行无法超过配置并发上限。当前是 escrow 的共享总上限，不声称完整可嵌套账户体系。

TeamStrategy 为纯同步版本化策略，按已采纳成员结果提出 TeamSelection。默认 SequentialTeam、RouterTeam、SupervisorTeam（有限并行 workers + 最后 supervisor），显式路由值，不隐式模型调用。成员输入来自原任务和已保存结果，最大成员数与并发有限。支持自定义策略；提案只能调用未执行的注册成员，汇总有限 JSON。父失败/取消停止派发并把取消传播到已链接子 Run；晚到结果/未知效果保留可观察，真实 Task/线程持有原 Coordinator。

规划：Planner.plan 为 async 受管理提案；默认 RulePlanner 与 ModelPlanner，后者通过一个已注册受限 planner Agent 的子 Run 产出 JSON。DynamicWorkflowSpec 限定注册 worker、最大修订次数、每个 worker 的 child_budget 和最多执行步骤。计划只能指定 allowlist 成员、有限 step ID、JSON 输入、父总预算内调用；每个修订只创建新未执行调用，不能改写旧效果/已执行结果。

提案接收后独立持久化 received_proposal，再验证/采纳 PlanRevision。恢复使用保存提案，不重调 Planner。纯 PlanVerifier 依据已完成结果提出 succeeded/failed/replan，默认完成 verifier 和规则 verifier；保存结果快照/修订证据。重规划有硬次数上限；未知业务效果不得自动新调用替代。自定义 async Planner 必须只产生计划；外部副作用不被框架管理，应使用受管理工具/子 Agent。

审批与核验：挂起父 diagnostics 包含子 Run、待审批 Action 和未知效果；用户对实际子 Run approve/reconcile，父 drive 恢复。已取消父不可重开；新调用前复核 Manifest 和父状态。保存策略/Planner/Verifier/worker identities，组件变化拒绝继续，已有 command receipt 仍能重放。

错误与取消：父 drive 使用现有 in-flight/shield/thread 归属。bulk Task 取消不能释放真实子 handler；重启以保存父子链接、提案和执行证据恢复。失败策略默认 fail-fast，取消其他在途孩子，保留其效果，不把异常正文存入 Run。未交付远程 A2A、MQ、跨 Scope 委派、无限层团队或通用流式节点。

验收：团队三种策略、自定义策略、计划/重规划、能力拒绝、共享总上限、child approval/replay/restart、未知效果保留、父取消传播、真实线程关闭门槛、提案接收后崩溃不重复规划、旧 native/v3 恢复、配置 starter 与安装包证据。模型规划 fixture 不代表真实模型规划质量。
