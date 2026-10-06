# Static Workflow review — dev10

Date: 2026-10-06. Base `8b27888`; reviewed implementation `bb4f60b`. Independent fresh reviewer: gpt-6-astra, read-only checkout. Scope: [G1 specification](../../docs/superpowers/specs/2026-10-06-static-workflow-design.md) and [plan](../../docs/superpowers/plans/2026-10-06-static-workflow.md).

## Result

No concrete Critical, Important or Minor defect found. Reviewer assessed the change ready to merge within the serial G1 scope. This is a local code review; no merge, remote publication or enterprise acceptance occurred.

The reviewer read the complete new plan/compiler/interpreter/runtime code and native integration/adoption changes. It confirmed executing-component identity checks, independently validated interpreter selections, missing/null distinctions, Session append/recheck/commit recovery, and the intentional legacy compatibility bridge.

## Verification

- Implementer fresh project-virtualenv suite: **803 passed in 70.54s**, warnings as errors; 82 tests added over dev9.
- Reviewer fresh Workflow suites: **82 passed**, warnings as errors.
- Reviewer fresh complete suite: **803 passed in 70.29s**, warnings as errors; Git whitespace check passed and checkout remained clean.
- Reviewer independent temporary probes: compiler normalization/pinning; transform mutation cannot change original input, saved node input or plan config; optional bindings preserve null/false/zero while applying defaults only to missing values.
- Implementer real-process crash windows: node start, node completion and Session append. Each recovered workflow has one business effect, two model fixture calls and one Session message. Model/tool receiving cancellation prevents successor scheduling.
- Implementer installed actual dev9→dev10: original native receipts/Manifest unchanged, queued Chat fixture calls once then zero on repeated drive, one approved demo business effect. Four original starter dictionaries have identical SHA-256 digests.
- Installed dev10 outside checkout: both Graph branches and read-only node inspection pass; queued profile v1 resumes after default moves to v2, new task uses v2; actual installed dev9 refuses the queued Graph with typed `definition_mismatch` before dispatch, dev10 resumes it. All 106 public imports exist and pip check passes.

Installed/build evidence was supplied to the reviewer rather than independently repeated. No live provider/model quality, remote data backend, throughput comparison or AgentScope/LangGraph benchmark was executed.

## Scope decisions retained

The reviewer explicitly set aside the following; the implementer retains each decision with its consequence:

| Decision | Reason and consequence |
| --- | --- |
| Hidden I/O, threads or effects in purportedly pure callbacks | Pure callbacks are trusted host computations. Such effects must use a managed tool/executor; they cannot obtain graph recovery guarantees by claiming purity. |
| Parallel, dynamic Plan, ChildRun and dataflow | Excluded from serial G1 and remain explicit deliverables; users cannot depend on these modes yet. |
| Live-provider task quality | Offline tests prove structure/recovery only; model quality requires the independent M1 evaluation. |
| Deliberately false component identity | Host/component author must version behavior truthfully; a false identity cannot prove compatible historical execution. |
| Eliminating the legacy Agent/sequence bridge | Preserve the existing request/Manifest behavior until explicit migration; costs a temporary dual entry path. |

The reviewer suggested optionally retaining its successful probes as additional regressions. It did not identify a defect or require a fix pass. No second review was requested.

## Remaining work

G2 tooling and bounded parallel execution, managed async custom nodes, dynamic Plan/teams, full data adapters, stream checkpoints and distributed execution remain planned. Full M1 still requires grouped fault reporting, real-model quality, independent Temporal authority and external developer adoption. The [static Workflow guide](../../docs/static-workflows.md) and [implementation matrix](../../docs/implementation-status.md) describe actual support.
