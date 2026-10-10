# Default Session Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 补齐外置 Temporal Session 必需的默认 SessionReceiptBackend 核验能力，保持内存／SQLite／Redis／PostgreSQL 同一精确回执契约，并固化完整外置 Session 的读写与执行责任。

**Architecture:** 会话数据后端只保存带稳定 message_id 的原子 CAS 记录和回执；现有 Local Run 或 Temporal History 持有状态、未知写和占用。新增内存／SQLite 的 scoped inspect_message；SQLite 使用原消息投影及保留原始字符串ID的独立失效索引，默认旧发布／数据格式保持。外置 Temporal 链路不能在本批标完成。

**Tech Stack:** Python3.11+、SessionReceiptBackend／validate_inspection、默认 Memory/SQLite、既有 Local remote Session 保存恢复。

**Spec:** architecture/specs/agent-capability-binding-contract.md；architecture/specs/agent-facade-session-contract.md；新 temporal-session-data-contract.md。

## Global Constraints

- 持续授权、原非主分支、逐批仅本地提交，不推送；完整 R01–R26 保持。
- 默认回执源于真实已提交记录，不从模型或执行状态推测写入成功。
- Scope、实际地址、message_id、revision 和完整消息一次读取；不存在为 receipt=None。
- 整个 SQLite 核验处于同一事务，dirty 旧写者先重建原投影；干净索引不得读取完整会话。
- 默认发布/原数据格式保持；允许借用数据 Store，但不由回执端口创造执行租约。

## Review Focus

- 同名不同Scope／namespace、旧revision重复提交、缺失／冲突／复制回执、返回值detach、线程／关闭／重启和SQLite dirty投影。
- 默认新增receipt能力是否改变Local Session路由；同库默认保持，独立SQLite／Memory明确远程数据职责和借用资源生命周期。
- 已提交写入但ACK丢失只能核验原message_id，不重跑业务；不知道结果的写仍保持原Turn占用。
- 不把默认数据SPI当成Temporal外置Session实现；新规格必须覆盖原Run/Parent完成门禁、每Agent与根Conversation地址、原History身份、异步写核验及物理别名。

### Task 1: 默认精确回执端口

**Files:** modify memory.py/session_receipts.py；new tests/test_default_session_receipts.py。

**Interfaces:** session_receipt_version=1、inspect_message(scope,session_id,message_id)->completed JSON，sync/async明确兼容。

- [x] RED：memory/SQLite缺失、精确Scope/地址、消息revision与当前revision、重复写、detach、reopen、dirty投影和不读取全会话；Expected: 缺端口失败。
- [x] GREEN：实现默认inspect、SQLite点查索引和共同Schema，检查已有remote/Session/Recall回归；Expected: 全通过。

### Task 2: 原保存恢复和完整外置设计

**Files:** Local默认及独立Session恢复 tests；new architecture/specs/temporal-session-data-contract.md；默认Session指南。

- [x] 真实进程ACK丢失／restart、原审批／业务一次效果、独立SQLite借用关闭、默认Local路由与旧wheel兼容；Expected: 精确核验原写而不再次执行业务。
- [x] 固定完整Temporal外置设计：唯一原执行权威、root和member地址、accepted读快照、CAS写意图/回执/未知核验、成功与静默/占用顺序及namespace物理资源身份；Expected: 当前未实现字段明确为目标，不伪称交付。

### Task 3: 最终交付

**Files:** 能力矩阵/队列/Guide/acceptance/CI、dev64。

- [x] 一个独立只读最终review；有证据问题RED→GREEN，最终全量/安装/core-only/build/旧默认与原回执兼容；Expected: 全通过。最终3613passed/198skipped，安装146，实际63↔64兼容与core-only通过；验收记录列独立门槛。
- [x] 同步进度、当前限制与后续Temporal全链路，完成后仅本地提交；完整目标继续。
