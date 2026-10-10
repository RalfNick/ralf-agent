# Implementation status — 0.1.0.dev59

dev54 adds opt-in [TextTokenizer, token chunks and output reserve](tokenization.md),
dependency-free UTF-8 byte units and optional owned tiktoken vocabulary. Budgeted/managed
factories support explicit byte counters/reserves; custom model tokenizers use SDK injection.
Original character defaults and receipt replay remain. Canonical text tokens exclude vendor
framing/tool schemas and do not prove billing, long-context quality or complete H3.
[Final dev54 evidence](../architecture/reviews/2026-10-10-tokenization.md):
3296 passed/92 configured-service skips,127 installed contracts,192 identical modules,
core-only optional refusal and actual cl100k_base Unicode checks.

dev55 adds opt-in [FileArtifactStore](file-artifacts.md), core-only POSIX JSON payloads
with a bounded SQLite receipt index and explicit JSON/TOML factories. Scope, TTL,
read limits, original references and managed offload protocols remain. Process-loss
publication/replay and composite Local recovery are tested; final evidence is
recorded in [dev55 acceptance](../architecture/reviews/2026-10-11-file-artifacts.md).
Final3343 passed/98 configured-service skips,117 installed contracts and193 identical modules.
Separately, installed file6 and original SQLite6 actual Temporal Worker/History contracts pass
on the verified official CLI1.9.1/Server1.32.0 with SDK1.34.0, including restart and cancellation.
This is same-host resource recovery, not distributed filesystem consistency.
Retention/GC, global disk quota, S3 and distributed filesystem consistency remain open.

dev56 adds explicit [complete-corpus Facts indexing](fact-indexing.md): bounded
memory/SQLite/Redis enumeration, fixed source snapshots, replaceable CAS metadata,
accepted embedding receipts, idempotent vector writes and complete activation.
Default SQLite/Hash assembly remains offline; HTTP embedding and Qdrant are explicit.
Recall hydrates original facts and checks publication/version/value/TTL. Writes require
explicit rebuild. Temporal Facts bindings, repair/GC and actual
semantic quality remain separate gates. Final3397 passed/98 configured skips,74 installed contracts,197 identical modules,
core-only offline indexing and dev55↔56 original receipt compatibility are recorded in
[dev56 acceptance](../architecture/reviews/2026-10-11-fact-indexing.md).

dev57 adds native PostgreSQL fact_snapshot/scan_facts, persistent scoped dataset epochs,
existing writer locks and named server cursors with capped key/value byte projections.
Explicit initialize adds the epoch table while preserving old session/fact interfaces.
Actual isolated PostgreSQL16.15 verifies complete-corpus indexing, reconnect, async
assembly, Agent references, owned close and four process-loss windows. See
[PostgreSQL acceptance](../architecture/reviews/2026-10-11-postgres-fact-indexing.md).
Final3436 passed/68 service-dependent skips,73 installed contracts,198 identical modules,
core-only default indexing, original receipt/starter compatibility and actual dev56↔57
PostgreSQL schema/data/generation upgrade pass. Remote Qdrant composition and Temporal
Facts bindings still require separate evidence.

dev58 adds opt-in [Temporal Facts bindings and bounded recall](temporal-facts.md),
scoped namespace selection, fixed source/client/method identity and replaceable pure
recall planner. Original Context Activities and History accept independent Knowledge,
Facts and recall evidence; managed finalize preserves the original classification.
Default-off releases remain unchanged. Temporal Knowledge selectors, shared Sessions,
other roles and semantic quality remain open; [dev58 acceptance](../architecture/reviews/2026-10-11-temporal-facts.md)
records each verification gate separately. Final3417 passed/119 configured-service skips;
source Temporal12 + original16, installed Temporal12 + contracts94 and200 identical modules pass.

dev59 adds [Temporal scoped Knowledge bindings](temporal-knowledge-bindings.md): host namespace
allowlists, actual selected namespace releases, native composition/method/database/client
pins and pure original-source validation. Global/raw releases remain compatible; scoped
bindings opt into knowledge_protocol=1 in temporal-3. Facts and Knowledge evidence remain
separate; the last source await precedes History dispatch admission. Shared Sessions,
other roles, automatic Temporal Profile assembly and semantic quality remain open.
Final3436 passed/131 configured skips; source Temporal12 + existing28, installed Temporal12,
installed contracts63, core-only and actual dev58↔59 default/raw release compatibility pass.
202 Python modules are identical across source/wheel/sdist/install. Actual PostgreSQL16.15
Activity/source probes pass; no live model quality or cross-machine deployment claim.
Evidence is recorded in [dev59 acceptance](../architecture/reviews/2026-10-11-temporal-knowledge.md).

