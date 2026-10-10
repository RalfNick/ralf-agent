# Temporal automatic memory and per-Agent bindings

User intent: implement the next H3 capabilities with recovery evidence, update capability documents and commit locally, never push. Continue inline under existing authorization without extra design approval handoffs.

## Authority and compatibility

Temporal History exclusively owns Run decisions, auxiliary phases, credit reservations, dispatch grants and receipts. Activities propose/observe; never construct LocalEngine/ExecutionStore. Existing temporal-1/2 manifests and histories keep their semantics. New memory/binding releases explicitly use temporal-3; old workers refuse them.

## Binding boundary

Reuse AgentDefinition, BoundDefinition, AgentBindingDescriptor and scoped borrowed BindingCatalog. Support versioned provider, context, knowledge, tool_set and stage_policy choices at each declared actual Agent path, including sequence, graph, Team, dynamic DAG and nested members. Parent child requests project only their declared binding subtree. Inherit/disabled follow required-role rules. Reject unsupported roles/resource selectors before acceptance; no custom Harness, shared Session/Facts recall or runtime catalog hot switch. Default memory is opt-in stage_policy. Pure planners do not implicitly acquire memory; explicit planner Agents retain host defaults.

Bind the full registered release, implementation and actual in-process objects/methods before and after awaited I/O. Scope, original caller request, path, target namespace/backend and provider identity stay fixed. All components borrowed; stop Workers before closing them. Distributed workers require shared durable memory; in-memory is only a deterministic test fixture.

## Memory stages

After an actual Agent final decision is validated, History records immutable result/input/source identity before advancing the next step or completing the Run. Reuse grounded ManagedMemoryPolicy/ManagedModelMemoryPolicy: models choose allowlisted keys, never invent persisted values. Pure preparation/adoption can retry; selector and CAS each maximum_attempts=1. Each selector/CAS reserves one execution credit independently. Optional preparation/selection/admission failures do not fail an otherwise completed business result, but unknown costs/remote execution retain evidence and parent allowance.

Persist selector response before pure adoption. Fact identity uses original Run/node/key; CAS writes expected_version=0. Temporal requires exact fact inspection v1; bounded recall-only targets explicitly unsupported. Read before dispatch and verify afterwards; once dispatched, no retry/write on recovery. History guards business/selector/CAS dispatch against cancellation. Cancellation accepts late evidence but never schedules a new selector or write. Explicit drive may read-verify unresolved terminal facts; observation APIs remain pure. Fact evidence never proves that a timed-out remote handler has stopped.

## Acceptance

Deterministic tests cover native/sequence, all advanced binding projection, target/provider drift, invalid responses, unknown costs, budget exhaustion, cancellation and terminal recovery. Actual Temporal Service acceptance kills/restarts Worker after selector response before adoption and after CAS dispatch, verifies no duplicate selector/CAS, replays actual parent/child Histories. wheel installation, old protocol identity/regression and full suite gates required. No real model credentials/network calls. Semantic quality, belief revision/retraction/forgetting, shared sessions and lifecycle governance remain separate deliverables.
