# dev41／H3b1 受管理上下文准备验证与审查

基线 `7898b78`／dev40；范围为本阶段最终工作区。按
[设计规格](../../docs/superpowers/specs/2026-10-09-managed-context-preparation.md)与
[实现计划](../../docs/superpowers/plans/2026-10-09-managed-context-preparation.md)
持续 inline 开发、TDD、一名全新上下文只读审查、一轮修复；只做本地提交。

Local 原生／顺序自动摘要复用纯 context 绑定与原执行权威，默认关闭；
完整遗漏历史组、固定来源与引用、独立预算、摘要意图／响应／业务投影分阶段
保存。未知模型调用保留额度且不重试；终态仅采纳已有证据。原 Action／Session
证据及最新完整工具组保留。JSON／TOML 工厂与 schema8 原子准入已接通。

## 独立审查与一轮修复

一名全新上下文只读审查发现四个 Important，无 Critical／Minor；
Declined to judge 为空。均确认实际影响并在同一轮完成六个 RED→GREEN 用例：

1. prepared 状态保留 reserved／unknown 独立额度，可复用一次额度再次调用。
   prepared 必须尚无任何派发预留证据；矛盾恢复和只读回执均拒绝。
2. 摘要调用中替换注册项可掩盖实际 Provider 漂移。先保存响应，再检查实际
   返回响应的对象；不采纳错误发布输出，终态可离线结算已有响应。
3. 同步请求校验中取消仍会派发摘要。派发事务重读 terminal／cancelling；
   关闭业务后不预留、不调用，只保留未派发阶段用于证据恢复。
4. Temporal 接受纯 assemble 外形却忽略自动摘要。注册时明确拒绝两个模式，
   已支持的普通纯 ContextBuilder 保持原契约。

修复后定向 **120 passed**；没有发起第二次审查。包装核对额外发现 SDK 版本
常量未同步，已用真实旧安装包复现 RED，并校正至 dev41、增加一致性测试。
该修正后重新冻结全量与分发验收。独立审查不认证后续作者执行的分发／服务结果。

## 已完成的分发与兼容验证

| 检查 | 结果 |
| --- | --- |
| 冻结 wheel 安装后定向契约、warnings-as-errors | 163 passed |
| dev40／dev41 默认定义双向恢复 | 每方向 11 类原生／顺序／绑定／图／并行／Team／Plan／DAG／嵌套／transform；原回执与 Manifest 不变，每方向11个唯一业务效果 |
| 实际 dev40 schema2–7 Session 原回执续接 | 6 类；新版恢复不调用模型 |
| schema8 旧版拒绝与实际新版重启 | dev40 只读／读写均拒绝；新版分别复用已保存响应及保留未知调用额度，均不重复摘要 |
| source／wheel／sdist／installed | 159 个模块内容一致，SDK／分发版本均为0.1.0.dev41 |
| root exports／starter | 原295 exports保留，新增ManagedContextPipeline共296；两版各实际生成21种，文件摘要全部一致 |
| 依赖与静态检查 | dependencies／extras／scripts不变；Ruff、格式、Git空白、凭证模式卫生及修改文档262个本地链接通过 |

最终全量 warnings-as-errors：**2678 passed／66 skipped，391.27s**。
安装包额外验证分 Agent 的 Provider／Context 绑定、AgentRun 回执，以及摘要额度
耗尽后的固定 fallback、无隐藏调用；均通过。未配置的真实服务保留跳过，
本阶段没有进行新的 Redis／PostgreSQL／Temporal 线上或真实模型质量认证。

## 实施取舍

- 沿用用户已授权 feature checkout、持续 inline 和本地提交，不新增常规确认；
  代价是实现者承担共用工作区隔离与范围判断。
- 首期仅摘要同 Run 完整遗漏历史组，限定原生／顺序；代价是 Session／RAG
  自动压缩、高级／Temporal 组合与完整 H3 未交付，已明确拒绝或列为待办。
- 审查提交前完整 tracked diff 与新增文件，验证后一次本地提交；代价是
  未提交范围可能漏收，由独立文件清单和最终 diff 复核。

没有调用付费真实模型，不宣称事实保留、业务任务质量或 AgentScope 对等质量。
没有配置的真实服务保留显式跳过。未知摘要没有远端查询接口，额度不会自动释放。
执行权威持久记录间的独立缺失／矛盾必须拒绝；不提供被攻破权威的密码学完整性。
见[使用与剩余范围](../../docs/managed-context-stages.md)。
