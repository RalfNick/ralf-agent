# Temporal Agent API — dev34 / H2c1–H2c2

Current dev60: [Temporal automatic memory and per-Agent bindings](temporal-memory-bindings.md), [Facts recall](temporal-facts.md), [scoped Knowledge](temporal-knowledge-bindings.md) and opt-in [History Sessions](temporal-sessions.md) reuse original Histories. Legacy default-off identities remain unchanged; external Session data and other binding roles remain unsupported.

Use the same Agent/AgentHarness/AgentRun API with an explicitly configured
TemporalEngine. Native AgentSpec/WorkflowSpec are supported; an explicitly
registered orchestration release also enables Graph, Team, Dynamic and nested
definitions. No new server Workflow, History format or execution authority is introduced.
See [Temporal setup](temporal-execution.md) for the optional SDK, fixed worker
release, trusted Scope and running Service/Workers.

```python
from relf_agent import AgentSpec, Runtime

# engine is a configured TemporalEngine; its Client and Workers are borrowed.
async with Runtime.from_temporal(engine, owned=False) as runtime:
    agent = runtime.create_agent(AgentSpec("support", "Answer using evidence", ("lookup",)))
    run = await agent.submit("Where is order 123?", command_id="order-123-1")
    observed = await run.wait(wait_timeout=10)
    print(observed.snapshot.state, observed.wait_reason)
    saved_ref = run.ref.to_dict()
    for item in await run.pending():
        print(item["kind"], item["action_id"], item["digest"])
```

Tools/providers and their approval/effect rules come from the registered worker
release. The facade selects a definition; it does not run models/tools in the
client. Standalone `Agent(model=..., db_path=...)` remains the Local default.

## Reference and recovery

```python
from relf_agent import RunRef, Runtime

async with Runtime.from_temporal(reconnected_engine) as runtime:
    run = await runtime.aattach(RunRef.from_dict(saved_ref))
    pending = await run.pending()
    if pending:
        approval = pending[0]
        owner = await runtime.aattach(RunRef.from_dict(approval["ref"]))
        await owner.approve(
            approval["action_id"], approval["digest"], command_id="approve-order-123-1"
        )
    print((await run.wait(wait_timeout=30)).snapshot.result)
```

`await runtime.areference(run_id)` obtains a validated original RunRef.
`await runtime.aattach(ref)` validates actual resource, trusted Scope, original
release and native/parent backend before returning a handle. Local Runtime offers these
same additive async methods. Existing Local sync reference/attach stay compatible;
Temporal sync variants explicitly request the async variants.

The opaque locator hashes the Client's actual endpoint, namespace and optional
`authority_locator` alias seed. The seed is not the resulting RunRef locator;
save `runtime.authority_locator`/the returned ref. Reconnect using the original
canonical endpoint, namespace, seed and Scope. Queue/default release changes do
not move the authority or re-resolve historical receipts. Endpoint aliases,
cluster-ID discovery and cross-service migration are not normalized automatically.
Client/resource/Scope changes inside an open Runtime are rejected, including
changes during an awaited query/control. Create/use/close on the same event loop.
Each operation captures a configuration view so default engine methods use the
original Client/namespace/Scope/release throughout internal awaits. A late change
can still occur after the original server accepted the authorized control; it is
reported, never redirected to the replacement resource. Custom engine overrides
must honor this view rather than call a captured mutable original dispatcher.

Always provide original command_id. Duplicate submit/controls return their
original receipts. Cancellation or response loss does not prove nonacceptance;
retry the exact original request/ID. Runtime holds started submit/resume/control
RPC tasks independently of the caller, so cancellation of that await does not
discard the RPC. Event-loop/process termination still requires explicit recovery.

## Observation and explicit controls

status/events/diagnostics/pending/wait/attachment only query accepted facts;
they never emit drive/cancel or retry a model. Submit and controls wake the
existing server Workflow. Explicit resume uses the original engine drive command;
its client polling is zero-duration and Workers keep execution ownership.

wait returns on terminal or human-wait states; `terminal_only=True` waits for a
terminal state. wait_timeout bounds slow remote queries too. A timed-out query
returns the last validated snapshot with its actual `observed_at`, rather than
claiming fresh server state. Handles receive an initial snapshot at submission/
async attachment; `wait_timeout=0` uses that observation. Query errors propagate;
caller cancellation propagates CancelledError and stops only observation.
Transport/query TimeoutError propagates; only expiration of this wait's own timer
becomes observation_timeout. Cached/returned values are detached. Timeout never creates a business timed_out
state, cancels Activities or proves external effects have stopped.

approve/reject via `approved=False`, cancel and manual reconcile keep existing
CommandReceipt semantics. Only explicit resume emits drive. Richer reconciliation
query and DAG patch remain available on the raw TemporalEngine, outside this subset.

## Graph, teams, plans and actual control owners

