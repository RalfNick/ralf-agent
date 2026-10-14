# Temporal public deployment and safe retirement implementation plan

> **For agentic workers:** use the existing authorized parallel execution method, TDD and independent review; root integrates shared original authorities.

**Goal:** Make ordinary deployment admission publicly usable with original first-acceptance recovery and safe root-capacity turnover; keep the complete phase-three matrix intact.

**Architecture:** Registry stores first immutable submission/receipt and retires slots only after its own SDK-owned proof Activity. Original Run/Parent Histories own actual Activity obligations and irreversible tree seals. SDK transport has no independent business persistence.

**Tech Stack:** Python 3.11+, existing optional Temporal SDK, ContextExecutionOwner and ComponentRegistry; dedicated local Temporal Service for evidence.

**Spec:** `architecture/specs/temporal-deployment-public-contract.md`.

## Global constraints

- Default Profile/Manifest/request bytes and original default History compatibility remain required.
- Private version-1 selected workers retain held-only semantics; public uses version 2. Existing v1 Registry is not replaced or silently adopted.
- Coding physical close and SDK Session coordinator are still required later integration, explicitly refused now; batch 2 remains open.
- No new scheduler, third business authority, forced eviction, TTL or monetary-only release.
- Envelope maximum 1 MiB, original cumulative command limit, bounded actual-call ledger.
- Frozen source/wheel/installed, source/installed actual service, original Worker compatibility and owned cleanup recorded separately. No new full-stage/model-quality claim; local commits only, no push.

## Review focus

1. Lost reserve/start/release responses preserve the same accepted root, first Manifest/queue/timeout and immutable receipt.
2. Zero-cost reservations and manual effects do not prove physical handler end.
3. Failed on_end ACK and whole-loop cancellation preserve actual-call obligations.
4. Child ABANDON, missing/pinned epoch and forged seals cannot retire a live subtree.
5. Closure/dispatch races resolve atomically in original History; exact duplicate controls stay readable after seal.

## Task 1 — original closure and physical ownership

**Owner:** state worker. Create `temporal_deployment_release_state.py`, `temporal_deployment_release.py` and focused tests; no root-owned files.

**Consumes:** original deployment proof `view`, `_proof`, `_ancestry`, `_policy`, `_namespace`; original state reservations/stages/child intents; Runtime fixed ContextExecutionOwner. **Produces:** pure initialize/begin_activity/end_activity/closure/view/seal/check_unsealed; transport execute/registered_activity/wrap_activity/check_owner/close_owner with exact interfaces in spec. `RELEASE_ACTIVITY="ralf.temporal.deployment-release.v2"`.

- [x] RED predicate tests for each Review Focus condition; actual stage fixtures and all reservation statuses, including amount zero.
- [x] Implement strict pure ledger identities, invocation exclusivity, detached views and irreversible seals. Original recorded receipts precede mutable guard.
- [x] RED actual owner cancellation/tracked thread, failed durable end ACK, registered Activity marker and Registry-origin verification tests.
- [x] Implement Runtime-owned shielded call execution and original epoch-pinned end Update, bottom-up SDK tree proof/seal and two release modes. Registry verification mode never trusts supplied proof without actual SDK reads.
- [x] Focused tests and independent root review; report exact files/results, do not commit independently.

## Task 2 — original first-acceptance SDK transport

**Owner:** transport worker. Create `temporal_deployment_submissions.py` and tests; modify `temporal_agent_runtime.py` and `temporal_host_runtime.py`／`temporal_profile_host.py` hosted routing. Do not edit Registry/state/Engine shared files.

**Consumes:** Engine scope/client/release/timeout/queue, Registry queries/Updates in spec. **Produces:** `async submit(engine, spec, input, *, command_id, budget, session_id) -> RunHandle`, `async guard(engine, kind, command_id, target, payload)`, and `async diagnostics(engine)`.

- [x] RED tests for original envelope/receipt, configuration mismatch, reserve/start uncertainty and racing aliases/queues.
- [x] Reuse stable logical request normalization and namespace identity; lookup before current-release checks. Fresh requests validate existing bindings/schemas/tree admission before reservation.
- [x] Query/start exact first envelope with original SDK policies, pin actual epoch and record original business receipt. Failures never release or replace original resources.
- [x] Higher facade duplicate preflight and hosted Registry routing adjusted only in owned assigned files, preserving defaults.
- [x] Focused tests, no new SDK authority or credentials; independent root review and report.
- [x] Add internal sealed-retirement recovery: verify original Registry envelope／Scope／namespace／epoch and certificate, issue fresh root-only exact duplicate seal Update to wake original History, and return read-only for an existing retirement. Actual stationary outage RED→targeted GREEN and refusal tests retained; no public helper API or direct Registry release.

