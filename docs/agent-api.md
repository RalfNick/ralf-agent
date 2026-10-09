# Local Agent API — dev31 / H2a

H2a delivers an async Local stateless application entry, independent task hosting,
pure observations and retryable closing. Existing Harness remains the pure
DecisionPolicy; AgentHarness freezes capability declarations and delegates actual
execution to LocalEngine. dev32 adds the explicit [colocated native/sequence Session H2b1 subset](session-api.md); dev33 adds the [Temporal native/sequence entry](temporal-agent-api.md). dev34 extends this entry to registered Graph/Team/Dynamic/nested definitions. Full H1/H2, Temporal bindings/shared Sessions and automatic H3 stages remain pending.

## Standalone Agent

Provide an explicit model and trusted tools; no credential discovery or paid calls
occur during construction. Native Providers follow the [model guide](model-adapters.md).

```python
from ralf_agent import Agent, ToolRegistry

tools = ToolRegistry()


def lookup(order_id: str) -> dict:
    return {"order_id": order_id, "status": "ready"}


tools.register_function(lookup, effect="read_only")

# model is your explicitly configured Provider; db_path is your execution database.
async with Agent(model=model, tools=tools, db_path=".ralf/runs.sqlite") as agent:
    observed = await agent.run("Look up order 123", command_id="order-123")
    print(observed.snapshot.state, observed.snapshot.result)
```

`command_id` is required. `run` is submit+wait; result is a WaitResult, whose
snapshot remains authoritative business state. Waiting approvals/reconciliation
are successful observations, not successful business outcomes.

## Shared Runtime and existing definitions

```python
from ralf_agent import AgentHarness, AgentSpec, Runtime

async with Runtime(local_engine, owned=False) as runtime:
    agent = runtime.create_agent(AgentHarness(AgentSpec("research", "Research the task")))
    handle = await agent.submit("Question", command_id="research-1")
    observed = await handle.wait(wait_timeout=5)
    await agent.aclose()  # Only closes this entry; Runtime and handle remain usable.
    print(await handle.status())
```

`owned=False` is the default for injected LocalEngine/RuntimeInstance. Runtime owns
its hosted tasks, drains them, and leaves borrowed Engine/resources open. Explicit
owned=True closes the injected authority after draining. Standalone Agent owns
its created Runtime. Keep a shared Runtime open for all its borrowed Agents.

Existing AgentDefinition/BoundDefinition, sequence, Graph/parallel, Team and
Dynamic/nested specifications are accepted without rewriting legacy requests.
Per-Agent bindings and actual limits remain with the authority. Runtime supports
`from_profile(profile, path, builder=..., scope=trusted_scope)` and `await afrom_profile(...)`; the latter
preserves existing loop-bound async factories and owned cleanup.
Scope comes from the trusted host; omitting it preserves the builder's local default.

## Wait, controls and reconnect

- wait/status/attach only read committed facts. Timeout returns
  observation_timeout; cancelling their await propagates CancelledError and does
  not cancel business execution. terminal_only=True waits through human pauses.
- submit/resume and explicit controls wake the hosted authority. A failed host
  reports ExecutionHostFailed on both root and child waits, retaining the original Run; fix the original
  component and explicitly resume. Queries never choose a new model/release.
- status/events/diagnostics expose durable evidence; they do not create new work.
- `await handle.pending()` discovers original approval/reconciliation owners,
  including nested children. Attach that returned RunRef to apply the control;
  the original root is then woken, without independently dispatching its child.
- approve/cancel/reconcile require stable command_id and return original receipts.

```python
from ralf_agent import RunRef

for item in await handle.pending():
    owner = runtime.attach(RunRef.from_dict(item["ref"]))
    if item["kind"] == "approval":
        await owner.approve(item["action_id"], item["digest"], command_id="approve-1")
```

RunRef.to_dict/from_dict serializes Scope, original release digest, run_id and an
opaque authority locator, without clients or credentials. The default locator
hashes the execution Store's stable backend identity; custom stores need a trusted
stable opaque locator. File/authority movement is an explicit migration, not a
silent alias change. Reference validation is routing/access checking, not identity
authentication; trusted host Scope remains the current security boundary.

After closing, live handles raise RuntimeClosed. Open a new Runtime using the
original code/components/database, attach(ref), then explicitly resume or apply a
control. attach alone does not restart old queued/paused work.

## Closing and limitations

Default drain blocks new accepts, waits hosted tasks and real managed threads,
and parks stable approval/unknown-effect responsibilities with their RunRefs.
The CloseReport is available as runtime.close_report or returned by aclose.
Terminal Run state alone does not imply unknown writes have been resolved.

close_timeout defaults30 seconds; timeout raises CloseIncomplete with a report,
keeping the shutdown task/resources and necessary ownership. A cancelled close
wait also leaves cleanup running. Retry await runtime.aclose; store/client closing
failures remain retryable. Body errors remain primary, with closing failure noted
and chained. Pending approval is not automatically rejected. Explicit
close_policy='cancel' applies stable cancellation only to managed Runs, waiting
actual completion before releasing resources. Cancellation is not remote rollback.

One Runtime uses one hosting event loop. Existing async resource creation-loop affinity is checked before accepting intent or binding the facade; a wrong-loop call leaves owner-loop recovery available. Close it before stopping that loop.
Actual process/loop exit does not promise continuing Local work; durable accepted
intent can be explicitly recovered. Runtime task indexes contain active/paused/
failed-host responsibilities, not an unbounded completed-Run history.

The Local raw stateless submit entry still refuses shared session_id, queue, deadline_at and handoff. dev32 provides explicit [colocated native/sequence Sessions](session-api.md) with durable Turn/rebind; dev33 provides explicit Runtime.from_temporal for native/sequence remote runs. Broader Session/remote facade combinations remain pending. Private per-Run legacy
Session storage remains; it is not cross-Turn conversation coordination. Default
polling waits are not streaming dataflow or hosted SSE. CLI still uses its legacy
entry. Remaining H2b remote/composite Sessions, H3 recommended managed context/memory/RAG and H4 environments
remain separate deliverables.
