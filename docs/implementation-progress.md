# Implementation progress — 2026-10-05 M1 local runtime

Dev69（基线 ddb6dbb/dev68）：[Temporal Profile 装配](temporal-profiles.md)复用工厂与原 History，提供十类声明绑定、远程 Session UUID 初始化、实际 Worker／处理器／资源排空和安装包离线模块。完整 R04/H1/H3/H5 仍开放；[最终验收](../architecture/reviews/2026-10-11-temporal-profile-assembly.md)：源码4021 passed/320配置跳过；源码及安装包实际服务各53项通过，235模块一致，旧68兼容通过；5项review问题已修复，服务已停止，仅交付本批子集。


Plan: docs/superpowers/plans/2026-10-05-m1-local-runtime.md.

- Baseline: remote repository has no refs; local architecture committed as aa074d9.
- Ruling: develop in the newly initialized feature branch in the user workspace; there is no pre-existing code branch to protect. Preserve the architecture files and avoid moving the user's project.
- Ruling: this deliverable is v0.1.0.dev1, the first M1 increment. Temporal probe and full enterprise integrations remain tracked; local software must run without those dependencies.
- Ruling: execution credits are an enforceable attempt budget, not a currency guarantee. Unknown provider billing remains explicit.
- Pre-flight: Engine consumes the same Scope/CommandReceipt, ToolRegistry and SQLite transaction contract exercised by storage tests; CLI consumes RunHandle and the same persisted snapshots. No competing scheduler.
- Tasks 1–4: core SDK/CLI implemented. RED: missing modules and CLI, followed by behavioral failures for unresolved-write resubmission and cancellation releasing the coordinator. GREEN: `python3 -m pytest -q` → 35 passed, including real os._exit(77) after downstream commit.
- Ruling: memory/provider modules were built before the native loop because the loop consumes them. All public runtime exports were verified together in one initial implementation commit.
- Ruling: file-backed preview runs on POSIX (Linux/macOS), enforced by OS file locking. Windows coordinator support is not declared.
- Security correction: subprocess tests now receive PATH/PYTHONPATH only; host credential environment is not inherited or expanded in failure diagnostics.
- Task 5: Apache-2.0 license, README, contribution guide, support matrix, CI, source/wheel packaging, SDK sample and offline evaluation added. Evaluation is scripted runtime regression, not live-model task quality.
- Review gate: one independent read-only implementation review, architecture baseline aa074d9 to runtime commit 5b79fa2. Three Important findings, no Critical findings. RED: nine failing regression cases reproduced crash/cancel effect loss, cancellation scheduling races and invalid HTTP response success. GREEN: the fixes passed the full suite.
- Cancellation extension: policy and replacement-memory callbacks exposed additional commit-window cases (three RED failures); authoritative cancellation is checked again before dispatch and result commitment. GREEN: 52 tests passed on Python 3.12.7.
- Deferred review finding: callable instances and functools.partial need named-function wrappers; documented as a preview limitation, with direct support left for a later increment. Enterprise guarantees excluded from this review remain explicit in implementation-status.md.
- Final verification: fresh Python 3.12.7 virtual environment, editable `.[dev]` installation succeeded; 52 tests passed in 2.75s with pytest 9.1.1. Ruff 0.16.10 lint and format checks passed, and `git diff --check` passed. Isolated `python -m build` produced the wheel and source distribution; source archive includes fixtures, examples, architecture and license, with no runtime state.
- Installed-wheel verification: clean virtual environment, CLI invoked from outside the checkout; submit → approval → restart/resume succeeded with exactly one actual business write. All three offline runtime cases passed using the installed package. `pip check` reported no broken requirements. The workspace environment was then switched to the tested editable install for development.
- Scope at delivery: first M1 increment complete; remaining M1/enterprise work is listed in implementation-status.md. One review pass completed and Important findings fixed; no second review requested. No live paid model, production business service or remote publication performed.

## Architecture and extensibility review — dev2

- User requested a serious review and improvements. Three parallel reviewers examined execution consistency, extensibility and actual SDK/CLI use, followed by one bounded integration audit of the new ports and async I/O. No remote publication or live models.
- RED→GREEN: six execution regressions (queued drive, terminal late errors, single ResultCommit, fixed historic costs), nine tools/provider cases, nine CLI cases and 36 initially failing configuration cases. Changes stayed within explicit file ownership before integration.
- Root RED→GREEN: ten extension/context/storage failures; four integration failures for symlink ownership, async context changes, final memory cancellation and cached bridge identity; independent memory/bridge regressions; three invalid context/lease cleanup cases.
- Delivered: version 1 ExecutionStore, CoordinatorLease and ContextBuilder; native async memory ports, thread-safe explicit bridge and redacted memory errors; optional memory selection with accurate manifests; scoped authority query ports; readonly CLI observation; custom importable factory/example; callable tools and strict preflight validation.
- Fixed kernel identity changed to local-2 and package to 0.1.0.dev2. dev1 continuations require the original runtime; no silent migration. Review report and extension guide record the remaining enterprise, full-memory-query and separate receipt-persistence gates.
- Final verification: fresh editable dev2 installation; 141 tests passed in 5.75s on Python 3.12.7. Ruff lint/format, pip check and git diff --check passed. Standard isolated build produced wheel/sdist with setuptools 84.0.0; local Markdown links checked across 12 documents.
- Installed-wheel checks outside checkout: approval/restart retained one business effect; custom importable Agent factory completed through CLI resume/status; offline runtime evaluation passed 3/3. The example entry was corrected to import its canonical profile, keeping tool module identity consistent across SDK and CLI. Workspace environment is restored to editable dev2.

## Reliability boundary review — dev3

- User supplied seven reproductions against f806a55. Baseline verification: 141 passed in 5.72s. Parallel work covered database aliases, expiry validation and independent engine regressions; root integrated submit identity, execution lifecycle, authorization, final decisions and post-append identity checks.
- RED→GREEN: database aliases/chdir reproduced in real subprocesses; invalid expiry reproduced divergent permanent/hidden facts; nine engine boundary regressions reproduced policy/response/append gaps; four submission/lifecycle regressions reproduced alias conflicts and retained execution objects.
- Independent review added JSON-encoded empty text and generator authorization bypasses, both reproduced and fixed. A 30-round queue/cancel exercise with 12 waiters per round retained shielded ownership, one effect and complete in-memory cleanup.
- Delivered all seven fixes, 72 additional permanent cases and a pure final-output validator. Complete Harness/ToolExecutor ports, separate response/receipt persistence, backend Recall/indexes/capacity and Temporal authority remain gates in the new reliability review; no parallel backend was added.
- Version changed to 0.1.0.dev3 / local-3; ExecutionStore and SQLite Schema remain v1. Old Runs remain observable/cancellable/reconcilable by ID; continuation and historical submit replay require the original runtime. No command digest or Run migration is advertised.
- Final verification: Python 3.12.7, `pytest -q -W error` → 213 passed in 7.38s. Ruff lint/format and git diff --check passed; local links checked in 12 documents. CI Python 3.11/3.13 were not run locally.
- Standard wheel/sdist built with the installed setuptools via `python3 -m build --no-isolation`. Installed dev3 wheel used outside the checkout: approval/restart and repeated submit retained one Run and one actual business write; custom importable SDK/CLI profile succeeded; offline evaluation passed 3/3. Dependency check passed, and the editable dev3 wheel was built for restoring the development environment.

## Authorization and shutdown review — dev4

- User supplied one P1 and two P2 reproductions against f494bbc/dev3. Baseline: 213 passed in 6.25s. Parallel work reproduced strict policy return failures, close/lease failures and actual executor-thread cancellation, followed by two independent read-only integration reviews.
- RED→GREEN: 12 policy failures (context-manager wrappers and other non-None results), real self-managed event-loop cancellation with a still-running synchronous effect, close failure releasing ownership, and closed Engine operations reaching SQLite. Tests use valid approval/unknown-effect targets so malformed commands cannot mask a lifecycle failure.
- Delivered: the sole synchronous None-return authorization contract; actual framework-owned worker tracking with pending/start/finish transitions independent of Task callbacks; per-Run recovery checks; ThreadedMemoryAdapter ownership via guarded ContextVars; wait_for_threads for graceful stopping; close_failed/store_closed/closed guards and safe close/release retries.
- Root reproduced the same ownership gap in threaded session read/append after loop.close; both now retain the lease. Cancelling the thread wait also preserves ownership. Framework-independent user background work remains the adapter author's responsibility.
- Version is 0.1.0.dev4; local-3, ExecutionStore v1, SQLite Schema v1 and dev3 request digests are retained. This is a compatible safety fix for valid dev3 configurations; policies returning booleans/objects must adopt the explicit None/exception contract. No new backend or parallel execution capability was introduced.
- Final verification: Python 3.12.7, pytest -q -W error → 256 passed in 8.33s (43 added cases); Ruff lint/format and git diff --check passed; local links checked in 13 documents. CI Python 3.11/3.13 were not run locally.
- Standard no-isolation wheel/sdist build succeeded. Outside the checkout, a queued Run created by the actual installed dev3 wheel resumed successfully under installed dev4, and repeating the original submit returned the exact original handle/receipt. Dev4 approval/restart/repeated submit retained one business write; offline evaluation passed 3/3. The dev4 editable wheel was built to restore the workspace environment; dependency check passed.
- Remaining gates are unchanged: full Harness/ToolExecutor boundaries, separate model/effect receipt persistence and crash windows, backend Recall/indexes/capacity, and independent Temporal authority. See the authorization/shutdown review and extension guide for exact service stop and adapter ownership contracts.

## Adoption review — dev5

- User's dev4 adoption review distinguishes the reliable Local core preview from full M1 acceptance and a general enterprise framework. This increment addresses concrete first-use friction and specifies remaining experiments; it does not claim framework superiority, live-model quality or completed M1.
- Delivered a package-contained `ralf init` starter, an editable standalone factory and trusted offline business service. The generated application does not depend on checkout examples or repository PYTHONPATH. CLI explicit factories can load the current trusted project directory from the console entry point.
- Delivered JSON-compatible CLI commands plus optional text summaries and read-only `inspect`: reviewable tool parameters/digests, shell-quoted approve/reject/resume hints with stable command IDs, execution-credit totals and unconfirmed writes retained even after Run cancellation. Observation never imports factories or acquires a Coordinator.
- Added wheel/source installation paths, recovery/diagnostics, common API documentation, changelog, release process and security reporting. The acceptance protocol separates scripted regression from actual model quality, same-scenario comparison, fault-window/Temporal and independent external-user evidence.
- Package is 0.1.0.dev5; kernel local-3, SQLite Schema/ExecutionStore v1 and dev3 request identities are unchanged. Valid dev3/dev4 Runs remain compatible; no automatic migration, backend, sandbox or distributed execution was added.
- RED→GREEN: missing CLI inspection/text/init behavior, standalone generation and real installed-wheel use. Independent review found that initializing the shell's current empty directory replaced its inode; three path-alias regressions now require a typed rejection without changing the directory. Scope denial and repeat rejection/approval receipts remain protected.
- Final runtime verification: Python 3.12.7, `pytest -q -W error` → 274 passed in 18.48s (18 added cases); Ruff lint/format and git diff --check passed. Twenty task specifications and their JSON Schema passed static validation; 76 local links and eight Python documentation blocks passed checks. The fixture/oracle/runner remain unimplemented, results are null and no real-model scores exist.
- Installed wheel verification outside checkout: standalone starter, console factory imports without PYTHONPATH, copied inspection commands, repeated approval, restart and exact submit receipt replay retained one business write. The wheel regression also uses real os._exit(77) after business commit and recovers the original effect once. An actual dev4-wheel queued Run completed under the dev5 wheel with the exact original Run/receipt/Release. Editable dev5 was restored; pip check passed.
- Wheel and source distribution built without isolation using installed setuptools. Wheel contains starter and CLI views; source distribution contains the guides, changelog/security policy, task specifications and recovery tests. Existing offline runtime regression remains 3/3, separately labeled; CI Python 3.11/3.13, real-model/peer comparison, external developer trials and Temporal were not run locally. No remote publication was performed.