Target architecture update: [AgentHarness](../architecture/viewpoints/harness-runtime.md)
defines broad Harness/Core roles, per-Agent bindings, Agent/Session facade, managed
context/memory/RAG stages and H1–H5 delivery gates. The [binding contract](../architecture/specs/agent-capability-binding-contract.md)
has delivered [H1a and Local H1b subsets](agent-bindings.md): native Agent/sequence,
Graph, Team, Dynamic and nested members share six scoped selectable roles, stable
declaration paths, fixed parent/child releases and JSON/TOML v2 assembly.
[H1a verification/review](../architecture/reviews/2026-10-08-agent-capability-bindings.md)
records 1902 passing tests, 42 service-dependent skips and installed old/new compatibility.
dev26 [Local H1b verification](../architecture/reviews/2026-10-08-composite-agent-bindings.md)
records 1959 passed/42 configured-service skips and 117 installed contracts;
actual dev25 upgrades retain native/H1a releases and old wheels refuse new composites.
dev27 delivers [Local Session H1c](session-bindings.md): selected sync/async backends,
host-authorized namespaces and durable actual-address admission.
[H1c verification/review](../architecture/reviews/2026-10-08-session-capability-bindings.md)
records 1998 passed/43 service-dependent skips, 155 installed binding contracts,
actual Redis1/PGskip1 and dev26-to-dev27 approval recovery with original releases.
dev28 delivers [Local scoped data H1d](data-bindings.md): Facts/Knowledge host namespace
views, source provenance, actual delegated-client guards and bounded continuation.
[H1d review](../architecture/reviews/2026-10-08-scoped-data-bindings.md) records
2055 passed/44 service skips, 211 installed contracts, actual Redis1/PGskip1 and
dev27 upgrade of nine original approvals. [Fixed DeepSeek trial](live-model-quality-dev28.md)
records business10/16 (repair0/6) and scoped extraction4/4; valid final JSON did
not prove actual repair completion. dev29 adds opt-in pure [Agent completion verification](completion-verification.md), durable receipt correspondence and bounded feedback. Managed async/model verification, PlanVerifier business defaults and broad quality remain open.
[H1e verification/review](../architecture/reviews/2026-10-08-completion-verification.md) records final2113 passed/44 configured-service skips, 250 installed contracts and ten dev28 original approvals recovered. [Fixed single-run DeepSeek trial](live-model-quality-dev29.md) passes eight synthetic business tasks with 17 calls; this does not establish broad task quality or framework parity.
dev30 adds [Local numeric limits H1f](agent-limits.md): pure replaceable policy, mandatory host intersection, pinned per-Agent decision/context/tool-Action caps and atomic over-limit batch refusal. No distributed capacity or currency ceiling is implied.
dev31 delivers [H2a Local stateless Agent API](agent-api.md): immutable AgentHarness,
Runtime-owned Local drive tasks, Agent/AgentRun/RunRef, observation-only wait,
nested control ownership/waking and retryable drain/cancel closing. Full H1/H2
are not complete; remote Sessions, Temporal bindings and automatic
managed stages remain partial. SDK is dev57. The [Facade/Session target contract](../architecture/specs/agent-facade-session-contract.md)
now specifies observation-only waiting, durable busy refusal, Session binding revisions,
and ownership-aware closing. H2a implements the declared Local stateless subset;
remaining shared routing and backend requirements are not changes to legacy
Local/Temporal drive semantics.
[H2a verification/review](../architecture/reviews/2026-10-09-local-agent-facade.md) records final2235 passed/44 configured-service skips, 176 installed contracts, ten actual old/new wheel approval scenarios in both directions, and two reproduced host/lifecycle findings fixed in one TDD pass. No paid-model or full Harness quality claim follows.

dev32 adds [H2b1 colocated Local Sessions](session-api.md): durable native/sequence Turn admission, canonical routes, original binding revisions, stable busy/mismatch receipts and idle CAS rebind. Required result-save/actual-handler/unknown-effect gates retain occupancy. First valid Session atomically activates schema2; older SDKs refuse it. Complete H2b, remote/composite Sessions and Temporal facade remain pending. [H2b1 verification/review](../architecture/reviews/2026-10-09-local-session-turns.md) records final2280 passed/44 configured-service skips, 159 installed contracts, nine schema1 old/new wheel approval scenarios in each direction and actual schema2 refusal/recovery. Three independently reproduced boundary findings were fixed in one TDD pass.

dev33 adds [H2c1 Temporal native/sequence Agent entry](temporal-agent-api.md): shared Agent/AgentRun API and portable RunRef/WaitResult, async reference/attachment, operation-pinned Client/namespace/Scope/release, managed outbound RPC ownership and detach-only client closing. Own observation timers return the last validated snapshot with actual observed_at; query errors propagate. Existing History/commands and Local schema1/schema2 are unchanged. [H2c1 verification/review](../architecture/reviews/2026-10-09-temporal-agent-facade.md) records final2317 passed/47 configured-service skips, 206 installed contracts, actual persisted Service/Worker/History three source and three installed probes, and eleven old/new Local approval cases in each direction. Advanced compositions/bindings/shared Sessions and full H2 remain pending.

dev34 adds H2c2 [registered composite Agent entry](temporal-agent-api.md): Graph/Team/Dynamic/nested definitions, original parent references, bounded pinned discovery of actual child controls and parent outcome_unknown observations. Terminal native approval projection omits unusable controls while preserving action/receipt ledgers. Temporal bindings/shared Sessions and full H2 remain pending. [H2c2 verification/review](../architecture/reviews/2026-10-09-temporal-composite-agent-facade.md) records final2352 passed/56 skipped,231 installed contracts,12 source+12 installed actual-Service probes and actual dev33 original History/Local schema1/schema2 recovery. A compatible v2 patch marker fixes new-parent bookkeeping comparison; legacy histories retain v1.

dev35 adds H2b2 [colocated composite Sessions](session-api.md): Graph/parallel, Team, Dynamic linear-plan/DAG and nested Turns, original member bindings, atomic final conversation/success and bounded descendant occupancy. Successful open/rebind enables monotonic schema3; dev34 readers refuse it before execution. Remote/shared Temporal Sessions, composite root namespaces and full H2 remain pending. [H2b2 evidence](../architecture/reviews/2026-10-09-local-composite-session-turns.md) records actual old/new wheel recovery and final gates.

dev36 adds H2b3 [authorized composite root namespaces](session-api.md): separate borrowed host resource, allowlisted per-open selection, independent original Run admission evidence and canonical parent/member IDs. Configured roots opt into schema4; actual dev35 refuses4. SDK/factory assembly is delivered; Profile declaration, remote Sessions and complete H2 remain pending. [H2b3 review/evidence](../architecture/reviews/2026-10-09-composite-conversation-namespaces.md) records final gates.

dev37 adds root conversation declarations through JSON/TOML Profile components and sync/async Runtime assembly, plus the installed `sessions` starter with original Profile/Turn reconnection and pure status. Previous20 starter trees and absent-component Profile identities remain compatible. [dev37 evidence](../architecture/reviews/2026-10-09-configured-conversation-entry.md) records final2457/56 source,212 installed contracts and44 bidirectional wheel cases. Remote Sessions, Temporal bindings and full H2 remain pending.

The [current remaining-work checklist](remaining-work.md) maps each layer to delivered
subsets, missing capabilities and outstanding acceptance, with H1–H5 priorities.

