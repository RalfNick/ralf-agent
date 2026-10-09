# Message transport and A2A — dev16

Transport hands commands to an execution authority. It does not run a second
scheduler, own Run state or turn LocalEngine into a distributed engine.
Public `MessageBus` has an `InMemoryMessageBus` default and optional
`RedisStreamsBus`. Inbox/AsyncInbox, Outbox/AsyncOutbox and CommandAdapter are
structural ports: custom composition works without subclassing default adapters.
SQLiteInbox/SQLiteOutbox persist local handoff receipts independently of Run data.
PostgresInbox/PostgresOutbox supply shared native async handoff with atomic capacity
and immutable completion; see [async handoff and service setup](async-handoff.md).

```python
from ralf_agent import (
    AgentSpec,
    Scope,
    MessageEnvelope,
    InMemoryMessageBus,
    SQLiteInbox,
    LocalCommandAdapter,
    EngineCommandDispatcher,
    consume_delivery,
)


async def accept_one(engine):
    scope = engine.scope
    bus = InMemoryMessageBus()
    inbox = SQLiteInbox("handoff.sqlite")
    try:
        dispatcher = EngineCommandDispatcher(
            LocalCommandAdapter(engine), specs={"answer": AgentSpec("answer", "Answer the task")}
        )
        await bus.ensure_group(scope, "commands", "workers")
        message = MessageEnvelope(
            "request-1", "commands", {"kind": "submit", "spec": "answer", "input": "hello"}
        )
        await bus.publish(scope, message)
        deliveries = await bus.receive(scope, "commands", "workers", "worker-1")
        return await consume_delivery(
            bus, inbox, dispatcher, scope, "commands", "workers", deliveries[0]
        )
    finally:
        inbox.close()
        await bus.aclose()
```

The dispatcher resolves a host-owned spec alias, keeps `message_id` as the
engine command ID and accepts submit/approve/cancel/reconcile. LocalCommandAdapter
bridges sync controls; AsyncCommandAdapter bridges native async authorities such
as Temporal. It never calls `drive`. The host schedules execution on its authority.
Scope is trusted host input and must match the bound adapter; a payload cannot
select another principal or import Python code.

Inbox acceptance precedes engine control, and durable completion precedes ack.
A crash after engine acceptance replays that command to recover the original
receipt. Outbox commits enqueue before publication and publication evidence after
the broker reply. Redelivery preserves identity; changed content conflicts.
Lazy/non-None completion is refused and leaves delivery pending. Custom adapters
must provide these same durable/atomic guarantees; method presence alone is not
proof of conformance.

## Redis Streams

Install `ralf-agent[redis]` and connect with
`await RedisStreamsBus.connect(url, backend_id="my-mq-v1")`. The caller owns clients
passed directly unless `owns_client=True`; close failures retain a retry path.
Groups, pending entries, bounded idle claims, owner-checked ack and atomic publish
dedup use real Redis. Scope/topic bindings isolate messages. This implementation
uses bounded XPENDING/XCLAIM recovery. It retains dedup/receipt entries and refuses
new work at capacity; it does not silently trim pending entries. Retention,
compaction, general broker adapters and Redis failover/Cluster certification remain
future work. Sharing a SQLite handoff file across hosts is not a deployment option;
use PostgresInbox/PostgresOutbox or a conforming shared durable implementation for that topology.

## A2A polling subset

`A2AApplication` is a borrowed-resource ASGI app. The host supplies a native async
`authenticate(headers) -> Scope`, a synchronous `engine_for_scope(scope)` returning
the matching synchronous local or native async authority, a fixed spec, an Inbox and optional async wakeup.
It publishes an Agent Card and JSON-RPC `message/send`, `tasks/get`, `tasks/cancel`.
TaskControlBridge awaits completed controls, checks Scope and registered bindings
before/after calls, and rechecks before wakeup following Inbox I/O. The same app
can borrow TemporalEngine with a shared PostgresInbox. LocalA2AService provides
tracked local execution/shutdown and an installed a2a starter. The host supplies
remote resource lifetime; see [composition and ownership](async-handoff.md).

The protocol is pinned to [A2A 0.3.0](https://a2a-protocol.org/v0.3.0/specification/),
with text/data inputs and polling. SSE, push, gRPC, files, Task continuation and
state history are refused. The Card declares the RALF message-receipt extension
`urn:ralf:a2a:message-receipts:v1`; `tasks/get` with `metadata.ralfMessageId` retrieves
a submission receipt after an uncertain HTTP reply. An absent receipt never proves
that no remote effect occurred. This is a tested protocol subset, not full A2A
conformance certification or enterprise identity management.

`A2AClient` supports discover/send/get/cancel; `A2AClientPort` allows replacement.
Use `A2AToolSource(client)` through managed ToolSource registration with a host
ToolPolicy declaring `effect="queryable_write"`, `effect_key_argument="message_id"`
and `reconciler=source.reconcile`. This binds remote submission to the approved
Action's stable key. A timeout remains unknown; reconciliation only queries the
original receipt and never resubmits. Source/client ownership is explicit and
borrowed by default. Downstream business effects still need idempotency or evidence.

Real Redis process-death recovery, HTTP loopback discovery/dedup/cancel and custom
sync/async composition contracts are covered by tests. `ralf-agent[server]` provides
an optional ASGI runner; no socket or network service starts on base import.
