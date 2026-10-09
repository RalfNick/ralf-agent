# AgentHarness 命名、Facade 契约与 AgentScope 参考修订

日期：2026-10-08；RALF 实现基线：0.1.0.dev24。
范围：架构文档及相关源码边界核对。本文未交付 H1/H2 SDK，也未运行新 Facade 的行为测试。

## 1. 审查结论与三个 P2 的处理

保留 AgentHarness 包含 Core、纯 DecisionPolicy 提案、每 Agent 能力绑定与单一执行权威的主结构。
三个 P2 都成立，不能直接包装现有 drive/close 来实现统一入口。
新增[Agent Facade、Session 与关闭契约](../specs/agent-facade-session-contract.md)作为 H2 的规范输入。

| 审查项 | 当前实现证据 | 修订后的目标契约 | 状态 |
| --- | --- | --- | --- |
| 等待、超时与取消 | LocalEngine._guarded 在 caller 取消时提交业务取消；Temporal.drive 等待超时返回 snapshot | run=持久 submit+观察 wait；wait_timeout/断连/caller 取消只结束观察；显式 cancel 和持久 deadline 独立；Local Runtime 单独托管 drive | 设计闭环，待 H2 实现与共同验收 |
| 跨 Run/重启的串行 Session | Local submit 检查执行存储的 session_owner；没有耐久 Turn 队列 | SessionKey 固定 Scope/实际资源/namespace/session_id；绑定修订与协调后端固定；首期耐久 reject_if_busy；审批/输入/核验续接原 Run；queue 首期拒绝 | 设计闭环，待 H1/H2 实现 |
| owned/borrowed 与退出 | 当前 Engine.close 保护在途执行和失败关闭；没有统一 Agent Facade 的责任协议 | 独立 Agent 拥有自建 Runtime；共享 Agent 借用；默认 drain 到终态/稳定等待点，保留 RunRef/Session 占用；CloseIncomplete 保留必要归属；活句柄关闭后显式重连接 | 设计闭环，待 H2 实现 |

当前 RALF 源码定位：