2026-10-11. Current baseline: dev59, based on committed dev58 / 3a2408b. This is the M1 core preview. Full M1 acceptance, enterprise architecture and a production-ready v0.1 release have not been completed. Public interfaces remain experimental. Static Graph Workflow, managed Tool/MCP nodes, bounded parallel execution and explicit async component lifecycle are available. dev14 adds real Redis/PostgreSQL/Qdrant data adapters, bounded plan/execute/verify/replan and local child-Run teams. dev15 adds dynamic DAG/plan patches, nested local workflows, MQ/A2A handoff and an independently History-owned Temporal subset. dev16 adds native async A2A controls, shared PostgreSQL Inbox/Outbox and a packaged local HTTP service with tracked shutdown. dev17 adds History-owned distributed Graph/Team/Dynamic/nesting, fixed RAG snapshots with shared PG/Qdrant ports, per-Run execution policy/timers and an installed Temporal starter; business evaluation remains not_run without model configuration. dev18 adds replaceable UTF-8 parsing/chunking and atomic memory/SQLite/PostgreSQL ingestion receipts plus a user-document starter. dev19 adds explicit float HTTP embeddings, replaceable RRF/rerank and authority-validated parallel Hybrid retrieval with additive assembly and an offline user-document starter. dev20 adds opt-in pure context measurement/complete-group selection/excerpts, actual Harness-request measurement and scoped memory/SQLite artifacts with a seventeenth offline starter. dev21 adds opt-in sourced memory consolidation, managed model summaries, pure custom Temporal context and a bounded real DeepSeek trial. dev22 adds stateless native Responses/JSON/SSE, typed Python tools and an offline-first compatibility suite. dev47 adds explicit semantic/recall/Plan/Team combinations through existing authorities; see [H3 guide](h3-intelligent-combinations.md). Default native local-4/request/Manifest identities and original flat parents remain compatible; new nested/DAG definitions require dev15. Evidence is recorded in [implementation progress](implementation-progress.md).

