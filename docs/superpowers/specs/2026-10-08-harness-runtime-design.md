# AgentHarness 目标设计规格

日期：2026-10-08；状态：用户明确要求按已讨论的理想架构形成设计。
本次交付设计与现有架构整合，不包含新SDK实现或版本发布。

## 用户意图与约束

个人开发者配置模型和工具即可运行；每个Agent可独立定制上下文、记忆、
知识、策略和环境；静态/动态Workflow与Team保持共同执行/恢复语义；
本地无外部依赖，企业按需替换存储、Workers、沙箱和Service。
不得通过适配器数量宣称对齐AgentScope，亦不能破坏已验证的审批与效果契约。
保留当前dirty工作区、旧Run/History和证据；不提交、不推送、不读取凭据或付费调用。

用户认可的总体设计及规范内容集中在：
- [AgentHarness组件设计](../../../architecture/viewpoints/harness-runtime.md)；
- [Facade/Session行为契约](../../../architecture/specs/agent-facade-session-contract.md)；
- [审查修订与AgentScope源码参考](../../../architecture/reviews/2026-10-08-agent-harness-facade.md)；
- [每Agent能力绑定契约](../../../architecture/specs/agent-capability-binding-contract.md)；
- [更新后的总架构](../../../architecture/design.md)。

## 确定决策

1. 广义Harness包含Core；现有Harness/NativeHarness保持DecisionPolicy的纯同步兼容。
2. AgentHarness负责组合、Facade和阶段组织；每Run的执行权威仍唯一。Runtime保留为宿主资源和任务托管，公共Agent不再增加HarnessAgent副本。
3. CapabilityBindings按Agent固定，不把普通团队拆成多套不协调Engine。
4. 原AgentSpec/Profile/Manifest不通过增加默认字段改变摘要；新语义用版本包装。
5. Context/Memory/RAG/Artifact构成受管理管线；纯策略无隐藏I/O/费用/重试。
6. 执行/Session/Facts/Knowledge/Vector/Artifact/展示分别管理，默认组合可独立替换。
7. Service、Sandbox和外部Runner通过明确能力接口接入，不虚构隔离或逐步恢复。
8. 首先H1绑定、H2入口，再H3默认链路、H4环境/协作、H5后端/企业治理。
9. H2统一wait只观察，deadline/cancel独立；串行会话首期耐久busy拒绝，queue显式不支持；关闭区分owned/borrowed，默认drain保留原待办，失败不释放必要归属。
10. AgentScope参考固定为用户指定本地2.0.10dev源码，借鉴统一入口/typed事件/工具目录/宿主生命周期，不照搬Task取消或整体AgentState恢复。
   总体范围必须拆成独立实施规格，不能一次重写整个Engine。

## 本次设计交付验收

- 图与文字的Harness/Core/执行权威定义一致，所有新接口标为目标而非已实现。
- 对组件给出职责、默认行为、替换位置、作用域、版本和生命周期要求。
- 首期绑定明确inherit/ref/disabled、请求与Release身份、资源范围、
  HostPolicy上界、父子传播、本地/Temporal拒绝矩阵和恢复兼容。
- 自动辅助工作有required/best_effort语义，后台任务需独立接受/预算；
  展示delta不提前采纳动作，业务验证级别不冒充默认质量保证。
- 更新总架构、能力视角、路线与入口链接，修正dev24三个P2已经修复的过时说明。
- Markdown相对链接、Mermaid和示例基本语法可检查；
  现有122SDK字节与dev24验证快照一致，产品版本与运行代码不变。

## 后续开发入口

H1是下一份实施规格/计划的范围；H2在独立Facade契约下实现任务托管、耐久准入及关闭，禁止直接包装legacy drive伪装语义一致。后续以组件设计第12节阶段门槛逐项推进。
本次不提前编造新Agent/Binding API实现或将未支持Temporal组合标为兼容。
设计文件的可审查交付即本次任务结果，不要求再确认已明确的设计授权。
