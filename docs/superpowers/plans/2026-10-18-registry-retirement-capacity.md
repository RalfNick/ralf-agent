# Original Registry retirement at Update exhaustion

Scope: existing P3-3 necessary recovery. No new backend, admission allowance,
compaction or execution authority. Basic SDK/dev99/dev113 remain frozen.

The unchanged 435-file installed wheel reproduced a held root after exactly
2,000 accepted/completed Registry Updates: one business write, physical end and
all end ACKs drained, Run quiescent, release Activity returned
`deployment_release_failed`; original retirement wait failed after 38.385s.
Evidence: `/private/tmp/ralf-agent-p3-registry-retirement-probe-20261018-v2/`.
The earlier fixture AttributeError and stopped-service connection failure remain
separate invalid product probes. The actual service used the same existing CLI
with a fresh owned database; it has shut down without touching older databases.

1. Add failing tests for a fixed original Registry retirement observation.
2. Call the complete existing asynchronous `release_deployment_root` handler via
   one bounded Signal/Query observation. Preserve original SDK epoch, full Scope,
   namespace UUID, policy, root/certificate, verifier Activity and post-await commit.
   Pending observations are never evicted; delivery/timeout do not release quota.
3. Integrate only the existing public release Activity. Pin source and Worker
   callable inventory. No generic fallback to Update on errors. Historical
   selected publications use their matching immutable SDK/Worker; the original
   Update handler remains available and saved History must still replay.
4. Run affected tests, original/default compatibility, installed package checks
   and the same genuine Registry-pressure retirement assertions, including Worker
   restart, original receipts, History replay and owned closure. Keep original
   case deadlines and failure evidence.
5. Update current capability evidence; commit locally only. Full P3-3/P3-2 and
   later gates remain open unless their own original requirements are verified.