## Execution components and receiving stages — dev6

- User requested continued development after comparing RALF's general application coverage with AgentScope. This bounded increment delivers replaceable native execution components and closes two local persistence windows; it does not implement the broader RAG, provider ecosystem, multi-Agent or enterprise feature set.
- Delivered public Harness/NativeHarness, ModelRequest/DecisionProposal, ToolExecutor/PythonToolExecutor and immutable DispatchEnvelope/EffectObservation views. LocalEngine owns authorization, approvals, stable actions, reservations, dispatch intent, adoption and workflow progress. Default construction is unchanged; custom pure policies and async business executors are injectable.
- Complete model responses and executor observations now commit independently before decision/result adoption. Actual process death after receiver commit reuses saved evidence without repeating Provider/handler/query; cancellation retains facts/costs, skips new proposals and never reopens terminal Runs. CLI read-only inspection distinguishes saved evidence awaiting adoption from unknown writes.
- RED→GREEN: 24 Harness, 37 executor, eight integration, 10 process/cancellation receiver, four component-example, six evidence-inspection and 13 independent review cases; 102 added cases over dev5's 274. The component example validates approval-before-dispatch, single-effect recovery, effect-key deduplication and sequential Workflow using an external business fixture.
- Independent review found actual Provider identity changes hidden by registry replacement, pre-call failures being marked unknown, and rejected retry attempts obscuring earlier unknown effects/settling the wrong attempt. Fixes pin actual call objects, distinguish not_dispatched with zero settlement, preserve historical unknown blocking/reconciliation and settle the real dispatched attempt. A second read-only review verified adoption rollback/real thread ownership and corrected the final-output documentation to refer to DecisionProposal.
- Version is 0.1.0.dev6, kernel local-4; Harness/Executor identities are pinned. SQLite Schema/ExecutionStore stay v1 and dev3 caller request digests are unchanged. Actual installed dev5-to-dev6 verification retained the exact original submit handle/receipt, allowed observation/cancellation/manual effect confirmation, and rejected old-kernel continuation before external work. No automatic Run migration is advertised.
- Final runtime verification: Python 3.12.7, pytest -q -W error → 376 passed in 25.49s. Ruff lint/format and git diff --check passed. The 20 evaluation task specifications validate but remain specification_only, results=null and runner/fixture not_implemented; no model intelligence scores are inferred.
- Wheel/sdist built without isolation. A dedicated virtual environment outside the checkout imported the dev6 package from its own site-packages with matching source/metadata versions; installed third-party dependencies were reused without network fetching. Installed-wheel custom Harness/Executor Workflow, both receiver crash windows, old-version submit replay and cancelled unknown-effect confirmation passed; business operations remained one effect. The permanent wheel-starter fixture now force-installs its wheel even if parent editable metadata is visible.
- Guides, API, recovery, support matrix, changelog, architecture boundaries and compatibility were updated. Remaining M1 gates are grouped fault reports, live-model quality, independent Temporal probe and external developer adoption. RAG/vector/Redis adapters, MCP/sandbox, parallel/multi-process and enterprise identity remain unimplemented. CI Python 3.11/3.13 were not run locally; no remote publication was performed.
- Final documentation checks: 23 documents, 134 local links, 12 Python blocks and 18 shell blocks passed. The dev6 editable installation was restored with matching package/source versions; pip check passed.

## Bounded recall and local knowledge — dev7

- Delivered opt-in MemoryRecallPolicy, RecallQuery/Page, sync/async paging and FactReferenceValidator ports. Native in-memory/SQLite pages respect candidate and canonical output allowances, Scope, TTL, generation and Session high water; Legacy explicitly materializes full reads. Threaded paging/validation retain real worker ownership across event-loop cancellation.
- Delivered independent KnowledgeStore/KnowledgeRetriever/EmbeddingProvider/VectorIndex, in-memory/SQLite CAS/TTL authority, chunks and deletion versions. Lexical retrieval is the default Chinese/English path; injectable embedding plus local exact cosine indexes provide a real vector path. Authority hydration filters stale versions, retired sources and digest mismatches; there is no hosted embedding default or automatic reindexing.
- Model Actions save candidate knowledge/fact references with the actual request snapshot. New/unknown dispatch validates the original sources; already-received responses are adopted directly. Independent review reproduced and fixed fact changes during other awaits, final TTL races, and delegated actual-client identity changes, adding 13 behavior regressions. Additional malformed cursor and unrepresentable retrieval-limit regressions now return ValidationError. See the [review](../architecture/reviews/2026-10-06-recall-rag.md).
- Added standalone editable `ralf init --template rag` and source knowledge example, with real ingested Chinese/English runbooks, versioned original citations and explicit no-evidence results. Start-up respects updated, deleted and expired seed documents. Offline Provider behavior proves the source chain, not AI answer quality.
- Fresh full validation: **571 passed**, with `pytest -q -W error`, Python 3.12.7 on macOS. Ruff lint/format and Git whitespace checks passed. The two new process fixtures die after committed model dispatch/response events: recovery preserves the unknown snapshot/held budget or directly adopts received evidence without another retrieval/model call.
- Actual installed dev6 → dev7 verification used a dedicated virtual environment outside checkout with no repository imports or credential environment. Original submit receipt and Manifest were identical, local-4 default continuation succeeded and the business ledger contained exactly one effect. Installed dev7 wheel RAG queries, both source-deletion crash windows and explicit cosine/stale-hit filtering passed. Source/package versions matched; pip check passed. Third-party dependencies were reused locally without fetching.
- Wheel/sdist build without isolation passed; wheel contains 22 SDK modules and packaged starters, while sdist includes new tutorials, example, review and process tests. Artifacts exclude database/credential fixtures. Preview remains dev7/local-4 with ExecutionStore v1 and the dev3 request digest; optional Recall/Knowledge identities require original configuration on recovery.
- Capacity, efficient final Session append, indexed Run queries, lifecycle retention/migrations, live models, grouped M1 reports, Temporal authority and external adoption remain gates. Redis/PostgreSQL/managed vector adapters, document connectors/enterprise ACL, automatic semantic memory, MCP/sandbox, multi-Agent and parallel/distributed execution are not delivered. CI 3.11/3.13 and remote publication were not performed locally.
- The dev7 editable installation was restored with matching source/package versions and all public imports; pip check passed. Documentation checks cover 26 documents, 142 local links, 15 Python blocks and 23 shell blocks, plus valid task-case JSON. Blocks were syntax-checked; real starter/install/recovery executions are reported separately above.

## Public ports and versioned assembly — dev8

- Delivered structural ExecutionEngine and optional RuntimeDiagnostics/RunDiagnostics; CLI factories need neither LocalEngine inheritance nor .store. KnowledgeContextPort accepts direct application implementations. Pure synchronous RecallPlanner selects MemoryRecallPolicy for a new model Action; saved plans/references/snapshots survive unknown retries without replanning. Existing default behavior remains intact.
- Delivered immutable RuntimeProfile/Catalog, strict JSON/TOML declarations, explicit ComponentRegistry, local RuntimeBuilder/RuntimeInstance and original-profile ProfiledEngine routing. Included adapters cover offline echo/Chat Completions, native Harness/Executor/context, SQLite/in-memory memory, bounded/fixed Recall and SQLite lexical knowledge. Unknown adapters and inline default-provider credentials are rejected; custom factories remain explicitly trusted application code.
- New --config and run --spec paths plus a packaged config starter allow default assembly without editing Python. New defaults affect only new requests; retained original declarations select old components. Catalog does not archive code/data or migrate Runs. Receipt lookup precedes configuration activation, and default scoped control replay needs no old profile or idle active runtime.
- Independent review reproduced four P2s in invalid-engine cleanup, rejected-runtime close retry, control receipt routing and optional diagnostics. All were fixed and the review file now passes 25 cases, including parameter conflicts, principal/workspace denial and unchanged Run/events/budget. Root additionally verified false/failed close, invalid/async factories, typed construction errors and real thread ownership. See [review disposition](../architecture/reviews/2026-10-06-runtime-assembly.md).
- Fresh complete validation: Python 3.12.7/macOS, `pytest -q -W error` → **645 passed in 49.98s**, 74 cases added over dev7. Ruff lint/format and Git whitespace checks pass. Real process approvals under a changed default preserve the original model/tool version and one business effect; active actual tool threads block switching and resource release until drained.
- Actual installed dev7 → dev8 verification outside checkout preserves the exact original handle/receipt/Manifest, resumes local-4 successfully and performs one business write. Installed config-v1 continues under default config-v2; custom registered business tools preserve the old version and repeat approval receipt. A removed original profile still permits recorded receipt replay and refuses continuation. Incomplete close retains the real lease/resources, and retry releases them once. The isolated wheel imports all 86 public names with matching source/package dev8 metadata; pip check passes, using reused third-party dependencies and no credential environment or network fetching.
- Wheel/sdist build without isolation passes. The wheel contains 25 SDK modules and packaged starters; the sdist includes the assembly guide, plan/design, independent review and new tests. Kernel local-4, execution Schema v1 and dev3 caller digests stay unchanged; profile/planner add identities only when explicitly enabled. No remote push, release or publication was performed.
- Graph/parallel Workflow, multi-Agent, MCP/sandbox, model streaming/capability negotiation, managed memory/vector adapters, enterprise identity, capacity/retention/migrations and distributed execution remain unimplemented. Full M1 still requires grouped fault evidence, real-model quality, independent Temporal authority and external adoption. CI Python 3.11/3.13 were not run locally.
- Documentation checks cover 30 documents, 157 local links, 16 Python blocks, 26 shell blocks and one TOML configuration block; the 20 task-case specifications validate against JSON Schema, remain specification_only with results=null, and have no model scores. Code blocks were syntax-checked; actual installed starter/history/recovery results are reported separately. The editable dev8 installation is restored with matching source/metadata and all public imports; pip check passes.

## Default model protocols and complete streams — dev9

