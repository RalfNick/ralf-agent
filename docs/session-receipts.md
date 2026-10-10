# 精确 Session 消息回执

dev64 的默认 `InMemoryMemory` 和 `SQLiteMemory` 增加 `session_receipt_version=1` 与同步
`inspect_message`。既有 RedisMemory/PostgresMemory 使用同一结果契约的 native async 方法。
Session 数据只提供写入证据，Run/Turn 推进仍由原执行权威负责。

```python
from contextlib import closing
from ralf_agent import Scope, SQLiteMemory

scope = Scope()
with closing(SQLiteMemory("conversation.sqlite")) as sessions:
    sessions.append(
        scope,
        "chat",
        {"role": "assistant", "content": "你好"},
        expected_revision=0,
        message_id="turn-1:result",
    )
    receipt = sessions.inspect_message(scope, "chat", "turn-1:result")
    assert receipt["revision"] == 1
    assert receipt["receipt"] == {
        "revision": 1,
        "message": {"role": "assistant", "content": "你好"},
    }
```

当前 revision 可以晚于原消息 revision。不存在的消息返回 `receipt=None`，不能据此确认写入。
Scope、实际存储地址和 message_id 必须匹配；返回值脱离后端对象，调用方修改不会改变原消息。
消息必须是有限 JSON object；旧数据中模糊的重复 ID 或非对象记录不能成为成功证据。
回执不承诺消息语义正确，也不自动修复冲突。

`SessionBindingResource` 选出的视图按获准 namespace 转换实际地址，视图的 async
`inspect_message` 返回转换后的 storage_key。同步端口可通过 `memory_call` 调用；线程安全的
同步远端可显式使用 `ThreadedMemoryAdapter`，桥接器会拒绝混合 async inspection 和读取期间后端替换。
SQLiteMemory 必须在创建线程使用，不能套 ThreadedMemoryAdapter。
接口类型见 `ralf_agent.session_receipts.SyncSessionReceiptBackend` 与 `SessionReceiptBackend`。

SQLite 在既有消息事务投影旁增加原始字符串 ID 索引，并按 seq 查询单条消息。原整数 ID 不会变成字符串成功回执。干净索引不解码整个会话；旧写者使消息或 ID 投影变脏时，
同一事务先重建再核验。索引为兼容性增加，不改变原会话 JSON 数据格式。
内存默认扫描已持有的消息 ID，适合离线/短会话，无跨进程耐久性；稳定 backend_id 也不会让
重建的空内存恢复丢失的数据。单条回执查询仍受调用方消息大小约束。

默认同库 SQLite Session 仍走原 Local 原子保存。独立 SQLite／内存资源可通过现有 Local
远程 Session admission 保存意图/准确回执路线使用；后端仅被借用，不由 Runtime 自动关闭。
独立 SQLite 的原生 Agent 与 Team 根保存经过实际进程退出恢复：写前退出重试原保存，提交后
退出核验原 ID；均不重复模型/业务写入。数据库共享不提供跨独立执行权威租约。新接受的独立默认 SQLite Session 需要本版回执端口；
实际旧 dev63 恢复会在模型/业务派发前拒绝，不能降级成旧同库语义。原同库 Session/Run/审批回执兼容保持。

**Temporal 外置 Session 数据尚未交付。** 默认回执是其前置能力，完整读/写/完成门禁与根/成员
责任见[目标契约](../architecture/specs/temporal-session-data-contract.md)；当前 Temporal
仍支持[History Session](temporal-sessions.md)。证据与限制见[dev64 验收](../architecture/reviews/2026-10-11-default-session-receipts.md)。
