# Bounded parallel Workflow — dev12

Date: 2026-10-06. User authorizes continued implementation toward the general framework/AgentScope goal. This increment delivers G2 local graph fan-out/join with bounded concurrency; it does not implement ChildRun/delegation or distributed scheduling.

## Choice and contracts

Use isolated node execution frames inside the same authoritative Run. Each frame reuses the existing LocalEngine model/tool/adoption loop through an internal store view. The view merges only its node progress/actions into the latest parent transaction; budgets, commands, events, scope, stable effects and Coordinator remain owned by the parent. Independent child Runs would prematurely introduce G3 budget/delegation semantics; asyncio.gather over the current singleton node would overwrite state.

`GraphWorkflowSpec(..., max_concurrency=1)` preserves all existing caller/plan identities when 1. Explicit integer 2..32 uses static plan v3 and serializes max_concurrency. Serial Tool plans stay v2; other serial plans stay v1. Unknown fields/version combinations are rejected. Parallel nodes may be Agent, Tool or pure Transform; dependencies/conditions/input/result bindings remain explicit.

`WorkflowBatch(selections=(), skipped=(), done=False, result=None)` is a detached finite proposal. `WorkflowScheduler.identity` plus pure `select(plan, input, states, limit) -> WorkflowBatch` can be injected as `LocalEngine(..., workflow_scheduler=...)`. Default `StaticWorkflowScheduler` returns declaration-order eligible nodes up to the positive limit. Common boundary validates every selected node, binding, skip, completion, duplicates and count. Active/blocked nodes are not eligible and their dependents wait. Runtime profiles can explicitly register a scheduler factory; no scheduler identity enters legacy manifests.

## Execution and lifetime

Each node has a saved bound input, single-node plan and manifest, isolated messages/decisions, and stable node Session ID `<parent-session>:node:<node-id>`. Results merge only through declared bindings. Agent memory facts retain the named Agent scope. Parent Session messages are not an implicit cross-branch channel. Accepted session_ids reserve the root and all derived names through ExecutionStore.session_owner. Frame output/action state is persisted in the parent JSON; no new execution database Schema or independent Run record.

A frame store shares the actual authority transaction and budget, maps local action node positions to the parent plan index, and merges against latest parent data. Commands for approval/reconciliation route to that frame; cancellation applies to the entire Run. A successful node's result is immutable; later branches cannot overwrite it. Independent model/tool receipts can be adopted after cancellation without new proposals or successor scheduling.

Parent owns the supervisor and every worker Task independently, plus the existing actual thread tracker. Caller cancellation shields real work and marks the Run cancelling. Event-loop-wide cancellation cannot permit a close/recovery while worker Tasks or real synchronous/MCP calls are alive. Internal frames use the fixed native serial compiler/interpreter; the parent scheduler selects branches. Control delivery during a sibling await may leave a frame resumable for the next drive, rather than retrying it twice in one drive. Default worker concurrency is per Run; no process-wide/tenant capacity guarantee. Pure transforms remain synchronous computations.

On failure, stop scheduling new nodes, retain completed results and wait for started work/evidence before drive returns. Failure wins over late success. Approval/unknown-effect pauses are per branch: independent eligible work may finish, then parent exposes waiting_reconciliation before waiting_approval. A restart retries each blocked/running node at most once per drive and preserves existing effect policy. Shared integer credits are atomically reserved; parallelism cannot multiply the allowance.

## Acceptance

Behavior tests prove overlapping Agent and Tool calls using barriers, never timing-speed assertions; configurable cap; dependency joins/skips; isolated Session histories; shared budget; multiple approvals/repeated control commands; unknown-write/manual reconciliation; stop-on-failure; cancellation and actual thread ownership; malicious/mutating scheduler refusal and identity pinning. Real process exits after model/tool receiver commits recover without repeating confirmed work. Installed parallel starter and actual dev11 legacy identity replay are required. Full suite, lint/build/docs and one fresh read-only review close the increment. No live model/performance/comparative superiority claim.