- [Local 等待取消](../../src/ralf_agent/engine.py#L838)、[Local Session 准入](../../src/ralf_agent/engine.py#L481)、[Local 关闭](../../src/ralf_agent/engine.py#L221)。
- [Session 占用读取](../../src/ralf_agent/storage.py#L206)、[Temporal 等待](../../src/ralf_agent/temporal.py#L350)。

上述源码链接仅作本次工作区定位；行号会随实现变更。旧 drive、原 AgentSpec/Profile/Manifest 和命令身份不在本轮改写。
新 Facade 的目标语义必须通过版本入口实现，不能把文档修订标成这些 legacy 接口已经改变。

## 2. 命名决定

| 名称 | 定位与使用原则 |
| --- | --- |
| Agent | 唯一面向应用的原生 Agent 入口；不再增加 HarnessAgent 与其竞争 |
| AgentHarness | 每 Agent 的策略、能力组合与受管理阶段；包含 Core 执行循环的逻辑系统 |
| Runtime | 宿主资源装配、owned/borrowed 生命周期与本地执行任务托管；多个 Agent 可以共享 |
| DecisionPolicy | 纯准备/提案职责；现有 Harness/NativeHarness API 保持兼容 |
| RuntimeKernel | 公共纯校验与确定性规则的逻辑边界；按重复规则逐步提取，不先创建大而全的 Kernel 类 |
| ExecutionAuthority | Run 事实的唯一权威概念；Local Coordinator/SQLite 或 Temporal Workflow/History |
| ExecutionEngine | 应用与后端执行协议；具体实现仍保留 LocalEngine/TemporalEngine 等已有名称 |
| RunTaskSupervisor | Runtime 内部的本地 Task 托管组件，不决定业务状态或创建另一套恢复日志 |
| SessionAdmission | 执行后端中的串行 Turn 准入协议；不是会话消息存储，也不是第二个业务调度器 |

目标组件采用 AgentHarness，替代先前目标名称 HarnessRuntime，避免与共享宿主 Runtime 混用。
历史文档文件名 harness-runtime.md、既有类名和导入路径保持兼容，不做机械全仓改名。
新公开类型在实现时再检查导出、序列化版本和现有 RuntimeBuilder/RuntimeInstance/TemporalRuntime 的职责。

## 3. 用户指定 AgentScope 源码参考

本地路径：/Users/bytedance/PycharmProjects/agentscope。
读取快照：2.0.10dev，commit 48c4b9ce0f9a3f86e5c3385d43cd2220245eef10，2026-10-08。
该快照与此前引用的 v2.0.9 不同；只读源码，不运行其服务或模型，不修改该 checkout。
以下路径相对该 checkout，结论限于此快照，不代表所有历史版本或最新远端发布。

| 源码位置 | 观察到的组织方式 | RALF 借鉴与边界 |
| --- | --- | --- |
| src/agentscope/agent/__init__.py；agent/_agent.py:117、288、332 | 导出统一 Agent；reply/reply_stream 消费同一循环；显式配置模型、Toolkit、Middleware、state | 简单统一入口与高级配置渐进开放；RALF 的 wait/control 仍按耐久命令区分；此快照未导出 HarnessAgent |
| src/agentscope/event/_event.py | typed 生命周期、内容 delta、确认、中断与外部结果事件 | 统一展示/续接协议；delta 不作为已采纳决策，批准或输入必须对应原持久等待对象 |
| src/agentscope/tool/_toolkit.py:66 | 工具 Schema、调用、分组、MCP 与 Skill 的聚合入口 | 借鉴工具目录的组织和开发体验；保留 RALF 的工具发现、宿主授权、效果分类和执行回执分工 |
| src/agentscope/middleware/_base.py；agent/_agent.py | reply/reasoning/permission/acting/model/context 等组合钩子 | 扩展点明确且组合方便；RALF 纯策略保持无 I/O，受管理摘要/检索不藏入观察 hook，hook 不改变权威终态 |
| src/agentscope/state/_state.py:209 | AgentState 组织 session_id、上下文、摘要等连续交互状态 | 借鉴 Session 状态组织；Run/Action/审批/未知效果仍有独立耐久事实，不能合并成整体 AgentState |
| src/agentscope/app/_router/_chat.py:1；app/_manager/_chat_run_registry.py:23 | 请求触发后台运行；SSE 单独订阅；registry 强引用 Task；新输入与 HITL 唤醒路径分开 | 借鉴执行与观察分离、宿主 Task 托管和明确续接；Task 索引不等于持久 Turn 队列，H2 的占用由执行后端记录 |
| src/agentscope/app/_service/_chat.py:797、1497 | 会话执行锁；取消时 shield 并等待保存 Task，保存结束后才离开会话锁范围 | 借鉴保存后解除占用；RALF 还需跨 Run/重启的 Turn/绑定修订、远程保存回执及真实 handler 静默证据 |
| src/agentscope/app/_lifespan.py:40、58 | 统一 AsyncExitStack 组织依赖与后台服务，逆序关闭 | 借鉴所有权和异常路径收尾；RALF 默认 drain/稳定暂停及 CloseIncomplete 必须明确 |
| src/agentscope/app/workspace_manager/_base.py | 工作区与隔离环境有独立生命周期端口 | 保留 Workspace、Sandbox、Skill 的独立可替换角色；源码阅读不证明 RALF 已提供实际隔离 |

特别不照搬：

- Agent._reply 对 CancelledError 的业务中断处理，不能定义为 RALF 观察 Task 的取消行为。
- ChatRunRegistry.__aexit__ 取消所有 Task，不能替代 RALF owned Runtime 的默认 drain。
- 当前 AgentScope A2AAgent 约定拥有注入客户端；RALF 统一注入资源默认 borrowed，显式 own 才关闭。
- MessageBus 的锁/队列、AgentState 和展示事件，不能替代 RALF 的 Run 权威、效果日志或耐久 Turn 接受记录。

这些是对源码组织的选择性借鉴，不是能力对齐、可靠性优越或兼容性的实验结论。

## 4. 唯一权威与实施顺序

Session 协调是会话准入权威，Run 执行是业务权威，二者各负责一种事实。
Local 可事务记录 Turn/占用/Run 意图；Temporal 由 Session 协调 Workflow 记录准入与启动意图，
Run Workflow 仍独占 Action/审批/预算/终态。跨 Workflow 启动采用固定身份及补偿恢复，不能宣称共同事务。
SessionStore 只负责消息内容/版本，远程 append 的幂等回执确认后才解除相应占用。

顺序保持 H1→H2→H3：

1. H1 落实[能力绑定](../specs/agent-capability-binding-contract.md)，包括稳定资源身份、作用域、固定 Release、后端支持/拒绝和 owned/borrowed。
2. H2 先交付独立执行托管、纯观察 wait、耐久 busy 拒绝、Session 修订和关闭/重连接。后端能力不齐时明确拒绝，不开放表面等价入口。
3. H3 复用已有受管理 Agent/Action 组合默认检索、摘要和记忆链路；新阶段有独立版本、预算和接收证据。
4. Turn FIFO、Workspace/Skill/Sandbox、完整企业服务及其他后端能力按各自门槛推进，不混入首期 Facade。

验收采用[Facade 契约第9节](../specs/agent-facade-session-contract.md#9-h2验收矩阵)，
覆盖两后端观察取消、提交不确定、忙碌续接、Session 别名/重启、共享关闭、超时/线程退出和真实旧版本恢复。
这些是后续必测要求，本次只检查文档一致性、链接/示例基本语法和 dev24 SDK 字节未改变。

相关入口：[总架构](../design.md)、[AgentHarness 架构](../viewpoints/harness-runtime.md)、
[建设顺序](../../docs/agentscope-alignment.md)、[当前实现状态](../../docs/implementation-status.md)。
