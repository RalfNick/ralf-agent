# Unified invocation middleware and durable event subscriptions — dev23

The user authorized continuation of the ordered AgentScope-alignment roadmap.
A2 is split by dependency: this coherent increment delivers middleware/event
foundations and an installed observable application. Input continuation, useful
workspace tools and container Sandbox follow with separate authority/resource gates.

## Middleware

New InvocationMiddleware exposes synchronous before(record)/after(record), explicit
JSON identity and no return value. InvocationRecord is immutable JSON with operation
model/tool/reconcile and phase before/after. Fields expose detached values; hooks
cannot rewrite Provider requests, tool envelopes, observations or approvals. Empty
pipeline and NoopMiddleware are defaults; LoggingMiddleware logs only operation,
phase and payload digest. Trusted host code/configuration is explicit, never loaded
automatically. Async/lazy hooks are refused; remote telemetry belongs outside this
synchronous receipt boundary.

MiddlewareProvider and MiddlewareToolExecutor implement existing ports and borrow
all delegates/hooks. Before hooks run in declaration order, after hooks in reverse.
Before-hook errors prevent delegate invocation but the Engine may conservatively
record unknown outcome/credits because its dispatch intent already exists. After
observers cannot erase a completed receipt: failures produce sanitized diagnostic
logging and the original response/observation remains available for adoption. No
raw exception text or payload enters those diagnostic messages. After hooks are not
an authorization policy. Current wrapper/delegate/hook identities and Python entry
code are pinned/rechecked before dispatch; after-dispatch identity drift remains
visible for Engine rejection after evidence storage. Captured/global dependencies
require explicit host version/configuration. Default native releases remain identical.

Provider preflight delegates its pure synchronous validation without executing
hooks. Complete returns detached finite ModelResponse. Optional stream forwarding
closes the borrowed stream iterator, rejects malformed/extra events, holds its
complete response until source exhaustion, and applies after observers once before
emitting it. Early consumer close never fabricates a response/usage. Tool envelopes
remain immutable; original effect keys, digest, reconciler and thread ownership pass
through. Wrappers never close borrowed providers/executors.

Default runtime profile provider adapter middleware wraps one explicitly registered
synchronous provider declaration (nested middleware refused); logging/max_bytes are
validated before a Store is allocated. Tool executor middleware-python wraps the
existing PythonToolExecutor. Custom middleware is SDK-injected or assembled by
explicit registered factories, including async factories owned by the host.

## Durable events

SyncRunEventSource/AsyncRunEventSource require scope/status/events ports. Sources are
borrowed: LocalEngine, SQLiteRunReader, ProfiledEngine or TemporalEngine. No subscriber
drives/cancels/closes an Engine. EventCursor binds Scope/run_id/after with version1,
strict bounded JSON/base64url token serialization; tokens are not authentication.
EventEnvelope contains an immutable RunEvent snapshot, cursor and deterministic
SSE encoding. SSE uses a fixed event name and encoded cursor ID, never unsanitized
kind/run-id lines. Authorized event data can contain private business evidence.

RunEventSubscription is a pull async iterator. Pages are bounded to1000records and
4MiB; IDs/sequence/JSON shapes are validated atomically, and a gap is a typed error,
never silent loss. Source Scope, mode and method bindings are pinned and rechecked
before/after awaits and before delivering buffered records. Cursor advances only
when a record is yielded; callers persist their last delivered cursor. Reconnection
from an older saved cursor can redeliver records; application acknowledgments are
outside this iterator. No implicit retention/compaction or exactly-once delivery.

Follow mode polls with finite interval/read timeout, drains a terminal Run with a
second read after terminal status, and continues through approval/reconciliation
pauses. Snapshot mode stops after an empty page. Optional max_events limits total
emissions. There is no producer/background pump; private read Tasks and idle waits
are cancelled/drained by aclose or caller cancellation. Closing a subscription does
not cancel business execution. Async reader cancellation is a client-side request;
synchronous custom readers must be trusted and bounded. Single consumer/loop affinity
is explicit; concurrent __anext__ calls fail. Slow consumers do not cause unbounded
queues. Event polling is observation, not a model-token or WebSocket authority.

## Usability and verification

Public APIs, profile defaults, ralf-watch-events console and twentieth observable
starter must work from an installed wheel. SDK guide distinguishes request hooks,
persisted Run events, stream fragments and execution authority. No dependencies or
old19starter contents change. TDD covers immutability/order, lazy callbacks, malformed
returns, after-receipt failures, cancellation/thread lifetime, profile validation,
source drift/gaps/reconnect/terminal race/close and actual approval across restart.
Actual Temporal event consumption and middleware dispatch are tested through the
real service. Actualdev22 native/local/History release recovery and old template
contents, full actual services, wheel/base imports and package/CI/lint/format gates
must pass. Exactly one fresh read-only reviewer, Important/Critical TDD fixes once.
No credentials/paid calls, Git commit/push/publication or destructive checkout cleanup.
