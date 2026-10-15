# Invocation middleware and durable events — dev23

This is the first A2 increment from the [ordered roadmap](agentscope-alignment.md).
It adds opt-in middleware and resumable committed-event observation. Existing
native definitions and default execution authority retain their identities.
Input continuation, workspace tools, container Sandbox and live HTTP/WebSocket
services remain separate increments.

## Observe model and tool calls

```python
from ralf_agent import (
    LoggingMiddleware,
    MiddlewareProvider,
    MiddlewareToolExecutor,
    PythonToolExecutor,
)

provider = MiddlewareProvider(my_provider, [LoggingMiddleware()])
executor = MiddlewareToolExecutor(PythonToolExecutor(tools), [LoggingMiddleware()])
# Inject provider/executor into LocalEngine or TemporalRuntime as usual.
```

InvocationMiddleware has explicit JSON identity and synchronous before(record) /
after(record) methods returning exactly None. NoopMiddleware is the minimal default;
empty pipelines are also supported. LoggingMiddleware writes only operation, phase
and payload SHA256. InvocationRecord exposes detached JSON views, so mutations
cannot rewrite requests, approved arguments, envelopes or observations.

Custom hooks are ordinary host objects:

```python
class AuditObserver:
    identity = {"kind": "my-audit", "version": "1"}

    def before(self, record):
        observe_metadata(record.operation, record.phase, record.payload_digest)

    def after(self, record):
        observe_metadata(record.operation, record.phase, record.payload_digest)
```

Operations are model/tool/reconcile; phases are before/after. Model before payload
contains messages/tools, and model after contains response. Tool/reconcile payloads
contain the original envelope and, after completion, an observation or unknown None.
Before order is declaration order; after order is reversed. Hooks observe every real
attempt, not once per business effect: an audit sink needs its own deduplication.
Tool contexts include original run/action/attempt/effect key; Provider ports do not
provide run context. Middleware is trusted host Python, with no isolation.

Before failures stop delegate invocation. The Engine has already recorded its
intent, so credits/outcome can remain conservatively unknown; this is not billing
proof. Authorizations use the existing host policy and approval contracts. After
observers cannot veto results: their exceptions, lazy/non-None returns or diagnostic
logging failures leave the completed receipt available for Engine adoption. Errors
are logged with fixed codes, without exception strings, traceback or raw data.
This diagnostic channel is not a durable audit log; async telemetry belongs in an
external event consumer rather than between effect receipt and adoption.

Wrappers snapshot declared identities and normalized Python entry code, verify
before dispatch and expose current identity drift for Engine post-receipt checks.
Optional stream/preflight presence, mode and entry code are included. The whole
after dispatcher is protected so its replacement cannot erase a known receipt.
Identity drift never grants approval. Captured/global/owner dependencies still need
explicit configuration/version identities; this is not a sandbox. Current wrapper
registrations are immutable deployments: construct a new release for changed code.
Wrappers borrow providers/executors/hooks, and never close their clients. Factory
owners must close actual resources explicitly.

Preflight validates the underlying request without running hooks. Optional model
stream forwarding closes the delegated iterator; it holds a final ModelResponse
until source exhaustion and rejects extra events. Early consumer close has no after
response callback and does not fabricate usage/decision. Text fragments remain
presentation data. Async/lazy hooks and non-Python entry points are refused.

## Default profile assembly

```python
from ralf_agent import RuntimeBuilder, RuntimeProfile

profile = RuntimeProfile(
    "observable",
    "1",
    {
        "default": {
            "adapter": "middleware",
            "config": {
                "provider": {"adapter": "offline-echo"},
                "logging": True,
                "max_bytes": 4_000_000,
            },
        }
    },
    components={
        "tool_executor": {
            "adapter": "middleware-python",
            "config": {"logging": True},
        }
    },
)
with RuntimeBuilder().build(profile, ".ralf/runs.sqlite") as engine:
    pass
```

