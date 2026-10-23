# Temporal Context read lifetime

Dev68 delivers this explicit read-lifetime subset. Final source, installed-package,
real service and dev67 compatibility evidence is recorded in
[acceptance](../architecture/reviews/2026-10-11-temporal-context-read-lifetime.md).
Full H3/M1 and R01–R26 remain open.

Ordinary Context and the managed `plan`, `read`, `verify`, `finalize` phases can
explicitly retain their actual handlers through observer cancellation and Activity
timeout. The original Native History still owns admission and progression. It
requires both response evidence and actual end evidence before scheduling the next
operation or letting a Session release its Turn. Parent child-budget settlement
uses the same original quiescence evidence.

```python
from relf_agent import ContextExecutionOwner, TemporalRuntime, ToolRegistry

execution = TemporalRuntime(
    providers={"default": provider},
    tools=ToolRegistry(),
    context_reads=True,
    # Add the existing context_builder, knowledge, facts, session_store,
    # binding_catalog and session_topology components as needed.
)
```

Build the Worker with `build_temporal_worker`. It binds dispatch and end updates
to the original actual Workflow UUID and namespace. SDK users do not implement
these callbacks. Per-Agent views inherit the host owner and cannot disable this
governance through a Context or storage selection.

Keep the Worker running while draining handlers and their end acknowledgements:

```python
async with build_temporal_worker(client, task_queue=queue, runtime=execution):
    # Run the application using the existing TemporalEngine/Runtime APIs.
    try:
        await application()
    finally:
        await execution.close_context_execution(wait_timeout=30)
        await execution.close_session_execution(wait_timeout=30)
# Close application-owned clients/data only after their execution owners drained.
```

`wait_context_executions(wait_timeout=30)` returns a strict boolean. Closing rejects
new Context reads from this runtime (including pending admission waits) and raises `CloseIncomplete` if a handler or
end acknowledgement remains. Retain the original resources and retry the drain.
An observer's cancellation or a server timeout is insufficient evidence of a
thread's termination.

## Replace the owner

Inject a `ContextExecutionPort` with fixed JSON `identity` and async
`execute(operation, *, proof, on_end=None)`, `wait(*, wait_timeout=30)` and
`aclose(*, wait_timeout=30)` methods. `execute` awaits the actual value, keeps
delegated work owned, and acknowledges completion through the supplied callback
only after the handler and its tracked threads end. The callback's completed
return is `None`. Failed or cancelled notifications remain owned until retried
and acknowledged. A returned lazy value is not completed I/O.

```python
shared_owner = ContextExecutionOwner(max_calls=8)
execution = TemporalRuntime(
    providers={"default": provider},
    tools=ToolRegistry(),
    context_reads=True,
    context_execution=shared_owner,
)
```

The injected owner is borrowed: runtime close waits for it and closes this
runtime's read admission, but does not close the shared owner. The application
closes it after all sharing runtimes drain. Registered providers, stores and
client pools remain borrowed in both forms.

Default thread-safe memory bridges reuse `ThreadExecutionTracker`; async clients
stay on their creation loop. Sharing one owner concurrently across multiple
event-loop threads is unsupported; sequential-loop cancellation recovery retains
its original work and retries notifications when the pinned client remains usable.
Opt-in threaded dataset inspection also fixes its
actual metadata bridge in `context_read_metadata_bridges`, preserving the legacy
dataset-port release. A replacement port cannot detach undeclared background
work. `ContextExecutionRejected(handler_not_started=True)` is valid only if that
refusal started no handler. Duplicate ownership reports `False`, so it cannot
discharge the first still-running reader.

## Evidence and boundaries

`await engine.context_read_stages(run_id)` queries original History without data
reads or recovery. Records expose the fixed phase/request digest/epoch, response
observation, actual end proof and status. Invalid snapshots become failure
evidence while retaining the handler gate. Late responses cannot revive a
cancelled Run. Ungranted timed-out reads are permanently fenced.

This API owns the five declared read phases. Summary model calls, artifact
writes, business models/tools, root Session reads and Session saves retain their
own execution/effect contracts. A Context drain is not a whole-Worker shutdown
certificate. If a process dies before its end notification is acknowledged, the
original History keeps the read gate closed. Restarting a Worker alone cannot
release it. A trusted supervisor may submit the exact original end proof only
after verifying that the original process and delegated handlers have terminated.
The process-recovery tests use an owned process kill followed by actual wait;
this is a read-only recovery boundary, not proof that external writes are safe
to repeat. There is no automatic process supervisor or recovery CLI in this subset.

`context_reads=False` preserves legacy manifest/request/retry behavior. Explicit
enablement publishes `kernel=temporal-3`, `binding_protocol=2` and
`context_read_protocol=1`; dev67 refuses the new binding protocol before I/O.
Actual dev67→dev68→dev67 default and native save-v1 tests preserve original
approval/Turn receipts and one tool execution per original Run.
