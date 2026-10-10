# dev42／H3a2 自动模型记忆阶段验证与审查

基线0d17976／dev41；[规格](../../docs/superpowers/specs/2026-10-10-managed-model-memory.md)、
[执行计划](../../docs/superpowers/plans/2026-10-10-managed-model-memory.md)。
Local 原生／顺序，默认关闭。纯 ManagedModelMemoryPolicy 让模型选择允许的
结果字段；值由宿主来源取回。原 memory_stages 保存选择意图／响应／字段／预算，
继续复用事实 CAS 与准确回执。新语义9拒绝旧代码；默认和旧 schema 保持。

定向覆盖空／非法／未知选择、派发／响应／字段／CAS 重启、独立证据损坏、
Provider 替换漂移、校验取消、真实异步任务托管、不可追加未选字段和声明工厂。

## 一次独立审查与修复

一位 fresh-context gpt-6-astra/high reviewer 只读审查完整本阶段差异和所有新文件，
运行44项新增测试，并补充复现。无 Critical／Minor，四项 Important 按实际影响保留：

1. P1：派发前缺少独立预算证明核验。伪装成支持扩展的 Store 不保存 reservation
   仍会调用模型。现在在派发事务内复核 executing journal 与准确 reservation；缺失
   或矛盾的证明在模型调用前拒绝。
2. P1：同 release 替换隐藏实际策略／目标方法漂移。现在捕获并检查真正执行过的
   request/select/admission 及 CAS/准确查询/分页查询/validate 方法的原策略。Scope
   丢失也作为固定发布违约传播，不落入辅助未知；写入可能已发生时保留 writing 与
   held evidence，不能静默确认原契约成功。
3. P2：同步校验结束后授权已过期仍派发。现在在派发事务内、reserve 前重查期限；
   已合法派发的旧响应仍可按证据结算。
4. P2：普通 request／provider validation 异常影响已完成业务。现在仅组件纯准备／
   校验异常转为持久辅助失败，零 selector 派发／预算。权限、发布身份和持久化错误
   继续传播；提案存储失败不伪装成 selector hook 失败。

四项先以9项 RED 复现；持久化错误补1项 RED，Scope 的四类 I/O 补4项 RED。
一轮修复后150项相关回归通过；最终 boundary 模块16项通过。无二次审查或延期 Minor。

## 发布和兼容证据

- 冻结 wheel 安装后的相关契约206 passed；SDK 与分发 metadata 均0.1.0.dev42。
- 实际 dev41/dev42 wheel 双向接续11类默认定义的审批；原回执与 release 保持，
  每个方向恰好11个不同业务效果，重复控制／提交不追加效果。
- 旧 schema2–7 的六种实际 Session 组合由新 wheel 接续，恢复 Provider 零调用；
  旧 schema8 的独立摘要响应保存窗口由新 wheel 采纳，没有重复摘要。
- schema9 在派发、响应、字段采纳、CAS 回执四个真实关闭／重开窗口恢复；新
  Provider 业务／selector 零调用，已确认事实一份，未知派发 held1不重试。旧 dev41
  在 writable／readonly 两种模式均拒绝四个新库（8次拒绝）。
- source/wheel/sdist/installed 共161个 Python 模块逐字节一致；原296 root exports
  保留，新增 ManagedModelMemoryPolicy 后297；实际生成的21个 starter 文件树哈希
  与 dev41 完全相同。依赖、extras、CLI scripts、Python 声明不变。

冻结完整回归2738 passed／66 configured-service skips，379.10s；使用 `-W error`。
Ruff、568个文件的格式检查、Git 空白检查和本轮修改文档链接／凭据模式检查通过。
未配置的真实服务保持跳过，不据此确认线上服务兼容。最终 wheel SHA256：
`2ba296c6c15501c36e632e855eb1e523f80b92c19b55d930aa55d04afb323749`；
sdist SHA256：`645db58a3a80e93f89c4770874bdbdf1c2aebf4a53f6cf825792acf000651d06`。

## 本轮裁定与未评估范围

按作出顺序保留所有裁定：

- 沿用用户授权的 feature checkout／inline／本地提交；代价是共用工作区隔离和
  范围风险由实现者承担。
- 首期仅模型选择允许的已完成结果字段、Local 原生／顺序；保持来源和既有权威，
  代价是自由合成、高级／Temporal 和完整 H3 仍未覆盖。
- 最终提交前审查 working-tree／新增文件，补足空 commit range；代价是遗漏风险，
  通过全量新增文件清单审查补偿。
- 审查未评估自由合成、高级／Temporal／完整 H3；规格明确限定子集，代价是能力
  广度及框架对等仍未完成。
- 审查未评估付费模型和线上服务质量；本轮仅确定性 fixtures，无付费调用，代价
  是不能得出模型质量或线上兼容结论。
- 审查将完整回归／构建／安装兼容交给作者冻结验证；作者执行这些门槛，代价是
  弱于独立复现整套发布资格。

无真实模型或真实服务新增质量结论，不把功能覆盖称为 AgentScope 对等验收。
