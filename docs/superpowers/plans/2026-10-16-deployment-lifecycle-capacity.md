# Original deployment lifecycle capacity repair

> **For agentic workers:** Use the existing authorized native implementation and independent review; do not request another approval or open new scope.

**Goal:** Finish the actual public Tool/evidence-ACK/Owner-close case blocked on the original Run's 2,000 distinct Updates, including original seal/retirement evidence.

**Architecture:** A dedicated public-only `temporal_deployment_lifecycle_transport` carries exactly `deployment_call_started` and `deployment_seal` to complete original Run/Parent handlers. It shares no business authority with the observer and does not classify SDK capacity errors as no-start. Existing four end handlers/transport and every underlying reducer remain unchanged.

**Tech stack:** Existing Temporal SDK, Scope/proof DTOs and original History; no new dependencies or deployments.

**Spec:** `architecture/specs/temporal-recovery-capacity-contract.md`; prior actual failure `architecture/reviews/2026-10-16-temporal-execution-end-capacity.md`.

## Constraints and review focus

- Full Scope, public protocol2/3/4, original SDK first/current/original epoch, namespace, operation, payload digest and bounded observation ID; reject other operations/private/default.
- Fixed begin identity/attempt/invocation and typed allowed ACK; repeated observations must run complete existing exclusive grant/sealed refusal rules.
- Seal still proves original closure/all children and is independently reread/verified by the existing release Activity; no fabricated retirement.
- Cache64 only observations. New call ledger capacity4096 remains, original identities are not evicted, and uncertainty never authorizes fallback or clears Owner obligations.
- Exact legacy status + SDK original identity + second pinned status permits only the old fixed Update ID. Post-Signal uncertainty/cancellation/timeout has no Update fallback.

## Task 1 — original lifecycle observations and consumers

Files: create `src/ralf_agent/temporal_deployment_lifecycle_transport.py`; modify `temporal_workflow.py` (Signal/view), `temporal_deployment_release.py` (begin and seal only), publication/composition callable inventories and their existing independent tests. Create real-handler and client transport tests.

- [x] Reuse the immutable dd543c8 actual public failure as RED; test missing transport and complete original begin/seal handler semantics before production edits.
- [x] Implement `accept(owner,envelope,info)`, `observe(owner,envelope,info)`, `execute(client,run_id,operation,proof,*,execution_epoch,legacy_update_id)` with fixed operations, non-suspending handlers, bounded observations, original pins and typed receipts.
- [x] Preserve callback owner/actual-SDK checks and release verifier's original tree/certificate/post-await checks. Register/pin only the new original-Workflow Signal; selected experimental Histories retain matching immutable Workers.
- [x] Run focused tests including legacy consumers and affected replacement/closure tests; fix actual defects without weakening fault injection.

## Task 2 — actual closure, packaging and evidence

Files: strengthen `tests/test_temporal_execution_end_capacity_service.py` for public effect evidence adoption, Run seal and root retirement; add immutable public legacy Worker compatibility through original callback IDs where needed. Update current summary, matrix, contract/releasing and one batch record.

- [x] Keep 2,000 Updates, once business write, original cancel receipt, all end/ACK/Owner obligations, Worker restart and History replay; preserve every previous failure and all original timeouts.
- [x] Run only the previously failing public scenario early; include original seal/retirement instead of accepting Run quiescence alone. Any remaining lifecycle failure stays open with original evidence.
- [x] Freeze/build an independent wheel, run affected source and isolated installed regressions, default publication/saved History compatibility, actual public pressure and old Worker compatibility. Reuse unaffected accepted evidence only within its original exact range.
- [x] Review, synchronize documents and checksums, then local commit only. P3-2/S2 and other P3-3 native/Session/Registry/History gates stay open; do not unlock P3-4/5/A or claim all R01–R26 complete.

Completion evidence and retained failures: `architecture/reviews/2026-10-16-temporal-deployment-lifecycle-capacity.md`. Only this batch is closed; whole-stage gates remain open.
