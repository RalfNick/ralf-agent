# Temporal DecisionPolicy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 沿 R01/H1 公共纯 Harness prepare/propose 契约接通 Temporal 宿主默认和每 Agent DecisionPolicy。

**Architecture:** Worker 固定纯策略及实际方法，生成已准备请求与原响应的决策证据；原 Run History 校验原派发摘要、所选注册、原响应和工具提案，再提交原 Action、审批、额度、完成验证及记忆。不增加状态权威。

**Tech Stack:** Python3.11+、Harness/NativeHarness/ModelRequest/DecisionProposal、BindingCatalog、可选 Temporal SDK。

**Spec:** architecture/specs/agent-capability-binding-contract.md；architecture/viewpoints/harness-runtime.md。

## Global Constraints

- 用户持续执行授权；沿现有非主分支原地实现，仅本地提交不推送。
- 显式 decision_protocol=1/temporal-3；默认原生无额外策略的旧发布／History 保持。
- inherit/ref，必需角色 disabled 拒绝；纯同步策略不执行 I/O、模型、工具或状态提交。
- 具体 ModelRequest/DecisionProposal、detach、实例／方法／指纹及原请求固定；模型后漂移保存收到响应与用量，不能提交提案。
- 模型准备可裁剪／重排已授权工具描述，不能新增或修改工具授权；实际请求服从字符/token/输出预留限制。

## Review Focus

- 原始请求、注册、Scope、响应与提案不能混用；恶意或惰性返回、对象／方法漂移均失败关闭。
- 自定义策略不是审批／Schema／limits／CompletionVerifier 的旁路；取消后的迟到模型只留证据。
- 当前节点／子 Run 路径，prepare/propose 重启与实际 Activity 沙箱、History replay、默认旧新兼容。
- 纯策略与 Provider 同处模型 Activity，已接受证据恢复不再次调用；未接受的外部模型响应不承诺恰好一次收费。

### Task 1: 纯注册、绑定及实际模型请求

**Files:** Create src/ralf_agent/temporal_decision.py；extend component_fingerprint.py only for __class__ super captures with deterministic base method fingerprints；modify temporal_activities.py、temporal_bindings.py；create tests/test_temporal_decision.py。

**Interfaces:** registration(policy), pin/check_pin, validate_prepared_tools；decision_protocol=1，decision_registration 包含 identity 和 prepare/propose 指纹。

- [x] RED 宿主／Agent 选择、不同 prepare/propose、生效输出、实例／方法漂移、惰性返回、工具/Context越界；运行 pytest，Expected: 缺少自定义支持失败。
- [x] GREEN 接入明确注册和 detached 请求／提案，运行新测试和现有 Harness／Temporal Completion/Limits，Expected: 全通过。

### Task 2: 原 History 采纳和真实恢复

**Files:** create temporal_decision_state.py for pure protocol/boolean adoption checks, modify temporal_state.py/temporal.py；new service/Worker fixtures tests/temporal_decision_worker.py、tests/test_temporal_decision_service.py。

**Interfaces:** 原 model response 增加 decision_evidence：固定注册、原请求摘要、prepared_request、received_response_digest、proposal_digest。原 History 独立验证原 release/step 和工具子集，无另一调度器。

- [x] RED 缺失／替换证据、原响应和决策不一致、取消、额度和完成验证组合；Expected: 不会采纳错配提案。
- [x] GREEN 原 History 验证并保留原响应／用量；Actual 普通/managed 六类 kill/restart/replay，Expected: 已接受业务模型／提案不重复，审批工具一次效果。
- [x] 安装包实际场景、core-only、dev62→63→62 默认原 History/审批兼容，Expected: 全通过；旧 Worker 在派发前拒绝新协议。

### Task 3: 验收文档和本地提交

**Files:** guide、acceptance、R01–R26 queue/status、Harness/绑定规格、CI、版本63。

- [x] 只读独立最终审查，实际复现后修复问题；最终全量pytest、Ruff/格式/空白、wheel/sdist及模块/文档一致，Expected: 全通过。
- [x] 同步严格默认与替换、纯／I/O边界、当前证据及未完成能力；本地提交后继续完整目标。
