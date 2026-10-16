# HTTP Run controls

The optional RALF extension `urn:ralf:a2a:run-controls:v1` adds approval,
manual reconciliation and a recovery wakeup to the existing A2A JSON-RPC endpoint.
The original Engine owns Run/Action state, command identity and receipts. The HTTP
layer does not introduce another execution authority or durable command database.
Existing applications keep the extension disabled by default.

## Enable and use

```python
service = LocalA2AService(
    engine=engine,
    inbox=inbox,
    spec=spec,
    authenticate=authenticate,
    url="http://127.0.0.1:8000/rpc",
    enable_run_controls=True,
    enable_run_events=True,
)
```

Use trusted host authentication as in the existing service. Each request checks
the original Scope and Run before calling a control. This does not provide
enterprise identity, resource ACL or a new authorization policy.

```python
task = await client.get_task(task_id)
pending = task["metadata"]["ralf"]["pending"][0]
receipt = await client.approve_task(
    task_id,
    pending["action_id"],
    pending["digest"],
    command_id=saved_approval_command_id,
    approved=True,
)
```

Inspect the original pending Action and digest before approving. Save a stable
command ID with the caller's intended control. A lost HTTP response or host wakeup
failure can occur after the authority accepted that command: retry the same
request and command ID to retrieve the original receipt. Changing its payload is
an idempotency conflict. Poll the original Task for business completion; an applied
control receipt does not mean the Run or external operation has succeeded.

Manual reconciliation uses an externally verified result:

```python
receipt = await client.reconcile_task(
    task_id,
    original_action_id,
    verified_business_result,
    command_id=saved_reconciliation_command_id,
)
```

The trusted caller must establish that result against the business system. An
HTTP receipt is not evidence of an external write. This route does not expose the
SDK's `query=True` option. A recovery wakeup can let the original Engine invoke an
already registered reconciler; an unqueryable unknown effect remains unresolved
until the existing reconciliation contract is satisfied. It is never blindly
replayed. For a direct Agent, the Action ID can be recovered from the original
`effect_unknown` event (Local) or `action_outcome_unknown` event (Temporal) via
[event pages](http-events.md), or trusted SDK inspection. Composite child identity
continues to use existing orchestration inspection; this extension adds no generic
child discovery API.

## Wire contract and recovery responsibility

| JSON-RPC method | Exact parameters | Result |
| --- | --- | --- |
| `tasks/approve` | `id`, `actionId`, `targetDigest`, `commandId`; optional boolean `approved` (default true) | Original durable command receipt envelope |
| `tasks/reconcile` | `id`, `actionId`, `result`, `commandId` | Original durable command receipt envelope |
| `tasks/resume` | `id` | Original Task snapshot with a non-durable recovery hint |

Receipt envelopes contain `kind="ralf.control-receipt"`, `taskId` and `receipt`.
The latter retains the original `command_id`, `run_id`, `kind`, `record_state`,
`apply_state` and `outcome`. The client validates their identities and durable
recording before returning. A pending or rejected receipt retains its authority's
meaning. These methods are a RALF extension, not additional standard A2A methods.

```python
task = await client.resume_task(task_id)
assert task["metadata"]["ralf"]["recoveryHint"] == {
    "accepted": True, "durable": False,
}
```

Resume has no command ID or durable acceptance guarantee. It asks the trusted host
to wake the existing Run; the original execution authority determines what can
progress. It does not itself clear an unknown effect, prove handler termination or
confirm business success. Repeated hints may be coalesced by the host.

`LocalA2AService` wires this hint to its existing managed root dispatcher, including
paused recovery states and cancellation cleanup. It tracks the actual drives and
retains its existing owned shutdown responsibility. A borrowed `A2AApplication`
requires an explicit native async `recovery_wakeup(scope, run_id)` callback that
finishes to `None`; without one, resume returns unsupported (`-32004`). Such a host
must retain its Engine/Worker lifecycle. For example, a Temporal host can await its
existing `engine.drive(run_id, wait_seconds=0)` inside this callback and return
`None`; this is an integration contract, not a new live Temporal acceptance result.
The original optional approval/reconciliation ports must match the authority's
sync or native async mode. Legacy required ports remain unchanged.

An owned Local service rejects requests once shutdown starts (503), joins its
managed work and closes owned resources according to its existing contract.
A borrowed application does not close the host's Engine or clients. HTTP disconnect
or observation timeout must not be interpreted as a business cancellation or
proof that a submitted control did not apply. Recover the original receipt using
the same identity; use explicit existing cancellation for business cancellation.

## Verified scope and remaining work

The local candidate is
`dist/p3-controls-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`, with
`verification.json` and `SHA256SUMS` alongside it. The original basic SDK artifact
and the earlier event-only candidate remain unchanged. See the
[acceptance record](../architecture/reviews/2026-10-16-http-run-controls.md).

Local SQLite evidence covers concurrent duplicates, lost wakeup replies, an
unknown write, original query-based recovery, restart, real HTTP processes and
owned shutdown with no active drives or handler threads. Native async adapter
tests use a real Local authority, not a live Temporal service. These controls do
not consume Inbox entries, so an Inbox at capacity does not block them. The
execution authority's cumulative command capacity remains a separate open issue.
P3-3 still requires that capacity behavior and the selected complete
Local/Temporal service acceptance. P3-2/S2 and its original 360-second gate remain
open; this batch changes no Engine or Temporal execution protocol.