- Implemented ModelCapabilities, StreamingModelProvider and detached ModelStreamEvent, shared HTTP/SSE lifetime and independent Chat/Anthropic/Gemini conversions. Chat supports explicit generation parameters; DeepSeek has a disabled-thinking/max_tokens preset, Anthropic supports text/client functions, and Gemini supports native text only. No vendor SDK or runtime dependency was added.
- The Engine optionally validates the actual Harness request before a new Action/reservation, then rechecks before actual dispatch and rereads cancellation state. Old Providers without the pure method remain compatible. Complete SSE results enter the same independent receiving/adoption stages; deltas are transient text, never tool Actions or durable Run events. Stream truncation/cancellation does not publish tool proposals and retains the existing unknown model-credit reservation.
- Registry adapters and packaged model starter require explicit model/protocol/credential references. Placeholder and invalid configuration fail before creating the execution database; supplied credential refs do not fall back to unrelated variables. Native unsupported message fields and reasoning continuations are rejected rather than discarded. Model capabilities can disable implemented behavior but cannot enable missing protocols; disabled tools also reject unsolicited response proposals.
- RED→GREEN: Chat 23 initial failures, native 19 initial failures, assembly 7 failures/6 valid controls. Root added cancellation/limits/preflight and malformed/opaque proposal cases; independent review found five P2s and supplied 9 RED/1 positive case. All are fixed: empty Anthropic JSON delta, explicit Chat SSE error marker, malformed shape, dropped named speakers and unsupported reasoning history. The [review](../architecture/reviews/2026-10-06-model-adapters.md) states the actual evidence and remaining uncertainty.
- Fresh complete verification: macOS/Python 3.12.7, `pytest -q -W error` → **721 passed in 63.26s**, 76 cases over dev8. Ruff lint/format and Git whitespace checks pass. Anthropic approval-to-tool-result uses real Engine adoption with one tool execution; all actual Tasks cancelled during an unfinished HTTP stream close the response, keep the borrowed client and retain held=1 without a tool Action.
- Standard no-isolation wheel/sdist build succeeds. In a dedicated environment outside the checkout, actual dev8 → dev9 preserves original demo and queued Chat handles/receipts/Manifest/identity. Demo approval/restart produces one business effect; queued Chat invokes the HTTP fixture once, and subsequent drive invokes it zero times. Original oncall/rag/config starter dictionaries have identical SHA-256 digests across installed versions.
- Installed dev9 imports all 92 public names with matching package/source metadata and passes pip check. All three HTTP protocols run nonstream/SSE fixture requests once, with correct authentication/parameter/usage and stream close; DeepSeek's explicit preset identity is verified. A generated model project rejects placeholders without creating a database, then runs the configured installed HTTP fixture once. Reused third-party dependencies require no network fetching; subprocess environments contain no inherited credentials, only explicit dummy fixture values where needed.
- The wheel contains 28 SDK modules and packaged templates; the sdist carries the guide, design/plan, review and new regressions. Default local-4, ExecutionStore/SQLite v1, caller digests, Chat identity and legacy templates remain unchanged. New parameters/stream modes/protocols fix new identities; old Runs cannot silently adopt them. Editable installation is restored separately with matching metadata and imports.
- No live vendor/account/model compatibility or AI-quality run was performed. Native Gemini signed tools, opaque thinking continuation, server tools, multimodal, Responses API, automatic routing and durable token streaming remain unimplemented. Graph/parallel/multi-Agent, MCP/sandbox, enterprise/service/distributed execution and full M1 gates remain. CI Python 3.11/3.13, remote push and publication were not performed locally.
- Documentation verification covers 34 documents, 174 local links, 17 Python blocks, 28 shell blocks and two TOML blocks. The 20 task-case specifications still validate against JSON Schema, remain specification_only/results=null and provide no model score. Blocks were syntax-checked; actual installed applications/protocols/recovery were tested separately. Source and editable dev9 metadata, all public imports and pip check agree.

## General framework scope clarification — 2026-10-06

- User clarified the full target: replaceable abstractions plus usable defaults across models, Agent/teams, static/dynamic/dataflow Workflow, tools, context, memory, RAG, remote data and execution modes, with adoption and capability goals measured against AgentScope.
- Added the [framework capability viewpoint](../architecture/viewpoints/framework-capabilities.md), including the dev9-versus-target matrix, component lifecycle and conformance requirements, distinct stream semantics, controlled Plan/child-Run boundaries, role-specific storage adapters and G1–G6 delivery dependencies. AgentScope comparison freezes v2.0.9 / 2e706a6 and calls for task/user evidence; no benchmark was executed.
- Revised architecture document v0.3, README roadmap, extension guide and immediate increments to prioritize the general SDK before full enterprise execution. Existing M1 gates and runtime guarantees remain required. This is a documentation change; package dev9, local-4 and current runtime/API behavior remain unchanged.
- Verification: 36 documents, 213 local links, 15 architecture section links, 17 Python/28 shell/two TOML blocks and task-case JSON syntax checked; Git whitespace checks pass. No runtime tests were rerun for this documentation-only change. Live-model, external-service and cross-framework experiments were not executed.

## Static plans and serial Graph Workflow — dev10

- Delivered immutable plan v1 and public ValueRef/Literal/InputMap/BranchCondition/GraphNode/GraphWorkflowSpec, pure compiler/interpreter/transform ports and default implementations. Dependencies, condition/skip propagation, explicit optional joins, input/output mapping and Schema validation run in a serial graph; no parallel/loop/dynamic/ChildRun/dataflow claim.
- Graphs compile once on first command acceptance and pin plan/component identities. Node input/results persist with execution authority; native Agent nodes reuse existing model/tool receiving/adoption, approvals, budgets and effect reconciliation. Pure transform result and node completion commit together. A focused workflow runtime helper keeps selection/transitions out of the native model/tool loop.
- Explicit JSON/TOML declarations and component factories, plan/node diagnostics and packaged graph starter are implemented. Default legacy request/local-4/Manifest, ExecutionStore v1 and original starter dictionaries remain on their compatibility path; compiler normalization can be explicitly converted to a new Graph declaration. Graph records include a native read shape and a new workflow Manifest so dev9 refuses them before scheduling.
- RED→GREEN: 41 missing public API assertions, 20 unsupported graph/component engine cases and six missing loader/config/starter cases; three additional identity-type/bound-input and two strategy-order/normalization failures fixed; downlevel release read-shape failure fixed. Real process exit after node start, node completion and Session append recovers with one business effect, two model fixture calls and one Session message. Model/tool receiving cancellation does not schedule successors.
- Fresh complete verification in project .venv: Python 3.12, `python -m pytest -q -W error` → **803 passed in 70.54s**, 82 cases over dev9. The first system-Python run had five generated-application import failures; those child interpreters lacked the installed package. The corrected project run includes all five. Ruff lint/format pass; source/editable package metadata now both report dev10.
- Ruling: retain the default Agent/sequence compatibility bridge while Graph uses pinned IR/components. This preserves historical behavior and costs a temporary dual entry path until explicit migration. Workflows remain serial; trusted pure transforms cannot hide I/O or substitute for a managed async executor.
- Standard no-isolation wheel/sdist build passes. Outside-checkout installed actual dev9→dev10 preserves native receipts/Manifest and all four original starter dictionaries; queued Chat fixture dispatches once then zero, approved demo writes once. Graph branches, old/new profile history, read-only node inspection and actual installed dev9 typed refusal followed by dev10 recovery pass. All 106 public names exist; pip check passes.
- Independent read-only gpt-6-astra [review](../architecture/reviews/2026-10-06-static-workflow.md) found no concrete Critical/Important/Minor defect. Reviewer ran 82 Workflow tests and the full **803-test suite in 70.29s**, warnings as errors, plus mutation/binding/compiler probes. Pure host contracts, excluded future modes, live quality and the compatibility bridge remain documented boundaries; no second review or fix pass was needed.
- No live-model, enterprise backend or cross-framework benchmark is claimed by these offline tests. Python 3.11/3.13 CI and remote publication were not performed locally.
- Final documentation verification: 40 documents, 235 local links, 21 Python blocks, 31 shell blocks and two TOML blocks pass syntax/link checks; task-case JSON remains valid. Ruff checks 90 formatted source/test files, Git whitespace checks and editable-install dependency checks pass.

## Managed Tool nodes and MCP sources — dev11

- User requested continued implementation toward AgentScope-level default components and extension paths. G2's connected tool increment adds public ToolDescriptor/ToolPolicy/ToolSource, atomic selected registrations, MCPTransport/MCPToolSource and default one-shot POSIX stdio. AgentScope v2.0.9's discovery/dispatch/lifetime separation informed the design; implementation is independent.
- Explicit Graph Tool nodes dispatch async/sync business handlers without a model. A shared Action proposal builder and existing ToolExecutor authority retain policy/approval, credits, stable effects, independent receipt/adoption, unknown-write reconciliation and cancellation. Real process exit after receipt commit resumes without another business write. Tool output Schema failure retains the confirmed effect.
- Source descriptors and policies are fixed snapshots. Host policies override untrusted MCP hints; default remote tools are unqueryable writes requiring approval. Idempotent writes require an explicitly reserved string argument injected from InvocationContext.effect_key; flat root Schema mapping is validated. Queryable writes need an explicit reconciler. Discovery errors/collisions cannot partially register names.
- Default stdio uses a real tracked worker, explicit argv/environment, fixed cwd, bounded JSON-RPC/pagination and finite timeout. Initialize/initialized and same-session descriptor checks precede calls. Completion/cancellation terminates the process group and reaps the direct peer; actual thread completion retains Coordinator ownership. Custom sources/transports are borrowed and their persistent resources remain host-owned.
- Package-contained mcp starter executes a real offline business peer, waits for approval and deduplicates by the stable effect key. New source/MCP/Tool/starter suites contain 61 tests. RED→GREEN: 20 missing source APIs, 19 missing MCP APIs, 15 unsupported Tool-node cases and a missing starter; existing v1 format rejection pins canonical non-Tool plans at v1.
- Fresh complete project-virtualenv suite: **864 passed in 71.19s**, warnings as errors. Ruff lint/format and Git whitespace checks pass; 100 Python source/test files are formatted. Standard no-isolation wheel/sdist build succeeds. Documentation checks cover 43 documents, 244 local links, 25 Python blocks, 32 shell blocks and two TOML blocks; task-case JSON is valid.
- Default native local-4/ExecutionStore v1 identities and Graph v1 serialization stay unchanged. Tool-bearing static plans use v2, requiring at least one Tool node; old runtimes cannot continue them. This leaves non-Tool custom compilers on canonical v1 and does not perform automatic migration.
- Installed actual dev10→dev11 preserves native receipts/Manifest, queued Chat dispatch once then zero, one demo business effect and all five old starter dictionaries. Graph v1 branches/profile history/replay pass; Tool v2 is refused by actual dev10 before dispatch. Installed MCP approval/restart/replay writes one effect; all 114 public names and pip check pass. The complete outside-checkout upgrade/artifact run passed again after the review fixes.
- Independent review ran 61 new and 102 existing lifecycle/executor/Workflow tests and reproduced four gaps. The single fix pass adds 8 RED→GREEN cases: session-local cursors stay in one stdio discovery session, reserved keys fail before approvals/reservations, malformed negotiation uses ToolSourceError and boolean reserved schemas use ValidationError. Focused final suites: 69 passed in 3.99s; fresh full final suite: **872 passed in 77.37s**, warnings as errors. No second review was requested.
- G2 bounded parallelism, HTTP/OAuth/persistent MCP, CLI sandbox, arbitrary NodeExecutor, dynamic Plan/ChildRun/teams and enterprise execution remain future work. Offline protocol/fixture tests establish no live-provider/task-quality or AgentScope superiority claim. Python 3.11/3.13 and remote publication have not been run locally.
- Final documentation verification after the review record: 44 documents, 249 local links, 25 Python blocks, 32 shell blocks and two TOML blocks pass syntax/link checks. The task-case specification remains JSON-valid and supplies no model quality score. Review evidence and scope rulings are retained in the [managed-tools review](../architecture/reviews/2026-10-06-managed-tools.md).