| Capability | Delivered in this increment | Boundary / next work |
| --- | --- | --- |
| Native Agent | Model/tool loop, fixed AgentSpec, decision limit, common final-output validation and nullable output Schema | One complete response per Action, optionally collected via SSE; provider does not run tools |
| Per-Agent bindings | Local native/sequence/Graph/Team/Dynamic/nested ten selectable roles (provider/decision_policy/context/session/facts/knowledge/tool_set/verifier/limits/stage_policy), fixed paths/releases and Profile v2; Temporal temporal-3 six roles (provider/context/knowledge/tool_set/stage_policy/facts), including host Facts/Knowledge namespace selectors | Local scoped Session/Facts/Knowledge resources and remote Session routes delivered; artifacts/workspace/sandbox/skills roles, Temporal remaining roles/selectors/shared Sessions and full H1/H2 remain pending |
| H3 starting combinations | Seven version-1 Profiles; new explicit semantic-knowledge, memory-recall, Plan/Team plus recommended_harness on original Specs/AgentHarness; replaceable pure ReferenceSelector, saved source-bound selection | Semantic profile needs explicit HTTP Embedding/async assembly/indexing; overlap ranks bounded candidates only; default instruction-only members and Schema/CompleteVerifier do not prove task quality. Old three presets retain identity |
| Execution components | Public pure synchronous Harness with NativeHarness default; async ToolExecutor with PythonToolExecutor default; pinned identities and detached/immutable dispatch values | Engine retains governance and authority; arbitrary user Python remains trusted; no sandbox/external Runner implementation |
| Runtime assembly | Immutable versioned profiles/catalog, explicit factory registry, strict JSON/TOML, default local builder; original-profile routing, receipt replay before current configuration | Explicit SDK abuild/register_async/owned async cleanup with loop affinity; synchronous ProfiledEngine/CLI do not route async factories. One local instance at a time; original declarations/code/data must remain available; no plugin auto-discovery, hot watcher, code archive or migration |
| Workflow | Legacy sequence and static serial/bounded parallel Agent/Transform/Tool graph; nested sequence/graph/team/dynamic members via managed child Runs | General loops, streaming dataflow and arbitrary async nodes pending; static graph nodes retain existing types |
| Dynamic planning | Flat PlanProposal compatibility plus DAGProposal/DAGNode, default rule/model DAG planners, dependencies/bindings/conditions, durable revisions and CAS pending-node patches; capabilities/limits in PlanningRequest | Finite batch execution; async/model Verifier, interactive needs_input continuation and broader repeated live quality baseline pending |
| Multi-Agent | Sequential/Router/Supervisor, recursive managed definition trees, pinned ancestor releases, isolated Sessions and recursive child-cap settlement; failure/cancel propagation and joined diagnostics | Local defaults plus opt-in Temporal child Workflows; remote communication uses explicit ToolSource/handoff; global capacity and enterprise identities pending |
| Local execution | ExecutionStore v1, CoordinatorLease, SQLite reference authority, asyncio, one POSIX coordinator with fixed path/inode checks, hard-link rejection and real worker-thread ownership | Store/lease ports require atomicity and ownership conformance; no multi-process pool or distributed scheduler |
| Shared Agent entry | Local H2a/H2b1/H2b2 plus Temporal H2c1 native/sequence and H2c2 registered advanced compositions; common Agent/AgentRun/RunRef/WaitResult and async attachment; independently managed Local drives or remote RPCs | Temporal temporal-3 facade accepts six registered binding roles including Facts; shared Sessions, other roles, direct Tool/Transform graph nodes and non-detach close refused; full H2 and semantic H3 quality pending |
| Message handoff | Structural MessageBus, Inbox/AsyncInbox, Outbox/AsyncOutbox, CommandAdapter; in-memory/SQLite defaults, real Redis Streams dedup/claim/ack; shared PostgreSQL Inbox/Outbox, durable completion before ack | Capacity rejection preserves pending/dedup evidence; retention/compaction, additional broker adapters and failover certification pending |
| A2A | Explicit ASGI native or async-authority service, TaskControlBridge, local owned lifecycle/starter, trusted host authentication, Card and JSON-RPC0.3 polling subset; replaceable A2AClientPort and approval/queryable-write ToolSource | Text/data only; no SSE/push/gRPC/files/Task continuation; receipt extension required for message lookup; Temporal composition supports native async controls; definition validation follows the selected execution backend/release |
| Distributed execution | TemporalEngine async facade, independent Workflow/History command/action/credit authority, registered workers, EffectJournal port and PostgreSQL evidence default; actual two-worker kills/replay | Native Agent/sequence default; explicit orchestration_release adds Agent-node Graph/Team/Dynamic/nesting and registered RAG. temporal-3 adds scoped catalog provider/context/knowledge/tool_set/stage_policy/facts, bounded Facts namespace recall and History-managed automatic grounded memory; direct Tool/Transform graph nodes, shared Sessions/custom Harness and other role selection refused; retention/Continue-As-New/global quotas/deployment versions pending |
| Commands | Scoped idempotent submit/approve/reject/cancel/reconcile and local and Temporal DAG patch; original request separate from first resolved release; durable Inbox/Outbox transport receipts | Local commands are sync, Temporal controls async; legacy digest migration, send_input/auth and local deadlines pending |
| Agent completion | Mandatory Schema acceptance; opt-in pure CompletionVerifier, configurable committed tool receipt/result/argument rules, detached typed task input and durable accept/reject/bounded retry feedback; Local per-Agent bindings and Profile factories | External Schema references never retrieve; async/model stages and plan-level business oracle remain pending; receipt correspondence does not establish arbitrary external truth |
| Recovery | Independent model response and executor observation receiving stages before DecisionCommit/ResultCommit; adopted decision reuse, stable Actions, unknown-write reconciliation; 10 receiver-window/cancellation regressions pass | Grouped M1 fault report remains; manual reconcile is one command/result transaction; no external exactly-once guarantee |
| Effects | Four declared categories; exact-key reconciler; same tool/args unresolved writes block resubmission | Reconciler returns confirmed result or unknown; richer not-executed/in-progress proof pending |
| Approvals | Persistent pending object, operation digest and explicit local-owner decision | Temporal History-based approval expiry delivered; local expiration, resource-level authorization and enterprise actors pending |
| Budget | Atomic integer execution credits, unknown holds and recursive parent child-cap escrow settled after terminal/quiescent descendant completion | Currency ceilings, global shared accounts and provider billing guarantees pending |
| Memory | Independent sync/async Session/facts ports; SQLite/in-memory and real Redis/PostgreSQL CAS/dedup/logical TTL; paged recall, Session high-water and current-fact validation; opt-in rule/model field selection with source-grounded append-only admission and replay | Semantic revision/retraction and atomic multi-fact admission pending. Legacy/full Session reads and some writes may materialize history; no export/migration/retention, Redis Cluster/failover or full server-version matrix |
| Knowledge / RAG | Scoped in-memory/SQLite/PostgreSQL document authority, CAS/TTL/deletion versions, replaceable text/Markdown parser, opt-in bounded HTML/DOCX body and optional text-PDF parsers and character/paragraph Chunker; atomic document/chunk/term/receipt ingestion, Chinese/English lexical retrieval and provenance validation | knowledge_committed receipt excludes vector readiness; explicit reindex; no advanced connectors, enterprise source ACL/catalog, background indexing or live answer-quality baseline; explicit HTTP Embedding protocol/hybrid/rerank delivered, online semantic compatibility still unverified |
| Vector retrieval | EmbeddingProvider/VectorIndex/VectorRetriever ports; local exact cosine and real Qdrant HTTP adapter; authoritative version/digest hydration; offline HashEmbeddingProvider | Hash embedding is a deterministic token baseline; no hosted semantic embedding default, pgvector, default semantic reranker or cross-service atomic index commit; embedding costs outside execution credits |
| Context | Local native/composite and Temporal managed summaries/reference excerpts/tool offloads with independent receiving/acceptance; replaceable ContextBuilder/MessageCounter/ContextBudgeter/ContextSummarizer, persisted actual snapshot/measurement, exact chars and explicit token estimate, complete tool groups and optional deterministic excerpts; pure RecallPlanner records actual queries; explicit managed model summaries with frozen consumers and registered Temporal custom context | Opt-in TextTokenizer/tiktoken and canonical output reserve delivered; actual model vocabularies, vendor framing, semantic-preservation quality and enterprise source authorization catalog pending |
| Artifacts | ArtifactReference and sync/async ports; explicit memory/SQLite and opt-in POSIX file JSON storage with Scope, digest, UTF-8/read limits, immutable TTL and atomic namespace capacity; application-selected tool reference/preview contract | Managed automatic tool offload delivered; no automatic GC, remote artifact default, global disk quota, enterprise IAM or cross-Run transaction |
| Tools | Trusted functions/callable instances/bound methods/partial, detached descriptors, Schema, fixed manifest/code digest, strict None-return synchronous authorization, executor-owned receipt queries | Captured state belongs in explicit version/config; Async ToolSource/explicit host policy/atomic selected registration; default MCP stdio with tracked worker/process lifetime; typed keyword-function registration with Schema inference, host context injection and pre-authorization default resolution. HTTP/OAuth/persistent MCP, CLI/sandbox and resource leases pending |
| Models | Chat Completions text/functions, DeepSeek disabled-thinking preset, native Anthropic text/client tools, Gemini text and stateless Responses text/functions/JSON; generation parameters, optional pure preflight, complete SSE normalization and scoped capability refusal | Text only; Gemini functions/opaque reasoning, full Responses continuation, SDKs and routing pending. Borrowed clients remain application-owned; abuild factories may explicitly own async clients; local fixtures do not establish live model/account compatibility or task quality |
| Events | Durable per-Run sequence, stable event ID, pagination; opt-in scoped sync/async pull subscriptions, cursor reconnect, SSE encoding and read-only CLI | Retention/compaction, HTTP/WebSocket live transport, model-token authority and OTel pending |
| Evaluation | Offline runtime fixtures, frozen20-case proposal evaluation and eight-case business-task executor; tool ordering/parameters/approval/stop/restart checks and error/usage/latency/private reports | Offline model_quality is null; dev21 small real trial records failures and follow-up scores; no full repeated final-config task/answer/citation baseline or equal-framework superiority result |
| Temporal probe | Independent Agent/sequence and explicit Graph/Team/Dynamic/nesting backends; RAG snapshots, scoped Updates, History replay and actual two-worker failure probes | Full M1 grouped fault/live quality/external onboarding gates remain; unsupported node types, shared Sessions and deployment/remote-stop governance remain |
| External Runner | Not delivered | Codex isolated profile in v0.2; other adapters subject to individual conformance |
| CLI / first use | Twenty-one packaged starters including dag/nested/a2a/temporal/ingest/hybrid/context/memory/model-check/observable; child control hints and remote worker/client CLI; separate planning/business evaluation consoles | Model templates require explicit config; CLI/ProfiledEngine remain synchronous local authorities; local HTTP service owns shutdown; shared remote gateway lifetime remains host-owned |
| Enterprise | Limited protocol/adapter trials only | OIDC, resource ACL, production service/console, retention/migration, failover and operational restore acceptance remain roadmap |

