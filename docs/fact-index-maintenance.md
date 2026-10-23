# Automatic native Facts index maintenance

This opt-in composition refreshes an index through an original Graph ToolAction
before a reader Agent. It extends the existing Facts index with generation-bound
maintenance; the original `IndexedMemoryStore.rebuild` and its defaults remain
unchanged. Native SQLite/Hash wiring is the initial supported composition.
Candidate source checks are separate from final installed release acceptance.

Install the locally built wheel and create the editable application:

```sh
python -m pip install /path/to/relf_agent-0.1.0a5-py3-none-any.whl
ralf init application --template memory-index
cd application
python -m agent_app run --format toml --command-prefix first
python -m agent_app run --format json --borrowed --session-id borrowed-preferences --command-prefix second
```

The generated SDK, JSON and TOML declarations select the same business corpus.
Within one ownership mode, format changes preserve the original Session binding.
Switching owned/borrowed mode changes that binding, so the second command explicitly
selects a different Session. The CLI default remains `preferences-session`; use
`--session-id` to select a Session without weakening its fixed binding checks.
An explicit resource ID, trusted Scope and Facts namespace identify each pairing;
helpers compute the canonical config digest internally. The app-prefixed adapter
names select its full editable source in `agent_app/adapter.py` and its sibling
index/tool modules. The packaged default adapters remain independently available.

Each actual Session turn runs a serial Graph with two nodes: a maintenance tool
with `Literal({})` and a ready-only output Schema, then a dependent preferences
Agent. The fresh first index has no Facts. The first adopted offline result commits
a grounded preference through the existing rule memory stage. The second turn
refreshes automatically, and its original model request receives the actual
current Fact key, version and value. Session data uses the execution database;
Facts, vectors and catalog each use separate native files. No manual rebuild or
implicit seed occurs during run, construction or recovery.

The offline provider is a disclosed wiring and lifecycle signal. Model/task quality,
remote services, HTTP/custom embeddings or indexes, and Team/DAG/Temporal
maintenance remain unverified. This bounded native increment does not close the
remaining R01–R26/H3/M1 requirements.

## SDK composition

```python
from ralf_agent import (
    AgentSpec, ComponentRegistry, ModelResponse, RuntimeBuilder, RuntimeProfile,
    fact_index_maintenance_components, fact_index_maintenance_writer,
    maintained_agent_workflow,
)

class PreferenceFixture:
    identity = {"kind": "preference-wiring-fixture", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output={"preference": "green tea"})

registry = ComponentRegistry()
registry.register("provider", "preference-fixture", lambda config, context: PreferenceFixture())
config = {"resource_id": "preferences-index", "namespace": "preferences"}
components = fact_index_maintenance_components(config)
components["recall_policy"] = {"adapter": "bounded-recall"}
components["stage_policy"] = {
    "adapter": "sourced-memory-async",
    "config": {
        "fields": {"preference": ["result", "preference"]},
        "namespace": "preferences",
        "memory": fact_index_maintenance_writer(config),
    },
}
profile = RuntimeProfile("preferences", "1", {
    "default": {"adapter": "preference-fixture"},
}, components)
instance = await RuntimeBuilder(registry).abuild(profile, ".ralf/runs.sqlite")
flow = maintained_agent_workflow(AgentSpec("preferences", "Read current Facts"), config)
```

This fixture returns a disclosed wiring value; replace its provider and grounded
admission fields for your application. The editable template supplies a complete
Session flow with observed context. Use `await instance.aclose()`
on the original loop after execution has drained. The reader uses the exact
maintained index. The stage writer borrows the same original native Facts source
through `maintained-index-writer`; its raw CAS validation remains independent of
index publication. A write changes the source generation, so the next original
maintenance Action publishes the new index before recall.

Default paths are `.ralf/facts.sqlite`, `.ralf/fact-vectors.sqlite` and
`.ralf/fact-catalog.sqlite`. Declare native `backend`, `embedding`, `index` and
`catalog` options to replace paths/dimensions. These factories validate declarations,
Scope, namespace, resource ID, dimensions and bounds before data allocation; they
reject remote/custom ports and Temporal contexts. A synchronous build refuses
before opening backends. Facts reader and writer references require tools-first
construction and the exact matching config. The helper rejects reader Agent names
that differ from the fixed namespace; custom binding compositions must explicitly
select the corresponding Facts namespace.

## Bounds, receipts and shutdown

The maintenance ToolSource fixes one trusted index and namespace. Empty caller
arguments cannot select resources, Scope, limits, or supply the reserved effect
key. Its host policy explicitly grants an idempotent write with approval disabled,
original key injection, and the exact source reconciler. Before index effects,
its separate CAS journal fixes the original Run/Action/key and source snapshot.
Historical completed receipts reconcile that exact effect even after newer Facts
arrive. Recall independently requires the current source generation.

Only `ready` passes the reader gate. `partial` records actual bounded progress;
`source_changed` records the typed refusal. A new original Action/Turn can continue
with a new effect key. Generic CAS, budget and malformed-port failures preserve
pending intent and their original errors. No hidden retry or cumulative allowance
across many Actions is claimed. Defaults are batch32, source page64000 bytes,
records100000, pages64 per dispatch; supported maxima are batch128, bytes64000,
records100000 and pages256. Original Engine credits remain independent.

The BuildContext owns source/vector/catalog before the async ToolSource so reverse
cleanup drains the source first. Weak pairing entries do not retain BuildContexts.
For explicit SDK borrowing, `create_fact_index_maintenance_owner` supplies the
original owner; register it with `borrowed=owner` and select helpers with
`borrowed=True`. Borrowed adapter names use the `-borrowed` suffix. Close the Runtime
first, then `await owner.aclose()` on its creation loop. A cancelled/incomplete
source drain keeps borrowed connections live. The owner retains its original source/index/native cleanup ledger and checks them
before and after drain. Its public native view is a read-only tuple. Pointer drift
fails closed with `DefinitionMismatch`, retaining `error.maintenance_owner`; restore
the original selected fields and retry on the same loop after actual drain. Native
close failures retain the original pending ledger; construction failure preserves
the original cause.
The generated app also retains its original Runtime/RuntimeInstance/borrowed owner
on `error.application_cleanup`, allowing a concrete same-loop retry after drain.

## Explicit seed and original recovery

```sh
python -m agent_app seed --preference coffee
python -m agent_app inspect RUN_ID
python -m agent_app resume RUN_ID
```

Seeding is an explicit idempotent host write. Inspection uses the original
`ProfiledEngine` through `agent_app.runtime:create_engine` and never discovers,
opens or seeds maintenance backends. Async resume reads the original accepted
profile identity with `SQLiteRunReader`, resolves it in the catalog, reconstructs
through `abuild`, reconnects the recorded Session reference and resumes the original
Run. A changed default alias cannot replace that profile. Missing/changed originals
fail before maintenance effects. Preserve the generated source/catalog for recovery.

The existing synchronous `ralf --factory agent_app.runtime:create_engine resume`
cannot construct these async tools and is not advertised as a continuation path.
Explicit resume retains original authority semantics, including separately reserved
new Attempts and old unknown holds where the original recovery contract permits them.
Only exact received effect/model receipts justify adoption without redispatch.
