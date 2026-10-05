# Implementation status — 0.1.0.dev1

2026-10-05. This is the first M1 increment, not the completed enterprise architecture or a production-ready v0.1 release. Public interfaces are experimental.

| Capability | Delivered in this increment | Boundary / next work |
| --- | --- | --- |
| Native Agent | Model/tool loop, fixed AgentSpec, decision limit, output Schema | One-shot model calls; provider does not run tools |
| Workflow | Sequential AgentSpec steps with verified result handoff | Branches/parallel/dynamic planning/child Runs pending |
| Local execution | SQLite journal, asyncio, one POSIX coordinator, OS lock | No Windows coordinator, multi-process pool or distributed scheduler |
| Commands | Scoped idempotent submit/approve/reject/cancel/reconcile | Local record/apply share transaction; send_input/auth, pending outbox receipts and deadlines pending |
| Recovery | Adopted response reuse, stable Action IDs, effect intent/result, unknown-write reconciliation | Model response before adoption and independent receipt-before-result need further separation; recovery does not guarantee external exactly-once effects |
| Effects | Four declared categories; exact-key reconciler; same tool/args unresolved writes block resubmission | Reconciler returns confirmed result or unknown; richer not-executed/in-progress proof pending |
| Approvals | Persistent pending object, operation digest and explicit local-owner decision | Expiration, resource-level authorization and enterprise actors pending |
| Budget | Atomic integer execution-credit reservations, per-Attempt settlement, unknown holds | Monetary budgets, shared child-run accounts and hard provider limits pending |
| Memory | Independent SessionStore/LongTermMemoryStore, SQLite and memory implementations, scoped CAS/TTL facts | Full deletion/export/migration, Redis/PostgreSQL adapters and vector ports pending |
| Context | Persisted actual message snapshot/manifest, character bound, complete tool-group trimming | Token-aware accounting, large-content offload, automatic summary and source authorization catalog pending |
| Tools | Trusted Python functions, Schema, fixed manifests/code digest, optional policy/reconciler | Callable objects/partial require a named wrapper; CLI/MCP/HTTP providers, activation lifecycle, sandbox and resource leases pending |
| Models | Chat Completions Provider, normalized tool calls/usage, redacted errors, no hidden retries | HTTP fixture tests passed; live-provider/model conformance and quality runs pending |
| Events | Durable per-Run sequence, stable composite event ID, pagination | Retention/cursor-expiry snapshot, streaming API and OTel pending |
| Evaluation | Offline runtime regression report and process-crash tests | Live AI task quality, compression fact retention and statistical baseline pending |
| Temporal | Not delivered | Minimal internal contract probe is remaining M1 work; full backend follows enterprise stage |
| External Runner | Not delivered | Codex isolated profile in v0.2; other adapters subject to individual conformance |
| Enterprise | Not delivered | OIDC, API/console, multi-workspace resource ACL, MQ/A2A, KB/production Oncall and restore exercise remain roadmap |

## Immediate next increments

1. Separate full model-response persistence from decision adoption and effect receipts from result commits; broaden crash-window tests. Add versioned storage ports and reliable command outcomes.
2. Complete pending input/deadline/approval expiry, explicit unknown model retry policy and stronger resource lifecycle handling.
3. Validate real model task completion/tool choice/stopping and context retention against a fixed scenario set; retain the offline regression suite separately.
4. Run the minimum Temporal contract probe using the same approval/cancel/unknown-effect cases. Do not advertise Temporal support before actual tests pass.
5. Add the first external Runner, replacement backend, CLI/MCP isolation and parallel/multi-process execution under the agreed v0.2 scope.

## Interpretation of guarantees

Scope is provided by the trusted host, not authenticated by an enterprise identity service. Python handlers can access the host environment and must be trusted. Provider/tool version and explicit configuration identity belong to the integrator; changing hidden handler dependencies without updating the manifest is outside this preview's compatibility guarantee.

Unknown business effects remain recorded even if cancellation/other failure ends the Run. A different Run ID is not a safe recovery mechanism. The unresolved-write guard compares tool name and normalized JSON arguments within the owner scope; resource aliases or equivalent arguments require future business identity normalization and can already be constrained by host policy.

File-backed coordinator locking currently supports Linux/macOS. The context limit counts JSON characters, not model Tokens. The budget limits synthetic execution credits, not actual currency. The demo is deterministic scripted execution, not an AI intelligence benchmark.

## Review disposition

The implementation review found three important issues: cancelling a crashed Run could hide an unresolved effect, scheduled work could overwrite cancellation, and empty/refused/incomplete HTTP responses could be accepted as success. Regression tests first reproduced these failures; the recovery, scheduling and provider fixes now pass. Host policy/memory callbacks are also checked before dispatch and final result commitment.

The minor callable-object registration limitation remains tracked: ordinary named functions are the supported registration form for this increment. Monetary budgets, enterprise authorization, sandbox isolation, Temporal and live-model quality still require their own implementation and validation; the local review does not certify them.