## Immediate next increments

The [dev23 holistic review](../architecture/reviews/2026-10-08-agent-framework-alignment.md)
identified three concrete defects. dev24 fixes duplicate Temporal call IDs,
completed-response evidence loss and all-or-nothing default Session recall.
[Shared acceptance and recall](shared-model-context-contracts.md) documents the
common pure rules and recorded legacy History compatibility. dev25 delivers the
native Agent/sequence six-role H1a binding subset; dev26 extends it to Local
Graph/Team/Dynamic/nested members. dev27 delivers Local Session backends/namespace/address admission. dev28 delivers scoped Facts/Knowledge namespaces and provenance. Temporal delivers six binding roles with Facts/Knowledge namespace selectors; other resource selectors,
remaining Agent/Session APIs, advanced Temporal facade and recommended managed
memory/RAG combinations remain next work; these increments do not complete
AgentScope parity. The [remaining-work audit](remaining-work.md) separates these
gaps from components already delivered.

The [M1 acceptance protocol](m1-acceptance.md) defines real-model tasks, a LangGraph comparison, external developer onboarding and independent Temporal authority. Task fixtures are a specification, not a benchmark. The [getting started](getting-started.md), [recall/RAG](recall-and-rag.md), [execution components](execution-components.md), [recovery](recovery-guide.md), [API](api-reference.md) and [release](releasing.md) guides cover the preview.

The [runtime assembly guide](runtime-assembly.md) documents profile compatibility, explicit factories and public ports. The [static Workflow guide](static-workflows.md) covers graphs; [orchestration](orchestration.md) covers delivered local teams/planning; [remote data](remote-data.md) covers real Redis/PG/Qdrant adapters. The [model guide](model-adapters.md) separates protocols from online evidence. Temporal registered RAG and execution limits are covered by [distributed composition](temporal-composition.md). Global/tenant capacity, streaming dataflow/live event transport, model routing/multimodal, persistent/HTTP MCP and broader distributed orchestration remain separate deliverables.

The [async handoff guide](async-handoff.md) covers native async A2A, shared PostgreSQL receipts and the default local service.

The [general framework capability plan](../architecture/viewpoints/framework-capabilities.md) records the full target. G1 static graphs and parts of G2 Tool/MCP/parallel are delivered. dev14 delivers G3's bounded local planning/team kernel and G4's first real remote adapters; real-model G3 acceptance and G4's full parsing/embedding/context/memory pipeline remain. dev15 delivers G3 DAG/nesting and the first independently History-owned Agent/sequence execution subset; G5 streams/Runners and broader G6 enterprise services follow separately. SDK increments do not close remaining M1 gates by themselves.

1. Extend the verified dev6 component/receiver regressions into grouped M1 fault reports. Both local receiver windows now have real process/cancellation evidence; migrations and complete command outcomes remain.
2. Complete pending input/local deadline/local approval expiry, explicit unknown model retry policy and stronger resource lifecycle handling.
3. Validate real model task completion/tool choice/stopping and context retention against a fixed scenario set; retain the offline regression suite separately.
4. Extend the delivered Recall/Session indexes to efficient final append, indexed Run/unknown-effect queries and capacity limits separate from budgets. Cancelled but still active calls must retain capacity until completion.
5. Extend the delivered independently History-owned Temporal subset using the same approval/cancel/unknown-effect contracts; retain explicit refusal of unsupported orchestration and require actual service tests for each new capability.
6. Deliver the general SDK increments against the existing approval/budget/recovery contracts, with starters and adapter conformance per capability. Add the first external Runner and broaden the delivered Temporal subset through their own authority/resource gates; keep M1 acceptance and feature support distinct.

## Interpretation of guarantees

Scope is provided by the trusted host, not authenticated by an enterprise identity service. Python handlers can access the host environment and must be trusted. Provider/tool version and explicit configuration identity belong to the integrator; changing hidden handler dependencies without updating the manifest is outside this preview's compatibility guarantee.

Unknown business effects remain recorded even if cancellation/other failure ends the Run. A different Run ID is not a safe recovery mechanism. The unresolved-write guard compares tool name and normalized JSON arguments within the owner scope; resource aliases or equivalent arguments require future business identity normalization and can already be constrained by host policy.

File-backed coordinator locking currently supports Linux/macOS. The original context limit counts JSON characters; an opt-in counter adds a message budget, whose UTF-8 token estimate is not exact model usage. The budget limits synthetic execution credits, not actual currency. The demo is deterministic scripted execution, not an AI intelligence benchmark.

## Review disposition

The initial review fixed crash/cancel effect loss, scheduled cancellation overrides and empty/refused/incomplete model response success. The second review verified the complete implementation and extension paths, fixed late result/cancellation races, pinned historical settlements, mutable configuration and backend identity, and introduced storage/lease/context/async memory ports. Custom SDK profiles are now resumable through the CLI factory. See the [review report](../architecture/reviews/2026-10-05-runtime-extensibility.md) and [extension guide](extending.md) for evidence, ownership, capability limits and the remaining architectural work.

The third review reproduced seven gaps left by the 141-test baseline: unsafe database aliases, ignored async authorization, configuration-dependent submit identity, empty custom-provider decisions, post-append backend changes, retained completed tasks/locks, and invalid expiry values. dev3 closes those boundaries and adds regressions, including encoded empty text and generator authorization. See the [reliability disposition and gates](../architecture/reviews/2026-10-05-reliability-boundaries.md). The extracted final-output validator is a first pure boundary, not a completed Harness or ToolExecutor implementation.

