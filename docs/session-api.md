# Durable Local Sessions — dev32 / H2b1

H2b1 adds explicit durable conversations for native Agents, sequential Workflows
and their existing capability bindings. Session and execution records share the
same SQLite connection and Coordinator. Remote Session stores, Graph/Team/Dynamic
Sessions and Temporal facade remain unsupported; stateless composition is unchanged.

## Open and continue

```python
from ralf_agent import Agent

# model is an explicitly configured Provider. No model call occurs when opening.
async with Agent(model=model, db_path=".ralf/runs.sqlite") as agent:
    session = await agent.open_session("customer-42", command_id="open-42")
    first = await session.run("My order is 123", command_id="turn-1", wait_timeout=10)
    second = await session.run("What was the order?", command_id="turn-2", wait_timeout=10)
    print(second.snapshot.state, second.snapshot.result)
    ref = session.ref.to_dict()
```

`run` returns WaitResult; use submit for AgentRun with `.turn` (TurnAdmission).
Each accepted Turn has a stable turn_id, increasing turn_seq, original binding
revision, input digest and RunRef. Coordination also fixes the Runtime authority_locator; reconnect with the original locator, not an unregistered alias. Duplicate command_id returns the exact original
Turn/receipt. Reusing it with changed input/budget/ref conflicts. History is read
through the existing Session/context ports; this does not claim real recall quality.

Shared Runtime uses `await agent.open_session(...)` or
`await runtime.open_session(AgentHarness(definition), session_id, command_id=...)`.
`runtime.attach_session(SessionRef.from_dict(ref))` observes the existing route.
Attach/status/turns do not resume work. Use the original RunRef and explicit
resume/approve/cancel/reconcile; human control is not a new Turn.

## Busy, binding and rebind

```python
from ralf_agent import SessionBusy

try:
    run = await session.submit("Next request", command_id="next-1")
except SessionBusy as busy:
    original = runtime.attach(busy.run_ref)
    print(await original.pending())
```

Busy rejects durably with the original RunRef and `.receipt`; replaying that same
command stays rejected after the blocker completes. A new attempt uses a new ID.
Busy does not create a second Run or increment seq. Reject receipts identify the
rejected proposed Run; its original blocker is `busy.run_ref`.

Opening fixes the declaration and resolved manifest. Moved defaults never silently
upgrade existing Sessions. Original receipt replay precedes current model resolution;
new input with missing original components refuses; successfully resolved changed manifests produce durable binding rejection receipts. Restore them or rebind
explicitly while idle:

```python
updated = await session.rebind(
    new_definition,
    expected_binding_revision=session.ref.binding_revision,
    command_id="rebind-1",
)
```

Rebind is a durable CAS, retaining old declarations/receipts and affecting future
Turns only. Use the returned entry/ref; a stale handle cannot submit a new Turn,
but its accepted command still replays and its history remains observable.
Changing resource/namespace requires a new Session/explicit branch, not rebind.

## What occupies the Session

Approval, nonterminal intent, actual handlers/threads and unknown tool writes keep
the lane busy through close/restart. A succeeded native/sequence also requires
confirmed final Session append matching the original result/message_id. Failed
before successful result intent need not invent an assistant message.

`await session.status()` is a pure evidence-based eligibility observation;
`await session.turns(after=0, limit=100)` returns up to1000 ordered records.
The latest owner pointer advances atomically on the next explicit admission/rebind,
not on a timer or observation. Run state, real execution quiescence, save confirmation
and unknown effects are separate conditions. No queue or TTL lease is supplied.

Session entry close only detaches. Shared Runtime and existing RunHandles retain
H2a ownership/observation behavior. After Runtime close, use original code/components,
SQLite file and explicit SessionRef/RunRef reconnect; no new defaults or dispatch
are chosen by queries. Port/factory implementations must finish synchronously
inside the owning execution transaction. Mutation methods return None, save evidence is an actual bool, and read methods return concrete finite JSON data; deferred results are rejected without entering them.

## Resource safety and Schema2

SessionKey fixes trusted workspace/principal, canonical physical resource digest,
namespace and ID. Only SQLiteMemory sharing the actual execution connection is
allowed, optionally through an authorized SessionView. All sequence steps share
one namespace; address aliases cannot register separate routes. Raw submit is
refused on registered addresses even while idle; explicit Turn admission holds
the scoped permit and original acceptance transaction.

The first valid Session open atomically enables execution schema2 and creates the
Session/Turn tables. Ordinary databases without Session activation stay schema1.
Current Readers support both; dev31 and earlier SDKs refuse schema2 before execution.
This is an explicit opt-in one-way compatibility boundary: keep upgraded code for
an activated database, or use a separate schema1 database for old executors.
Failed first acceptance rolls back activation. There is no automatic downgrade.

`SessionAdmissionStore` is an optional, replaceable authority-bound port; custom
stores expose create_session_admission and must share the real transaction owner,
backend identity, raw-route protection, legacy query and save evidence. This does
not make arbitrary database adapters or independent Redis/PG coordinators compatible.

Shared remote routing/admission, additional Session compositions, durable FIFO,
input continuation, deadline, handoff, Temporal entry and full H2b remain separate
capabilities in the [remaining checklist](remaining-work.md).
