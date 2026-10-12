# Actual Tool execution lifetime

Use this explicit Temporal option when a cancelled Activity observer must retain
the actual Python operation, delegated threads and the original History end
acknowledgement. It composes with Agent, sequential, Graph, Team, Dynamic and nested
definitions through their original managed child Runs.

```python
from ralf_agent import TemporalProfile, TemporalRuntimeBuilder

profile = TemporalProfile(
    "app",
    "1",
    {"default": {"adapter": "offline-echo"}},
    {"tool_execution": {"adapter": "tracked", "config": {"version": "1", "max_calls": 8}}},
)
assembly = await TemporalRuntimeBuilder().abuild(profile)
try:
    # Start its Worker and create an Engine with the original Temporal client.
    release = assembly.release
finally:
    await assembly.aclose()
```

`max_calls` is 1–256 and includes calls awaiting an end acknowledgement. The
configuration is preflighted before data or Worker allocation. Local Profiles
reject this Temporal-only component. Omitted configuration retains existing
manifest and execution behavior. Explicit publication requires new Workers:
`temporal-3`, `binding_protocol=3`, `tool_execution_protocol.version=1`. Existing
Context read protocol1 can compose with it.

`ToolExecutionPort` exposes fixed ordinary JSON `identity` and asynchronous
`execute(operation, *, proof, on_end=None)`, `wait(*, wait_timeout=30)` and
`aclose(*, wait_timeout=30)`. `ToolExecutionOwner(version="1", max_calls=8)` is
the basic implementation. A custom port must own the actual operation and all
delegated threads until completion, then retain/retry the original end callback
until acknowledged. It must not execute a duplicate original call. Identity and
the implementations are fixed at publication and checked during execution.

Direct `TemporalRuntime(tool_execution=owner, ...)` injection borrows the owner.
Runtime closure waits for it but does not close a shared port. The tracked Profile
factory owns its owner in the original assembly ledger. Assembly closure stops
admission, drains actual execution and end acknowledgements, then stops its
Worker and closes owned tools, native roots and clients. `CloseIncomplete` retains
resources for a later retry. Use finite nonnegative close timeouts.

Original History persists the complete Tool intent before dispatch. Dedicated
admission and end Updates bind Scope, Action, release, request digest and Workflow
epoch; callbacks retain the original SDK Workflow handle and namespace. Missing
callbacks refuse execution before I/O. An end proof is accepted idempotently by
the original History and is available after Worker restart.

Effect evidence is independent. A receipt query can settle the effect budget but
cannot prove a remote handler stopped. Actual end can confirm stopping while an
effect remains unknown. Both gates must close before quiescence; a cancelled Run
stays cancelled after late evidence. Next business operations wait for original
Tool ends, while acknowledgement and reconciliation can continue. Diagnostics
include `workflow.tool_executions` only for this opt-in publication.

This does not provide process isolation, an external peer stop guarantee, or
automatic recovery of an owner killed with its process. An end proof lost with
that process remains conservative. See [native lifetime acceptance](../architecture/reviews/2026-10-12-native-write-lifetime.md)
and [remaining capability list](remaining-work.md).