The fourth review reproduced context-manager policy bypasses, cancelled Tasks hiding running executor threads, and Store close failures releasing ownership too early. dev4 enforces the sole None-return authorization contract, tracks actual framework-managed tool/reconciler/memory threads independently of Tasks, and keeps failed-close Engines quiesced under their lease. See the [authorization/shutdown disposition](../architecture/reviews/2026-10-05-authorization-shutdown.md). This lifecycle work does not implement capacity limits, sandbox termination, separate receipt persistence or Temporal authority.

dev6 adds public Harness/ToolExecutor boundaries and separates durable receiving from adoption. A saved response is proposed/adopted without repeating the Provider call; a saved tool observation is committed without repeating the handler/query. Received evidence may settle after cancellation, while proposals/follow-up scheduling and terminal reopening remain forbidden. Model credits settle on receiving the complete response, tool credits on ResultCommit; missing usage remains unknown. Manual owner reconcile uses its existing atomic command/result transaction. The 10 real-process/cancellation receiver tests pass; see [execution components](execution-components.md). This closes these local implementation windows without completing grouped M1 reporting, live-model, Temporal or external-adoption gates.

Independent dev6 review additionally fixed actual Provider source changes hidden by registry replacement, pre-call refusals incorrectly becoming unknown effects, and rejected retries obscuring earlier unknown attempts. Undispatched attempts release only their own reservations; historical unknown effects remain blocked/reconcilable and settlement targets the real dispatched attempt. The [review disposition](../architecture/reviews/2026-10-06-execution-components.md) records evidence and compatibility.

dev7 adds bounded Recall and local RAG. Independent review found and fixed facts changing while knowledge awaits and sources expiring during later asynchronous validation. New/unknown model dispatch reuses the original references and snapshot, validates current facts/knowledge, and preserves historical unknown reservations if refused. Already-received responses are adopted without new source reads or Provider calls. Validation is conservative over all retrieved candidates, and multiple authorities do not provide a cross-backend atomic snapshot.

dev8 adds public structural ports and versioned assembly. Independent review fixed invalid-return cleanup, retained close retry, control receipt replay during another profile's execution and optional diagnostics. Default SQLite reads enforce the original command Scope/payload before returning receipts; changing defaults or losing an old profile does not prevent replay. Installed-wheel history and resource ownership evidence are recorded in the [review](../architecture/reviews/2026-10-06-runtime-assembly.md).

dev9 adds implemented model protocols and complete SSE collection. Independent review fixed empty JSON deltas, error-frame handling, malformed response normalization and lossy native/opaque history. Shared preflight and response capabilities cannot authorize tools; the existing Engine adoption/effect protocol remains authoritative. Default identity/installed dev8 compatibility, fixture coverage and unavailable online evidence are recorded in the [model review](../architecture/reviews/2026-10-06-model-adapters.md).

Monetary budgets, enterprise authorization, sandbox isolation, full Temporal feature parity and live-model quality still require implementation and validation. dev8 retains default dev6/dev7 local-4 compatibility, adding identities only for explicitly enabled Recall/Knowledge/planner/profile. Catalog routing resolves retained original declarations and adapters; it does not migrate Runs. dev3–dev5 local-3 continuation requires the original runtime. SQLite Schema v1 and dev3 caller request digests remain unchanged; old receipts do not grant new-kernel continuation. dev1/dev2 submit replay needs the original version. Automatic Run/command migration is unsupported.

The [managed tools guide](managed-tools.md) distinguishes borrowed source/transport lifetimes, one-shot POSIX process ownership, explicit host effects, reserved idempotency fields and Tool plan v2. Existing v1 plans retain their representation; no automatic migration or general sandbox is provided.

The [parallel Workflow guide](parallel-workflows.md) documents v3 graph node isolation within one Run. Default serial identities remain unchanged. dev14 teams/plans separately use linked child Runs; both remain local execution.

The [framework parity review](../architecture/reviews/2026-10-06-framework-parity.md) records the dev12 comparison and contract repairs. Subsequent dev14 additions are recorded in the [data/orchestration review](../architecture/reviews/2026-10-07-data-orchestration.md); no cross-framework benchmark or superiority claim is established.

The [async assembly guide](async-assembly.md) documents dev13 lifecycle support and its SDK/CLI boundary; the original synchronous authority contracts and default identities remain.

The dev15 guides describe [DAG/nesting](dynamic-dag.md), [MQ/A2A](remote-handoff.md), [Temporal](temporal-execution.md) and [proposal evaluation](planning-evaluation.md). Runtime/transport evidence does not establish real model quality or full M1 acceptance.


The [dev16 handoff review](../architecture/reviews/2026-10-07-async-handoff.md) records async controls, shared PostgreSQL receipts, local service shutdown, initialization/callable drift fixes, actual services and installed compatibility evidence.

Dev17: [distributed composition](temporal-composition.md) and [business evaluation](business-evaluation.md) separate delivered execution behavior from enterprise and live-model quality acceptance. A queryable effect receipt does not prove a lost remote handler stopped; parent escrow remains held until actual quiescence is proven.

The [document ingestion guide](document-ingestion.md) describes dev18 D1: independently replaceable parsing/chunking, atomic knowledge receipts and the fifteenth installed starter. The [intelligent data pipeline design](../architecture/viewpoints/intelligent-data-pipeline.md) separates this delivery from pending D2 semantic/hybrid retrieval, D3 context/memory and D4 live quality.

Dev18 evidence: [document ingestion review](../architecture/reviews/2026-10-07-document-ingestion.md) records atomic knowledge receipts, fixed extension boundaries, actual services/process loss, compatible installed upgrades and one independent review. Semantic AI quality and remaining D2–D4 are separate gates.

Dev19 D2: [hybrid retrieval](hybrid-retrieval.md) documents explicit HTTP embeddings, rank/ID proposal ports, frozen and repeatedly source-validated candidates, structured branch lifetime, strict/degrade semantics and new factory names. Offline defaults remain; semantic/task quality and D3/D4 require their own evidence.

The [dev19 review](../architecture/reviews/2026-10-07-hybrid-retrieval.md) records the verified extension boundaries, four independent fixes, real transport/data combination and installed compatibility evidence.

