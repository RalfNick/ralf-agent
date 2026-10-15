# Temporal deployment Coding implementation plan

> **For agentic workers:** use the explicitly authorized parallel execution method, TDD, disjoint ownership and independent review. Root integrates original authorities.

**Goal:** Deliver public deployment admission and retirement across the already selected Temporal Coding definitions, preserving actual native/handler lifetime and original recovery.

**Architecture:** Registry3 atomically indexes the original root and first envelope. Run/Parent Histories retain all native grants, actual calls, child physical evidence and irreversible seals. A fixed SDK-owned verifier may fence only a precisely proven stopped original Coding call; the transport bridge never owns another Run or permission state machine.

**Tech Stack:** Python 3.11+, optional Temporal SDK, existing PG EffectJournal/RunnerJournal, Codex POSIX/Docker execution, public SDK/Profile factories.

**Spec:** `architecture/specs/temporal-deployment-coding-contract.md`.

**Current checkpoint:** dev120 remains an uncommitted candidate. The thirteen selected topology cases and four real Docker gates have passed in separate frozen-source runs. Original Tool-worker death at both selected windows and the four additional recovery cases passed in Trials39–40. Owned close still has a product defect involving original maintenance admission and late queued release; its repair and regression are in progress. The no-candidate negative test's PostgreSQL TEXT decoding correction, actual approval-idle window, final full regression, installation and compatibility remain pending. SDK Session coordinator is still the next required batch. The [acceptance record](../../../architecture/reviews/2026-10-15-temporal-coding-wake-latency.md) distinguishes these proofs from real-model quality and stage completion.

## Global constraints

- Full native Agent/sequence, selected graph/parallel, Team/Dynamic and bounded recursive Coding scope stays required; coordinator integration remains required next work.
- Explicit deployment publication3/Registry3; current ordinary2 may use Registry2/3, Coding3 requires Registry3, existing Registry1/2 cannot upgrade silently.
- Retain native6/binding22 and composition7/binding23 shapes and full inventories; append bridge/state/verifier to all22 existing deployment source pins.
- Preserve default unselected Profile/Manifest/request bytes; immutable dev119 Worker recovery for old selected publications.
- Original metadata/envelope/certificate schemas remain; zero-cost unknown/effect/fee/physical evidence stay separate.
- Close fences new acceptance, then original Run stop intents; no invented cross-History atomic native grant.
- No global PID-based fence, missing-owner inference, forced release, TTL, second scoped Registry, business replay or new model-quality claim.
- Product/fixtures freeze, source/installed actual Temporal+PG and real Docker proof recorded separately. Only local commit; goal/batch2 remain open until their own full gates pass.

## Review focus

1. Close races with accepted but uncertain SDK start: late original History is stop-only, no new phase grant; uncertainty keeps its claim.
2. Activity/Tool ledger stopped while native pending/fence/create/foreign work remains: no seal.
3. Genuine Worker death after original Turn: cold control of original CID/owner, exact Coding call fence, no new prepare/Thread/Turn/fee.
4. Mixed ordinary2/Coding3 Host creation order, cross-Scope command IDs and close filters cannot bypass shared quota.
5. Two original child epoch/ancestry proofs must agree, including hidden Agents, prior revision and no-PG-row children.

## Task 1 — original pure Coding closure, fence association and guards

**Owner:** state worker. Create `src/ralf_agent/temporal_deployment_coding_state.py` and `tests/test_temporal_deployment_coding_state.py`; modify only `temporal_deployment_release_state.py` and its owned tests. Root wires guards into existing Coding modules.

**Consumes:** original Coding `stopped(state)`/`physical_stop_view(state)`, deployment call records, exact `delegated_execution.tool_request`, original native owner and `tool_executions[action_id].coding_owner_stop_proof`.

**Produces:** `selected(manifest) -> bool`; `closure_reasons(state) -> list[str]`; `coding_call_candidate(state, identity) -> dict`; `adopt_call_fence(state, request, attestation) -> dict`; `guard_mutation(state, previous, requested) -> bool` where an exact recorded duplicate returns True, otherwise a sealed state refuses. Candidate fields are exactly those in the spec. Attestation is SDK-owned, not raw Update data.

- [ ] RED: use real native/state fixtures with terminal/settled ledgers but pending native stop, live owner, missing physical child, old revision and zero-value unknown; assert closure refuses.
- [ ] RED: actual call carrier/action/Tool invocation/native owner mismatches, missing owner, foreign ordinary/model call, changed epoch/namespace/runner and unsafe PID-only proof all refuse.
- [ ] Implement pure exact association and physical closure, v3 `fence_proof=None` initial records and fenced evidence, without changing v2 record shape.
- [ ] RED→GREEN exact post-seal duplicate vs new grant/receipt/stop/child mutation rules, detached proof and immutable children/close identity.
- [ ] Focused tests and independent root review; freeze and report, no agent commits.

