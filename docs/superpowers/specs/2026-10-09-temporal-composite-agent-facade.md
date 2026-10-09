# Temporal composite Agent facade — H2c2

Continue the approved Harness architecture after dev33. Deliver stateless Graph,
Team, Dynamic DAG and nested definitions through the existing Agent API when an
orchestration release is registered. History remains the sole execution authority;
no new Workflow, command schema, scheduling loop or Local behavior is introduced.

## Behavior

- Runtime capabilities report the currently configured native/orchestration subset.
  Unsupported binding wrappers and Session/queue/deadline combinations still refuse.
- Submit, async reference/attach, status/events/diagnostics, observation-only wait,
  explicit resume/cancel and detach use original parent or native History. Changing
  default providers/queue after acceptance never changes the original receipt/ref.
- Parent pending discovery reads authoritative child intents and fresh child
  diagnostics, recursively, using one pinned client dispatch view. Ignore aggregated
  parent pending items: actual native children own approvals and unknown tools.
  Return each control with its actual owner's RunRef; attach that ref to approve or
  reconcile. Root cancellation uses the server's existing propagation contract.
- Validate child identity against the parent's persisted scope, command, request
  and manifest; reject cycles, excessive traversal and mismatched evidence. Do not
  query intents not yet marked started. A started but unavailable child is an error,
  not an empty successful discovery. Discovery is bounded and is not an atomic
  tree snapshot; callers must handle races through existing command receipts.
- Existing pending item keys remain compatible. No automatic parent drive after a
  child control: Workers already observe children. No synthetic success/receipts.
- Synchronous binding selectors, shared Sessions, direct Tool/Transform graph nodes
  and new public DAG patch helpers remain outside this increment. Raw patch_plan
  remains available. Claims concern execution contracts, not model planning quality.

## Acceptance

Real pure Temporal parent/native authorities below a network-only fixture prove
graph/team/dynamic/nested execution and exact child control receipts; actual local
persisted Service/Workers prove approval/reconnect/cancel and History replay.
Cancellation and slow observation remain client-only; no alternate dispatcher or
unbounded traversal. Installed wheel tests and full existing suite remain green.
Capture actual dev33 wheel before changes; no new dependencies/public exports,
Local schema changes, paid model calls, automatic commits or remote publication.

Actual Worker verification additionally found sandbox class duplication in linear
planning and same-revision child cancellation bookkeeping conflicts. Import typed
planning values at the passed-through parent-state boundary. Use a compatible
Temporal patch marker for v2 resource-evidence comparison; marker-less History
retains v1 semantics. Do not infer automatic repair of legacy affected Runs or
certify old Workers on new v2 histories.
