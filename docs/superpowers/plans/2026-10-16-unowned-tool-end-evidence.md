# Preserve each original unowned Tool handler's end obligation

P3-3 safety prerequisite found while auditing scoped manual admission. Reproduced:
unknown Tool A -> operator/query effect confirmation -> Tool B success clears A's
remote uncertainty, although A's handler has no end proof. A parent can settle early.
Do not expand scoped manual admission while this default path is unsafe.

- [x] RED genuine Run state, zero-cost Tools, operator/query and parent stop facts.
- [x] Minimal per-Action unconfirmed-end fact; only original actual result clears
  its own fact, independent of effect adoption/ACK and other Tool results.
- [x] Original Temporal patch gates new runs; preserve no-marker legacy replay and
  existing Owner/native contracts. No new execution authority or backend.
- [x] Affected source/isolated installation, stable defaults/saved History checks.
- [x] Actual owned-process thread timeout, manual confirmation, other Tool result,
  parent retention, Worker restart and replay; immutable old Worker risk baseline.
- [x] Independent review, truthful limitations/capability docs and local commit.

Legacy unsafe behavior is evidence, never a passed safety gate. The default
no-Owner path conservatively retains unknown without an original end receipt;
physical exit observed externally is not forged into a Workflow callback.
Scoped manual capacity and remaining Update/History lifecycle gates remain open.

Verification: source/isolated install each1,176 passed; actual same-wheel2 passed
(current protected scenario plus explicit old risk baseline), original2 failed
observer run retained. Local commit records this batch; no remote push. See
[acceptance](../../../architecture/reviews/2026-10-16-temporal-unowned-tool-end.md).
