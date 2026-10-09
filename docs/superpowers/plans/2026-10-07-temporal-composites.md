# dev17 Temporal composites implementation plan

> Native inline executing-plans + TDD; one fresh final review. Existing implementation authorization persists; no repeated approval/commit/publication.

Goal: distributed finite composition, durable RAG evidence and versioned execution limits with a usable default and honest quality reporting.
Architecture: pure ParentState, separate History ParentWorkflow, registered control/selection/context Activities; native authority remains independent.
Spec: [design](../specs/2026-10-07-temporal-composites-design.md).

## Global constraints

- Python3.11+, unchanged httpx/jsonschema base dependencies and6 extras.
- Existing native manifest/request/History and13starter dictionaries preserved.
- Trees≤8levels/256components; credit escrow settled only after actual child quiescence.
- Actor Scope/child identity/release fixed; no local Engine inside Temporal or automatic write retries.
- Default limits: max_children256/max_concurrency32/max_depth8; deadlinesNone.
- Model quality requires explicit config; no guessed paid calls.

## Review focus

- Cancellation or child failed after external dispatch retains unknown evidence/cap, no successor writes.
- Two repeated registry/start calls or parent worker kill recover original children exactly.
- Malformed custom selection/observer/RAG evidence and implementation drift fail before dispatch/adoption.
- Patch/deadline/approval expiry cannot reset finished or dispatched node state or extend prior expiry.
- Old native History/default manifest compatible; missing optional services produce explicit refusal.

### Task1: Pure parent authority and versioned execution policy

Files: temporal_parent_state.py/governance.py; test_temporal_composites.py.
Produces: TemporalParentState(run_id,scope,command_id,request,manifest,epoch=None); next_calls/accept_selection/observe/command/snapshot/diagnostics; TemporalExecutionPolicy.identity. Uses existing compiler/typed Planner/Team DTOs.
- [x] RED finite DAGbindings, custom selection refusal, child intent IDs, escrow/quiescence, cancelled late observation, nested depths, patchCAS. Expected missing parent state.
- [x] Implement deterministic state and policy without I/O. Validate proposals via existing DAG/graph decoder; stable child identity rooted in parent and revision.
- [x] GREEN pure state cases and legacyTemporal tests. Expected all selected tests pass.

### Task2: Distributed workflow, managed selection, RAG and timers

Files: temporal_parent_workflow.py/temporal_control_activities.py; modify temporal.py/temporal_activities.py/temporal_workflow.py/temporal_state.py; new tests temporal_context/governance/service_composites.
Consumes Task1 state/limits; produces runtime.orchestration_release, extended facade submit/patch, registered child control/selection/context Activities and independentParentWorkflow.
- [x] RED extended facade refusesgraph/team, planning typed contracts, context snapshot beforemodel/stale reference refusal and timers. Expected missing extended release/activities.
- [x] Implement fixed component registry and explicit extended release; StartChild intent→registry→ChildWorkflow, read observations adoptedHistory; no local store.
- [x] GREEN actual twoWorker DAG/Team/planning/nesting, approval/unknown/cancel, worker kill/patch/replay, PG/Qdrant context/snapshot, deadline/approval timer. Expected original IDs/effects/budgets retained.

### Task3: Installed default and business quality

Files: temporal_starter.py/business_evaluation.py/business_evaluation_cli.py; tests/test_temporal_starter.py/test_business_evaluation.py; docs/CI/dev17 metadata.
Consumes extended release/facade/limits/context; provides standalone default app and explicit business evaluation command.
- [x] RED starter unavailable/installed factory independence and distinct semantic case scorer. Expected missing template/evaluator.
- [x] Implement explicit offline default, model/key-env configuration, private evidence and bounded calls. Default reportsnot_run; offline modelqualitynull.
- [x] GREEN installed app againstactualService, repeat/restart/childapproval/RAG; offline qualityregression; actual model run only if user config arrives. Expected correct truthfullabels and no hidden costs.

### Final gates

- [x] One independent reviewer; Important findings RED→GREEN and complete suite.
- [x] Full actualservices suite, outsidewheel contracts, actualdev16 compatibility/Histories/13templates, SDKsource/wheel/sdist/installedbyteequality, baseoptionalimports.
- [x] Ruff/format/docs/Git/pip checks, honest capabilitymatrix and quality evidence; stoptemporaryservices.
