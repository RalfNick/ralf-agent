# Distributed composition and execution governance — dev17

2026-10-07, Python 3.12.7. Implemented the user's continuing request for distributed
DAG/Team/RAG and flexible defaults. This remains the M1 core preview; full M1,
enterprise acceptance, live model quality and competitor parity are not declared.

- TemporalParentState is pure state; independent ParentWorkflow stores plan revisions,
  stable child intents, observations, commands and cap escrow in History. Registered
  control/selection/context Activities have explicit completion boundaries; no local
  execution store is wrapped inside Temporal. Actual ChildWorkflows own native actions.
- Explicit orchestration_release pins strategy/planner/verifier identities and method
  digests. Defaults can be replaced; managed model planning uses a tool-free child.
  Agent-node Graph/Team/flat-Dynamic/DAG/nesting are supported within finite limits.
  Direct Tool/Transform Graph nodes and shared Sessions remain refused.
- Context retrieval has a separate Activity/evidence snapshot before model dispatch,
  with fixed source revalidation. Actual PostgreSQL/Qdrant tests validate shared data,
  Scope isolation, source versions, worker restart and History replay without a second
  model call. Hash embeddings/offline Providers are regression baselines.
- TemporalExecutionPolicy registers per-Run child/concurrency/depth/tool limits,
  deadlines and fixed approval expiry. It does not supply OIDC/enterprise actors,
  global quotas, cost guarantees, History cleanup or deployment failover certification.
- The installed temporal starter has its own remote worker/client CLI, no local
  execution DB, and explicit Service configuration. Business evaluation has eight
  distinct outcomes, actual effect records, ordering/approval checks and DB reopen;
  default not_run and offline model_quality=null avoid inferred live scores.

## Independent review and corrections

One fresh read-only reviewer found one P1 and two P2 issues. Six reproductions
failed before the fixes and pass as permanent regressions:

1. Dynamic proposals/patches could introduce remote Schema references into Workflow
   validation. Every node/graph output Schema is now checked before adoption.
2. Contradictory quiescent observations could release held/unknown child credits.
   Validation now precedes mutation; settlement requires no pending/held evidence.
3. The business oracle could approve a fix before diagnostic evidence. Approval and
   scoring now require the proposing model to have consumed the diagnostic receipt;
   later inspection cannot make an earlier unsafe proposal pass.

An additional RED→GREEN regression keeps DAG successors blocked until successful
children are actually quiescent. Review scope exclusions (enterprise/live models,
independent service evidence, downtime timer arrival order) remain explicit. Root
ran the actual service/replay tests; no second review or paid call was performed.

## Verified evidence

- Full source suite with actual task-owned Redis/PostgreSQL/Qdrant/Temporal:
  **1462 passed in 349.78s**, warnings treated as errors.
- Outside-checkout installed wheel contracts with actual services:
  **244 passed in 83.51s**. Import-origin checks cover every loaded SDK module.
- Installed base contracts with redis/psycopg/temporalio/uvicorn blocked:
  **188 passed, 5 expected skips in 5.80s**. All198 exports import without optional SDKs.
- Actual dev16→dev17 native/static-graph/flat-team/plan/DAG/nested Run/receipt/child
  approval compatibility; original13 packaged template dictionaries unchanged.
- Actual dev16 wheel created native Temporal Run and command-registry Histories;
  dev17 replayed both and continued original submit/control authority.
- Installed temporal starter: DAG/Team/RAG, repeated submit, Agent approval after
  worker restart, repeated approval and resume passed. No local execution DB.
- All77 SDK modules byte-identical across source/wheel/sdist/installed; unchanged
  httpx/jsonschema base dependencies and six optional extras. New guides/CLI packaged.
- Ruff lint/format, dependency/Git whitespace, CI YAML parse and current local links
  checked. Standard wheel/sdist built locally; no remote commit/publication implied.

## Decisions and remaining boundaries

A reconciled business effect does not prove a lost remote handler has stopped.
Parent escrow therefore remains unknown/held until actual quiescence is proven.
This conservatively prevents successor execution/capacity release; a permanently
lost handler still needs a future remote-stop administration contract. A separate
actual child-completion test confirms ordinary cancelled capacity is recovered.

The reviewer set aside broader enterprise quality/failover claims; they remain
outside delivery. Actual timer expiry and deadlines were tested, but every timer
arrival-order race across worker downtime is not certified. The succeeded but
nonquiescent successor issue was treated as a reliability finding and fixed.

No minor findings were deferred. Real model Provider/model/budget configuration
was requested but not supplied; live quality remains not_run. See
[distributed composition](../../docs/temporal-composition.md) and
[business evaluation](../../docs/business-evaluation.md) for adoption and limits.