Dev20 D3a: [context/artifacts](context-artifacts.md) and [review](../architecture/reviews/2026-10-07-context-artifacts.md) record pure context defaults, explicit large-result storage and compatible installed recovery. Automatic fact extraction, managed model summaries, semantic quality and enterprise/Temporal context acceptance remain pending.

Dev21: [managed memory](managed-memory.md), [Temporal context](temporal-custom-context.md) and [real trial](live-model-quality.md). Rule/model selectors, append-only sourced observations, durable managed summaries, pure frozen consumers and native JSON-object mode are available. Defaults retain original identities; automatic in-Run compression, semantic revision/retraction and full final-config model acceptance remain pending. Final evidence appears in [review](../architecture/reviews/2026-10-08-managed-memory.md).

Dev22 begins [ordered alignment](agentscope-alignment.md): [typed tools/native Responses](sdk-model-tools.md), native formatting/semantic SSE and bounded managed compatibility checks. The default no-provider console is not_run; offline fixtures and online protocol checks keep model_quality=null. Full AgentScope parity, sandbox/interactivity and online Responses compatibility remain pending.

Dev23 adds opt-in synchronous invocation middleware/default logging profiles and
scoped resumable committed-event observation. [Guide](middleware-and-events.md).
Default authority/releases remain; input continuation, Workspace/Sandbox and
AgentScope parity require subsequent increments.


