# HTTP durable event pages

This opt-in RALF extension uses the existing A2A JSON-RPC endpoint. It reads the
selected authority's committed Run events. It never drives a Run, submits a business
cancel, opens another database or starts a background event producer.

The local candidate is `dist/p3-events-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`,
with `verification.json` and `SHA256SUMS` beside it. The frozen basic SDK wheel in
`dist/basic-sdk-b871f61/` is unchanged and does not include this extension.

Enable it on an existing authenticated service:

```python
service = LocalA2AService(
    engine=engine,
    inbox=inbox,
    spec=spec,
    authenticate=authenticate,
    url="http://127.0.0.1:8000/rpc",
    enable_run_events=True,
)
```

The same option is available on a borrowed `A2AApplication`, including with a native
async authority. Keep the existing host-owned Worker, engine and Inbox lifecycle.
An enabled application requires `events` in the original controls' sync/async mode
when this route is called. Existing applications and structural A2A clients do not
gain new required ports when the extension is disabled, which is the default.

## Read and resume

```python
from ralf_agent import A2AClient

client = A2AClient(url, headers=host_authorization_headers)
try:
    page = await client.get_events(task_id, cursor=saved_token, limit=100)
    for record in page["events"]:
        consume(record["event"])
        save_cursor(record["cursor_token"])
finally:
    await client.aclose()
```

Use `cursor=None` initially. Save a cursor only after consuming its event. Reusing
an older cursor redelivers the same committed events; this is not exactly-once
delivery or an atomic consumer acknowledgment. Once all returned events have been
consumed, `page["cursor_token"]` is their last cursor. An empty page retains the
request cursor. It does not mean the Run has finished; inspect the original Task
and poll with host-chosen backoff when needed.

The Agent Card advertises `urn:ralf:a2a:run-events:v1`. JSON-RPC method `tasks/events`
accepts exactly `id`, optional `afterCursor` and optional `limit` (1–1000, default
100). The result contains `kind="ralf.event-page"`, `taskId`, `events` and
`cursor_token`. Each record is the original `EventEnvelope` wire shape. The client
checks Task identity, consecutive sequences, exact record cursors and the final
cursor before returning a page. This is a RALF extension, not standard A2A history,
SSE or model-token streaming; the Card's standard streaming capability stays false.

## Bounds, identity and interruption

Every request authenticates through the existing host callback, matches the
engine's trusted Scope, checks the cursor's Scope/Run and reads the original Run's
status. A cursor is encoded identity and position, not authentication or permission.
Do not expose business events without trusted access control. The extension does
not add enterprise identity, resource ACL or event redaction.

The original reader validates each page and bounds it to 1000 records/4,000,000 bytes.
HTTP responses obey the configured `max_response_bytes` (default 256 KiB), including
the JSON-RPC wrapper. A byte-limited page returns the fitting prefix and its last
returned cursor; subsequent events are read again on the next request. No producer
queue grows while clients are disconnected. If a single event cannot fit, or the
source page exceeds its bound, the request fails without publishing a new cursor;
reduce `limit` for an oversized source page, or inspect a large single event through
the existing SDK with appropriate trusted handling. Events are never silently cut.

Closing the HTTP client does not cancel the business Run. Each page is a bounded
read request, not a hosted long-running subscription. The existing HTTP request
timeout bounds observation, not the business deadline. If an ASGI request Task is
cancelled, the private event reader is cancelled and joined. Socket disconnect
does not prove an already dispatched backend query has stopped immediately; the
host still owns its request/backend lifecycle. Keep the same authority/storage
and identity to resume from a saved cursor after restart.

The later [Run control extension](http-run-controls.md) adds opt-in approval,
manual reconciliation and host recovery wakeup with Local evidence. It is supplied
in a separate candidate; the event-only wheel above remains immutable. P3-3 still
requires cumulative command-capacity behavior and complete selected Local/Temporal
service acceptance. S2 Coding Session and its original 360-second gate stay open;
these extensions do not change their support or execution protocols.
