# Temporal Completion Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 接通纯 CompletionVerifier 的宿主／每 Agent 选择、原回执验证和 Temporal History 恢复。

**Architecture:** Worker 的纯 Activity 生成 CompletionVerdict；原 Run History 固定原始节点输入、合法最终输出和已提交工具回执，验证原请求并一次采纳 accept/reject/retry。只有 accept 才进入原记忆／节点完成链路；Parent 和 Session 不新增执行权威。

**Tech Stack:** Python3.11+、公共 CompletionRequest/CompletionVerdict/ToolReceiptVerifier、BindingCatalog、可选 Temporal SDK。

**Spec:** architecture/specs/agent-capability-binding-contract.md；docs/completion-verification.md。

## Global Constraints

- 用户授权持续执行，仅本地提交，不推送。
- 显式 completion_protocol=1/temporal-3；未配置时原默认发布、Action 和 History 行为保持。
- verifier 是补充完成规则，disabled 可关闭补充规则，不能绕过 Schema／权限／审批。
- 同步纯策略只返回严格 CompletionVerdict，不包含网络／模型／存储 I/O。
- retry 消耗后续原模型决定／credits，不重置原上限；原工具效果不回滚／重复执行。

## Review Focus

- 同定义不同节点／嵌套路径和 JSON 输入：不能读取兄弟节点或旧 Session 的回执。
- 未验证完成不能写自动记忆、释放 Session 或推进后继节点。
- 取消与迟到结论：只保留证据，不能重新开启 Run。
- 身份／方法／Scope／请求摘要／非法或惰性结论：失败关闭。
- 实际 SDK 沙箱、Worker kill、retry 与 accept 的采纳：恢复不重复已接受验证，默认旧 History 不变。

### Task 1: 纯协议和 Worker 注册

**Files:** Create temporal_completion.py, temporal_completion_state.py; modify temporal_activities.py and temporal_bindings.py; test tests/test_temporal_completion.py.

**Interfaces:** registration(verifier), evaluate(runtime,request)->completed JSON; prepare(state,model_action,result), next_stage(state), accept_stage(state,action_id,response).

- [x] RED→GREEN：宿主/Agent inherit/ref/disabled、具体 verdict、请求/来源固定、Scope、方法/实例漂移和畸形返回。
- [x] 验证现有 Local CompletionVerifier 和原 Temporal limits 兼容。

### Task 2: 原 History 完成与恢复

**Files:** Modify temporal_state.py, temporal_workflow.py, temporal.py; add actual service/worker fixtures; fix projected child release digest in temporal_agent_controls.py; preserve retry correction via shared context_feedback.py, context.py and context_pipeline.py.

**Interfaces:** ralf.temporal.completion.v1 Activity；completion_stages 诊断；原模型 Action 的 completion_verification；accepted 输出通过原 Memory/complete_node。

- [x] RED→GREEN：accept/reject/retry、当前节点原类型输入、回执隔离、决策耗尽、取消及自动记忆门禁。
- [x] 实际普通/managed 六类编排 kill/restart/replay，接受后不重复验证；retry 后安全 Context read 恢复。
- [x] 实际安装包同场景；默认旧新安装与原审批 History 兼容。

### Task 3: 能力文档与本地交付

**Files:** guide/acceptance/capability queue/status/CI/version.

- [x] 一位只读独立审查，复现修复有证据的缺口；最终全量 pytest、Ruff/格式/空白、core-only、构建/模块/文档一致。
- [x] 同步真实证据、纯与模型 Verifier 边界、未完成能力；本地提交，继续 R01–R26。
