# H1b Local Composite Agent Bindings Implementation Plan

> Execute inline using executing-plans, TDD and verification-before-completion. The user authorized continued implementation of the existing binding architecture. Keep all changes/evidence local; no commit, push, publication, cleanup or model calls.

**Goal:** Extend the six delivered binding roles to Local Graph, Team, Dynamic and nested members, preserving original releases and one execution authority.
**Spec:** architecture/specs/agent-capability-binding-contract.md; architecture/viewpoints/harness-runtime.md.
**Architecture:** Stable declaration paths resolve immutable leaf bindings; graph node views and managed child definitions carry those selections explicitly. Composite manifests include scheduler/strategy/planner and nested releases alongside effective Agent identities.
**Tech Stack:** Existing Python/SQLite/async ports; no new dependencies.

## Global Constraints

- This is H1b Local composite binding support, not full H1/H2. Session backend refs/selectors, Temporal bindings, new environment roles and Facade/Turn semantics remain unsupported.
- Preserve native unbound and H1a Agent/sequence encodings/manifests and command replay. New composites use local-bindings-2; legacy control and close behavior remains.
- Use graph/nodes/ID, team/members/NAME, dynamic/members/NAME and recursive nested paths. Dynamic node IDs select fixed members; planner Agents remain host-pinned and cannot be selected by a new path.
- No ambient current-agent state, no alternate scheduler/state store. Graph tools/transforms retain host governance; tool sets only narrow original AgentSpec grants.
- Parent acceptance pins all registered members, even unselected members. Child submit and parent ancestry revalidate original bindings. Completed responses must persist before drift rejection.
- Stateless managed children omit the generated explicit Session request while retaining durable parent/call identity. Caller-specified Session on native/sequence/graph with a disabled leaf remains refused.
- Continue in the existing dirty feature checkout; a new worktree would omit authorized uncommitted increments. Preserve all existing files. Store evidence under this plan's own workspace.

## Review Focus

- Parallel graph node projections must use the correct resolver and manifest index, with no provider/context/knowledge cross-talk.
- Direct Tool/Transform nodes and custom compiler/scheduler/strategy/planner identities remain pinned and authorized. A compiler must not change Agent identities under fixed binding paths.
- Nested child wrappers must preserve path selection, Session isolation, parent scope, budgets, cancellation and original-release recovery.
- Registry removal/default changes return original submit receipts, while new dispatch cannot fall back or lose received evidence.
- Legacy dev25 wheel runs and H1a release bytes remain compatible; Temporal rejects new bindings before network I/O.

### Task 1: Stable composite declaration paths

**Files:** Add binding_paths.py; extend binding_definitions.py; tests/test_composite_bindings.py.
**Interfaces:** Enumerate encoded native leaf paths and project a bound parent's named member into AgentDefinition/BoundDefinition without changing original specs.

- [x] Write declaration/codec tests for graph/team/dynamic/nested leaves and rejection of non-Agent/unknown/ambiguous paths.
- [x] Run declaration tests; Expected: FAIL at current sequential-only validation.
- [x] Implement pure bounded traversal/projection; Expected: declaration tests PASS, original H1a tests unchanged.

### Task 2: Bound serial/parallel Graph runtime

**Files:** binding_runtime.py, binding_manifests.py, workflow_runtime.py, node_execution.py, engine.py; integration tests.
**Interfaces:** Composite manifest local-bindings-2 with durable node_paths and fixed leaf manifests; optional recorded plan; per-node context and resolver views; default root manifest for non-Agent graph nodes.

- [x] Write serial/parallel provider/context/tool isolation, invalid compiler mapping, direct Tool/Transform approval, drift/evidence and explicit Session tests.
- [x] Run graph tests; Expected: FAIL at missing composite manifest/routing.
- [x] Implement routing and release checks; Expected: targeted graph/parallel/H1a tests PASS.

### Task 3: Bound Team/Dynamic/nested children

**Files:** orchestration.py, binding_runtime.py, binding_paths.py; integration tests.
**Interfaces:** Optional member manifests preserve orchestration identities; child definitions carry projected bindings; generated child Sessions respect stateless selections.

- [x] Write teams, flat/dynamic DAG, nested graph/sequence/team, replay, approval restart, cancellation/budget and planner tests.
- [x] Run orchestration tests; Expected: FAIL at unbound parent manifest/child selection.
- [x] Implement fixed parent/child propagation; Expected: targeted orchestration/DAG/nested suites PASS.

### Task 4: Installed compatibility, documentation and final review

**Files:** docs/agent-bindings.md, implementation-status/progress/remaining-work, architecture binding/review records, README, CHANGELOG, pyproject.toml; installed tests.
**Interfaces:** Existing schema v2 factory registry and load_spec accept supported wrappers; backend capability matrix reports actual Local support and Temporal refusal.

- [x] Verify JSON/TOML config, CLI effect inspection, installed wheel, real dev25 wheel pending approval/H1a recovery and new-release refusal.
- [x] Run full pytest, Ruff/format/whitespace, wheel/sdist build; Expected: no failures, actual skips recorded.
- [x] One fresh-context final review; reproduce/fix important findings and record deferred scope. Update support claims only to delivered H1b.