## 2026-10-06 — dev12 local bounded parallel Workflow

Added explicit max_concurrency=2..32 static plan v3, a pure replaceable
WorkflowScheduler/WorkflowBatch and default declaration-order scheduling. Default
1 preserves serial v1/v2 declarations and manifests. Independent nodes have
transactionally merged execution frames and reserved isolated Sessions inside one
Run; actions, commands, budget and event sequence retain one authority.

Agent/Tool overlap, configurable caps, explicit joins/skips, shared budget,
multiple approvals/replay/restart, unknown effects/manual context reconciliation,
stop-on-failure, caller/bulk cancellation and real-thread ownership have behavior
coverage. Five real-process windows cover response/receipt commits, external
commit, node completion and Session append. An unsaved sibling model call may
retry; confirmed work is recovered through the original effect policy.

The parallel starter, JSON/TOML setting and scheduler factory are available from
the installed SDK. Diagnostics expose branch Sessions and outcomes without
internal execution frames. Full pre-review suite: 915 passed in 78.47s with
warnings as errors; Ruff/format/whitespace and document syntax/links passed.
Package/upgrade evidence and independent final review are recorded separately.
Per-Run concurrency does not deliver global capacity, planning, ChildRun/teams,
message queues, dataflow, multi-process/distributed execution or full M1.
See [parallel Workflow](parallel-workflows.md).

独立 dev12 Review 复现并修复：授权回调已核验完成仍重复派发、终态先于真实 Session append 结束而释放预留、父级失败事件缺失。七个新增回归通过；最终完整 suite **922 passed in 75.81s**，warnings-as-errors。资源静止标记持久保存，真实记忆线程／bulk cancellation／终态恢复有行为覆盖。审查取舍和安装证据见[并行审查记录](../architecture/reviews/2026-10-06-parallel-workflow.md)。

### dev12 框架能力审查后的契约修复

- 修复惰性租约/关闭接口、非法 Session ID 和配置诊断遗漏，新增 68 项回归。合法 Session 名称不规范化，请求摘要、local-4、Schema v1 和旧计划身份不变。
- 一次独立只读审查发现修复引入的共享租约竞争：获取失败时不能调用 release。两个真实争用用例 RED→GREEN，保留 acquire 抛异常时由适配器清理本次失败的原语义；没有第二轮审查。
- 最终完整 suite **990 passed in 78.58s**，warnings-as-errors；修复后针对性组合 106 项通过。Ruff、全仓库格式和 Git 空白检查通过，文档 Python 片段同时格式化。
- wheel/sdist 构建通过；37 个 SDK 模块与源码、安装副本逐字节一致。仓库外安装包契约测试 **68 passed in 0.97s**；旧 dev12 wheel 与 HEAD 的 37 个模块一致，实际保留原回执及恢复前记录、继续原生/v3 任务、返回节点诊断。
- 完整 AgentScope/LangChain/LangGraph 对齐和“特有能力超越”仍按行为与采用成本验收；本次没有交付动态 Plan/团队、远程存储或实时流，也没有竞品 benchmark。见[框架对齐审查](../architecture/reviews/2026-10-06-framework-parity.md)。

## 2026-10-06 — dev13 async assembly and owned client lifecycle

- Added public AsyncLifecycle, explicit register_async/abuild/own_async, RuntimeInstance.aclose and async context management. Existing synchronous factories/defaults remain usable; Store/Engine authority stays synchronous. Lifecycle is extracted into its own module while previous public import paths remain available.
- Owned async resources bind their creating loop, close in reverse order and retain incomplete cleanup for retry. Cancelling an outer waiter preserves the real cleanup Task. Cached operations refuse use after shutdown starts; wrong-loop drive fails before Action/budget mutation. Real tool threads keep the lease until drained.
- Packaged offline async starter uses a real httpx.AsyncClient with MockTransport, versioned TOML profiles, original-profile resume and receipt replay. It provides an application async entry; synchronous ProfiledEngine/CLI async routing remains unimplemented. Existing seven starter dictionaries are unchanged against the actual dev12 wheel.
- Single independent read-only review found two P2 issues: malformed rejected-engine drain could strand its valid close/lease, and cleanup self-reentry after outer cancellation could wait on itself. Both reproduced RED and were fixed in one pass; normal drain remains strict and Runtime/Context cleanup reject self-reentry. No second review was requested.
- Fresh project-venv suite on Python 3.12/macOS: **1018 passed in 88.78s**, warnings as errors; 28 tests added over the repaired dev12 baseline. Focused contracts: **113 passed in 13.71s**. An initial system-Python run passed 110 tests but lacked ralf_agent in two generated-app child interpreters; verification uses the installed project environment.
- No-isolation wheel/sdist build passes. Outside-checkout wheel tests: **92 passed in 1.33s**; actual dev12 wheel preserves pre-resume records/receipts and resumes native/v3 tasks under dev13. Installed async starter run/replay/resume and real client close pass; all **118** public exports import. SDK byte equality and final document/quality evidence are recorded in the [review](../architecture/reviews/2026-10-06-async-assembly.md).
- All 39 SDK modules match source/wheel/sdist/installation. Ruff lint/format, whitespace and pip check pass; editable metadata is dev13. Documentation verification covers 53 files, 297 local links, 28 Python/36 shell/2 TOML blocks. Offline runtime regression is 3/3 with one business write per case.
- This delivers reusable async resource ownership, not remote storage adapters, planning/teams, distributed execution, online model quality, full M1 or cross-framework superiority. Python 3.11/3.13 CI and remote publication were not performed locally.

## 2026-10-07 — dev14 remote data and bounded orchestration

- Delivered RedisMemory/PostgresMemory for async Session/Facts/pagination/current validation, PostgresKnowledgeStore document authority, QdrantVectorIndex with completed writes and scoped hits, and deterministic HashEmbeddingProvider. Optional redis/postgres/remote extras and explicit abuild factories preserve base dependencies and local execution authority. Real services: Redis8.8.0/client8.1.0, PG16.2/psycopg3.3.6, Qdrant1.19.2.
- Delivered immutable TeamSpec/DynamicWorkflowSpec, TeamStrategy/Planner/PlanVerifier, default sequential/router/supervisor and rule/model/complete strategies. Atomic child creation/link/escrow, separate Sessions, total credits, parent cancellation, unknown holds, original parent Release validation, proposal-receiving/adoption windows and bounded replan share the native Engine.
- Initial missing subsystems and governance/lifecycle edge cases were reproduced RED before implementation. Five real-process durability windows preserve saved proposal/revision, child identity and completed work. Public starter/config/CLI diagnostics cover plan/team; original eight templates remain exact.
- One fresh independent read-only review found three Important issues, none Critical. Immediate sibling cancellation, retryable Qdrant cleanup and managed planning concurrency admission were fixed with five RED→GREEN cases; no second review. Full final suite **1223 passed in114.86s**, warnings-as-errors, with all actual services and no skipped cases. Final test/fixture formatting changes were verified by the related25 tests; product code unchanged.
- Outside-checkout installed-wheel contracts **293 passed in7.73s**, including actual remote services and subprocess origin checks. Actual dev13→dev14 preserves native/v3 records/receipts and resumes them. All142 public exports import; eight prior starter dictionaries remain identical; installed Async run/replay/resume/client-close succeeds. Installed Plan/Team starter behavior is covered by the full suite.
- Actual dev13 refuses new Team/Plan parents and their approval-paused linked children before dispatch, with unchanged records and no writes. dev14 approves/replays the original child control and resumes each parent with one test write and held=0. No hidden migration or new default identity for legacy Runs.
- Source/wheel/sdist/installed SDK equality: **49 modules**; base metadata still requires only httpx/jsonschema, and public import succeeds with optional redis/psycopg imports blocked. Ruff lint/format (196 files), Git whitespace, CI YAML syntax and pip check pass. Documentation: 59 files,324 local links,32 Python/39 shell/2 TOML blocks; offline runtime regression3/3 with one write each. Editable metadata is dev14; task-owned temporary PG/Qdrant services were stopped after real-service verification.
- Scope and evidence are recorded in the [dev14 review](../architecture/reviews/2026-10-07-data-orchestration.md). No live model-quality, semantic retrieval, enterprise/failover/distributed or superiority claim; no commit, push or publication.

## 2026-10-07 — dev15 DAG/nesting, remote handoff and Temporal preview

- Added typed DAG proposals/conclusions, rule/managed model planners, dependency/condition/result binding reuse, bounded parallel nodes and scoped CAS pending-node patches. Nested sequence/graph/team/dynamic members have pinned ancestor releases, isolated child Sessions, recursive escrow settlement and finite depth/size. Root Sessions stay reserved until real descendant work stops. Original flat declarations/default identities remain.
- Added MessageBus with in-memory/real Redis Streams, structural sync/async Inbox/Outbox/CommandAdapter ports and durable SQLite handoff defaults. A2A0.3 polling subset, trusted host Scope, replaceable client and managed queryable-write ToolSource are explicit compositions, not execution authorities. Broker claim/ack/dedup and real HTTP process fixtures run with restricted child environments.
- Added explicit async TemporalEngine/worker/runtime and EffectJournal/PostgresEffectJournal. Workflow History owns commands, credits, Actions and terminal results; Activities never wrap LocalEngine. Native Agent/sequence only, unsupported orchestration/memory/context capabilities refused. Five actual two-worker scenarios each20 repetitions; strengthened blocked cancel-drive guard20/20. First hot-edited fixture batch stopped after57 passes and is retained separately, not reported as complete acceptance.
- One independent read-only review found/fixed P1 canceled Temporal resurrection, P2 A2A root endpoint routing and P2 incomplete Journal durability returns. RED→GREEN plus same-reviewer rechecks73 passed. Pre-review full suite1357 passed209.85s; stable repaired full suite **1376 passed227.68s**, warnings as errors, actual services, no skips. Planner public return annotation was aligned afterward and its34 relevant cases passed.
- Frozen20-case managed ModelDAGPlanner proposal evaluator and console added; default report not_run. Explicit offline fixture3/3 with model_quality=null. Real model/call-cost configuration remains pending; no live quality, worker-outcome or equal-framework benchmark result asserted.
- Actual dev14 wheel native/v3 and Team/flat Plan records/receipts resume under dev15. New DAG/nested approval trees stop before dispatch under olddev14 without mutations; its nested reader can raise rawKeyError (unsupported downgrade). Underdev15 the original child approval/replay resumes each with one test write. Ten old starter dictionaries are exact; new installed dag/nested run/replay/queued restart succeeds;189 public exports import, including with optional dependencies blocked.
- Installed contract test area initially lacked source-only eval fixtures/wrapper:5 failures and346 passes. Those5 are setup failures, not SDK import/model failures; fixtures are added separately and the final installed verification is recorded in the [review](../architecture/reviews/2026-10-07-dag-remote-execution.md). Base dependencies remain httpx/jsonschema; Temporal/server are optional extras. No commit, push, public release, enterprise parity or completeM1 claim.