## Task 2 — original acceptance/control/owned-close transport bridge

**Owner:** transport worker. Create `src/ralf_agent/temporal_deployment_coding_bridge.py`, `tests/test_temporal_deployment_coding_bridge.py`; modify only `temporal_deployment_submissions.py` and its owned tests. Root wires old control/Runtime/Host callers.

**Consumes:** Registry3 scoped coding operations and first submission, original deployment SDK proof, existing composition proof/control helpers, original immutable SDK epochs.

**Produces:** `logical_request(spec, input, *, budget, session_id) -> dict`; `async root_admission(runtime, client, value, info) -> dict`; `async control(runtime, client, value, info) -> dict`; `async close(runtime, *, client, scope) -> None`; `async verify_call_stop(runtime, client, value, info) -> dict`; `registered_stop_activity(runtime, client)`. Fixed name `ralf.temporal.deployment-coding-stop.v3`, exact marker validated by `is_registered_stop_activity(runtime, client, function)`. Root/code state owns mutation; bridge validates actual SDK/physical proof and returns it.

- [ ] RED structural bound-runner normalization independent of moved aliases; missing/old Registry and mixed version handshakes; first envelope and closed-start races.
- [ ] Implement scoped Registry3 routes referencing the same original acceptance. Combined control executes once and supplies exact original Coding physical evidence; no duplicate business command.
- [ ] RED fake stopped call certificate, actual live original owner and changed host/epoch/runner; verifier reads original pinned candidate and checks OS birth through existing Coding runtime before returning exact evidence.
- [ ] Implement owned close over original candidates; use existing native/tree cleanup, retain receiver/SDK/PG on failed stops. Read-only diagnostics must not start a Registry.
- [ ] Focused SDK/transport tests, concrete API/race review, source freeze/report; no agent commits or service restarts.

## Task 3 — Registry3, public assembly and original Workflow integration

**Owner:** root. Modify protocol publication, Runtime, Builder/Assembly/Agent/Host, Registry state/Workflow, original Run/Parent dispatch and existing Coding guard hooks.

- [x] Preserve immutable dev119 install/wheel/product provenance before product edits; read current support matrix and obtain independent design audits.
- [ ] RED Registry3 scoped atomic index/close tests. Implement configuration versions2/3, shared quota, original record-derived coding candidates/bind/admission/close; original scopes isolated, no transplanted command-only index.
- [ ] RED public Coding SDK/Profile/factory construction and mixed Host order. Permit only public3 plus current Coding, no private/public ambiguity; preserve Session coordinator refusal and default publication.
- [ ] Register fixed cold-call verifier with exact exemption marker, SDK-owned original Run Update and native-loop eligible-call retry. Require current candidate unchanged after verification await; no raw caller attestation.
- [ ] Wire bridge root admission/control/close, cross-check and pin both child epochs in one SDK start, process closed roots through original stop-only cancellation before new business.
- [ ] Wire pure post-seal guards with exact already-recorded receipt replies. Persist original cold owner-stop proof even when Tool end was already acknowledged, without mutating earlier proof.
- [ ] Affected RED→GREEN, negative old/new publication checks and original default comparison; review before freezing actual acceptance.

## Task 4 — actual service and physical evidence

**Owner:** service worker. Create `tests/test_temporal_deployment_coding_service.py` and private/new test-only fixture helpers; root owns services, PG/Docker lifecycle, final build/install/docs/commit.

- [ ] Actual Temporal+PG thirteen selected topology/configuration cases, one root/start and accurate original result/fees, shared scope capacity and turnover.
- [ ] Approval/restart, accepted reserve/start lost reply with alias/queue change, native body commit-and-hold plus zero credits, independent stop/tool/deployment/effect ACK failures.
- [ ] Actual Worker exits after Turn; cold original native resource/owner proof and exact call fence. No new native permission or business writes, immutable child/Root SDK identities.
- [ ] Native CREATE never-GO versus sent/unknown, complete original stop and failed close retention, original hidden/revision/no-PG-row child obligations; no false daemon evidence from peers.
- [ ] Root: real Docker/CLI original CREATE reply/CID windows and physical process/container inspection; preserve genuine uncertain outcomes rather than fake negative proof.
- [ ] Root: freeze source/test identity, affected source/installed and actual services, default/source/installed history compatibility, credentials/package/source inventories and owned cleanup separately.
- [ ] Root: synchronize status/matrix/architecture/acceptance docs, local commit only. No full stage or new real-model-quality completion from this batch.
