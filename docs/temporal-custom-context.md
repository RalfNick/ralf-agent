# Registered Temporal custom context

Current dev46: [Temporal automatic memory and per-Agent bindings](temporal-memory-bindings.md) adds the opt-in temporal-3 protocol. Legacy protocol identities remain unchanged; shared Session/Facts recall and other binding roles remain unsupported.

dev21 accepts custom synchronous ContextBuilders, including the budgeted pipeline,
as explicit worker dependencies. Native default releases retain the dev20 manifest;
custom builders add `context_registration` with configuration and implementation
digests. Deploy matching registrations on every Worker for the task queue.

```python
from relf_agent import BudgetedContextAssembler, UTF8TokenEstimator, ToolRegistry
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal import TemporalEngine, build_temporal_worker

runtime = TemporalRuntime(
    providers={"default": provider},
    tools=ToolRegistry(),
    context_builder=BudgetedContextAssembler(
        counter=UTF8TokenEstimator(),
        max_units=4096,
    ),
)
worker = build_temporal_worker(client, task_queue="ralf-context-v1", runtime=runtime)
engine = TemporalEngine(client, task_queue="ralf-context-v1", release=runtime.manifest)
```

The ContextBuilder still implements pure `assemble(history, references, max_chars)`.
An optional synchronous `validate_request(messages, max_chars)` returns a completed
ContextMeasure and checks the actual Harness request. Counter units can be estimates;
they do not promise exact model tokens or billing limits.

A context Activity assembles bounded messages and returns a snapshot. Workflow
History records that snapshot before scheduling the model Activity. The worker
validates registration before and after calls, checks optional knowledge sources
after awaits, then validates the actual prepared request before disclosure. Swapping
an instance, method, validator or configuration under the same identity is rejected.
Lazy/async builder results are unsupported. Activity retries remain disabled; worker
failure after a model request can leave an unknown charged outcome, as in the
existing native contract. Context assembly itself cannot perform model/tool I/O.

Use ManagedModelSummarizer on a tool-free Temporal Agent to create a durable summary,
then register a frozen summary in the builder when its coverage matches the intended
history. Live model summarization inside a ContextBuilder is not supported. Shared
Session/Facts recall, custom Harness and arbitrary runtime catalog switching remain
outside this release. Temporal retains independent History authority.

The real-service acceptance test uses two separate Worker processes, records context
before an approval pause, kills both Workers, restarts them, resumes the same Run,
then replays Run and summary History. This is separate from baseline native History
compatibility and deterministic state tests.

Dev44 additionally accepts explicitly registered `ManagedContextPipeline`/`ManagedDataContext` via temporal-2: History owns independent auxiliary stages and actual child Agent decisions. Pure custom builders keep temporal-1. See [managed Temporal context](composite-temporal-context.md); this does not add Session/Temporal per-Agent bindings or automatic memory writes.
