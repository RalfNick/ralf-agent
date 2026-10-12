# Session Model History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** 完整交付可替换/可配置的跨Turn原生历史，涵盖Local/Temporal默认与真实远程替换。

**Architecture:** 原ModelHistory增加显式session/frame模式；原Session CAS/receipt和原Run/History推进。无新的执行权威。

**Tech Stack:** Python3.11+、现SQLite/Redis/PostgreSQL/Temporal、pytest/Ruff，无新增核心依赖。

**Spec:** docs/superpowers/specs/2026-10-13-session-model-history-design.md

## Global Constraints

- dev88 `ff9b417`，旧ModelHistory1/DTO/descriptor1默认不变；新mode为history2/local7/joint8/schema13。
- envelope999,998 canonical chars（单项page外围[]占2chars）、stream128 envelopes/8MiB；无截断/摘要降级。
- shared frame/envelope/read函数签名以规格为准；source字段准确，不追加调用方手填key。
- 持续开发/并行已授权，仅本地提交，不推送，不用离线冒充真实质量。

## Review Focus

- sequence/graph切换会重置messages；冻结发生在原节点完成前，源current_task不能取root input。
- 外部成功但原根失败；下一Turn只能使用原权威发布的完整资格证据。
- 多Agent/并行/重复调用/重绑定；stream沿固定路径和owner，不由名字或随机ID猜测。
- full pagination不能skip大记录；拒绝不完整/换snapshot/伪覆盖，不能当reference召回。
- 每Agent策略禁用/替换；新role只显式descriptor2输出，旧默认恢复字节不变。

### Task 1: Pure frame and strict native data adapter（parallel A）

**Files:** model_history.py；new session_model_history.py/native_session_history.py；new test_session_model_history.py/test_native_session_history.py。
**Interfaces:** 规格中的Complete scope/frame/registration与三envelope/address/read函数。普通run方法指纹不变；read有I/O，其余纯函数。

- [x] frame完整past/current/refs、raw签名/callID/JSON、重复ID分组、lazy/tamper/测量/超限失败测试先RED。
- [x] 纯policy与完整公共guard；原registration只有新scope加frame methods；默认帧保护所有选中原消息。
- [x] strict原page读取、原生隔离地址、完整envelope校验、核心Memory/SQLite和自定义替换测试GREEN；真实Redis/PostgreSQL各九项完整有界reader通过。

### Task 2: Per-Agent binding and configuration（parallel C）

**Files:** binding_types/catalog/runtime/manifests.py；runtime_builder.py及相关factory；temporal_profile.py/temporal_builder.py；SDK导出；new test_model_history_bindings.py/test_session_history_configuration.py。
**Interfaces:** descriptor1保持十四role；显式model_history选择输出descriptor2；StepComponents末尾model_history可选；Catalog/Registry固定model_history_registration。complete adapter接受scope。

- [x] v1默认字节/显式v2继承refdisabled、纯对象/方法替换、bound/nested解析、sync/async配置先RED。
- [x] 原binding角色解析与默认host选取；新策略必须显式续接，非法配置store创建前拒绝；owned/borrowed保持。
- [x] 配置和绑定新测试及旧绑定/装配回归GREEN；不编辑engine.py或Temporal权威文件。

### Task 3: Temporal default, remote and actual paths（parallel B）

**Files:** temporal_*.py权威/阶段/runtime，排除Task2 profile/builder；new test_temporal_session_model_history.py与Worker/service测试。
**Interfaces:** Task1 frame/envelope/helper、Task2角色与StepComponents；joint8/history2沿原Session/Run记录完整episode与发布资格，旧joint1–7保持。

- [x] 原Session两Turn/frame/currentTask/最终采纳/source发布/晚回执/失败根、不完整guards先RED；最终容量与实际parent bundle新增RED已修复。
- [x] 原History默认bundle、Context/实际request/frame守护和所有原stage gates；外部原read/save收据与真实handler所有权。
- [x] native/sequence/graph/team/plan/nested真实Agent路径和外部数据替换；纯恢复/取消/rebindGREEN，实际Session/Worker恢复和replay补齐；默认/外置128轮已实际验证，外置使用显式128MiB私有服务，原50MiB限制证据保留。

### Task 4: Local authority and integrated acceptance（root）

**Files:** engine.py/storage.py/currentTask与workflow/node/orchestration集成；new local_session_model_history.py；new Local/composition/process/remote测试；文档/能力/CI/version。
**Interfaces:** Task1 frame/envelope/read、Task2实际策略；原Store的schema13与发布事实查询/保存，真实Task/叶子freeze和根成功原事务/外部receipt。

- [x] native两Turn/当前查询、早期节点freeze/失败根资格、同conn rollback/未知外写/busy/rebind、合法callID先RED。
- [x] 原Run固定snapshot/currentTask；默认原成功事务完整publish；异步外部intent/inspect/receipt恢复；所有编排/每Agent路径；无SQL原publication端口/同步完成/准确回读31项通过。
- [x] 实际Redis/PG/Temporal、独立核心/安装例子、旧dev88默认/Run/Session/旧拒绝与一轮独立review。
- [x] 全量/构建/安装字节/文档与能力验收记录均通过；未通过能力不完成；本地提交在验收后执行，实际结果以Git为准；完整目标active。