- Final outside-checkout wheel contracts **351 passed in56.13s** after source-only eval fixture preparation; SDK origin checks pass. Base dependency-blocking contracts121 passed/1 expected SDK-required skip;189 public imports succeed with all optional adapters blocked. All65SDK modules equal source/wheel/sdist/installed. Ruff lint/format237files, whitespace, pip check and69document/361link/35Python/43shell/2TOML validation pass. CI YAML parsed with Ruby; actual service helper boots/stops locally, GitHub jobs/other Python versions not executed. Task-owned PG/Qdrant/Temporal services are stopped after final evidence.


## 异步交接与默认服务 — dev16

- 新增结构化 SyncTaskControls/AsyncTaskControls/TaskControlBridge，A2A 接入原生异步权威，固定 Scope／模式／方法与 callable 入口；中央验收完成 DTO／命令身份／有限 JSON。
- 新增共享 PostgresInbox/PostgresOutbox，按 Scope 原子容量、完整消息去重、不可变完成；broker 发布在 DB 事务外，真实进程退出后按原身份修复。
- 新增 LocalA2AService 与第十三种 a2a 包内模板，显式宿主凭据，真实 HTTP／SQLite 默认；跟踪 drive、等待真实线程，取消关闭等待仍保留清理，关闭阶段失败可重试。
- 独立 review 的 callable 实现漂移及全量复现的 Temporal run 前首次控制竞态均 RED→GREEN；实际双 HTTP／双 Worker／PG 及实际旧 wheel History 重放通过。
- 最终全套1412项、仓库外实际 wheel 契约206项通过；阻断可选SDK的基础组合146项通过、5项按预期skip。195个公开导入，69个SDK模块 source/wheel/sdist/installed字节一致；原十二种starter及dev15原生／图／团队／DAG／嵌套回执与审批恢复兼容。
- 真实模型质量仍not_run；Temporal仍Agent/sequence子集，完整M1、企业治理和竞品对等质量尚未验收。详细失败／修复／支持边界见[本轮审查](../architecture/reviews/2026-10-07-async-handoff.md)及[使用指南](async-handoff.md)。未提交或发布。

## Distributed composition and governance — dev17

- Delivered independent Temporal parent/child composition for Agent-node Graph,
  Team, flat/DAG planning and nesting; explicit orchestration release and replaceable
  registered strategies/planners/verifiers. Fixed scoped child intent and cap before
  dispatch; CAS pending-only patches and immutable control receipts.
- Added separate RAG Context Activity/snapshot, fixed-reference revalidation and
  actual PostgreSQL/Qdrant combination; immutable per-Run execution limits, History
  deadlines and fixed approval expiry. Added packaged temporal starter and eight-case
  business evaluator with actual effects/reconstruction and not_run default.
- One independent review: P1 remote DAG Schema, P2 contradictory escrow settlement,
  P2 unsafe evaluation ordering. Six RED→GREEN regressions fixed them; an additional
  failed successor test now gates advancement on actual child quiescence.
- Full actual-services suite1462passed349.78s; outside installed contracts244passed83.51s;
  optional-blocked base188passed5expectedskip5.80s. Actualdev16 local/History receipts,
  original13templates, installed starter and77SDK-modulebyteidentity verified.
- Live model configuration remains unavailable; offline15calls/8cases are regression
  evidence only. Global identity/capacity, retention, remote-stop administration and
  downtime/failover certification remain separate acceptance gates. Details in the
  [review](../architecture/reviews/2026-10-07-temporal-composites.md).

## Document ingestion and default extensibility — dev18

- Continued approved D1 from the intelligent-data design. Delivered structural pure Parser/Chunker, immutable bounded source/span/prepared/receipt DTOs, borrowed async coordinator and memory/SQLite/PostgreSQL atomic knowledge ingestion. Native local-4/default releases, legacy put/chunks and original fourteen templates remain.
- TDD includes missing APIs/templates, independent storage replay/CAS/conflicts, default chunk configuration, lazy/corrupt extension returns, atomic rollback, real two-connection admissions, actual process loss before/after commit, explicit PG/Qdrant indexing and source validation. New fifteenth ingest starter works with actual user files and grounded offline evidence.
- One independent reviewer found receipt construction repeatedly decoding the full snapshot per chunk; watched RED counts72→520 with16→128chunks, fixed to single decode and reused IDs. Identical4096chunk upper-bound case64.539s→0.0269s. SQLite backend identity nuance documented; stronger public receipt locator self-consistency remains a nonblocking future conformance check.
- Installed wheel contracts303passed124.69s; optionalclientsblockedbase240passed7expectedskips10.55s;84SDKmodules/211exports, original14templatedictionaries and actualdev17native/graph/team/flat/DAG/nested receipts and Temporal nativeRun/registryHistory recovery verified. Final fullsuite/cleanup recorded below when complete.
- D1 knowledge_committed does not mean vectors ready; embedding/indexing remains explicitly separate. Full M1, semantic/hybrid retrieval, intelligent context/memory, external adoption and real paid-model quality are not claimed. See[review](../architecture/reviews/2026-10-07-document-ingestion.md) and[guide](document-ingestion.md).

- Final verification: 1521passed374.81s withactualservices/-Werror; lint/format/Gitwhitespace/links/CI/requirements passed. Finalstandardwheel/sdist rebuiltwithcurrentguide/review; editabledev18 metadata restored. Alltemporaryservicemanagers stoppedafterverification. No paidmodel/publication; source andledger preserved.

## Composable hybrid retrieval review — dev19

- Review first:3RED incorrect ingestion receipt IDs/order/range→53relatedGREEN, preserving validdev18receipts. D2 delivers explicit float HTTP Embedding/immutableusage, rank/ID proposals and one-authority Hybrid parallel retrieval; offline defaults and async ownership documented. New3factorynames and16thstarter leaveold15templates unchanged.
- TDD:22missingHTTPAPIRED→25GREEN; laterUnicode/overflow2RED→typedpreflight;12missingpipelineRED→39HTTP/pipelineGREEN; fusion registrationdrift1RED→rejectbeforeranker; newconfiguration/starter3RED→GREEN;106selectedactualPG/Qdrant/localHTTP/storage tests pass43.68s. HTTPfixture uses Hash vectors, not semantic quality.
- Onefreshindependentreviewer found4P2, noP1: mutablelist duringsourceawait, TTL expirationbeforeexternalrerank, expandedlimitsaboveglobalcaps, invalidweightsacceptedbeforeallocation.8permanentRED→104localGREEN. Frozenorder, anotherauthoritycheckbeforerank, explicitglobalcaps andstrictpreflightclosed all4.
- Actualdev18wheel native/graph/team/flat/DAG/nested receipts and nativeTemporalRun/registryHistory continuation verified; original15templates unchanged,221exports optional-importsafe,90SDKmodulesbyteidentical. Firstfull1573passed477.79s; finalfull/installed/cleanup recordedbelow whencomplete. No paidmodel, commit/push/publication. See[review](../architecture/reviews/2026-10-07-hybrid-retrieval.md) and[guide](hybrid-retrieval.md).

- Finaldev19gates:1581passed343.49s fullactualservices/-Werror;363passed101.81s outsidewheel;298passed7expectedskips14.28s optionalSDKblocked. Ruff/format/Gitwhite/links/CI/requirements green;90SDKmodules/221exports; original15templates andactualdev18local/Temporalrecoverycompatible. Finalwheel/sdist refreshedwithcurrentguide/review; editabledev19 restored; taskservice shutdownconfirmedafterverification. No paidsemanticmodel/publication.


## Pure context and explicit artifact review — dev20

- Added structural MessageCounter/ContextBudgeter/ContextSummarizer, completed typed measures/summaries, and opt-in BudgetedContextAssembler. Default exact chars, whole-group tail selection and explicit deterministic historical excerpts are usable offline; UTF-8 tokens are an estimate. Required policy/task and latest complete tool evidence survive; history, Session and execution authority are unchanged.
- Added actual-request measurement after Harness.prepare, recorded snapshot/measurement/provenance, and strict pure plugin identities/bindings/returns. Existing default ContextAssembler and native local-4 identities retain behavior.
- Added ArtifactReference and sync/async ports, memory/SQLite defaults with explicit JSON puts/gets/deletes, immutable TTL/SHA256/Scope/backend, UTF-8/read bounds, atomic duplicate/capacity, safe path/lifecycle and real process crash/concurrency evidence. No implicit tool result offload/GC/global quota or distributed artifact store.
- Added strict budgeted factory and seventeenth context starter. Actual dev19 wheel's sixteen template dictionaries and local/native Temporal History recovery are preserved; basic dependencies unchanged. The offline application performs large-result storage, bounded sample tools and factory restart.
- One independent review found two P2 mutable-object boundaries; both reproduced RED and fixed in one pass with three GREEN regressions/204 related tests. No important/minor left. Final actual full suite1652passed395.38s; installed431contracts plus3review regressions and the corrected cancellation case pass; optionalSDKblocked369passed7expectedskips. One intermediate actual run exposed a cancellation-test precondition race, traced in originalHistory; test now awaits child cancellation, retains strict budget/one-write checks, and passed6consecutive actual repeats. Runtime authority bytes remain unchanged. Package/Ruff/format/Gitwhite/links/CI/pip checks pass. See [review](../architecture/reviews/2026-10-07-context-artifacts.md) and [guide](context-artifacts.md).
- Automatic fact extraction/retraction, managed model summaries, custom Temporal context, real semantic/task quality and enterprise governance remain pending. Continued SDK delivery is not complete M1 or cross-framework superiority evidence.


## Managed memory and live quality — dev21

