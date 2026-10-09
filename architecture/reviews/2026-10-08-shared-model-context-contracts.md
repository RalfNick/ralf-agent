# dev24 — 共享模型采纳与近期会话修复

本次沿用 [整体架构审查](2026-10-08-agent-framework-alignment.md) 的边界，
修复三个已复现 P2，并抽出公共纯规则。没有新增执行权威或隐含模型重试。

- Local／Temporal 新响应共用 `validate_decision`：声明工具、有效参数 Schema、
  最终输出与整批 call ID 验收；默认参数先解析，生成 ID 后再次检查碰撞。
  Temporal 重复 ID 不再生成待执行工具 Action。
- Activity v2 先保留响应证据，再解释提案与复核组件。拒绝 Schema、参数、
  工具或身份漂移仍结算已完成执行；取消后的已知响应只补证据和结算。
  原始响应、有效提案与 token 用量未知分别表达。
- 两个 ContextBuilder 共用完整近期 Session 后缀选择，支持原生 task/result
  记录与对话轮次；工具调用／结果成组保留，不跳过过大的最新轮次，
  原始存储与已保存请求不重写。

一位全新上下文 reviewer 检查了实际 dev23 wheel 对比增量、69 项针对性测试，
并补充六个拒绝／预算边界探针与三个旧状态转换对照。
确认一项 Important：整条响应序列化失败会丢失独立已知的完成与用量。
8 项新增复现先失败，再验证修复：保留合法字段、记录 `invalid_fields`，
拒绝采纳，并关闭未执行的 coroutine/generator。无效原始对象不能重建。
没有 Critical 或 Minor；按一轮修复执行，未再次派 reviewer。

## 验证范围

针对性模型／默认参数／Harness／上下文／控制回归为259通过、2个未配置服务跳过。
新真实 Temporal Schema／重复 ID 案例验证拒绝、用量、静默完成、History 重放与
Worker 重启；实际 dev23 wheel 的 native／graph／team／plan／DAG／nested
本地恢复，以及旧 Run／CommandRegistry History 重放单独验证。
最终全量 **1884通过**（380.99s，warnings as errors），安装包 **666通过**，
基础依赖／可选 SDK 阻断 **595通过、9个预期跳过**。包字节与静态门槛在
[实现进度](../../docs/implementation-progress.md)登记。
真实模型质量、跨框架对等表现和企业容量仍未验证。

## 审查边界与取舍

- 所有改动保留在当前工作区，完整本地验证代替发布；不提交、不推送、不清理旧增量与证据。
- 先共用采纳／证据／召回规则；每 Agent 能力绑定、简单 Agent/Session 入口和推荐受管理链路为下一步，完整对齐仍未交付。
- 旧 Activity 回执保持历史转换，包括过去的未知结果或重复 ID；没有追改旧事实。混合版本 Worker 部署未认证。
- 合适的完整引用与已保存请求不重写；原生 assistant/task 结果视为完整轮次，任意无 task 的 assistant 不能据此裁剪为完整证据。
- 无效字段保留安全标记而非原始非 JSON 值；已完成执行与未知 token 计量分开，不保证费用封顶。
- 实际服务、安装、starter、字节与升级门槛由实现方完成；证据覆盖测试组合，不代表生产认证。
- 分页性能、自动压缩／摘要、facade／绑定和混合部署仍是未交付门槛，长历史仍可能完整读入并重复计量后缀。
- Harness 原始响应与提案可以不同；应用语义依赖显式策略及版本，而非强制二者相等。
- 手工伪造／重复调用内部 accept_model 不属于公开接口；受支持的是 Activity 回执交付与 History 重放。
- 空调用 ID 继续生成 fallback，但有效 ID 必须唯一；空值本身不是拒绝依据。
- 完整合适的原始 Session 引用保持既有证据语义；裁剪单独验证完整性，不将引用当成认证执行事实。
- 任意 caller 的 task 元数据不是认证来源；有限 JSON wire 会规范化 tuple/list，未据此宣称任意 Python 对象等价。
- 旧增量保留与兼容检查不等于重新审查整个框架；未读取凭据或发起付费调用，对齐／质量／生产结论仍有限。

Deferred minors：无。共享规则的使用与限制见[契约指南](../../docs/shared-model-context-contracts.md)。
