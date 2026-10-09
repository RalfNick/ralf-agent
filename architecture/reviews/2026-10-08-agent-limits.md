# dev30 — Local Agent limits / H1f

日期：2026-10-08；基线：实际dev29 SDK/wheel → 未提交dev30增量。

交付：纯AgentLimitsPolicy、不可变Proposal与FixedAgentLimits；宿主／AgentSpec／所选
策略取最小值；有效上限随首次接受发布固定；决策／上下文／工具动作额度实际执行。
批次超量整体拒绝，不生成可执行工具Action；恢复／核验既有Action不重复占槽。
Local原生、顺序、图／并行、Team、动态flat/DAG与嵌套成员支持limits绑定、JSON/TOML
与sync/async工厂。显式选择kernel6；默认未配置保持旧发布兼容。

## 行为审查与修复

- 纯策略RED15 → GREEN15；执行／绑定RED27 → GREEN，初版Task2相关测试174通过。
- 补充复现：虚拟并行节点重新计算策略可换掉父Run接受的caps。RED实际绕过cap1；
  修复为父级固定事实投影，包含并行/绑定98项测试通过。
- 一次独立最终审查发现一项 Important：成员首次创建子 Run 时可能重新接受比父级
  已固定成员更宽松的caps。12个无绑定／绑定的Team、动态flat/DAG、顺序／并行图及
  嵌套Team案例实际RED复现。修复为接受及恢复时递归比较原成员固定caps，并记录
  limits-bearing父子关系的原成员身份；未配置limits的旧关系字段不变。
- 修复后102项相关案例通过；另补六个团队／规划／嵌套审批重启与两个受管理模型
  Planner案例。最终相关测试194通过。无Critical／Minor，Declined为空；未重复审查。

## 最终验证

- 最终完整 **2183 passed／44 skipped**，344.41s；跳过项依赖未配置的真实服务。
  Ruff、格式（453文件）与Git空白检查通过。
- 在checkout之外实际安装的dev30 wheel **320项契约通过**，10.43s；
  SDK／wheel／sdist／安装包134个模块字节一致，私有日志／数据库／凭据未进入产物。
- 实际dev29创建13类审批，dev30恢复原提交／审批回执、Manifest／Release，13项
  业务效果各一次。覆盖大Schema、各编排形态、Session/Facts/Verifier及混合绑定。
- 旧wheel拒绝新limits发布、模型调用0、证据不变；新limits审批重启后继续成功，
  合计14项效果各写一次。没有新增付费模型测试或改变历史质量报告。

全部证据保留本地；未提交、推送或发布。当前是开发预览，不能由测试数量推断AgentScope对齐或生产可用。
全局容量、期限、真实费用、环境／Artifact阶段、H2与Temporal绑定仍待交付。
