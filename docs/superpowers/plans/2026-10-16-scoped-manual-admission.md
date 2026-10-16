# Original scoped manual recovery at capacity

P3-3 only; no new backend or execution authority. Keep P3-2/S2 and old failures.
Use writing-plans/TDD/verification workflows within existing authorized scope.

1. Add RED tests in `test_temporal_scoped_manual_recovery.py`: full normal
   capacity, original submit/Action slot, zero-cost M inventory, same-ID replay,
   different-ID race, epoch change, result conflict, caller proof rejection.
2. Add focused `temporal_scoped_manual_recovery.py`, reusing manual_payload, for scoped prepare/commit
   and exact read-only verifier transported by existing CONTROL Activity. Original
   SDK Start and Tool Scheduled payload bind original accepted request, Scope,
   Action/envelope/epoch. No Started requirement or physical-stop inference.
   Owner still needs original grant; native and old unsafe no-marker unknowns
   gain no allowance. Verify Registry SDK epoch and namespace before/after awaits.
3. Wire original Registry Update and existing SDK fallback only after definitive
   ordinary capacity refusal. Signal cannot transport caller recovery metadata.
   Return immutable epoch binding, including exact repeated controls; send the
   actual Run command to that pinned epoch. Keep normal and legacy contracts.
4. Affected regression and isolated wheel; real Temporal default full4096 manual
   recovery, original duplicate receipt, end debt/Owner distinction, restart and
   History replay. Preserve all failed attempts/time bounds and owned cleanup.
5. Independent review, unique current summary/capacity contract, local commit.

Bound: normal+cancel+drive <=3C, protected manual <=M original verified ordinary
Actions across original accepted Run Histories; no fixed4096/Run assertion.
Activity result is only admission proof; original Run alone adopts effects.

Completed this batch: original scoped admission/epoch binding,57 focused cases,
source/installed each1,233 passing checks and final actual1 passed/129.402s.
Two actual failures, initial RED and intermediate unaccepted builds are retained.
Independent review found no P1/P2. The [acceptance record](../../../architecture/reviews/2026-10-16-temporal-scoped-manual-recovery.md)
limits this to the stated SDK subset; full P3-3/P3-2 remain open. Local commit only.
