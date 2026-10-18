# P3-4 最小身份与脱敏审计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 复用已有授权链，提供默认有界、可替换的服务审计，并验证两位有效调用者的隔离。

**Architecture:** `A2AApplication` 在原 RPC 边界产生独立审计观察，不参与业务状态推进。`ServiceAudit` 使用固定字段与 HMAC 引用；默认内存环形缓冲，宿主可替换同步 sink。原命令、效果与 History 保持不变。

**Tech Stack:** Python 3.11+、stdlib、原 ASGI／SQLite 权威。

**Spec:** [冻结 P3-4](../../phase3-support-matrix.md#固定剩余清单)。用户已允许独立推进并保留全部门槛，既有持续自主执行与并行方式继续适用，不重复请求设计批准。

## Global Constraints

- 仅本地提交，不推送远端；S2原360秒失败及所有验收门槛保留。
- 不引入身份联邦、控制总线、新执行权威、后台审计线程或新的数据后端。
- 本批不关闭完整P3-4；产品安全保留和所选远程服务验收仍待。

## 审计契约与实现选择

- 公共 `AuditRecord` 是冻结DTO，只含版本、事件UUID、时间、有限operation/outcome及五个可空HMAC引用：Scope、RPC请求、Task、message、command。
- 不采集正文、工具参数、结果、错误详情、header/token、游标或原始身份；未知method映射为固定`unsupported`。认证失败没有可信Scope。
- `ServiceAudit(sink=None, *, key=None)` 默认 `InMemoryAuditSink(max_records=1000)`；默认随机32字节HMAC key只关联本实例。宿主传入至少32字节key可跨重启关联，不把key写入记录。
- `AuditSink.emit(record) -> None` 必须同步完成。sink是借用资源；宿主负责持久化、关闭和访问控制。默认环形缓冲溢出统计dropped，不是持久合规日志。
- 审计是best-effort观察：sink异常／非None返回仅增加安全的失败计数，不改变已接受的命令回执、不重试业务。中断／超时同样记录观察结果，不声称业务未执行；进程崩溃可能漏记录。
- 默认关闭，既有Card与HTTP协议不变。显式 `audit=ServiceAudit(...)` 可用于直接Application或LocalA2AService选项。

## Review Focus

- 用户输入将密钥放入任意正文／ID／method／错误时，审计仍无原文。
- 同一可信身份与消息在同一key下重试／重建实例可关联；换key不可关联。
- sink抛异常或返回惰性对象时，已接受Run不被错误报告或重复提交。
- 调用方超时／取消／断连只产生观察，原命令和执行责任不转移。
- 第二个有效身份在同一原数据库访问外Scope任务，拒绝发生在原权威而非空库NotFound。

### Task 1: 审计产品入口

**Files:** Create `src/ralf_agent/service_audit.py`, `tests/test_service_audit.py`, `tests/test_a2a_service_audit.py`; modify `src/ralf_agent/a2a.py`, `src/ralf_agent/__init__.py`.

**Interfaces:** Produces `AuditRecord`, `AuditSink`, `InMemoryAuditSink`, `ServiceAudit`; consumes fixed original RPC/auth path. `ServiceAudit.record(*, scope, method, outcome, request_id=None, task_id=None, message_id=None, command_id=None) -> None` is observer-only.

- [x] Write failing fixed-schema/HMAC/buffer/failure tests and ASGI auth/send/retry/error/interruption tests; observe RED.
- [x] Implement minimal contract and optional `A2AApplication(..., audit=None)`; no business changes.
- [x] Run affected A2A, lifecycle, events, controls and audit tests; expected zero failures. Register isolated wheel verification and scope limits.

### Task 2: 双有效身份与文档验收

**Files:** Create `tests/test_a2a_scope_isolation.py`; update original capability documents, add audit usage and acceptance record.

**Interfaces:** Consumes existing Scope/auth/controls/events only. No Task 1 shared code; independent test work may run in parallel.

- [x] Verify both valid identities can submit/query own Runs; crossScope query/control/events rejected, no original mutation/write.
- [x] Verify auth failure/forgedScope rejection and original approval/recovery still work.
- [x] Review final change once; fix actual blockers, run necessary affected/source/install checks, document exact evidence; local commit only.

Pre-flight: Task 2 consumes existing public APIs only; no new shared interfaces. Safe retention remains a separate original P3-4 deliverable, not an audit-ring TTL.

执行结果：见[验收记录](../../../architecture/reviews/2026-10-18-p3-service-audit.md)。按原计划交付最小子集，完整P3-4仍开放；四项既有输入夹具失败独立保留，未过滤后宣称全量通过。
