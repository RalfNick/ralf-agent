# Distributed composition — dev17 preview

Install `relf-agent[temporal]` and provide a Temporal Service. Native Agent/sequence
use the existing `runtime.manifest`; Graph/Team/Dynamic use the explicit
`runtime.orchestration_release`. A registered Parent Workflow owns its plan,
child intents, scoped commands and budget in History. It starts actual Child
Workflows; an Activity does not create a LocalEngine or a competing SQL scheduler.

```python
from temporalio.client import Client
from relf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    Scope,
    TemporalEngine,
    TemporalRuntime,
    TemporalExecutionPolicy,
    ToolRegistry,
    build_temporal_worker,
)
from relf_agent.runtime_builder import EchoProvider


async def example(address):
    client = await Client.connect(address)
    runtime = TemporalRuntime(
        providers={"default": EchoProvider("offline")},
        tools=ToolRegistry(),
        execution_policy=TemporalExecutionPolicy(
            max_children=32,
            max_concurrency=4,
            max_depth=4,
            run_timeout_seconds=300,
            approval_timeout_seconds=120,
            allowed_tools=(),
        ),
    )
    release = runtime.orchestration_release
    engine = TemporalEngine(
        client,
        task_queue="my-release-v1",
        release=release,
        scope=Scope("workspace", "trusted-owner"),
    )
    async with build_temporal_worker(
        client, task_queue="my-release-v1", runtime=runtime, release=release
    ):
        handle = await engine.submit(
            DynamicWorkflowSpec(
                "diagnosis",
                {"inspect": AgentSpec("inspect", "Answer")},
                plan_mode="dag",
                child_budget=8,
            ),
            "database timeout",
            command_id="diagnose-1",
            budget=16,
        )
        result = await engine.drive(handle.run_id)
        print(result)
    await engine.aclose()
```

## Delivered definitions and extension points

Static Graph supports Agent nodes, dependency bindings, conditions and bounded
parallelism. A direct Graph Tool/Transform node is refused; place business tools
inside a managed Agent. Team and Dynamic members may contain Agent/sequence/Graph/
Team/Dynamic trees up to the declared limits. Shared Sessions, arbitrary loops,
streaming dataflow and catalog hot routing are unsupported by this backend.

Defaults are `sequential`/`router`/`supervisor` TeamStrategy,
`rule`/`model`/`dag-rule`/`dag-model` Planner and `complete` PlanVerifier. Inject
`team_strategies={name: component}`, `planners={name: component}` or
`plan_verifiers={name: component}` into TemporalRuntime. Registries pin explicit
identity/configuration and method implementation digests; retain original releases
and executable code for recovery. TeamStrategy and Verifier finish synchronously
with typed DTOs; Planner is async and returns PlanProposal/DAGProposal/
PlanningConclusion. Lazy or malformed completion is refused. Model planners declare
a tool-free `agent: AgentSpec`; its model call is a budgeted Child Workflow. The
Planner consumes that recorded result through its caller, rather than making a
hidden Provider request. PlanningRequest contains available definitions, observed
results, remaining steps/revisions, concurrency, depth and credit constraints.

After a DAG is accepted, `await engine.patch_plan(run_id, proposal,
expected_plan_revision=revision, command_id="patch-1")` records an immutable CAS
receipt. Dispatched, completed and skipped nodes cannot change. The remaining
child limit spans earlier plans. Invalid patches raise a typed exception;
the command's immutable rejected application remains recorded in events.

## Evidence, capacity and cancellation

A parent reserves the entire child credit cap and records stable child identity
before registration/start. Repeated dispatch uses that original ID. It adopts
scoped child evidence; terminal state alone does not release the cap. Release
requires actual quiescence, confirmed remote stop and no unknown/acknowledgement/
reconciliation hold. Parent budgets expose an uncertain child cap as unknown;
this is an escrow hold, not a claim about monetary usage.

Approvals and reconciliations apply to the actual leaf Run. Parent pending entries
include `run_id`, Action and digest. A parent query contains its last adopted
child observation: it can briefly lag a newly applied leaf control. Poll
status/diagnostics or drive for convergence. Failure/cancel stops new children,
requests cancellation of started children and keeps late receipts. Parent cancel acceptance records propagation intent; each child adopts cancellation in its own History. A concurrent child control may arrive first. Observe the child cancellation state before a recovery operation that requires the child to be cancelled; the parent receipt alone is not that acknowledgement. No automatic
business rollback or arbitrary external exactly-once guarantee is provided.
Business writes require the EffectJournal plus downstream idempotency or
queryable receipts described in [Temporal execution](temporal-execution.md).

## Execution governance

TemporalExecutionPolicy is immutable and versioned in the release. Defaults are
256 children, 32 concurrent children per parent and 8 definition levels; timeout
fields and tool allowlist are absent by default. Limits cannot be hot edited for
an accepted Run. Run deadlines and approval expiry use History timers. Repeated
drive does not extend an approval's first deadline. Timer precision follows the
Service; these are not millisecond scheduling guarantees. Timeout/cancel keeps
in-flight effects and credits until actual completion or verified reconciliation.

These are per-Run execution controls. Scope comes from the trusted host. Enterprise
OIDC/RBAC/ABAC, resource ownership, tenant/global quotas, cost ceilings, audit
administration, retention/Continue-As-New and certified deployment failover are
still deployment requirements or pending capabilities. Use fresh queues for new
releases and retain compatible old workers; this preview does not certify mixed
version rolling deployments.

## Distributed RAG

`TemporalRuntime(knowledge=KnowledgeContext(...))` uses the existing async Retriever
and KnowledgeStore/VectorIndex ports. Context retrieval is a separate Activity;
History records messages, references and context identity before model dispatch.
The model Activity validates the fixed reference versions/digests and runtime
again before calling the Provider. It does not silently retrieve a replacement
snapshot. Completed Runs and History replay reuse recorded evidence.

For a shared default: explicitly connect/initialize PostgresKnowledgeStore and
QdrantVectorIndex; compose VectorRetriever with HashEmbeddingProvider (offline
baseline) or your async EmbeddingProvider; pass KnowledgeContext to the Runtime.
Insert and index documents explicitly using the same Scope/namespace. Exact
hydration from PostgreSQL validates Qdrant hits before evidence is used. See
[remote data](remote-data.md) for constructors, CAS and resource ownership.

The host owns these remote connections and closes them after worker shutdown.
Native History context remains default; custom Harness and remote
Session/Fact memory are not advertised as supported by Temporal. Source document
updates cause fixed-reference validation to refuse a new model call; they do not
rewrite historic results. Semantic retrieval quality depends on the embedding,
corpus and actual model evaluation.

## Installed starter

```shell
relf --format text init my-distributed-agent --template temporal
cd my-distributed-agent
# Set RALF_TEMPORAL_ADDRESS to your actual Service in both terminals.
python -m agent_app worker
# Another terminal:
python -m agent_app run --kind dag --input "database timeout" --command-id first
python -m agent_app run --kind team --input hello --command-id first-team
python -m agent_app run --kind agent --ask-approval --command-id first-review
```

The packaged application needs no repository checkout or local execution DB. Its
Provider and per-worker lexical guide are offline fixtures. The default tool is
read-only; it demonstrates durable approval without requiring PostgreSQL effects.
Edit `agent_app/runtime.py` to register your model, tools and shared knowledge.
Use status output's actual leaf Run for approve/reconcile. Execution quality is
measured separately in [business evaluation](business-evaluation.md).

Dev21 registers pure custom ContextBuilders through an additive release and a
separate History snapshot; default native context remains compatible. See
[custom context](temporal-custom-context.md).
