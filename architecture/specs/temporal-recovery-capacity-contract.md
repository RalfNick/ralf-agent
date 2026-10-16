# Public Temporal root recovery under command pressure

2026-10-16 · Experimental selected deployment publications 2/3/4.
This is one part of P3-3, not completion of its full capacity requirement.

## Authority and bounded allowance

The original deployment Registry retains scoped command identity and immutable
receipts. Run/Parent Histories retain all business state, effects, stop obligations
and quota settlement. No control bypasses the Registry or creates a new authority.

Normal cumulative command capacity remains unchanged. When that capacity is full,
a fresh control of an original **held-bound root** may use one additional `cancel`
record and one additional `drive` record. Both require the exact digest of
`{scope, kind}` with no business arguments. The first cancellation retains the
caller's command ID. The mechanical drive uses the original Registry's chosen ID.
A different fresh ID cannot consume the same slot again. Exact duplicates and
identity conflicts are checked before capacity and current root availability.
Original records are never deleted, overwritten or made reusable after retirement.

Each accepted root first consumed a normal command record. Thus there can be at
most `capacity` accepted roots over the Registry lifetime, at most `2 * capacity`
protection records, and at most `3 * capacity` total command records. The protection
index is similarly bounded. Counts still report actual records; the normal limit
is not silently increased for arbitrary commands. This bounds command identities,
not total Temporal History bytes or Update traffic. Caller backoff and later
retention work remain necessary.

Fresh descendant controls still require original SDK ancestry verification and
ordinary command capacity. `approve`, `reconcile`, `send_input`, `patch` and fresh
submissions gain no exemption. Private deployment1 and unselected scoped Registries
retain their old limits. In particular, accepting a root cancellation does not
prove that a descendant cancellation succeeded, an external handler stopped or an
unknown effect was reconciled. All existing evidence and resource obligations
continue to apply.

## Repeatable mechanical wake and old command collisions

A public SDK `drive` first tries `drive:` plus `digest([scope, run_id])`. It reuses
that command identity while sending a **fresh SDK Update** each time. The original
Run handler still wakes and requests existing recovery; the receipt remains the
first receipt. Parent duplicate drives also re-enable existing session/memory
recovery and fresh child observation, only for public, unsealed Histories. They
retain cancelling/stop intent and do not reopen business. Sealed retirement uses
its existing independent recovery path. Default/unselected drive still uses its
original fresh UUID identity.

An older legal command may occupy the derived ID with different content. That
conflict must remain a conflict. The Registry searches at most `N+1` deterministic
candidates against its `N` existing command keys; it chooses either a free ID or an
already matching original drive identity. After a protected drive is recorded,
its identity remains fixed. No existing command is replaced.

`deployment_diagnostics()` optionally includes:

- `recovery_controls`: this Scope's recorded protection controls, each with
  `run_id`, `execution_epoch`, `kind`, `command_id`. Use the original cancellation
  identity after a lost response; its receipt is still retrieved from the authority.
- `recovery_drive_hints`: only colliding root cases, each with `run_id`,
  `execution_epoch`, `command_id`, `durable:false`. Querying writes nothing. These
  are suggestions, not reservations, permissions or accepted command receipts.

Only after a real `IdempotencyConflict`, the SDK may read the original diagnostics
and retry its drive once with the matching root suggestion. Every original guard,
Scope, target, epoch and admission check still applies. A concurrent reservation
can invalidate a suggestion; registration then refuses safely and a later call
can read a fresh suggestion. No unbounded retry is added. A descendant or old
Registry without a matching hint keeps its original refusal.

## Compatibility and acceptance

Changed selected source inventories include `temporal.py`,
`temporal_deployment_registry.py` and `temporal_parent_workflow.py`; they identify a
new experimental release even though the publication integer remains 2/3/4.
Keep the exact package/release/Worker required by an old selected History.
Do not replace its immutable Worker, reset its Registry or claim these protection
semantics for an old Registry merely because its configuration integer matches.
New independent deployment identities do not resume an old task or clear its
obligations. Default publication and saved default History checks are distinct
from selected historical compatibility.

Required evidence for this increment: capacity-1 root protection in Registry2/3/4,
conflict/scope/payload/refusal immutability, bounded repeated IDs, original
cancellation receipt discovery, no fresh protection after retirement, old-ID
collision preservation, repeated actual Workflow handler wake with one command
record, and Parent cancelling/seal guards. Actual service/History and complete
P3-3 acceptance must be recorded separately. Root-only pure/transport tests cannot
close descendant, manual-control or scoped-Registry capacity requirements.
