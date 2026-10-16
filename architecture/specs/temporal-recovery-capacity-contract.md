# Public Temporal root recovery under command pressure

2026-10-16 · Experimental selected deployment publications 2/3/4.
This is one part of P3-3, not completion of its full capacity requirement.

## Authority and bounded allowance

The original deployment Registry retains scoped command identity and immutable
receipts. Run/Parent Histories retain all business state, effects, stop obligations
and quota settlement. No new external control bypasses the Registry or creates a
new authority; the original verified internal delegation remains in place.

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

Fresh external SDK descendant controls still require original SDK ancestry
verification and ordinary command capacity. The original Parent's internal
mechanical delegation is a separate, already authorized path described below.
`approve`, `reconcile`, `send_input`, `patch` and fresh
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

## Original Parent mechanical delegation

The original Parent's control Activity already verifies its original request,
Scope, source, namespace, held root, child intent, SDK ancestry and execution
epochs before controlling that child. The Coding bridge similarly verifies its
original child before invoking its internal command transport. Neither path
reserves a fresh external descendant command in the global Registry. There is no
new descendant protection map, caller authorization or authority in this increment.

For public selected releases, ordinary delegation keeps its original logical
command ID (parent ID/epoch, child ID/epoch, kind). The Coding transport now uses
owner ID, child ID/original epoch and kind; a mutable child revision is not a
business command identity. Each sends a fresh SDK Update, so a repeated drive
reaches the original Workflow handler while retaining the first command receipt.
Fixed SDK Update IDs would return a cached result without another handler wake.
Original stop intent and cancellation remain effective; drive does not reopen
business. Private/unselected branches retain their previous command-ID and SDK
Update-ID behavior, but their Coding release fingerprints can still change as
explained below.

Bounded logical command records do **not** bound SDK Updates or History events.
An actual production-capacity probe on 2026-10-16 hit the existing Service's
2,000-distinct-Update limit in the original Registry before its 4,096 ordinary
command allowance. Root protection therefore does not yet guarantee that a new
necessary control can reach a real exhausted History. The probe remains failed;
no service limit, command allowance or acceptance deadline was relaxed.

Repeated-wake evidence is separate: a genuine ordinary public child received
three fresh SDK Updates through the internal helper and recorded one logical
command. It does not prove native Coding execution, outer Activity authorization
or full-capacity tree recovery. See the [increment record](../reviews/2026-10-16-temporal-delegated-recovery.md).

Required next evidence must cover transport lifecycle as well as record capacity.
New business commands may receive safe backpressure. A first manual reconciliation
of an existing unqueryable unknown Action can be its only recovery route, so
refusing it forever cannot close the necessary-recovery requirement. Default
scoped Registries and the selected complete service chain remain unaccepted.
No alternate transport or Continue-as-New lifecycle is delivered by this change.

## Synchronous reservation transport repair

The next selected Worker provides `reserve_command` as a narrow original Registry
Signal, with `view(kind="deployment_reserve_receipt")` observation. It supports
only public2/3/4 `submit/approve/cancel/reconcile/drive/send_input/patch` reservations
without `descendant`. The Signal invokes the existing synchronous
`commands.reserve`; that method still owns all acceptance, identity, conflict,
capacity and root checks. Session `session_*` reservations, descendant Activity
verification and other Updates retain their original paths. This is no general
command transport and does not change ordinary command capacity.

Each SDK attempt carries a fresh bounded `observation_id`, the exact original
request and its Scope. Both Query and Signal verify original Registry epoch,
public selection, Scope, policy and namespace. An observation is bound to its
whole request digest; a live same-Scope observation ID with changed content cannot
replace its result. The SDK requires an exact version/id/digest/result response
before sending a Signal. Old or mismatched Workers are refused before delivery;
there is no automatic Update fallback after an unknown outcome.

Only 64 transport observations are retained, with deterministic oldest eviction.
They hold this attempt's original reserve result or refusal, not new business
state. Original commands/submissions/receipts are never evicted. Cache absence
means unprocessed or evicted and therefore **unknown**, never unaccepted. Signal
ACK is delivery only. The SDK queries the matching result with bounded backoff
and a 30-second observation timeout; caller cancellation or timeout does not undo
acceptance or release a root. A later attempt uses a fresh observation and the
same business command ID; the original state decides duplicate/conflict. A prior
refusal is not a permanent cached rejection of future business retries.

Malformed or unsupported Signals create no observation and cannot throw out of
the handler to poison the Workflow. Authorized original reserve refusals are
reported by the matching observation, without disabling later valid commands.
The 2-MiB transport envelope bound leaves room for the original 1-MiB submission
envelope; business limits remain in their original validation.

Signals still consume History events and can hit service lifecycle limits. This
repair does not prove every Registry/Run Update remains available indefinitely,
does not provide Continue-as-New, and does not close the required manual,
descendant, scoped or complete P3-3 service coverage. The raw Update2000 failure
and the first Signal4096/180 failure remain separate immutable evidence. Current
acceptance is recorded in the [reservation review](../reviews/2026-10-16-temporal-reservation-transport.md).

## Compatibility and acceptance

Changed selected source inventories include `temporal.py`,
`temporal_deployment_registry.py` and `temporal_parent_workflow.py`; this increment
also changes `temporal_deployment_execution.py` and
`temporal_coding_composition_control.py`. They identify a
new experimental release even though the publication integer remains 2/3/4.
The synchronous reservation repair additionally changes `temporal_workflow.py`,
`temporal_deployment_submissions.py` and `temporal_deployment_protocol.py`, pinning
the new `temporal_reservation_transport.py` in the public source inventory.
Keep the exact package/release/Worker required by an old selected History.
Do not replace its immutable Worker, reset its Registry or claim these protection
semantics for an old Registry merely because its configuration integer matches.
New independent deployment identities do not resume an old task or clear its
obligations. Default publication and saved default History checks are distinct
from selected historical compatibility. The internal Coding command helper is
also fingerprinted by experimental Coding compositions outside public deployment
selection. Keeping their legacy branch behavior does not mean those complete
release fingerprints remain equal; they also need their matching immutable Worker.

Required evidence for this increment: capacity-1 root protection in Registry2/3/4,
conflict/scope/payload/refusal immutability, bounded repeated IDs, original
cancellation receipt discovery, no fresh protection after retirement, old-ID
collision preservation, repeated actual Workflow handler wake with one command
record, and Parent cancelling/seal guards. Actual service/History and complete
P3-3 acceptance must be recorded separately. Root-only pure/transport tests cannot
close descendant, manual-control or scoped-Registry capacity requirements.