- Added opt-in MemoryPipeline with zero-model-call rule defaults or a one-credit managed field selector. Successful scoped sources, host allowlisted exact values, command/source/release bindings, append-only CAS facts, TTL/currentness and bounded replay are explicit. Existing memory ports cover SQLite/in-memory and real Redis/PostgreSQL; resources are borrowed and business/memory receipts remain separate.
- Added ManagedModelSummarizer and FrozenContextSummarizer with complete assistant/tool group coverage, durable usage/evidence and pure consumers. Added an eighteenth offline memory starter; the original seventeen template dictionaries remain unchanged. Summaries require explicit preparation; semantic revision/retraction, atomic multi-fact admission and automatic in-Run compression remain separate work.
- Registered pure Temporal custom ContextBuilders with executable/configuration identities, separately adopted History context snapshots and actual prepared-request bounds. Real two-process Worker kill/restart, approval, managed summary and replay contracts pass; default native manifests and actual dev20 History/local receipts remain compatible.
- One fresh independent reviewer found four P2, no Critical or Minor. One fix pass reproduced and fixed expiry receipts, lazy context adoption, dynamic/wrapped executable identity and explicit streaming bypass; eight permanent regressions include lazy extractor and oversized recall variants. No re-review or implementation delegation.
- Final actual-service full suite: **1686 passed in 365.29s**, warnings treated as errors. Outside-checkout installed wheel contracts: **468 passed in 108.01s**. Expanded optional-SDK-blocked contracts: **400 passed, 7 expected skips in 18.31s**. Actual dev20 native/graph/team/flat/DAG/nested and native Temporal History continuation verified. 246 public exports import without optional SDKs; base requirements and six extras remain unchanged. Source/wheel/sdist/installed bytes match for all 102 SDK modules. Ruff/format, documentation links, requirements, Git whitespace and CI YAML checks pass. CI includes the new starter/adapters/Temporal contracts; it was not run remotely. Task-owned PostgreSQL/Qdrant/Temporal service shutdown was confirmed; private credential exclusion is checked separately.
- The [real DeepSeek trial](live-model-quality.md) retains 38 paid calls and complete usage. Initial business0/8, planning3/6, summary3/3 and field-selection3/3; revised instructions3/4; explicit non-streaming JSON mode3/3 abstention cases. The full final-config eight-case business set was not rerun. Schema enforcement was retained, original failures remain, and no comparative framework superiority or complete M1 claim is made.


## Model and typed-tool foundations — dev22

- Following the [accepted order](agentscope-alignment.md), delivered stateless native Responses text/functions/JSON/SSE, additive model factory, typed keyword-function inference/registration and managed five-scenario compatibility SDK/CLI. A nineteenth offline model-check starter is packaged. Existing execution authority, low-level identities and old eighteen template contents remain compatible; no new base dependencies.
- One fresh review found P1 Schema remote retrieval and three P2 stream/default/report boundaries. One TDD fix pass resolves every finding, including effective defaults before Local/Temporal operation identity/approval/policy.21 permanent regression/control cases and127 related tests pass; no re-review or deferred Minor. [Review](../architecture/reviews/2026-10-08-sdk-model-tools.md) and [guide](sdk-model-tools.md) explain supported shapes and evidence.
- Final full actual-service suite1769passed365.20s; installed wheel551passed125.22s; optionalSDKblocked483passed/7expectedskip34.49s. Actualdev21 native/graph/team/flat/DAG/nested receipts, one-write approval recovery and nativeTemporalHistory continuation pass; installedTemporalstarter works after Worker restart.249uniqueexports and111SDKmodules have installation/byte-identity checks; requirements/extras unchanged. Build/Ruff/format/Gitwhite/links/CI checks pass locally.
- No provider means not_run; offline scores and online compatibility probes retain model_quality=null. No new live credentials or paid calls were used. Native reasoning/media/server tools, automatic in-Run compaction, unified live events/input, default Sandbox and enterprise parity remain subsequent increments. Python support remains3.11–3.13; upstream cancellation/billing is not inferred from consumer close. Services are stopped after verification; changes and artifacts remain local, with no commit/push/publication.


## Invocation middleware and committed event subscriptions — dev23

- Following the accepted A2 dependency order, added immutable invocation records, synchronous middleware, no-op/metadata logging defaults and structural Provider/ToolExecutor wrappers. Strict completed-None hooks, finite observations, current code/configuration identities and safe after dispatch preserve known receipts and original approved operations. Registered profile defaults and host injection remain explicit; resources are borrowed.
- Added scoped cursor/envelope ports, bounded sync/async Run event subscriptions, terminal tail draining, SSE encoding and read-only ralf-watch-events CLI. Pull consumption has no background producer and grants no execution authority. Timeout/cancellation retains and joins actual read tasks; interrupted close can be retried. The twentieth observable starter runs offline with typed tools, middleware and persisted event output; original nineteen templates remain unchanged.
- One fresh review found three Important boundaries: optional model entrypoints missing from identity, replaceable after dispatch losing receipts, and repeated cancellation losing a read cleanup handle. Eight permanent RED regressions reproduced them;73 focused tests pass after one fix pass. No re-review, implementer delegation or deferred Minor. See [review](../architecture/reviews/2026-10-08-middleware-events.md) and [guide](middleware-and-events.md).
- Final actual-service suite **1843 passed in389.47s**; installed wheel **625 passed in125.38s**; optional SDKs blocked **556 passed,7 expected skips in21.44s**. Initial full regression exposed an existing child-intent-before-StartChild test race; typed NotFound is retried within its original deadline, keeping actual reservation, cancellation/quiescence/credit and History assertions unchanged. Native authority code remains byte-identical to dev22.
- Actual dev22 native/graph/team/flat/DAG/nested and native Temporal History recovery, duplicate controls/one business write and installed Temporal starter across Worker restart pass.260 optional-safe exports and120 SDK modules have package identity checks; base requirements/extras remain unchanged. Build/Ruff/format/Git whitespace/31 link sets/CI/requirements checks pass locally; no remote CI or new paid calls. User changes and evidence remain local, without commit/push/publication.
- Input continuation, default Workspace tools/container Sandbox, HTTP/WebSocket service streams, async telemetry/OTel, automatic in-Run compaction and enterprise parity remain later increments. Trusted bounded/cooperative readers and explicitly versioned host dependencies are required; test gates do not certify arbitrary production deployments or real model quality.

## Shared model acceptance and recent Session — dev24

- User requested fixing dev23 review defects before further architecture expansion. Common pure decision/effective-ID validation now serves Local and new Temporal receipts; authorities retain independent scheduling and state commits.
- RED→GREEN:10 corrected model failures (Local controls already passed),5 corrected recent Session failures, then8 independently reviewed malformed-return failures. Final focused259passed/2actual-service skips. Returned invalid JSON uses diagnostic invalid_fields while serializable usage survives; no hidden retries or lazy model-field execution.
- Exactly one fresh reviewer; one Important fixed in one pass, no Critical/Minor, no re-review. Reviewer69tests, six boundary probes and three actualdev23 serialized-state comparisons complement implementation gates. Deferred/non-public boundaries are in the [disposition](../architecture/reviews/2026-10-08-shared-model-context-contracts.md).
- Fresh full suite1884passed380.99s/-Werror with actual PostgreSQL/Qdrant/Temporal and test-managed Redis; installed666passed123.32s; optional-SDK-blocked base595passed/9expectedskips25.08s. New actual Temporal rejection receipts survive History replay and Worker restart. No paid-model/quality or performance claim is inferred.
- Actualdev23 wheel → fixeddev24: native/graph/team/flat-plan/DAG/nested local recovery; original native/CommandRegistry Histories; additional legacy Schema rejection/duplicate-ID Histories replay with unchanged snapshots/budgets. All20previous starter dictionaries unchanged,260public exports optional-safe; installed Temporal starter DAG/Team RAG, approval/restart/repeated control pass.
-120baseline SDK modules:113unchanged,7modified,2new; current122modules preserved in source/tested wheel/installed byte evidence. Runtime native manifest identities unchanged. Existing historical receipts and request snapshots are preserved; mixed-version Worker deployment is not certified.
- Per-Agent capability binding, a simple Agent/Session facade and recommended managed memory/RAG chains remain next work. Full-history materialization, production governance and complete AgentScope alignment are still open.
- Local-only work: original branch/HEAD and prior dirty increments/evidence retained; no commit, push, publication, live credential read or model call. Final build/static/byte checks and owned-service shutdown receipts are retained privately.

## 2026-10-08 — dev25 H1a capability bindings

Plan: docs/superpowers/plans/2026-10-08-agent-capability-bindings.md.
Immutable wrappers and scoped catalog route six roles per native Agent/sequential step, including same logical Provider aliases. Fixed per-step releases preserve approval/replay and received evidence. Profile v1 encodings remain unchanged; v2 uses existing owned/borrowed and asynchronous cleanup.
Session overrides/Turn coordination, advanced/Temporal wrappers and new Facade semantics remain pending. New contract tests: 60 passed from the actual installed wheel. Final full regression: 1902 passed/42 service-dependent skips; Ruff/format/whitespace checks passed. Independent review found one CLI manifest P2, reproduced and fixed. Actual dev24 wheel approval recovery and duplicate controls preserved one business write. No live model or remote publication; ephemeral localhost service fixtures were exercised. Details: [H1a review](../architecture/reviews/2026-10-08-agent-capability-bindings.md).

## 2026-10-08 — dev26 Local H1b composite bindings

- Extended the existing six roles to Local Graph/Team/Dynamic/nested native members through stable declaration paths and fixed parent/child releases; original AgentSpec/parent definitions and local-bindings-1/native identities remain unchanged. New composite releases use local-bindings-2.
- Parallel frames use their own binding resolver; compiler Agent substitutions are refused, direct Tool/Transform nodes and model Planner remain host-governed. Child projection preserves scope, budget/cancel/approval recovery and Session-disabled behavior.
- JSON/TOML composite CLI run/resume/inspection passed for graph/team/dynamic. Six actual process crashes cover graph/nested response/receipt/external-commit windows with original selected providers and two unique business effects.
- Final post-review full regression: **1959 passed,42 skipped in344.59s**; actual installed old/new binding contracts: **117 passed**. Ruff/format/whitespace passed; wheel/sdist128 SDK modules match source. Actual dev25 wheel native/H1a Agent/sequence pending approvals upgrade with unchanged receipts/Manifest and one effect each; actual dev25 refuses the new bound graph release unchanged before a write, dev26 resumes it once.
- Fresh-context independent review found one P2: composite size validation blocked legacy native H1a schemas. RED2/GREEN3 verifies preserved native acceptance with unchanged sequence codec limits; actual old-wheel recovery now includes large native/sequence cases. Post-fix full regression and installed contracts pass; actual dev25 wheel approvals include530k/1.1MB native and900k sequence schemas, six original tasks with one effect each. Session resource selection, other roles, Temporal bindings and H2 Facade/Turn/closing remain pending. No live model calls, commits, push or publication. See [Local H1b review](../architecture/reviews/2026-10-08-composite-agent-bindings.md).

## 2026-10-08 — dev27 Local H1c Session bindings

- Added Session refs with existing sync/async ports, host-allowlisted namespace views and actual-address admission in the original acceptance transaction. Native/sequence/graph/team/dynamic/nested members retain their original routing and isolation; no new SQL authority or runtime dependency.
- JSON/TOML session-resource factories preserve owned/borrowed lifecycle. Alias/default/physical-key ownership, restart/approval, async drift, future serial claims and capability detection are covered. Selected views cannot be registered again or used as defaults.
- One fresh reviewer found two P2 and one P3; the capability inconsistency was treated as P2. One fix pass: RED6 then GREEN39, no rereview. Invalid authority returns never close borrowed objects.
- Final full suite: **1998 passed,43 skipped in335.12s**; final installed binding contracts: **155 passed in11.58s**; installed actual Redis1 passed/PG1 skipped. Ruff/format/whitespace pass;130 SDK modules match source/wheel/sdist/installed bytes.
- Actual dev26 wheel creates eight native/H1a/H1b/large-schema approvals; dev27 returns original receipts and manifests, repeated controls preserve one business effect each. Old wheel refuses new Session refs unchanged; dev27 then recovers one effect. H2 Facade/Turn/close, Temporal bindings, other selectors and cross-authority Session leases remain pending. No live model, credential read, commit, push or publication. See [H1c review](../architecture/reviews/2026-10-08-session-capability-bindings.md) and [Session tutorial](session-bindings.md).

