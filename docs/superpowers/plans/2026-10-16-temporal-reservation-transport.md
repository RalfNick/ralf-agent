# Public reservation transport repair

> **For agentic workers:** execute the authorized frozen P3-3 repair natively, with TDD and affected verification. Do not broaden the deployment matrix.

**Goal:** public Registry2/3/4 synchronous reservations can reach the original authority without consuming a distinct SDK Update for every reservation.

**Architecture:** a narrow original-Registry Signal calls existing `commands.reserve`; an existing `view` Query confirms this attempt's result. A bounded 64-entry observation cache is transport evidence only: eviction never removes business identities, and retries retain the original command. No descendant bypass, new authority or general command bus.

**Spec:** `architecture/specs/temporal-recovery-capacity-contract.md`; preserve all original gates and raw-Update service failures.

## Tasks

- [x] Write failing tests using original Workflow/state for duplicate/lost response, conflicts, wrong Scope/namespace/epoch, bounded eviction, retry after refusal and no false acceptance from Signal ACK. Add SDK transport tests and run RED.
- [x] Add `temporal_reservation_transport.py` with bounded validation/cache and SDK Signal/Query exchange. Register only selected synchronous reserve Signal/view handlers in `temporal_workflow.py`; pin the module in the public inventory. Wire only the seven supported no-descendant public kinds; keep Session/legacy/descendant Update behavior.
- [x] Run affected Registry/submission/control/Workflow/Session checks. The Session misrouting regression was caught and fixed; source/installed 34 modules each806 passed.
- [x] Reuse production4096/tree/held-provider/stop/retirement/cleanup assertions. Final installed concurrency48 case passed in126.286s. Preserve raw Update transport failure, all three subsequent failures and the120/180 deadlines; shared refusal assertion now checks stable SDK code and unchanged authority facts instead of noncontractual server wording.
- [x] Build separate wheel; installed806, default declaration/saved History compatibility and actual capacity/cleanup verified. Summary, review and contract synchronized for local commit only. No full P3-3 closure.

## Review focus

Signal delivery is not acceptance; Query must match observation/request/Scope. No receipt is invented on timeout/eviction. Malformed or unauthorized Signal cannot poison Workflow execution. Original epoch and immutable Worker requirement stay fixed. A retry after a prior refusal uses a fresh observation so the refusal does not become permanent business identity. Other Update lifecycle paths and full P3-3 stay open.