## Task 3 — shared public APIs and original Workflow integration

**Owner:** root. Modify Runtime, protocol publication, Registry pure state/Workflow, Engine, Builder/Assembly and original Run/Parent loops.

- [x] Preserve immutable dev118 installed package/provenance and create private evidence directory before product edits.
- [x] RED Registry acceptance/record/retirement tests; implement protocol-version selection, atomic full first envelope, original immutable receipt and original SDK-owned release verification Activity.
- [x] RED public configuration tests; reuse admission factories/validators, exact DTO and ownership cleanup. Select protocol v2 only through public policy; retain private v1 semantics.
- [x] Register release Activity and begin/end/seal Updates/query. Integrate source-pinned actual owner, mutable guards and terminal release retry/diagnostics. Record original wake ownership; no disposal on observer cancellation.
- [x] Public Engine and original higher facade invoke task-2 transport; assembly forwards fixed policy, drains actual calls/submissions before components close.
- [x] Shared targeted RED→GREEN and freeze product/source inventory for service acceptance.
- [x] Record final affected source／installed checks and default／original History compatibility evidence against that freeze; 410 matching product files and 48 unchanged test modules.

## Task 4 — actual service, installed acceptance and delivery

**Owner:** service worker, disjoint new test file `tests/test_temporal_deployment_public_service.py`; root owns service lifecycle, wheel/install, docs/CI/local commit.

- [x] Implement actual public SDK/Profile/JSON/TOML and factory replacement scenarios using deterministic business components; targeted source evidence retained.
- [x] Implement and exercise targeted selected definitions, turnover, approval/Worker restart, reply loss, no-poller retired duplicate and original History replay; retain preliminary failures and split recoveries.
- [x] Complete the final frozen source and independent installed Service matrix: each 27 public v2 and 17 private v1 cases, zero failures／errors／skips; do not sum preliminary split results.
- [x] Implement and exercise targeted genuine zero-cost committed sync write and independent reconciler: manual effect evidence cannot retire before actual end/ACK. Held async Provider and nested/parallel child cancellation retain root quota.
- [x] Independent review, concrete repairs and matching product／fixture freeze; public sealed-retirement stationary P2 preserved as actual RED→targeted GREEN.
- [x] Finish final affected source／installed checks (each 953, zero skips), actual Service cases, original default History compatibility and optional-SDK boundary (53 passed／68 skipped). New product edits invalidate relevant older evidence.
- [x] Synchronize capability／support／architecture／change log and final source／installed／Service／compatibility／cleanup acceptance fields; retain earlier failures and separate test-only SQLite effect-evidence adapter windows from required Temporal＋PG stage acceptance.
- [x] Build frozen wheel and complete independent installation, byte identity／import origin and original compatibility; register wheel SHA in acceptance record.
- [ ] Root: confirm final sdist bytes／SHA and final credentials-scan evidence in private `final-acceptance.json`.
- [x] Close only owned test services／Workers／Registry fixtures; verify zero Running Workflow, exited controller and no dedicated listening ports.
Deliver with a local commit, no push. Leave batch 2, full phase-three／R01–R26 and mandatory Coding／SDK Session-coordinator／Temporal＋PG stage work active.

## Final evidence scope

Source and independently installed affected checks each pass 953 tests; actual Service each passes 27 public v2 and 17 private v1 cases. No failure／error／skip in those suites. Optional-SDK import blocking is a separate boundary check (53 passed／68 skipped), not another installed package. The 953 checks come from 46 affected modules; two additional actual Service modules form the 48 frozen test files. The 410 product files are byte-equal. This is not the full stage. Real zero-cost write／ACK recovery windows use a test-only SQLite effect-evidence adapter; other deterministic cases use default components. No PostgreSQL, Docker or model calls. Frozen evidence and original failure records are indexed in `architecture/reviews/2026-10-15-temporal-deployment-public.md`.
