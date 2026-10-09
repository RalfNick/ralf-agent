# Independent Temporal execution — dev17 preview

`TemporalEngine` implements the public AsyncExecutionEngine/AsyncRuntimeDiagnostics
ports. Network controls are explicitly awaited. A Temporal Workflow owns commands,
Actions, approvals, credit reservations, evidence adoption and terminal decisions
in its History. Model/tool Activities use registered components; they do not wrap
LocalEngine or open a local execution store.

Install `ralf-agent[temporal]`; provide your Temporal Service and worker registration.
The SDK starts no server or worker implicitly. A minimal worker uses:

```python
from temporalio.client import Client
from ralf_agent import (
    TemporalRuntime,
    TemporalEngine,
    build_temporal_worker,
    ToolRegistry,
    AgentSpec,
)
from ralf_agent.runtime_builder import EchoProvider


async def run_example():
    client = await Client.connect("127.0.0.1:7233")
    runtime = TemporalRuntime(providers={"default": EchoProvider("offline")}, tools=ToolRegistry())
    worker = build_temporal_worker(client, task_queue="ralf-v1", runtime=runtime)
    engine = TemporalEngine(client, task_queue="ralf-v1", release=runtime.manifest)
    async with worker:
        handle = await engine.submit(AgentSpec("answer", "Answer"), "hello", command_id="first")
        result = await engine.drive(handle.run_id)
        assert result.state == "succeeded"
    await engine.aclose()
```

Run multiple worker processes on that queue with the same registered release.
The facade's Client and runtime dependencies are borrowed; the host closes owned
Provider/journal resources after worker shutdown. The release contains immutable
identities/code digests, never serialized live clients or credentials. Worker drift
is refused before new external dispatch. Changes require retaining workers capable
of the old release and its recorded queue; this increment adds no rolling-upgrade
or deployment-version management service.

## Supported capability subset

Native Agent and sequential Workflow are supported with the default NativeHarness
and History context. Provider and ToolExecutor ports are replaceable; synchronous
policy must return None after completed authorization, or raise a typed denial.
The default `runtime.manifest` supports this native subset. The explicit
`runtime.orchestration_release` adds Graph/DAG/Team/nesting and registered RAG,
as described in [distributed composition](temporal-composition.md). Shared Sessions,
fact memory, custom Harness and catalog routing remain refused.
Do not assume LocalEngine feature parity.

Scoped command IDs are checked across Runs/control kinds by a History-backed
identity registry; the target Run Workflow alone issues applied receipts.
Submit replay recovers the original release and receipt. Approval binds Action
and operation digest. Queries authenticate the trusted Scope. `drive` is a bounded
wait for progress; service/workers continue after a disconnected caller. Temporal
Updates and replay implement durable controls as described in its
[message-passing documentation](https://docs.temporal.io/develop/python/message-passing).

## External effects

Write tools require an EffectJournal. The default
`await PostgresEffectJournal.connect(dsn, backend_id="effects-v1")`, followed by
`await journal.initialize()`, persists dispatch intent and immutable received
observations. Pass it to TemporalRuntime(journal=journal). The public structural
EffectJournal port supports replacement with matching atomicity/exclusion contracts.
PostgreSQL is evidence storage, not a second execution authority.

Activities use one dispatch attempt, with no automatic write retry after a lost
reply. Uncertain Actions keep their credit hold. Reconcile by the original key with
`await engine.reconcile(run_id, action_id, command_id="query-1", query=True)` or
verified manual evidence. A cross-Run scoped tool/argument guard remains until
Workflow History adopts evidence and acknowledges the journal. Received evidence
alone cannot clear the guard. Cancellation stops new dispatch; late observations
remain evidence and cannot replace a cancelled terminal result.

History persists model/tool evidence before decision/result adoption. History can
be downloaded from the Client and checked with `replay_temporal_history(history)`.
Real worker kills after external commit, lost-receipt reconciliation and repeat
controls are acceptance probes. They establish these tested boundaries, not
arbitrary external exactly-once execution.

This preview keeps business-terminal Run Workflows open for receipt replay/late
evidence; command registry capacity is finite (4096). History compaction,
Continue-As-New, retention, global quotas, recovery administration,
enterprise identity and deployment failover remain unimplemented. Use separate
queues/retained registrations for trials and inspect actual History/service state.


In dev16 the same facade can be borrowed by A2AApplication with PostgresInbox; see [async handoff](async-handoff.md). Workflow state is initialized before Queries/Updates can arrive. Actual dev15 Run/registry History replay remains compatible. dev17 extends the execution subset through an explicit orchestration release; native identities remain unchanged.

Effect confirmation through a reconciler cannot prove a lost handler has stopped. A parent retains escrow when remote stop remains uncertain, even after effect credits have been settled. Recovery/remote-stop administration is a future contract. Native default History replay remains independent of the opt-in composition release.

Dev21 registers pure custom ContextBuilders through an additive release and a
separate History snapshot; default native context remains compatible. See
[custom context](temporal-custom-context.md).
