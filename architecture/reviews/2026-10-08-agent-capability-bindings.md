# H1a 能力绑定实现与审查 — dev25

日期：2026-10-08；基线：本轮修改前的实际 dev24 工作区与构建 wheel。
本轮交付原生 Agent/顺序 Workflow 的六类组件绑定，不标记完整 H1 或 H2 完成。

## 实现与架构边界

- 新增不可变 BindingSelection/AgentBindingDescriptor/AgentDefinition/BoundDefinition，
  不修改 AgentSpec 或旧请求的字段。
- BindingCatalog 固定可信 Scope、role/id/version 与组件 identity，对象默认 borrowed；
  Engine 使用按 Run/步骤选出的组件视图，不切换全局 current_agent。
- provider、decision_policy、context、facts、knowledge、tool_set 有真实路由。
  工具选择不得超过原 Agent 声明，HostPolicy/审批/执行器与预算继续由宿主控制。
- local-bindings-1 逐步骤固定发布；原未绑定 local-4/Profile v1/命令身份保持。
  收到模型响应先持久化，再检查绑定漂移，缺失原组件不回退新版本。
- JSON/TOML schema v2 通过原 ComponentRegistry/BuildContext 装配；
  同步/异步工厂及 owned/borrowed 关闭沿用已验证生命周期。
- Session 可继承或关闭，资源覆盖/selectors、Graph/Team/Dynamic/Temporal绑定、
  新 Facade/SessionAdmission/关闭语义均为明确未交付能力。

## 独立审查与修复

独立只读 reviewer：/root/h1a_binding_review，针对本轮与保存的 dev24 SDK 差异审查。
发现一项 P2：CLI 仍按旧顶层 providers/tools 读取新的逐步骤 manifest，导致
inspect、文本 status/run/resume 抛 KeyError。

三个实际复现测试先失败，再通过。新增纯记录访问函数供 Engine/CLI 使用：
按每个 Action 的 node 获取工具效果，不合并相同逻辑 Provider 槽位；
诊断展示每个步骤的绑定及模型。相关 CLI/执行回归 35 passed。

审查未发现其他可操作问题。reviewer 明确未判断的范围为 Session override/队列、
高级/Temporal绑定、H2、迁移/IAM及线上模型质量；这些仍是后续阶段，未被视为已验证。

## 验证证据

- 新声明、执行、装配与 CLI 测试：60 项；实际安装 wheel、从仓库外导入运行，60 passed。
- 最终完整回归：1902 passed、42 skipped，292.11 秒。跳过项需要未配置的远程服务；
  本地临时 Redis/HTTP fixture 经过实际执行，不能代替缺失服务的验收。
- 首次普通沙箱回归记录为 2 failed/1877 passed/40 skipped/22 errors；
  失败/错误来自本地服务端口绑定被拒绝。获准扩大测试权限后最终回归通过。
- Ruff、格式、Git 空白检查通过；127 SDK 文件与最终 wheel 内容逐字节一致。
- 文档相对链接、示例基本语法检查通过；绑定教程 Python 示例从实际安装包运行成功。
- 实际 dev24 wheel 创建等待审批；dev25 找回原提交/重复批准回执并成功恢复，
  原 manifest/release 保持，业务服务只写入一次。旧 wheel 拒绝新绑定发布而未执行。
- 没有调用真实模型、读取凭据、提交、推送或发布；测试数据及证据保存在本地。

本轮不重跑真实 Temporal History/PG/Qdrant 套件，也不宣称模型质量、完整M1或框架对等能力。

入口：[绑定教程](../../docs/agent-bindings.md)、[完整绑定目标](../specs/agent-capability-binding-contract.md)、
[实施计划](../../docs/superpowers/plans/2026-10-08-agent-capability-bindings.md)、
[当前实现状态](../../docs/implementation-status.md)。
