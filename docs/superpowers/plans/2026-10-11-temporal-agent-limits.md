# Temporal Agent Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将已有可替换 AgentLimitsPolicy 接入 Temporal 宿主和每 Agent 绑定，固定采纳的有效上限。

**Architecture:** Worker 的纯策略 Activity 返回 host/agent 原始提案；原 Run History 验证来源并采纳与 AgentSpec 的交集。既有 Run 继续独占审批、Action、预算、上下文和终态；Parent 沿原绑定路径传递选择。

**Tech Stack:** Python 3.11+，现有 AgentLimitProposal/FixedAgentLimits、BindingCatalog、可选 Temporal SDK。

**Spec:** architecture/specs/agent-capability-binding-contract.md；docs/agent-limits.md。

## Global Constraints

- 仅本地提交，不推送；默认无 LimitsPolicy 的旧发布和 History 保持原行为。
- 显式 limits_protocol=1；策略必须同步完成且返回严格 AgentLimitProposal。
- disabled 只禁用 Agent 选择，不能绕过宿主策略或 AgentSpec 上限。
- 策略为纯函数，不包含模型、数据库或业务 I/O；执行额度仍不是货币费用上限。

## Review Focus

- 策略实例、方法或身份变化：采纳前拒绝，已接受提案恢复不重新计算。
- 同定义不同序列节点和嵌套路径：各自采纳上限，不共享可变缓存。
- 取消先于提案采纳：只记录迟到证据，不启动模型或工具。
- 超限多工具批次：全部拒绝，不能创建部分 Action。
- 伪造来源、非法类型和惰性返回：失败关闭，不放宽限制。

### Task 1: 纯限制协议与 Worker 注册

**Files:** Create temporal_limits.py and temporal_limits_state.py; modify temporal_activities.py, temporal_bindings.py; test tests/test_temporal_limits.py.

**Interfaces:** registration(policy)->JSON; evaluate(runtime, request)->completed raw proposal response; next_stage(state)/accept_stage(state, action_id,response); effective_step(state,step)->JSON.

- [x] RED：自定义策略 host/agent/Spec 交集、disabled、身份漂移、惰性返回、非法/伪造响应。
- [x] 实现版本化注册、Scope/catalog 选择、纯提案和独立 History 验证。
- [x] GREEN：纯协议和既有本地 LimitsPolicy 回归。

### Task 2: 原 Run 限制与恢复

**Files:** Modify temporal_state.py, temporal_workflow.py, temporal.py; add service tests/worker fixture.

**Interfaces:** ralf.temporal.limits.v1 Activity; limits_stages evidence in diagnostics; existing context/model paths consume capped step.

- [x] RED：决定数、上下文、累计工具数、整批拒绝、迟到取消、同定义异绑定节点和实际 History 恢复。
- [x] GREEN：原 Workflow 接入纯阶段，固定一次采纳，不影响业务预算和效果恢复。
- [x] 实际 Temporal Service / Worker 恢复及 History replay；安装 wheel 同场景。

### Task 3: 文档、兼容和本地交付

**Files:** guides/capability queue/status/acceptance/version.

- [x] 独立只读审查，修复有证据的缺口；全量 pytest、Ruff/格式/空白、构建和默认发布兼容。
- [x] 记录真实验收和未交付边界；本地提交，继续整体能力目标。
