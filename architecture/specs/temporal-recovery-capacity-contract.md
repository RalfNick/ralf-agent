# Temporal recovery under command pressure

2026-10-16 · Experimental selected deployment publications 2/3/4 and the
explicitly limited default scoped cancellation below.
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
most `capacity` accepted roots over the Registry lifetime and at most `2 * capacity`
root protection records. Including the Action protection below, total command
records are at most `3 * capacity + M`. The protection
index is similarly bounded. Counts still report actual records; the normal limit
is not silently increased for arbitrary commands. This bounds command identities,
not total Temporal History bytes or Update traffic. Caller backoff and later
retention work remain necessary.

Fresh external SDK descendant controls still require original SDK ancestry
verification and ordinary command capacity, except the verified manual Action
protection below. The original Parent's internal
mechanical delegation is a separate, already authorized path described below.
`approve`, query-based `reconcile`, `send_input`, `patch` and fresh
submissions gain no exemption. Private deployment1 retains its old limits;
default scoped Registries have only the separate allowance below.
In particular, accepting a root cancellation does not
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
without `descendant` or asynchronous `recovery` proof metadata. The Signal invokes the existing synchronous
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

## Original Action manual confirmation

The next selected Worker adds a narrow protected manual `reconcile(query=False)`
reservation for an original unknown ordinary Tool Action, on a root or descendant.
The SDK first uses ordinary admission unchanged. Only a definitive validation
refusal may request the stronger proof path; observation timeout, caller
cancellation and identity/authorization failures never trigger that retry.
Normal-capacity legacy manual evidence, including completed late evidence,
therefore keeps its original behavior.

The original Registry's asynchronous `reserve` verifies its held-bound original
root and saved submission, then invokes its original release Activity. The Activity
verifies original Registry/target SDK epochs, namespace, Scope, manifest and full
descendant ancestry. It reads `deployment_manual_recovery` from the epoch-pinned
original Run. This pure Query requires an unsealed admitted History, an unknown
ordinary Tool Action, original dispatch and a matching **allowed actual Tool
Activity** in `deployment_calls`, with its original attempt ID, full carrier digest,
manifest and epoch. If ToolExecutionOwner is selected, its original grant,
invocation and complete Tool request digest must also match. Default ordinary
Tools do not acquire a new Owner requirement. Native delegated Coding Actions
are excluded from this proof, retaining their existing normal-capacity behavior.

After the Activity, the Registry rechecks root availability, global scoped command
identity and the Action slot before committing. Caller proof objects cannot take
the synchronous Signal/reserve path. Root manual bindings use version2 to pin the
same root/target SDK epoch; descendant bindings remain version1. Only manual
reconcile accepts a root binding. No direct external command bypass is added.

There is one immutable protected manual slot per `(Scope, target, original epoch,
Action ID)`, shared across caller command IDs, attempts and results. The first
verified registration wins; another fresh ID cannot reserve it again. Exact old
receipts remain discoverable before reading the current target, including after
retirement; changed payloads retain their original conflict. Manual payloads are
plain finite JSON with an explicit result and at most1MiB, including their fields.

Let `M` be the number of original ordinary Tool Actions with matching allowed
actual-call records across the original accepted trees. Each Action maps to a
distinct immutable Activity ID in its Run's4096-entry actual-call ledger; retries
do not create Action slots. Original finite child/depth policy and at most
`capacity` accepted roots bound those trees. Thus extra manual records are at
most `M`; zero-cost Tools do not evade this bound. This is not a History-byte or
Update-traffic bound. No business command or actual-call record is evicted.

The Registry receipt is only `not_applied`. The original Run alone adopts manual
evidence and handles races: a real receipt arriving after proof is retained and
late evidence cannot overwrite it; an irreversible seal still rejects new work.
Manual evidence never implies handler stop, effect ACK or root retirement. Their
original independent obligations continue. The current active-Worker probe is
separate from closing-Assembly maintenance, scoped Registry recovery, native
Coding proof and other Update lifecycle gates; full P3-3 stays open. Evidence is
recorded in the [manual recovery review](../reviews/2026-10-16-temporal-manual-recovery.md).

## Default scoped first cancellation

The next default Worker retains normal scoped admission at4096 records. At that
limit, one fresh pure `cancel` reservation per original submitted target may be
accepted. Its payload digest must equal `{scope, kind: "cancel"}`; the target
must appear in an original `submit` record. Same-Scope command identity/conflict
checks still happen first. The first protected ID is immutable; another fresh ID,
changed payload, unregistered target or a different control cannot claim its slot.
No original record is deleted. Additional records are bounded by original submit
targets, at most `capacity`, so total records are at most `2 * capacity`.

This original logical target record is not a deployment held-root proof or a
physical-stop certificate. Registry acceptance remains `not_applied`; the original
Run applies cancellation and retains its existing stopping/effect obligations.
Default scoped `drive`, manual recovery, native Coding and other fresh commands
gain no capacity exemption. Sessions retain their original Update transport and
limits. This does not provide indefinite Run/Registry History availability.

For the seven synchronous Run reservation kinds, the current SDK uses only the
original scoped Registry's `reserve_scoped_command` Signal and matching
`view(kind="scoped_reserve_receipt")` Query. The existing `commands.reserve` is
still the single admission authority. Scope, namespace, original Registry SDK
epoch and complete request digest bind each observation. The64-entry observation
cache never evicts business identities. Delivery is not acceptance; absent or
evicted observations are unknown. The30-second bounded observer may stop without
undoing a reservation; retry uses the original business command ID.

Before any Signal, the SDK may positively identify an old default Worker by its
exact legacy scoped configuration Query response, then use its original Update
contract. Unknown, malformed or foreign responses are refused. There is never an
Update fallback after Signal delivery, timeout or caller cancellation. Old Workers
retain their old capacity and Service Update limits; this compatibility path does
not retrofit the new cancellation allowance. Selected public Workers retain their
separate pinned protocol. Actual capacity, old Worker and History evidence is
recorded in the [scoped cancellation review](../reviews/2026-10-16-temporal-scoped-cancellation.md).

## Compatibility and acceptance

Changed selected source inventories include `temporal.py`,
`temporal_deployment_registry.py` and `temporal_parent_workflow.py`; this increment
also changes `temporal_deployment_execution.py` and
`temporal_coding_composition_control.py`. They identify a
new experimental release even though the publication integer remains 2/3/4.
The synchronous reservation repair additionally changes `temporal_workflow.py`,
`temporal_deployment_submissions.py` and `temporal_deployment_protocol.py`, pinning
the new `temporal_reservation_transport.py` in the public source inventory.
Manual protection additionally pins `temporal_manual_recovery.py`; its SDK,
Registry, Activity and Query changes require the matching new selected Worker.
The scoped increment also pins `temporal_scoped_reservation.py` in selected source
inventories. Default Card/publication equality and saved default History replay
must be checked separately from selected fingerprint compatibility.
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
