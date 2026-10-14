# Temporal deployment dispatch implementation plan

**Goal:** Connect original Registry admission to real Run/Parent SDK execution and inherited child authority, keeping full release/public acceptance gates open.

**Spec:** `architecture/specs/temporal-deployment-dispatch-contract.md`.

**Architecture:** Pure original-History metadata/adoption and SDK proof transport are separate. A fixed selected Worker guards every Activity; original Parent intents authorize descendants. No new scheduler, business authority or quota release.

**Execution:** Continuous parallel work authorized by user, disjoint ownership; root integration and local commit only. Use TDD and risk-scoped affected checks, frozen evidence reuse; no remote push or model credentials.

## Ownership and checks

1. State worker owns `temporal_deployment_execution_state.py`, `temporal_deployment_protocol.py` and their tests. Exact interfaces/schema in spec. RED strict metadata/path/pins/response tests, then implement; verify unchanged caller requests and source publication.
2. Transport worker owns `temporal_deployment_execution.py` and transport tests. RED SDK identity, namespace/epoch/parent/child/refusal tests, then implement admission, universal Activity wrapper and original child controls. No public Engine exemptions.
3. Service worker owns deployment-dispatch service test/fixture only. Coordinate actual source and installed Service with root; preserve unique SDK IDs, root occupancy, original History, Worker/fixture cleanup. Do not call models or change production.
4. Root owns Runtime, Manifest validation, worker registration, Run/Parent loops, Parent child-record metadata, query/Update and explicit Engine preflight. Test each new boundary before implementation; no alteration to default request identity or payloads.

## Delivery checklist

- [x] Freeze protocol and shared interfaces; independent architecture review.
- [x] Pure state, publication and SDK transport RED→GREEN.
- [x] Run/Parent gate, universal wrapper, original child projection/control and preflight integrated.
- [x] Independent code review; necessary fixes reproduced and verified, including original Parent intent recording/rollback and preservation of managed Activity request digests.
- [x] Actual source Service: 17 cases covering selected Agent/sequence/graph/Team/Dynamic/nested dispatch, approval/cancellation/restart, original ancestry/one root claim and History replay; owned fixture cleanup is part of the evidence.
- [x] Frozen source affected checks: 814 passed; default compatibility and fixed selected Worker/source gates included. This is an affected batch, not a new full-suite or model-quality claim.
- [x] Independent installed affected/Service repetition passed (814 + 17), default old History continued without new Provider calls; final wheel/sdist provenance recorded in `architecture/reviews/2026-10-14-temporal-deployment-dispatch.md`.
- [x] Synchronize capability/support documents with the worker-only scope and mandatory remaining gates.
- [x] Final acceptance evidence and local-only delivery prepared for the authorized commit; no push.

## Still required after this dependency

- [ ] Public SDK/Profile assembly and original uncertain-start/duplicate receipt recovery.
- [ ] Coding physical-stop/close transport and Session-coordinator root admission, retaining original authorities.
- [ ] Original tree/zero-cost/unknown/auxiliary/actual-handler closure and idempotent safe release.
- [ ] Full phase-three batch-2 selected-matrix acceptance; then hosted observation/control and subsequent governance batches.