## 2026-10-08 — dev28 Local H1d scoped data bindings

- Added explicit Facts/Knowledge host-allowlisted namespace resources and immutable borrowed views through native/sequence/graph/team/dynamic/nested Local routing. Facts provenance/actual-client guards and Knowledge source/config/retriever guards retain original authorities and ports.
- Added facts-resource/knowledge-resource JSON/TOML factories; actual underlying clients retain sync/async owned lifecycle. Data resources use local-bindings-4; Session refs are detected independently, preserving mixed address admission and data-only legacy Store compatibility.
- Exactly one fresh reviewer found P1 delegated-client drift and P2 provenance reservation dropping fitting records. RED7/1control passed→GREEN56; actual-record selection and source-only continuation preserve records while counting bounded reads, with possible extra remote round trips. No rereview.
- Final full regression2055passed/44skipped283.03s; installed211passed12.98s, actual installedRedis1passed/PG1skipped. Real dev27 wheel nine original pending approvals upgrade with unchanged receipts/Manifest and one effect each; old wheel refuses new scoped release unchanged, dev28 resumes once.
- One fixed DeepSeek trial26calls: frozen8×2 business10/16 (repair0/6, abstention/refusal10/10), scoped source extraction4/4;15742input/735output tokens. Repair cases falsely claim resolved after diagnostics with no business write. No changed oracle/instructions, retry or additional paid subset. Trial preceded final identity/pagination fixes; stable unpaged model inputs unchanged, no post-fix live rerun claimed.
- Other roles/Temporal bindings/H2/default managed stages/enterprise and framework parity remain pending. Key only ephemeral non-echo stdin/process memory. Preserve all source/evidence locally; no commit/push/publication. See [H1d review](../architecture/reviews/2026-10-08-scoped-data-bindings.md), [data tutorial](data-bindings.md) and [live results](live-model-quality-dev28.md).

## dev29 — Local completion verification / H1e

Delivered pure CompletionVerifier and detached DTOs, configurable committed-tool receipt rules, durable acceptance/rejection/bounded feedback before Session save, per-Agent verifier bindings and sync/async Profile factories across Local compositions. Default legacy release bytes preserved; PlanVerifier, managed model stages and Temporal bindings remain pending. Validation evidence is recorded in architecture/reviews/2026-10-08-completion-verification.md.

## dev30 — Local Agent limits / H1f

Delivered pure replaceable AgentLimitsPolicy and fixed default; accepted cap snapshots; mandatory host/Spec/Agent minimum; atomic over-limit tool-batch refusal and existing-Action recovery; Local native/sequence/graph/parallel/team/dynamic/nested selection and sync/async configuration. Global capacity, deadlines/currency and full H1/H2 remain pending. Evidence: architecture/reviews/2026-10-08-agent-limits.md.

## 2026-10-09 — dev31 Local stateless facade / H2a

Delivered immutable AgentHarness declaration composition, standalone Agent/shared Runtime, online AgentRun/portable RunRef/WaitResult, independent Local task hosting, pure observations, nested original-root controls and retryable owned/borrowed closing. Existing Harness remains pure; old RunHandle/request/Release/Action identities are preserved. Profile factories retain trusted Scope and loop-bound owned client cleanup.

One fresh read-only review found two Important issues: child waits missed root host failures; first wrong-loop calls could prevent rightful owner-loop cleanup. Five permanent tests failed RED and passed GREEN in one fix pass; no Critical/Minor or re-review. Final full2235 passed/44 configured-service skips369.01s; actual installed wheel outside checkout176 passed7.07s; source/wheel/sdist/installed139-module byte comparison, optional-free286 exports and20 unchanged starter maps. Actual dev30/dev31 wheels recover ten approval scenarios in both directions, preserving original receipts/Manifest and one business effect each.

Full H1/H2, durable Session/Turn, Temporal facade, automatic H3 stages, environments and production governance remain pending. No new base dependency, paid-model calls, commit/push/publication. See [API guide](agent-api.md), [review and all decisions](../architecture/reviews/2026-10-09-local-agent-facade.md), [remaining capability checklist](remaining-work.md).

## 2026-10-09 — dev32 colocated Local Sessions / H2b1

Delivered portable SessionKey/SessionRef/TurnAdmission, borrowed AgentSession and an optional transaction-bound SessionAdmissionStore with SQLite default. Native/sequence Turn admission shares existing command/Run acceptance, atomically preserves original bindings, sequence and route ownership, and provides stable busy/mismatch receipts and idle CAS rebind. Read-only observations do not advance occupancy or resume execution. Actual handlers, unknown effects and required result-save evidence retain occupancy across cancellation/restart. Registered physical routes reject legacy raw bypass even while idle.

One fresh read-only review found three Important boundaries: lazy custom admission results, non-durable resolved manifest-drift refusal, and substituted Runtime locators. Ten permanent regressions failed RED then passed GREEN in one fix pass; no Critical/Minor or re-review. Final full2280 passed/44 configured-service skips375.83s, -W error; actual installed wheel outside checkout159 passed6.05s. Source/wheel/sdist/installed144-module comparison, optional-free294 exports and20 unchanged starter content maps pass. Actual dev31/dev32 wheels recover nine schema1 approval cases in each direction with original receipts/Manifest and one business effect each. An activated schema2 database refuses the old wheel before dispatch; the new wheel reconnects, repeats approval safely and confirms one actual business effect.

Schema2 activation is opt-in, atomic and one-way; unchanged stateless databases remain schema1. Remote/composite Sessions, input/deadline/FIFO/handoff, Temporal facade and full H2b remain pending. No new base dependency, paid-model call, commit/push/publication or AgentScope parity claim. See [Session guide](session-api.md), [review and decisions](../architecture/reviews/2026-10-09-local-session-turns.md) and [remaining checklist](remaining-work.md).

## 2026-10-09 — dev33 Temporal native Agent facade / H2c1

Runtime.from_temporal shares Agent/AgentRun/RunRef/WaitResult for native/sequence, with async areference/aattach, pinned actual resource/Scope/release, strongly owned outbound RPCs, bounded pure observation and detach-only client lifecycle. Server History remains authoritative; Local behavior and schema1/schema2 remain. Unsupported advanced facade/bindings/shared Sessions refuse before acceptance.

One fresh review found three Important: mutable dispatcher crossed services during an internal await, transport TimeoutError was swallowed as observation timeout, and malformed drive responses were ignored. Eight permanent RED cases plus one unraisable lazy-coroutine error became37 GREEN1.16s in one fix pass, no re-review. Final full2317 passed/47 configured-service skips337.65s; actual installed contracts206 passed8.25s. Actual persisted Service/Worker/history source3 passed7.45s and installed3 passed6.27s; same-model offline-provider lookup audit establishes the stated execution scenarios, no live-model quality.

Actual dev32/dev33 wheels recover11 Local approvals each direction, including two schema2 Sessions, preserving original receipts/Manifest and one business effect each. Source/wheel/sdist/installed146-module equality,294 optional-free exports,20 unchanged starter maps and unchanged dependencies/extras/scripts pass. No paid call, commit/push/publication or full H2/AgentScope claim. See [guide](temporal-agent-api.md), [review and all decisions](../architecture/reviews/2026-10-09-temporal-agent-facade.md) and [remaining work](remaining-work.md).

## 2026-10-09 — dev34 Temporal composite Agent facade / H2c2

Registered Graph/Team/Dynamic/nested definitions now use the shared Agent API,
original parent History refs/receipts and bounded pinned actual child controls.
Unknown tools remain discoverable after root cancellation; contradictory pruning
evidence is refused. Native terminal approval projection retains original actions.
Actual Worker probes fixed sandbox planning imports and nested control-bookkeeping
comparison through a compatible v2 patch marker; old histories keep v1 semantics.

Final full2352passed56skipped; installed231passed; actual persisted Service/Worker
12 source +12 installed probes passed. Actual dev33 wheel recovery preserves4 Runs
and7 old/current parent-child histories; Local4 schema1/schema2 approvals recover
each wheel direction with original receipts/manifest and effect1. Source/wheel/
sdist/installed147 modules match;294 optional-free exports/20 starter maps and
dependencies remain compatible. One fresh reviewer Important finding fixed in
one RED→GREEN pass; no minors or re-review. No paid call/commit/push/publication.
See [API guide](temporal-agent-api.md), [review and all decisions](../architecture/reviews/2026-10-09-temporal-composite-agent-facade.md). Temporal bindings/shared Sessions, complete H1/H2 and H3 default managed chains remain open.


## 2026-10-09 — dev41 managed context preparation / H3b1

Opt-in ManagedContextPipeline plans/consumes pure complete omitted history groups;
original Local authority journals source/reference snapshots, summary intent/response,
frozen business projection and independent execution credits. Native/sequence support
rule excerpts or one tool-free host model call. Unknown calls retain credits and fall
back without retries; terminal adoption performs no model I/O. JSON/TOML factories
and per-Agent context selection reuse existing ports; semantic8 first admission is atomic.

One fresh reviewer found four Important; six RED cases became GREEN in one fix pass
with120 focused passes, no minors/re-review. Final2678 passed/66 configured-service
skips391.27s; frozen installed163 passed. Actual dev40/dev41 default11 definitions
recover in both directions with original receipts/Manifest and11 unique business effects
each; actual old schema2–7 Sessions retain original receipts with no recovery model call.
Old40 refuses8 in both modes; new41 separately reuses saved summary responses and holds
unknown calls across restart without retries.159 source/wheel/sdist/installed modules
match;295 root exports retained plus ManagedContextPipeline,21 actual starter maps
unchanged. SDK version constant and distribution metadata both41; no dependency/script
changes or paid model calls. Full H3, automatic Session/RAG compression, artifact
offloading, model extraction and advanced/Temporal stages remain open. See
[guide](managed-context-stages.md), [review/evidence](../architecture/reviews/2026-10-09-managed-context-preparation.md)
and [remaining work](remaining-work.md).

## 2026-10-10 — dev42 managed model-selected memory / H3a2

Opt-in ManagedModelMemoryPolicy adds pure request/select hooks over completed native/
sequence result fields. Host values remain grounded; original memory_stages journal
request/dispatch/response/keys, independent Action markers and one original selector
credit. Empty selection completes without facts; unknown holds without retry/fallback.
Existing CAS evidence, per-Agent grants and JSON/TOML sourced-memory(-async) factories
remain the authority. Semantic9 first admission is atomic; defaults stay disabled.

