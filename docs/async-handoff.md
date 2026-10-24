# Async execution handoff — dev16

Current executable examples require a6 (`relf_agent` / `relf`) in a separate environment. The dev16 label records the original delivery; it does not qualify a6. See [version boundaries](project-naming.md).
Use the same A2A polling application with local synchronous controls or a native
async execution authority. The default local service runs without Redis, PostgreSQL
or a model credential; shared deployments explicitly supply those services.
See [the transport contract](remote-handoff.md) and [Temporal's supported subset](temporal-execution.md).

## Default installed service

Install your preview wheel with the `server` extra, then generate an independent
application. For a wheel installation, use `python -m pip install "./relf_agent-0.1.0a7-py3-none-any.whl[server]"` with your local wheel path. Source installation and application generation:

```shell
python -m pip install -e '.[server]'
relf --format text init my-service --template a2a
cd my-service
python -m agent_app serve --port 8000
```

Before serving, set `RALF_A2A_TOKEN` locally to a fresh owner credential in both
terminals. The application refuses missing credentials before creating its database.
It does not generate or print credentials. From another terminal in that directory:

```shell
python -m agent_app client --input hello --command-id first
python -m agent_app client --input hello --command-id first
python -m agent_app client --task TASK_ID
relf --db .ralf/runs.sqlite --format text inspect TASK_ID
```

The editable `agent_app/runtime.py` provides the offline Provider, trusted Scope
mapping and Engine factory. HTTP, Run storage and SQLite Inbox are real. Repeating
the same message returns the original Task; different content requires a new command
ID. Acceptance and completion are distinct: poll the original Task. Keep the same
definitions and component identities when restarting. Read-only CLI inspection can
coexist with the host; writable local CLI controls require stopping that host first.

`LocalA2AService(engine=..., inbox=..., authenticate=..., spec=..., url=...)` takes
ownership only after construction succeeds. Its ASGI lifespan tracks drives, requests
cancellation on shutdown, waits for actual drives and handler threads, then closes the
Engine and Inbox in stages. Cancelling the `aclose()` caller preserves the cleanup task
and lease; a failed stage can be retried. Drive errors expose bounded typed codes through
`service.errors`. Custom construction failure leaves ownership with the caller.

This default has one HTTP worker and one local coordinator. Authentication maps one
owner credential to trusted Scope. Enterprise identity, ACL, quotas, deployment
failover and service administration require additional components.

## Replaceable completed controls

`SyncTaskControls` and `AsyncTaskControls` describe `scope`, `submit`, `status` and
`cancel`. `TaskControlBridge(engine, scope)` exposes awaited controls over either mode.
It borrows authority and never drives, closes, moves scheduling or starts a thread.
Sync calls finish on the coordinator thread; native async calls are awaited.

All three operations must use the same mode and return typed `RunHandle`,
`RunSnapshot` and `CommandReceipt` values. Lazy or nested awaitables are refused;
returned identities and finite JSON are validated centrally. Scope and operation
bindings are checked before and after each call, and before wakeup after Inbox I/O.
Callable objects and RuntimeInstance delegation work without concrete inheritance.
Changing a registered method body or callable entry point is refused. Hidden captured
state still belongs in explicit versioned component configuration.

A refusal after a remote call does not prove that nothing happened. Repair using
the original message and command identity, rather than creating a replacement Run.

## Shared PostgreSQL handoff

Install the `postgres` extra. `PostgresInbox` and `PostgresOutbox` implement the
existing AsyncInbox/AsyncOutbox ports; no PostgreSQL execution store is implied.
Call `initialize()` explicitly. Connected clients are owned; directly supplied async,
autocommit connections are borrowed unless `owns_connection=True`.

```python
from relf_agent import PostgresInbox, PostgresOutbox


async def create_handoff(dsn):
    inbox = await PostgresInbox.connect(dsn, backend_id="commands-v1", max_entries=10000)
    try:
        await inbox.initialize()
        outbox = await PostgresOutbox.connect(dsn, backend_id="commands-v1")
        try:
            await outbox.initialize()
            return inbox, outbox
        except BaseException:
            await outbox.aclose()
            raise
    except BaseException:
        await inbox.aclose()
        raise
```

Tables are separate, scoped by workspace/principal/message ID. `backend_id` identifies
the deployment; it is not an extra storage namespace. Two processes must agree on
capacity and use the same database and trusted Scope. Transactions atomically accept,
compare the entire envelope, enforce capacity and retain immutable completion.
Capacity defaults to 10000 retained records per Scope/table (1..1000000 configurable);
completed records also count. New work is refused at capacity while replay still works.
There is no automatic TTL, deletion or retention compaction. Pending/flush pages are
bounded to 1..1000. Plan archival without deleting still-required deduplication evidence.

Outbox enqueue commits before publication. Broker publication runs outside the database
transaction; completion commits after its reply. A crash between these stages can
publish again, using the original stable message ID. The broker must supply compatible
deduplication; RedisStreamsBus does. This is replayable handoff, not an arbitrary
exactly-once guarantee. Close prevents new operations, preserves real cleanup across
caller cancellation and supports retry. Hosts must close owned resources on their loop.

## Shared HTTP with Temporal

Run registered Temporal workers on the same retained queue/release as described in the
[worker guide](temporal-execution.md). Each HTTP process borrows its own TemporalEngine
facade and PostgreSQL Inbox connected to the shared database. A minimal gateway factory:

```python
from relf_agent import A2AApplication, AgentSpec, PostgresInbox


async def create_gateway(engine, dsn, authenticate, url):
    # authenticate is a native async host callback returning engine.scope.
    inbox = await PostgresInbox.connect(dsn, backend_id="shared-http-v1")
    try:
        await inbox.initialize()
        app = A2AApplication(
            engine_for_scope=lambda scope: engine,
            inbox=inbox,
            spec=AgentSpec("answer", "Answer the provided task"),
            authenticate=authenticate,
            url=url,
        )
        return app, inbox
    except BaseException:
        await inbox.aclose()
        raise
```

Temporal workers execute accepted Runs independently of the HTTP caller, so this example
needs no HTTP wakeup. Configure authentication, worker registration, service endpoints
and an ASGI runner explicitly. `A2AApplication` borrows resources; wrap its host lifespan
to close the Inbox/facade after stopping requests. It does not close providers or workers.
Never bind multiple HTTP workers to the same LocalEngine/SQLite coordinator.

Inbox accept precedes authority submit; completion precedes wakeup/reply. If a HTTP
process exits after submit but before completion, another process replays the same
message to recover the original authority receipt. Two HTTP processes and two Temporal
workers have actual process-death/dedup/History replay tests. This composition preserves
Temporal's Agent/sequence subset: it does not add distributed DAG/Team/RAG/nesting.

## 可选脱敏审计

`A2AApplication(..., audit=ServiceAudit(...))` 与 `LocalA2AService` 可复用同一观察入口。默认有界内存sink、同步替换、HMAC关联与故障语义见[服务审计](service-audit.md)。审计不是执行证据，不改变原Scope授权和资源所有权。