Configure Workers with `TemporalRuntime` and pass its `orchestration_release` to
TemporalEngine, as in [distributed composition setup](temporal-composition.md).
The same submit/reconnect/observe API then accepts the existing definitions:

```python
from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, RunRef, TeamSpec

specialist = AgentSpec("lookup", "Answer from the lookup result", ("lookup",))
graph = GraphWorkflowSpec("investigate", [GraphNode("lookup", agent=specialist)])
team = TeamSpec("support", {"investigator": graph}, child_budget=24)
agent = runtime.create_agent(team)
run = await agent.submit("Investigate order 123", command_id="investigate-123", budget=64)
await run.wait(wait_timeout=30)
for item in await run.pending():
    owner = await runtime.aattach(RunRef.from_dict(item["ref"]))
    if item["kind"] == "approval":
        await owner.approve(
            item["action_id"], item["digest"], command_id="approve-" + owner.ref.run_id
        )
# Workers observe child outcomes and advance the parent without client drive.
print((await run.wait(wait_timeout=30)).snapshot.state)
```

DynamicWorkflowSpec with a registered planner supports both sequential plans and
DAG plans, with existing bounded verification/replanning. Model planners run their
existing managed child Agent; using the facade does not establish planning quality.
Graph nodes must contain supported Agent definitions; direct Tool/Transform nodes
and other binding roles remain unsupported on Temporal. Dev46 temporal-3 accepts
the five versioned roles described above. Native/sequence support does
not require the orchestration extension. Capabilities reflect the current release;
an attached historical parent remains queryable if current defaults move.

`pending()` traverses original child intents and fresh diagnostics on one pinned
dispatch view. It validates parent-derived command/Run identities and original
request/manifest release correspondence. It ignores stale aggregate parent pending
items and returns actual native owners, including nested unknown tool effects after
root cancellation. Attach each returned ref before approval/reconciliation; passing
a child action to the parent is rejected by the authority.

Discovery is bounded to 4096 distinct identities and 16 levels; duplicates/cycles,
malformed or mismatched evidence fail explicitly. Intents not yet marked started
are skipped; an unavailable started child propagates its error. Settled children
have no pending work under the server contract. This is not an atomic tree snapshot;
workers may advance between queries, so controls must use original command IDs and
digests. Cancel root explicitly for server propagation; child controls require no
synthetic root drive. Parent `outcome_unknown` is a human-wait state. Native terminal
snapshots omit unusable approvals while retaining original Action and receipt records.
Manual reconciliation confirms an effect result, not that a lost remote handler
has stopped; diagnostics may retain unknown execution and ancestor credit holds.

New parent Histories use the compatible `ralf-parent-control-evidence-v2` patch
marker: snapshot, budget and execution stop/uncertainty evidence remain strict;
private child cancellation/planning bookkeeping does not create a false execution
conflict. Histories without the marker retain their original v1 comparison rules.
This preserves replay rather than rewriting old evidence, so a legacy Run affected
by that bookkeeping race does not acquire the new behavior automatically. Keep
current Workers for new v2 Histories; old-worker downgrade is not certified.

## Close and unsupported combinations

Remote default/only close policy is `detach`. Close stops new submissions and
flushes actual in-flight managed RPCs; it does not wait for business Runs to finish,
reject pending approvals, stop Workers or cancel Activities. Shared Agent close
only detaches its entry. `owned=True` additionally closes the TemporalEngine facade;
its Client transport and Workers remain borrowed under the original engine contract.
`CloseReport.parked` is empty for this client, which does not own server business
history; retain your RunRefs and original command IDs.

Close timeout raises CloseIncomplete and retains shielded cleanup; cancelled close
waits also leave cleanup running. Retry `await runtime.aclose(...)`; owned-close
failure remains retryable. An existing context-body exception remains primary.
`hosting_status.running` counts outbound RPC tasks, not server Runs/Activities;
completed tasks and historical Runs are not retained. RPC failures are counted,
not inferred to be server failure or nonacceptance. A finished failed RPC can still
leave a durable server intent, so recovery uses its original command ID.

Capability/refusal checks are explicit: six registered bound roles and registered definition subset.
External SessionStore selection, queue, deadline_at, input and handoff remain refused.
History Sessions require explicit session_protocol registration; see below. Local Session schema2 and
legacy releases are unchanged. Full
H2 and [remaining Harness stages](remaining-work.md) remain incomplete.

## dev60 History Session entry

Opt-in `TemporalRuntime(enable_sessions=True)` adds `await runtime.open_session`, `aattach_session` and asynchronous submit/status/turns/diagnostics/rebind. Native and registered advanced compositions share durable serial Turns. Session references use actual Namespace UUID identities, while original raw RunRef endpoint identities remain unchanged. Conversation is History-owned; external SessionStore binding selection remains refused. See [Session usage, recovery and bounds](temporal-sessions.md).
