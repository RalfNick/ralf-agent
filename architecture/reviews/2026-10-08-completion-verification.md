# dev29 — Local completion verification / H1e

日期：2026-10-08；基线：实际 dev28 SDK/wheel → 本地未提交 dev29 增量。

交付：纯 CompletionVerifier 与脱离执行状态的 DTO；可配置工具回执对应规则；
最终 Action 上的验证记录、有界反馈、审批与原预算；Local 原生、顺序、图／并行、
Team、Dynamic、嵌套成员 verifier 绑定与同步／异步装配。
无验证器的旧发布记录保持兼容；显式选择使用 local-bindings-5。
完整 H1、H2、受管理 async/model Verifier、PlanVerifier 默认业务验证及 Temporal 绑定仍待交付。

## 本轮初始验证

- Task1 RED21 → GREEN；完成门槛101 passed/2 skipped。
- Task2 RED14/legacy1pass → GREEN；绑定／核心／业务137 passed。
- 完整回归2095 passed/44配置依赖跳过；安装包232 passed。
- 实际dev28创建十类审批任务，dev29保留原manifest/release及提交／审批回执后恢复；
  测试业务服务十项效果各写一次。覆盖1.1MB合法Schema、原生、绑定Agent、顺序、
  图、并行、Team、动态、嵌套、Session与Facts资源。
- 实际旧wheel拒绝新verifier发布，状态证据保持原样、模型调用为零。
- [真实模型固定试验](../../docs/live-model-quality-dev29.md)：8/8、17次调用，
  三个修复各一次retry与一次批准写入；五个缺输入／应拒绝任务没有业务写入。

独立最终审查发现并复现两项 Important：外部 Schema 引用隐式 I/O 与结构化任务类型不一致。一次 TDD 修复：规则使用 non-retrieving registry；任务来自执行权威及前驱归一化结果。RED11／控制7 → GREEN59；无 Critical／Minor，Declined to judge 为空。修复后完整回归2113 passed／44配置依赖跳过（329.13秒），实际安装包250 passed；重新由dev28创建十类审批任务，修复版dev29恢复全部原回执且十项效果各写一次，旧wheel拒绝新发布。最终SDK／wheel／sdist／安装包的133个模块字节一致；公共试验报告无凭据、路径或私有数据库。没有提交、推送或发布；凭据未持久化。