dev38 adds H2b4a [remote native/sequence durable Turns](session-api.md#远程持久会话dev38h2b4a): existing Redis/PostgreSQL Session adapters expose bounded atomic exact-message receipts. The original Local authority journals required save intent, dispatch and receipt; lost acknowledgements pause and explicit recovery reuses adopted output without repeating business effects. Terminal recovery queries only and preserves cancelled/failed state. Stable remote SessionRef, independent admission metadata, conservative Scope/address refusal and transactional opt-in schema5 are delivered. Composite root remote data, cross-authority leases, Temporal shared Sessions, FIFO/input/deadline and full H2 remain pending. Actual-service and installed/upgrade evidence is recorded in the dev38 review; absent PostgreSQL configuration is not a delivery-quality claim.


dev39 delivers H2b4b [remote composite root conversations](session-api.md#远程复合根会话dev39h2b4b): Graph/parallel/direct-transform, Team, Dynamic Plan/DAG and nested Local Turns fix an explicit receipt-backed root resource independently of members. The original authority persists the final proposal, corresponding workflow/orchestration marker, required save and receipt; recovery completes the save directly without repeated planning, verification or child/business execution. Async Profile session-resource assembly reuses existing backend factories and owned lifecycle. Native↔composite idle rebind preserves one remote address. New capability atomically enables semantic schema6; old38 refuses it, previous schema1–5 remain supported. Cross-authority leases, Temporal binding/shared Sessions, FIFO/input/deadline, automatic Harness stages and complete H2 remain unfulfilled.


dev40 delivers the first Local H3a [managed rule-memory stage](managed-memory-stages.md) for native Agents and sequences. It is opt-in, separately host-granted, grounded and charged against Run execution credits. Original authority persists source/proposal/CAS intent/receipt evidence; unknown writes retain credits and explicit terminal recovery only inspects exact facts. Auxiliary failure does not replay business work or change terminal success. BindingCatalog supports stage_policy inherit/ref/disabled; JSON/TOML sourced-memory and sourced-memory-async reuse existing backend/client factories. Semantic7 activation is atomic with first enabled admission; dev39 readers refuse it. Default-off releases remain unchanged. Advanced/Temporal automatic stages, automatic model extraction, background jobs and semantic memory revision remain undelivered.


dev41 delivers H3b1 [managed context preparation](managed-context-stages.md) for opt-in Local native Agents/sequences. Pure per-Agent context bindings plan complete omitted same-Run groups; the original Engine owns rule/model summaries, fixed source/reference snapshots, independent intent/response/projection evidence and original-budget accounting. Invalid responses use a fixed fallback; dispatched unknown calls retain credits without retries. Terminal adoption is evidence-only, reference versions are revalidated before business disclosure, and real task/thread ownership is preserved. JSON/TOML managed-summary factories reuse host providers and pure counter/budgeter ports. Semantic8 activates on first enabled admission; old dev40 refuses8 while default identities/schemas1–7 remain compatible. Automatic Session/RAG compression, advanced/Temporal stages, model extraction and full H3 remain open; no new real-model quality claim.


dev42 adds H3a2 [automatic model-selected memory](managed-model-memory-stages.md), opt-in for Local native/sequence. Original memory_stages persist tool-free selection intent/response/keys and independent credits, before existing grounded CAS writes. Empty selection is valid; invalid/unknown selection writes nothing and never falls back to all fields. Actual provider/target/policy pinning, cancellation and evidence-only terminal settlement preserve the original authority. stage_policy and JSON/TOML sourced-memory(-async) factories reuse existing ports. Semantic9 first admission is atomic; dev41 refuses9; rule/default identities and schemas1–8 remain. Free-form/advanced/Temporal stages and full H3/quality remain open.

## dev43 H3 recommended data context

Versioned Local Basic / Local Knowledge / Managed Memory Profiles now compose the existing ports. Opt-in ManagedDataContext adds deterministic Session/knowledge/fact excerpts, existing managed history summaries, and artifact-backed large tool context projections with original-Run intent/read-back/receipt recovery. Default SQLite artifact factories are owned; SDK targets are borrowed; registry sync/async replacements are supported. Native Local Agents/sequences only, semantic Schema10; original default releases and schemas1–9 remain supported. Raw execution evidence is retained. Semantic reference summaries, remote artifact adapters/GC, advanced/Temporal automatic stages, final-config model quality and full H3 acceptance remain open. See [guide](recommended-harness.md).

## dev44 H3 composite and Temporal managed context

[Local advanced and Temporal context](composite-temporal-context.md) reuse the original pure policies, provider/artifact ports and execution authorities. Local graph/parallel/Team/dynamic/nested actual Agent decisions now support compression/offload; node frame journals and scoped summary reservations remain in the original Run. Optional semantic Schema11 rejects older readers. Temporal explicitly registers temporal-2 and separates pure plan, artifact read/write/verification, single-attempt summary response and final snapshot in History; source validation follows artifact awaits before model disclosure. Original temporal-1/default releases remain. Unknown summaries hold credits and remote uncertainty; late receipts settle after cancellation. Native/advanced real Worker kill/restart and parent/child History replay are tested. Automatic memory writes remain Local native/sequence only; Temporal per-Agent binding/shared Sessions, semantic reference quality, remote artifact defaults/GC, payload/storage governance and full H3 remain open.

Original History atomically admits managed external dispatch after preparatory reads; accepted cancellation blocks unadmitted calls. Previously granted operations retain late evidence. Unknown artifact execution remains nonquiescent after a receipt or successful later tool, holding the parent's child allowance. Knowledge adapters use the public references/validation contract; missing parallel execution frames fail against surviving original Action evidence.

## dev45 Local composite automatic memory

[Composite memory stages](composite-memory-stages.md) reuse rule/model-selected grounded policies and original CAS source/intent/receipt protocols for Local graph/parallel/Team/dynamic/nested actual Agents. Schema12 is optional and atomic; native/sequence identities and activation stay unchanged. Parallel workflow_node scopes source/fact keys, journals and budgets in original Run projections. Pure observations stay I/O-free; explicit closed-root resume recovers original terminal children under existing drive locks, never new selector/CAS dispatch, then settles parent escrow only with evidence. Versioned managed-memory defaults and per-Agent target bindings compose through existing sync/async factories. Temporal writes, semantic revision and full H3 quality remain pending.

## dev46 Temporal automatic memory and scoped Agent bindings

Explicit temporal-3 releases support versioned provider/context/knowledge/tool_set/stage_policy choices through original AgentDefinition/BoundDefinition paths, including actual native/sequence/graph/Team/dynamic/nested Agents. History owns source/selector/adoption/read/CAS/verification phases and independent credits. Exact fact inspection v1 required; no selector/CAS retry after dispatch. Explicit root drive recovers original uncertain child evidence without implicit query I/O. Found facts do not prove timed-out remote execution stopped; parent allowance remains held.

Legacy temporal-1/2 retained. Other Temporal binding roles, resource selectors, shared Sessions, semantic memory quality and full H3 remain pending. See [usage and boundaries](temporal-memory-bindings.md) and [acceptance](../architecture/reviews/2026-10-10-temporal-memory-bindings.md).

Dev47: [H3 intelligent combinations](h3-intelligent-combinations.md) add explicit semantic HTTP Hybrid, relevant bounded Facts/complete Session selection and Plan/Team starting definitions through original AgentHarness/authorities. Original version-1 presets/ManagedDataContext remain compatible. Final 2972 passed/92 optional-service skips; installed75, six dev46↔47 original approval/context/Manifest recoveries and eight process-exit windows. Independent review fixes seven reproduced failures; current capability contradictions corrected. No live quality or new remote-service certification. See [acceptance/rulings](../architecture/reviews/2026-10-10-h3-intelligent-combinations.md).

Dev48 adds [explicit HTTP reranking](http-reranking.md) through the existing AsyncReranker/Hybrid source authority, owned async factories and semantic Profile option. Old pure ranks/preset declarations remain. Preparation may repeat paid retrieval after interruption; rerank fees and live quality are not covered by execution credits.

Dev48 final: 3019 passed/92 optional-environment skips; installed103 contracts, 12 dev47↔48 default approval recoveries and two semantic identity-only recoveries with exact Profile/Context/Manifest equality. Old wheel rejects the new adapter before opening the database. Independent review's two real HTTPX transport/stream close failures reproduced RED→GREEN; no deferred minors. Wheel/sdist, Ruff/format/whitespace pass. See [acceptance and decisions](../architecture/reviews/2026-10-10-h3-http-reranking.md). No live rerank/answer-quality or renewed remote-service claim.

Dev49 adds [Query transform and semantic Facts recall](query-and-semantic-recall.md): replaceable sync/async transform, deterministic aliases, existing source validation, bounded original Facts semantic ranking, task-text planner and ordered reference selector. Explicit semantic-memory async Profile owns a separately versioned managed embedding lifetime; old seven Profiles/classes remain. Actual model-response process recovery, scoped Graph Facts and Temporal Query Knowledge replay have evidence. Semantic Facts is Local only; no corpus-wide index, live quality, fee ceiling or renewed remote-service certification.

Dev49 final: 3105 passed/92 optional-environment skips; installed86 new contracts, 12 dev48↔49 original approval recoveries and two semantic Knowledge identity-only recoveries preserve exact Profile/Context/fresh Manifest. All186 packaged Python modules match source. Three Important query-source expiry/resource/mutation findings reproduced RED→GREEN; no deferred minors. Build, static checks and local documentation links pass. See [acceptance and full decisions](../architecture/reviews/2026-10-10-query-semantic-recall.md).


Dev50 adds opt-in [model query transformation](model-query-transform.md): borrowed completed async ModelProvider, bounded strict tool-free proposals, named-provider JSON/TOML assembly and scoped Knowledge/Facts preflight. Original eight Profiles and absent-option identities remain; Local accepted Action and Temporal Knowledge snapshot recovery reuse original evidence. Preparation can repeat before acceptance; no model quality, fee ceiling or Temporal Facts claim.


Dev51 adds [pure HTML ingestion](html-ingestion.md): opt-in HtmlDocumentParser and installed ingest template, UTF-8 text extraction with bounded structure and original source/atomic receipt recovery. Text defaults remain unchanged. No browser/CSS/URL fetching; PDF/Office/connectors and full H3 remain open.

Dev52 adds [pure DOCX body ingestion](docx-ingestion.md): canonical UTF-8 WordprocessingML paragraphs/table text, bounded ZIP/XML validation and installed ingest template. Existing text/HTML pipelines and committed receipts remain compatible. Word layout, inherited styles, images, headers/notes and other Office/PDF formats remain outside this adapter; full H3/M1 is open.

Dev53 adds [optional text PDF ingestion](pdf-ingestion.md): lazy pypdf 6.20+ below 7, strict unencrypted page-order text, scoped library limits and installed ingest template. No core dependency or original Text/HTML/DOCX default changes. OCR/layout/real PDF compatibility corpus, global host isolation and full H3/M1 remain open.
