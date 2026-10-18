# P3-4 Local 工作消息压缩 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 提供一个默认SQLite上可实际使用的手动有界清理入口，不删除执行与恢复证据。

**Architecture:** `LocalEngine.compact_messages(run_id, *, command_id)`复用原Scope、Coordinator、Store command事务与revision CAS，只压缩普通成功Agent的冗余工作消息。保留前两条初始消息，所有Actions／原模型请求响应／效果／events／commands与其他表不动；原事务记录维护事件及幂等回执。复杂恢复组合明确拒绝，不能把这一窄切片记作完整P3-4。

**Tech Stack:** Python、既有LocalEngine／SQLiteStore。

**Spec:** [冻结P3-4](../../phase3-support-matrix.md#固定剩余清单)，用户已允许独立推进，全部门槛保持。

## Global Constraints

- 只新增SDK显式入口，不自动清理，不加HTTP端点、后台服务、统一purger或新数据后端。
- 仅本地提交，不推送；原S2失败、PG／Temporal保留门槛及P3-5／A不变。
- 首期只接收原生SQLiteStore、无父子／共享Session／辅助恢复stage的普通succeeded Agent；未知结构保守拒绝。
- 逻辑payload减少不等于物理文件缩小或敏感数据彻底擦除。

## Review Focus

- 终态仍有实际drive／线程或reserved／unknown预算时不得压缩。
- 重复command、同command冲突与重新打开原库后回执不变，不再执行模型／工具。
- 保存后、事件／回执提交前失败必须整体回滚；重开原库恢复原完整数据。
- 外Scope、绑定漂移、未知扩展／Session／图组合拒绝，不修改原任务。
- 压缩后原submit／approve／drive/status和事件cursor仍可用，Actions及效果回执逐字保留。

### Task 1: 事务性默认实现与恢复验收

**Files:** Create `src/ralf_agent/local_retention.py`, `tests/test_local_retention.py`; modify `src/ralf_agent/engine.py`, capability／usage／acceptance docs.

**Interfaces:** `compact_messages`返回原`CommandReceipt`，kind为`compact_messages`，outcome只含`removed_messages`、`removed_bytes`及`state_revision`。存储仅保留prefix2与固定维护标记；每次只操作一个明确Run，不扫描全库。

- [x] 写先失败测试：一次审批写入后压缩、重复回执／冲突／冷重启、事务故障回滚、活动与未知义务及不支持结构拒绝。
- [x] 原SQLite command事务中重读授权Run、校验原release和安全条件，保留原初始2条消息并删除尾部冗余副本，原提交与效果证据不变；无尾部时返回零。
- [x] 运行受影响Local／审批／存储／容量检查与隔离安装，记录确切范围和默认兼容；一次独立review后修复必要阻塞、本地提交。

Pre-flight: no shared interfaces. PG重复效果证据候选尚需原完成封存及数据集绑定证明，不在此Local切片中冒充已实现。

执行结果见[验收记录](../../../architecture/reviews/2026-10-18-local-retention.md)。本批窄实现／冷恢复与安装已验收，完整P3-4未关闭，原门槛不变。