One fresh reviewer found four Important: dispatch proof, actual policy/target method
drift hidden by replacement, expiry after validation and ordinary preparation failures.
One RED→GREEN pass includes actual Scope drift and persistence failure isolation;
150 focused regressions pass, no deferred minors or second review. Final frozen suite
2738 passed/66 configured-service skips379.10s; actual installed contracts206 passed.
Actual dev41/dev42 wheel defaults11 definitions recover both ways with original receipts/
release and11 unique effects each. Old schema2–7 Sessions and schema8 saved summaries
recover; four schema9 selector/CAS windows retain source/receipts without paid replay,
and old41 refuses9 in both modes.161 source/wheel/sdist/installed modules match, original
296 exports retained plus one,21 starter trees and dependencies unchanged. No paid model
or remote push/publication. Free-form/advanced/Temporal stages, Session/RAG compression,
semantic revision, default intelligent presets and full H3 remain open. See
[guide](managed-model-memory-stages.md),
[review and all rulings](../architecture/reviews/2026-10-10-managed-model-memory.md).


## 2026-10-10 — dev50 opt-in model query transformation / H3 R17

ModelQueryTransform borrows a fixed completed async ModelProvider and returns strict
bounded tool-free query proposals, preserving the original query by default. Native
Knowledge/Local semantic Facts factories resolve named Profile providers; JSON/TOML,
scoped resources and before-database alias validation reuse original assembly and ownership.
Original eight defaults and Run/History authorities remain. Final3168 passed/92 configured-service skips529.76s; installed64 contracts,187
source/wheel/sdist/installed modules byte-identical. Old8 Profiles recover both directions:
12 approval runs each one effect,4 semantic identity-only; old49 rejects3 new model
declarations before DB. One Important Facts ordering finding fixed in one12-case
RED→GREEN pass,96 focused regressions; no deferred minors. Evidence
in [review/evidence](../architecture/reviews/2026-10-10-model-query-transform.md).
Preparation before acceptance may repeat paid calls; Temporal Facts and real quality remain open.


## 2026-10-10 — dev51 native HTML ingestion / H3 R16

Pure HtmlDocumentParser and installed ingest .html/.htm reuse original source, Chunker,
atomic knowledge receipts and lexical citations. Preformatted code whitespace is preserved;
actual policy/helper identities, typed malformed input and bounded parser callbacks are
validated before commit. Text defaults remain unchanged.
One fresh reviewer found4 Important/1 Minor;11 RED→GREEN cases fixed in one pass,
84 focused passes/2 unconfigured PG skips. Installed82 contracts and188 byte-identical
source/wheel/sdist/installed modules verified. Text receipt/pipeline recovery both ways
and new HTML receipt recovery with old50 are verified; uncommitted HTML is refused
by old50. Final3197 passed/92 configured-service skips533.12s; Ruff/format/whitespace and
wheel/sdist pass. Evidence in
[evidence](../architecture/reviews/2026-10-10-html-ingestion.md).

## 2026-10-10 — dev52 canonical DOCX body ingestion / H3 R16

Adds a pure stdlib DocumentParser and installed ingest template for canonical DOCX paragraphs and table text. Reuses original source identity, parsed-character chunks and atomic knowledge receipts, with no new runtime dependency, file/URL fetching or execution authority. Native text/HTML definitions stay unchanged.

Initial 21 missing-API failures and one unsupported-template failure were observed before implementation. The first 109 adjacent parser/ingestion/starter tests pass, including actual SQLite process loss inside and after the transaction; full final evidence is recorded in the [acceptance review](../architecture/reviews/2026-10-10-docx-ingestion.md). Full H3/M1 and real Office interoperability remain open.

Dev52 final targeted/installed evidence: 115 passed each; five review/text regressions RED→GREEN. 189 Python modules match source/wheel/sdist/installed. Actual old51/new52 text and HTML receipts recover bidirectionally with unchanged fresh pipeline/content/chunk identities; committed new DOCX replays under old51, which refuses uncommitted DOCX without writes. See the acceptance record for the independent review and bounded scope rulings.

Dev52 frozen final regression: **3230 passed, 92 skipped in 580.41s**. Ruff, format, Git whitespace, dependency checks and wheel/sdist build pass; 11 changed documents/380 local links/8 Python blocks validate. No paid model, live remote-service certification or remote publication in this increment.

## 2026-10-10 — dev53 optional text PDF / H3 R16

Adds PdfDocumentParser using lazy pypdf>=6.20,<7 and scoped Configuration, with no core runtime dependency. Original source/hash/URI/metadata and atomic ingestion authority are retained; no OCR/rendering/URL/script execution or new scheduler. Eleven initial missing-API failures, one template unsupported-PDF failure and two registration/commit identity failures observed before their implementation/fix. Process recovery and final evidence in [acceptance record](../architecture/reviews/2026-10-10-pdf-ingestion.md). Full H3/M1 and real PDF corpus compatibility remain open.

Dev53 targeted and installed contracts: 141 passed each; eight review reproductions RED→GREEN in one correction pass. Independent core environment without pypdf imports SDK, runs text starter ingest/replay/query, refuses PDF with typed extra guidance/no writes, and replays a committed PDF through the original coordinator. 190 Python modules match across source/wheel/sdist/installed; text/HTML/DOCX receipts recover bidirectionally under old52/new53 with identical fresh pipeline/content/chunk identities.

Dev53 frozen final regression: **3256 passed, 92 skipped in 547.10s**; Ruff/format/Git whitespace/dependency/build checks pass. Twelve related documents/391 local links/9 Python blocks validate. No paid model, live remote-service recertification or remote publication.

## dev60 Temporal History Session Turns

Add opt-in Session coordination History, actual Namespace UUID identities, fixed bindings, durable serial Turns/busy receipts and idle CAS; preserve original business Run/Parent authority. Ordinary and managed Context keep Conversation separate from Facts/Knowledge and current-task retrieval. Frozen declarations and supervised RPC completion keep caller cancellation/detach separate from business cancellation. Default-off protocols remain. Evidence and open storage/lifecycle/quality gates appear in [dev60 acceptance](../architecture/reviews/2026-10-11-temporal-sessions.md).

## dev61 Temporal Agent limits

沿 R01/H1f 复用纯 AgentLimitsPolicy 和 FixedAgentLimits，Worker 生成提案、原 History 校验并固定逐节点 caps。原 Context／model／Tool Actions 执行限制，原 Parent 投影绑定子树。取消与恢复保留原证据，默认发布保持；最终验收见[记录](../architecture/reviews/2026-10-11-temporal-agent-limits.md)。

最终dev61：全量3492/164（523.45s、56122 exit0），源码实际12恢复+6超限、最终安装18真实Temporal/85契约、209模块、core-only与60→61→60原审批/回执/一次测试工具兼容。宿主入口P2、沙箱异常身份P2与错误码Minor已闭环，自有Service83761 exit0且stopped；只做本地提交。完整能力目标继续active。

## dev62 Temporal 纯完成验证

沿 R01/H1e 复用 CompletionVerifier 与 ToolReceiptVerifier，Worker 提出纯 verdict，原 Run History 固定当前节点原输入与已提交回执并一次采纳。accept 才进入原记忆和完成链路；retry 保留原额度、审批和受保护反馈，reject 明确失败。宿主／每 Agent inherit/ref/disabled 支持原生、顺序、图、Team、动态及嵌套。实际十八项恢复／取消／重放通过；最终交付证据见[验收记录](../architecture/reviews/2026-10-11-temporal-completion-verification.md)。模型验证、DecisionPolicy／外置 Session 和其他环境角色、H3 质量及完整 M1 继续开放。

最终dev62：全量3519 passed/182 skipped（537.24s，8978 exit0），源码实际Temporal18/133.86s、最终安装18/133.40s及163契约；212模块、core-only与61→62→61原审批／回执／一次工具兼容。只读review140通过且无待办P1/P2/Minor；两处控制／反馈P2已RED→GREEN。自有Service25330正常exit0且stopped。未调用真实模型、未重验远端数据库；只本地提交，完整R01–R26目标继续active。

## dev63 Temporal DecisionPolicy

沿 R01/H1 公共纯 Harness 的 prepare/propose，提供宿主默认／每 Agent inherit/ref；固定实际方法、编译器 super 闭包及原 Scope。实际模型请求与原响应/提案证据由原 Run History 一次采纳；不改变审批、Schema、limits、完成规则和记忆责任。Temporal 九类绑定已接通，外置 Session/环境角色、完整 Profile/服务治理和真实质量仍待交付。见[指南](temporal-decision-policy.md)和[验收](../architecture/reviews/2026-10-11-temporal-decision-policy.md)。

最终dev63：全量3563 passed/198 skipped（485.75s，95622 exit0）；冻结源码实际16/125.73s、最终安装实际16/126.11s及195契约。214模块、core-only与62→63→62原审批／回执／一次工具兼容通过。独立审查2项P2由2RED→195GREEN闭环，无待办Minor。自有Service75051正常exit0且stopped。未调用真实模型／重验远端数据库；仅本地提交，完整R01–R26继续active。

## dev68 Temporal Context 实际读取生命周期

沿 R01/R02/R14/R19 和既有唯一执行权威，显式 ContextExecutionOwner/Port 托管许可等待、
实际读取 Task／桥接线程及准确结束 ACK；原 Native History 保存许可、响应和结束，
原 Parent/Coordinator 使用同一静默门禁。五类只读 phase 覆盖原生／顺序／图／Team／
Plan／DAG／嵌套；数据／客户端借用与异步创建循环保持。默认 False、旧 native save-v1
和旧发布保持，新 binding2 由旧67在任何 Activity 前拒绝。

最终源码3940 passed/306 configured skips（498.96s）；安装241契约/22.69s与实际服务
39/303.78s、源码实际39/291.05s；231模块在源码/wheel/sdist/core/完整安装一致。真实
Redis/PG、原 Histories replay、独立 Worker kill+wait/restart、67↔68原审批／Turn／
准确回执兼容通过。单次 fresh-context review 的3项重要问题由14RED→114GREEN闭环，
无待办 Minor。原生兼容初始 fixture 硬停 Worker 时观察 Activity 默认60s，而断言15/30s
不足；原历史之后确认为 succeeded/quiescent 与 Coordinator idle，无重复效果。最终
fixture 采用明确2s Activity deadline、正常 Worker 关闭与原双完成门禁，已通过。
完整 H1/H2/H3/M1、R01–R26 和真实质量继续开放；不做远端推送。
详见[验收](../architecture/reviews/2026-10-11-temporal-context-read-lifetime.md)。

## dev70 Temporal 多版本 Host（子集验收通过）

沿 R04/H1/H5，TemporalProfileHost 只组合原 Assembly 与 Facade，不创建第三套业务状态。全 Catalog 固定和纯预检先于 I/O；原 Registry/Coordinator 队列需保留，默认选择不迁移旧 Run/Session。可信 Scope、实际 namespace UUID、原 Manifest 与版本均参与重连验证。所有版本实际调用、桥接线程和原结束通知排空后，才停止所有 Worker 并清理共享 owned ledger。借用 SDK Client 不清理。配置现在可声明既有 PostgreSQL EffectJournal；Local 与旧 dev69 拒绝该新声明。

见[指南](temporal-profiles.md)及[验收](../architecture/reviews/2026-10-11-temporal-profile-host.md)。本子集最终全量／安装／兼容门槛通过；完整 R01–R26、其余环境角色、部署版本／迁移、容量／保留、企业身份及真实质量继续开放。
