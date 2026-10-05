# Implementation status — 0.1.0.dev3

2026-10-05. This is the M1 core preview after the architecture/implementation review, not the completed enterprise architecture or a production-ready v0.1 release. Public interfaces are experimental; the fixed kernel identity is now local-3.

| Capability | Delivered in this increment | Boundary / next work |
| --- | --- | --- |
| Native Agent | Model/tool loop, fixed AgentSpec, decision limit, common final-output validation and nullable output Schema | One-shot model calls; provider does not run tools |
| Workflow | Sequential AgentSpec steps with verified result handoff | Branches/parallel/dynamic planning/child Runs pending |
| Local execution | ExecutionStore v1, CoordinatorLease, SQLite reference authority, asyncio, one POSIX coordinator with fixed path/inode checks and hard-link rejection | Store/lease ports require atomicity and ownership conformance; no multi-process pool or distributed scheduler |
| Commands | Scoped idempotent submit/approve/reject/cancel/reconcile; caller request identity separate from first resolved Release | Local record/apply share transaction; legacy submit digest migration pending; send_input/auth, pending outbox receipts and deadlines pending |
| Recovery | Adopted response reuse, stable Action IDs, effect intent/result, unknown-write reconciliation | Model response before adoption and independent receipt-before-result need further separation; recovery does not guarantee external exactly-once effects |
| Effects | Four declared categories; exact-key reconciler; same tool/args unresolved writes block resubmission | Reconciler returns confirmed result or unknown; richer not-executed/in-progress proof pending |
| Approvals | Persistent pending object, operation digest and explicit local-owner decision | Expiration, resource-level authorization and enterprise actors pending |
| Budget | Atomic integer execution-credit reservations, per-Attempt settlement, unknown holds | Monetary budgets, shared child-run accounts and hard provider limits pending |
| Memory | Independent sync/async Session and long-term ports, explicit thread bridge, SQLite/in-memory, scoped CAS/TTL facts with finite expiry validation and post-append Release checks | Full namespace/session reads; budgeted recall/pagination, deletion/export/migration, Redis/PostgreSQL/vector adapters pending |
| Context | Pinned replaceable ContextBuilder, persisted actual snapshot, character bound, complete tool-group trimming, optional memory selection | Token-aware accounting, large-content offload, automatic summary and source authorization catalog pending |
| Tools | Trusted functions/callable instances/bound methods/partial, detached descriptors, Schema, fixed manifest/code digest, fail-closed synchronous policy/reconciler | Captured state belongs in explicit version/config; CLI/MCP/HTTP providers, lifecycle, sandbox and resource leases pending |
| Models | Async Provider preflight, dynamic request identity, normalized calls/usage, redacted errors, one-shot built-in HTTP requests | Integrators own injected clients and retries; live-provider/model conformance and quality runs pending |
| Events | Durable per-Run sequence, stable composite event ID, pagination | Retention/cursor-expiry snapshot, streaming API and OTel pending |
| Evaluation | Offline runtime regression report and process-crash tests | Live AI task quality, compression fact retention and statistical baseline pending |
| Temporal | Not delivered | Minimal internal contract probe is remaining M1 work; full backend follows enterprise stage |
| External Runner | Not delivered | Codex isolated profile in v0.2; other adapters subject to individual conformance |
| CLI | Custom trusted factory for resume/approve/cancel, version/page size, read-only SQLite status/events | Observation uses default Scope and SQLite; general read API/enterprise identity pending |
| Enterprise | Not delivered | OIDC, API/console, multi-workspace resource ACL, MQ/A2A, KB/production Oncall and restore exercise remain roadmap |

## Immediate next increments

1. Separate pure Harness proposals and controlled ToolExecutor calls from Run advancement. Persist full model responses before DecisionCommit and independent effect receipts before ResultCommit; validate both windows with real process crashes. Storage v1 is now explicit; migrations and complete command outcomes remain.
2. Complete pending input/deadline/approval expiry, explicit unknown model retry policy and stronger resource lifecycle handling.
3. Validate real model task completion/tool choice/stopping and context retention against a fixed scenario set; retain the offline regression suite separately.
4. Add backend-filtered paginated Recall, transactional Session/unknown-effect indexes and capacity limits separate from budgets. Cancelled but still active calls retain capacity until completion.
5. Run the minimum Temporal contract probe using the same approval/cancel/unknown-effect cases, backed by independent Workflow/History authority. Do not advertise Temporal support before actual tests pass.
6. Add the first external Runner, replacement backend, CLI/MCP isolation and parallel/multi-process execution after those contract gates, under the agreed v0.2 scope.

## Interpretation of guarantees

Scope is provided by the trusted host, not authenticated by an enterprise identity service. Python handlers can access the host environment and must be trusted. Provider/tool version and explicit configuration identity belong to the integrator; changing hidden handler dependencies without updating the manifest is outside this preview's compatibility guarantee.

Unknown business effects remain recorded even if cancellation/other failure ends the Run. A different Run ID is not a safe recovery mechanism. The unresolved-write guard compares tool name and normalized JSON arguments within the owner scope; resource aliases or equivalent arguments require future business identity normalization and can already be constrained by host policy.

File-backed coordinator locking currently supports Linux/macOS. The context limit counts JSON characters, not model Tokens. The budget limits synthetic execution credits, not actual currency. The demo is deterministic scripted execution, not an AI intelligence benchmark.

## Review disposition

The initial review fixed crash/cancel effect loss, scheduled cancellation overrides and empty/refused/incomplete model response success. The second review verified the complete implementation and extension paths, fixed late result/cancellation races, pinned historical settlements, mutable configuration and backend identity, and introduced storage/lease/context/async memory ports. Custom SDK profiles are now resumable through the CLI factory. See the [review report](../architecture/reviews/2026-10-05-runtime-extensibility.md) and [extension guide](extending.md) for evidence, ownership, capability limits and the remaining architectural work.

The third review reproduced seven gaps left by the 141-test baseline: unsafe database aliases, ignored async authorization, configuration-dependent submit identity, empty custom-provider decisions, post-append backend changes, retained completed tasks/locks, and invalid expiry values. dev3 closes those boundaries and adds regressions, including encoded empty text and generator authorization. See the [reliability disposition and gates](../architecture/reviews/2026-10-05-reliability-boundaries.md). The extracted final-output validator is a first pure boundary, not a completed Harness or ToolExecutor implementation.

Callable registration limitations from the initial review are resolved. Monetary budgets, enterprise authorization, sandbox isolation, Temporal and live-model quality still require their own implementation and validation; local review does not certify them. dev1/dev2 Runs remain observable/cancellable/reconcilable by Run ID, but continuation and historical submit replay require their original version and configuration. dev3 request digests exclude the resolved Manifest; old submit digests have not been migrated. Automatic Run/command migration is not supported.
