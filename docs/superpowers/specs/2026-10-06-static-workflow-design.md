# G1 static Workflow implementation

Date: 2026-10-06. Implements the user-approved [G1 framework scope](../../../architecture/viewpoints/framework-capabilities.md). This is a serial local static-graph increment, not parallel execution, dynamic planning or multi-Agent support.

## Public values and components

- `ValueRef(source="input", path=(), required=True, default=None)`, `Literal(value)`, `InputMap(fields)` are explicit finite-JSON bindings. Missing required fields/results fail; optional references use the declared default. JSON null is distinct from missing. List paths accept non-negative integers; object paths accept strings. No eval or arbitrary expressions.
- `BranchCondition(value: ValueRef, equals, negate=False)` compares canonical JSON (bool and integer differ).
- `GraphNode(id, agent=None, transform=None, depends_on=(), input=ValueRef(), when=None, allow_skipped_dependencies=False, config={}, output_schema=None)` has exactly one Agent or registered pure transform. Stable IDs match `[A-Za-z][A-Za-z0-9_.-]{0,63}`, reserve `input`.
- `GraphWorkflowSpec(name, nodes, version="1", output=None, output_schema=None)` is snapshotted and validated. No output binding returns a map of completed node results. Explicit output may intentionally be null; output Schema governs it.
- `ExecutionPlan` is an immutable serialized IR snapshot with `to_dict()`, `identity`, format `ralf-static-plan`, schema version 1. Maximum 256 nodes, 32 reference path segments, 1 MiB serialized plan. Unique IDs/dependencies, acyclic graph, reference existence and dependency ancestry are validated before acceptance.
- `WorkflowCompiler.compile(spec) -> ExecutionPlan`, `WorkflowInterpreter.select(plan, input, states) -> WorkflowSelection` are pure synchronous ports with JSON identity. Defaults are `StaticWorkflowCompiler` and `StaticWorkflowInterpreter`; compiler normalizes Agent, sequence and graph. Graph execution uses the persisted plan. A compatibility bridge retains the existing default Agent/sequence record, request and Manifest contracts.
- Interpreter customization selects among eligible nodes. Engine independently checks eligibility, skip decisions, bound input, done/result semantics. Default selects the first eligible node in declaration order; false conditions and skipped required dependencies propagate. Allowing skipped dependencies is explicit, with optional refs for branch joins.
- `NodeTransform.transform(input, config)` is synchronous pure finite-JSON computation, versioned identity. Default `IdentityTransform` accepts empty config. Host registers transforms explicitly; no I/O, implicit Python import or code from declarations. Async/generator/lazy results reject; ordinary exceptions become validation failures. External-I/O/custom async nodes remain a future managed executor increment.

## Persistence and execution

Engine accepts GraphWorkflowSpec, compiles once inside first command acceptance and pins compiler/interpreter/used-transform identities plus plan digest in the graph Manifest. Caller idempotency uses the source declaration, not resolved components. Resume never recompiles. Current release checks verify the persisted plan and executing component identities before and after pure callbacks/awaits. Downlevel dev9 cannot continue Graph runs because it lacks the pinned workflow Manifest.

Graph node state and input/result snapshots live in the Run's execution authority. One current node is dispatched at a time. Native Agent nodes use existing model receiving/adoption, ToolExecutor, approval/budget/unknown-effect protocols. Completion follows durable Session append and atomic node-state commit; retry uses the same message ID. Transform result and node completion commit atomically. Skips, node starts/completions and run completion emit durable events. Fail/cancel prevent further scheduling; late evidence remains tracked without reopening completed nodes. No guarantee is offered for effects hidden in a supposedly pure transform.

Existing AgentSpec/WorkflowSpec submit identities, default local-4 Manifest, demo/oncall/rag/config/model starter dictionaries and ExecutionStore v1 remain unchanged. No SQL schema change; Run JSON carries graph plan/state. Full M1 remains unaccepted.

## Adoption and verification

`load_spec` accepts strict JSON/TOML kind=graph; RuntimeProfile can explicitly register compiler/interpreter/transform components. CLI accepts graph specs, read-only inspect shows plan/node states and streamlined summaries. `ralf init --template graph` runs from an installed wheel with offline echo, branch skipping, pure mapping and result composition; existing template files are byte-identical.

Tests must cover out-of-order dependencies; boolean/null/missing paths; skipped branches and optional joins; cycles/unknown refs/oversize; custom ordering/compiler/transform identity; mutation and lazy callbacks; Schema failures; acceptance dedup after config moves; actual approval close/restart and one business write; crash after completed node/Session append; cancellation and recorded evidence; legacy manifest/receipt and installed dev9→dev10 recovery. Full pytest with warnings as errors, Ruff lint/format, wheel/sdist, outside-checkout installed starters, documentation checks and a fresh independent code review are required. No paid model or remote service is needed for this increment.

## Execution decisions

The user instructed implementation after reviewing the framework design. Proceed inline in the existing clean feature branch; one reviewer at the end is mandated by the development skill. Keep the legacy execution bridge rather than silently changing historical execution semantics. This costs a temporary dual entry path, documented until an explicit IR migration is delivered.
