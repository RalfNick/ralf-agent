# H3 recommended semantic retrieval, recall and orchestration

Baseline adbc328/dev46. User authorizes continuous implementation, documentation synchronization, tests/acceptance and final local commit; no push. Reuse approved architecture and current branch. Existing authorization overrides redundant skill design/plan handoffs.

## Outcome and approach

Use public Runtime/AgentHarness and existing owned factories. Add explicit semantic-knowledge, memory-recall, plan-and-execute and team profiles, plus recommended_harness for Plan/Team declarations. No new execution authority or hidden I/O in pure hooks. A wrapper application lifecycle was considered and rejected because Runtime already owns hosting; changing existing preset version-1 defaults was rejected because historical identity must remain stable.

Semantic-knowledge requires caller-selected compatible float HTTP embedding model/dimensions/URL/auth reference and async assembly. Reuse sqlite-hybrid-http, parallel lexical/vector retrieval, RRF and authoritative validation. No hash fallback or automatic downloads, indexing or paid calls. Ingestion/indexing remain explicit existing operations. Preserve Knowledge retrieval order; configuring a service is not proof of semantic quality.

## Recall selection

Introduce a pure ReferenceSelector select(task,references)->unique original integer indices, with version/implementation/method pinning. Default OverlapReferenceSelector prioritizes recent Session reference, preserves Knowledge ordering, and ranks bounded Facts by lexical relevance. Never edits, synthesizes or grants reference access. Custom selectors are sync completed-only, bounded subsets; original source validation remains Engine-owned. Relevance is only within the already bounded recall candidates, not global/semantic recall.

RelevantDataContext extends existing ManagedDataContext through assemble/prepare/finish, freezes selector in identity, and applies the same selection during fallback and model-summary consumption. Old ManagedDataContext/preset default identities remain unchanged. Add sync/async relevant-data factory registration with owned artifact resources and direct selector injection.

## Plan and Team

recommended_harness('plan-and-execute'|'team', members=None, agent_bindings=None, **existing_spec_options) returns existing immutable AgentHarness. Defaults are explicit instruction-only members, bounded RulePlanner or SupervisorTeam; tools require host configuration. Model planning explicitly selects existing model planner. Custom members, pure strategies/planners/verifiers and original binding paths remain usable. No claim that CompleteVerifier or instruction-only members establishes task correctness.

Profiles use relevant-data, bounded recall and existing Schema verifier; optional memory writes remain explicit except memory-recall (allowlisted observed final result, namespace aligned by agent_name). Unknown kinds/options/configurations fail before resource allocation. No new dependencies, secrets, network bootstrap or remote model calls.

## Acceptance

Update current dev46 tables/baselines before feature work, preserving marked historical records. Add failing tests for useful Fact ordering under context pressure, malformed/lazy selector and identity drift, managed-summary restore, preset preflight, JSON/TOML and owned cleanup. End-to-end configured HTTP embedding fixture retrieves non-overlapping synonym evidence through real HTTP, index/source version validation and native Agent; no model-quality claim. Plan/Team default and customized members run through common Runtime, approval, duplicate commands and restart without duplicate effects. Build installed wheel; compare original preset identity/old wheel recovery. Whole suite/lint/format/whitespace, one fresh read-only reviewer and one RED/GREEN important-fix pass. Record dev47 scope and remaining H3 quality/remote defaults, locally commit, clean only own scratch.
