# Temporal Session／Turn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在统一 Agent/Session 入口提供 Temporal History 持久会话、串行 Turn、原绑定续接和恢复。

**Architecture:** Session 协调 Workflow 只负责路由、Turn/Run 启动意图和 Conversation；业务 Run Workflow 继续独占 Action/审批/预算/终态。先持久接受原 Turn/RunID，再幂等注册/启动，按原 Run 的独立静默/未知效果证据释放占用。

**Tech Stack:** Python3.11+、可选 Temporal SDK、现有公共 SessionKey/SessionRef/TurnAdmission/RunRef。

**Spec:** architecture/specs/agent-facade-session-contract.md 第5–9节。

## Global Constraints

- 用户持续开发授权优先，沿既有批准架构直接执行；仅本地提交，不推送。
- reject_if_busy；queue 不支持；审批/核验/取消作用于原 Run。
- Session 身份包含 Scope、实际 Namespace UUID 的资源身份、namespace/session_id。
- 使用 DescribeNamespace 取得实际 UUID；不能以可任意填写的 endpoint 别名生成另一占用。
- 新能力显式 opt-in session_protocol=1；旧 raw session_id／默认-off 发布保持。
- History Conversation 为首个默认存储；外置 Redis/PG Session 数据以现有端口后续接入，不能把端口存在标成验收完成。
- 控制 Workflow 不调用模型/业务工具；既有 Core/Harness/History 权威不变。

## Review Focus

- 接受后 caller 断连、Worker kill：原 Turn 与启动意图保持，不能释放可能已启动的占用。
- 相同 command_id 在忙碌后重放：原拒绝保持，绑定/默认移动不改旧回执。
- terminal 但 unknown／reserved／未静默／journal ack 尚未确认：仍忙碌。
- 旧 SessionRef 在 rebind 后：旧回执可找回，新输入拒绝；CAS只影响以后Turn。
- Namespace alias 与 Scope／namespace：同真实资源不重复占用，不同资源不静默续接。

### Task 1: 纯 Session 接受与证据协议

**Files:** Create src/ralf_agent/temporal_session_state.py; modify temporal_activities.py, temporal_state.py, temporal_parent_state.py; test tests/test_temporal_sessions.py.

**Interfaces:** TemporalSessionState(accepted).command(request), snapshot(), turns(after,limit), start_intent(), adopt_observation(proof). session_protocol=1；session_turn 和 session_history 为原 Run 请求的一部分。

- [x] 写行为测试：唯一 seq/run、busy/重放、旧ref与CAS、真实 NativeState 结果采纳、unknown/ack阻断、Scope/来源校验。
- [x] 运行缺能力RED；实现纯状态与新请求/发布验证；保持原默认身份。
- [x] 原Session/Temporal相关回归GREEN，记录容量/历史界限和未交付范围。

### Task 2: History 协调、原 Run 通知与启动恢复

**Files:** Create temporal_session_workflow.py, temporal_session_activities.py; modify temporal_workflow.py, temporal_parent_workflow.py, temporal.py.

**Interfaces:** ralf.temporal.sessions.v1 Workflow；command Update、view Query、wake Signal；注册原 Run identity 与 session observation Activity；原 Run 在静默终态通知协调者，查询/等待不推进。

- [x] 写并确认真实Service RED：busy审批、重复提交、Worker重启／已完成Turn、根子编排、History replay。
- [x] Session History 先接受 intent；幂等注册并启动原业务子Workflow；通知后独立读取原请求/发布/静默证据，原子保存Conversation并释放。
- [x] 审批期间不以高频轮询生产无限History；失败保留占用，显式控制唤醒恢复。
- [x] 实际Service验证GREEN；旧History replay保持。

### Task 3: 统一异步 Session API、文档与验收

**Files:** Create temporal_agent_session.py; modify temporal_agent_runtime.py, agent_runtime.py/capabilities where needed; tests/test_temporal_session_facade.py, service fixtures; guides/queue/status/acceptance/CI/version.

**Interfaces:** await runtime.open_session(...), await runtime.aattach_session(ref), async Session submit/status/turns/rebind；返回原公共DTO及TemporalAgentRun，owned客户端仅detach。

- [x] RED→GREEN：RPC配置固定/取消接受/关闭、跨Runtime重连与原RunRef、实际namespace UUID/alias、非法Scope/queue/rebind。
- [x] 完整pytest、真实源码/安装服务恢复、core-only默认、实际旧新wheel/默认Manifest/原Run兼容、Ruff/格式/空白。
- [x] 一位只读独立review；修复P1/P2并补复现；同步能力清单，明确外置Session存储、迁移、容量治理与其他R01–R26仍待完成。
- [x] 完成验收后仅本地提交，继续整体能力目标。
