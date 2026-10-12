# Model continuation and Gemini functions Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans／dispatching-parallel-agents，独立文件并行；root统一配置、集成、证据与一次最终review。用户授权执行方法已明确。

**Goal:** 在原Local／Temporal权威中保存与恢复模型续接，并接通完整Gemini函数工具链路。
**Architecture:** 续接只是已完成模型证据；纯规则校验owner/decision，原引擎仍唯一采纳／执行。新适配器显式注册，旧默认保持。
**Tech Stack:** Python3.11+、原httpx/jsonschema、SQLite与现有Temporal extra，无新增必需依赖。
**Spec:** [续接设计](../specs/2026-10-13-model-continuation-design.md)。

## Global Constraints

- 保持原ModelResponse三字段、旧默认Manifest、ModelResponse codec以及旧行为；新功能显式opt-in。
- ModelContinuation四字段有限JSON，≤131072 UTF-8bytes；不通过call_id夹带签名或在Provider内建立隐藏状态缓存。
- signed响应只能由原权威采纳；授权、审批、预算、真实handler生命周期与未知效果处理不变。
- 无新依赖、不隐式模型调用／下载；仅本地提交，完整R01–R26不由本批关闭。

## Review Focus

- Harness改调用／内容或typed-default填充：前者拒绝，后者工具参数正常解析而native原文不改。
- 模型响应与决策采纳间退出：保存原continuation后恢复不重新调用模型。
- 孤立／重复／缺失tool receipt，返回原id与synthetic hostID区分。
- SSE签名part与text／functionCall完整边界，thought不显示，片段未完整不执行。
- joint6配合managed Context／Artifact／Sandbox与旧Worker在任何Activity前拒绝；默认旧发布兼容。

## Task 1：公共续接与Local权威（worker A）

Files：model_continuation.py、model_evidence.py、engine.py及独立test_model_continuation.py/test_local_model_continuation.py；必要binding_runtime.py改动提前协调root。
Produces：ModelContinuation、ContinuedModelResponse及spec精确四纯函数；LocalEngine(model_continuation=False)。

- [x] 先写RED：detached/finite/bytes、owner/digest/harness更改、默认旧codec、未开启拒绝。
- [x] 实现公共类型／规则、received_response保存与Local显式Manifest/采纳、typed default原参数保持。
- [x] GREEN与真实os._exit／审批／重复／已采纳恢复，禁止全量或Git共享修改。

## Task 2：Gemini纯协议与HTTP adapter（worker B）

Files：gemini_functions.py、test_gemini_functions.py、test_gemini_function_stream.py；不改model_native.py，root负责导出。
Consumes：Task1 ModelContinuation/ContinuedModelResponse，创建raw decision digest与原Content/call_ids。
Produces：GeminiFunctionProvider继承GeminiProvider、continuation_identity纯属性。

- [x] RED：signed parts、并行／无id／id冲突、原请求与回执匹配、Schema及流完整采纳。
- [x] 实现functionDeclarations／strict request history／parts codec／SSE，旧text Provider不变。
- [x] GREEN，实际MockTransport原工具回路与取消，不调用外部服务或Git。

## Task 3：Temporal History续接协议（worker C）

Files：temporal_activities.py／temporal_state.py／相关joint协议validators／temporal_profile.py及独立tests；与root提前报确切列表避免冲突。
Consumes：Task1公共codec／validate_continuation／assistant_message／Provider continuation_identity。
Produces：TemporalRuntime(model_continuation=False)，joint6+model_continuation1；默认1–5identity不变。

- [x] RED：新协议未注册／owner／proposal冲突、received_response与采纳／History保存和请求。
- [x] 实现原Activity完成与History独立采纳，joint6所有原必要门禁；profile支持显式选项。
- [x] GREEN，原history状态机恢复／重放及旧默认；真实服务由root集成后统一。

## Task 4：装配、默认链路、文档与最终验收（root）

Files：runtime_builder.py/runtime_config.py／provider factory／Temporal assembly／SDK导出／CLI／能力文档／版本／CI及集成tests。

- [x] RED：Profile native continuation与gemini-functions；显式CLI新适配器，RAG/Plan/Team两种工具回路，未开启拒绝。
- [x] 实现配置与包装器委托，补单Agent／多组合／真实进程、源码及核心安装教程。
- [x] 一次独立review与统一RED→GREEN修复，冻结全量／安装／旧86与真实服务验收，文档不夸大模型质量。
- [x] 本地提交，完整目标active。