Middleware profiles wrap one registered synchronous Provider factory. Nested
middleware and nested async factories are refused before database construction.
Other registered synchronous adapters, including model adapters with api_key_env,
can be selected. Custom/async middleware assembly uses explicit registered host
factories with abuild and owned-resource registration. No plugin code is imported
from a profile. Limits allow at most16hooks and256–4000000observation bytes; oversized
after observations produce a diagnostic and preserve the original result.

## Subscribe to persisted events

With `follow=True`, `waiting_input` is a valid nonterminal status. A subscription
can remain open while the original Run waits for an answer. Closing the observer
leaves the question and Run unchanged; reconnect with its last consumed cursor to
read the persisted answer and subsequent events, including after an Engine restart.
Submitting the answer and driving the Run remain separate authority operations.

```python
from contextlib import aclosing
from ralf_agent import EventCursor, RunEventSubscription, SQLiteRunReader

reader = SQLiteRunReader(".ralf/runs.sqlite", scope=host_scope)
saved_cursor = EventCursor.from_token(saved_token) if saved_token else 0
async with aclosing(
    RunEventSubscription(reader, run_id, after=saved_cursor, page_size=100)
) as events:
    async for record in events:
        consume(record.event)
        save_cursor(record.cursor.token)
```

Use after=0 initially, or EventCursor.from_token(saved_token) when reconnecting.
LocalEngine/SQLiteRunReader/ProfiledEngine supply synchronous reader ports;
TemporalEngine supplies native async ports. The adapter pins Scope, mode and method
bindings before/after reads and before buffered delivery. Scope-bound cursor tokens
encode version/Run/sequence; they are not authentication, encryption or permissions.
Authorized events can contain private business data. Do not publish arbitrary
streams to unauthenticated clients.

This is a pull async iterator with bounded page storage and no producer queue.
Pages cap at1000records/4MiB. Sequence gaps/foreign Runs/malformed pages are refused
before any record from that page is delivered. Cursor advances as records return;
applications persist only successfully consumed cursor tokens. Reusing an older
cursor can redeliver events; delivery and application acknowledgment are separate.
There is no retention/compaction or exactly-once delivery guarantee.

Follow mode continues through approval/reconciliation pauses and drains terminal
Runs, including a second read after terminal status. follow=False reads a snapshot
until an empty page. max_events bounds emissions. poll_interval is0.01–60seconds;
read_timeout is0.001–300seconds per read, not total subscription lifetime. Reader
code is trusted: synchronous ports must finish promptly, and native async ports
must cooperate with cancellation. Timeout does not prove server-side query stop.

Use one consumer/event loop. aclose cancels and joins private reads/wakes idle waits
without cancelling or closing the Engine. If close itself is cancelled, read cleanup
continues shielded and a close retry joins it. Cancelling consumption drains the
outstanding read; timeout and repeated cancellation do not discard its task handle.
Observation never drives a Run; the application owns its drive
Task, execution lease and resource lifecycle.

EventEnvelope.to_sse serializes a fixed ralf.run event name, encoded cursor ID and
one JSON data line. Kind/run ID/data cannot inject extra SSE fields. This is a wire
encoder, not a server or model-token stream.

## Installed CLI and observable starter

```sh
ralf init my-observable --template observable
cd my-observable
python -m agent_app
ralf-watch-events --db .ralf/runs.sqlite --run-id RUN_ID
ralf-watch-events --db .ralf/runs.sqlite --run-id RUN_ID \
  --after-cursor CURSOR_TOKEN --follow --max-events 1000 --sse
```

The twentieth packaged starter uses a deterministic Provider, typed read-only tool,
profile middleware and committed-event NDJSON. It owns/joins its finite drive and
reports paused Runs after draining their already committed events. Repeated command
IDs reuse receipts. model_quality=null; no credentials or paid calls. Existing19
starter files are unchanged. The CLI is read-only, snapshot by default and never
creates a missing database. workspace/principal values come from the trusted host;
CLI errors contain stable codes, while stdout is reserved for authorized events.

Full service/install/upgrade evidence is recorded in the
[review](../architecture/reviews/2026-10-08-middleware-events.md).
