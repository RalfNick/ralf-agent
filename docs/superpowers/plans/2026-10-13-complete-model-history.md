# Complete Model History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** 在原 Local/Temporal 执行权威中完整保留已采纳模型交互，提供纯历史策略与配置、恢复验收。

**Architecture:** 原 DTO 编码不变，新增显式 model_history_protocol=1 与纯 ModelHistoryPolicy。决策采纳保存原 assistant，验证重试只追加反馈，完整原历史在模型 I/O 前受保护；无新调度器。

**Tech Stack:** Python 3.11+、现有 SQLite/Temporal、pytest、Ruff、现有核心依赖。

**Spec:** docs/superpowers/specs/2026-10-13-complete-model-history-design.md

## Global Constraints

- 保留 dev87 ModelContinuation/ModelResponse 编码、旧 False/local-5/joint6 默认和恢复身份。
- 新 Local 原生 kernel local-6；Temporal joint7；model_history_protocol=1。
- 跨 Turn native transcript 与两个 reasoning 适配器在后续完整交付，不宣称本批完成。
- 仅本地提交，不推送；无凭据不做付费模型请求。

## Review Focus

- 归一化业务 JSON 与原模型文本不同：原 assistant 保存原文本。
- 用户 Context/Harness 能修改字段或返回 lazy 对象：原权威校验且零模型派发。
- managed Context 摘要可能先发模型：新完整历史模式不做原生链路摘要降级。
- Worker/进程在 receipt/采纳/验证间退出：恢复不重复模型/assistant/结算。
- 任意 bound/native kernel 与非法协议字段：旧版本拒绝新模式，当前完整校验而非仅信标记。

### Task 1: Public pure policy (parallel owner A)

**Files:** Create src/ralf_agent/model_history.py, tests/test_model_history.py.

**Interfaces:** Produces ModelHistoryPolicy; CompleteModelHistory(allow_tool_result_projection=False); validate_model_history(history, messages, *, allow_tool_result_projection=False). Assemble signature and exact contract follow spec. Fixed identity includes version 1 and projection bool.

- [x] 写失败测试：完整 signed final、工具 receipt/order、参考前缀、投影开关、有限 JSON、测量预算、未完成组、lazy validator。
- [x] 运行指定 tests/test_model_history.py 证明 RED。
- [x] 实现纯策略和公共校验，不修改任何现有 Context 的旧身份。
- [x] 运行测试、Ruff 后交回 root 集成。

### Task 2: Temporal authority (parallel owner B)

**Files:** Modify temporal_activities.py, temporal_state.py, temporal_decision_state.py, temporal_completion_state.py, temporal managed/context/protocol validators; create tests/test_temporal_model_history.py. 不修改 Profile/Builder、SDK 导出或 Local。

**Interfaces:** Consume Task1 policy methods and model_history_registration(policy). TemporalRuntime(model_history=None), manifest.model_history_protocol=1 and model_history=model_history_registration(policy); pure original History validates complete policy declaration and actual native messages. Root handles Profile.

- [x] 写 signed final/retry、raw JSON、receipt/采纳重启、joint7 校验和身份漂移失败测试并验证 RED。
- [x] 固定策略对象/方法身份；原 Activity context 与原 History 均做保护；新模式完整 final 采纳且 retry 不重复 assistant。
- [x] 接通 joint7 所有必需原协议；1–6保持原载荷。
- [x] 运行新测试及既有 continuation/managed/binding tests，交回 root。

### Task 3: Local, Profile and public integration (root)

**Files:** Modify engine.py, completion_runtime.py, context_preparation.py, runtime_config.py, runtime_builder.py, temporal_profile.py/assembly, __init__.py; create tests/test_local_model_history.py, tests/test_model_history_assembly.py.

**Interfaces:** Consume Task1 policy; LocalEngine(model_history=None); Runtime/Temporal components.model_history complete adapter；Temporal execution.model_continuation=true。

- [x] 编写最终/验证/预算/managed artifact/身份/自定义 Provider 与恢复失败测试并确认 RED。
- [x] 在原 Manifest/采纳/实际请求边界加入门槛；新模式完整保存与重试，旧模式不变。
- [x] 在原 Context preparation 复用 reference/artifact I/O，完整模式不启动摘要；公共配置与 sync/async SDK 装配。
- [x] 新测试和组合/旧协议回归通过。

### Task 4: Evidence, review and local commit (root)

**Files:** docs/model-history.md, docs/model-continuation.md, docs/implementation-status.md, docs/implementation-progress.md, docs/remaining-work.md, architecture/viewpoints/framework-capabilities.md, architecture/reviews/2026-10-13-complete-model-history.md, CHANGELOG.md, pyproject.toml.

- [x] 一次新独立 review；对有效问题先 RED 再统一修复。
- [x] 实际 Temporal Worker/replay、源码完整回归、独立核心安装、wheel/sdist 及旧87身份/Run 兼容；记录真实终态。
- [x] 同步能力与未验收清单；版本 dev88；检查文档链接/凭据/空白。
- [x] 仅本地提交，工作区干净，目标继续 active；实际提交以 Git 记录为准。
