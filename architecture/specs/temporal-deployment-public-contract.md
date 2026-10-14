# Temporal public deployment admission and safe retirement

The required outcome is a usable ordinary Temporal deployment: public SDK/Profile assembly, original first-acceptance recovery, and safe root-capacity turnover. This follows dev118's internal SDK gate. Coding physical ownership and SDK Session-coordinator Turns remain required phase-three batch-2 integration; they stay explicitly refused in this dependency, not removed from the support matrix. No full-stage completion is inferred.

## Authority and compatibility

Registry owns immutable command/root acceptance and retirement. Original Run/Parent History owns execution, actual-call obligations and irreversible closure seals. SDK Activities mechanically verify original namespace UUID, epochs, parent relationships and held claims; no new scheduler or EffectJournal authority. Default manifests/requests remain unchanged. Existing private worker-only deployment publication stays version 1; public policy selects version 2 with fixed source inventory including release/state/transport/submission and actual owner implementation. Public Engine rejects version 1. Old selected publications require their matching immutable Worker; no implicit upgrades.

Registry initialization selects admission protocol 1 or 2. Its stable address does not change with version or policy. Public v2 must positively check the actual Registry configuration; an existing v1 Registry is never replaced, filled from current configuration, or silently adopted. A new deployment identity is required until an explicit migration proves its original obligations. Registry History retains all active and retired commands, bounded by the existing command-record limit.

## First acceptance and public submission

Reuse `DeploymentAdmissionPolicy`, `ComponentRegistry`'s synchronous/asynchronous `admission_policy` factories, `bounded` validation and exact DTO output contract. Public Runtime accepts `admission_policy`; conflicting private/public options reject before component inspection. Builder host and Profile selection cannot coexist. Selected Coding configuration rejects before owned construction; SDK Session-coordinator metadata remains refused. Assembly forwards its fixed policy and owns actual calls/submissions through close; borrowed SDK clients remain caller-owned.

The public submission transport lives in `temporal_deployment_submissions.py`, without its own persistence. It freezes the ordinary logical request using `submission_request` and `normalize_request(..., None)` before current-release checks, then converts that detached selected request with `json.loads(canonical(...))` to the SDK JSON representation. Tuple arrays (including `AgentSpec.tools` and nested input arrays) become lists before direct comparison with original History envelopes; the canonical request digest is unchanged, caller values are not mutated, and global/default codecs and default request bytes remain unchanged. Scope/command/request digest and original namespace UUID identify lookup. New submissions alone validate current schemas, bindings, release and context scope.

Protocol-2 root reservation adds `root_admission.submission`:

```python
{
    "version": 1,
    "request": original_logical_request,
    "manifest": original_full_manifest,
    "activity_timeout": original_activity_timeout,
    "task_queue": original_task_queue,
}
```

`root_admission` has exact `{version: 2, manifest_digest, submission}`. Validate request/manifest digests, supported public protocol/policy, finite positive timeout, nonempty queue, original request shape and bounded canonical envelope (maximum 1 MiB). The complete envelope and root claim commit atomically in the original Registry Update. A racing duplicate returns the first envelope, never its new manifest/queue/timeout. Original request identity remains separate from release choice.

Registry APIs (state methods and Workflow Update/query names):

- `deployment_configuration`: exact scoped policy/namespace query returning `{version: 2, registry_id, policy, namespace}`; version 1 is reported honestly and refused by public callers.
- `deployment_submission`: exact `{kind, scope, command_id, payload_digest, admission_policy, namespace}` query, returning `None` or detached `{reservation, submission, run_receipt, execution_epoch}`. Conflicting command content refuses. The result is scope-bound.
- Protocol-2 `reserve` returns the original reservation receipt plus the original `submission`; root metadata itself retains the existing exact schema. Its `apply_state=not_applied` never masquerades as a business Run receipt.
- `record_deployment_submission`: exact `{scope, admission_policy, namespace, command_id, run_id, request_digest, manifest_digest, proof_digest, execution_epoch, receipt}`; validate fixed original root and exact business submit receipt. Pin the immutable SDK epoch and business receipt; replay returns the same record. A retired root duplicate remains recoverable without a business Worker poller.

Submission lookup precedes release-dependent validation in Engine and higher client facade. Existing `run_receipt` returns its original RunHandle. Otherwise use the recorded envelope to query/start the original derived ID and queue with `REJECT_DUPLICATE`, conflict `FAIL`, no Workflow retry, then verify actual SDK namespace/first/current epoch, original manifest/request/metadata and submission receipt before recording it. Timeout, lost reserve/start response, cancellation and Worker absence retain the original claim; they never choose another ID, release quota, replace epochs or reconstruct fields from a moved alias. Deployment controls use the same Registry and Scope; include Dynamic `patch` in v2, retain v1 behavior.

## Actual-call ownership and closure

Pure `temporal_deployment_release_state.py` is conditional on public protocol v2. `initialize(state)` installs persistent call records and seal/retirement evidence. Existing deployment proof view stays byte-compatible; add separate `deployment_closure` query. Functions: `begin_activity(state, payload)`, `end_activity(state, payload)`, `closure(state)`, `view(state)`, `seal(state, payload)`, `check_unsealed(state)`. Closure view is `{version:1, deployment: deployment_state.view(state), ready: bool, reasons: list[str], calls: dict, seal: None | certificate}`. Seal payload is exact `{scope, children}`; the function validates own persistent obligations and exact direct child pins. Certificate fields are `version, scope, run_id, command_id, namespace, execution_epoch, original_execution_epoch, request_digest, manifest_digest, admission_digest, receipt_digest, terminal_state, closure_digest, children, proof_digest`. Direct child seal entries are exact `call_id, run_id, command_id, execution_epoch, request_digest, admission_digest, seal_digest`; settled proven-undispatched children use `execution_epoch=None, seal_digest=None`. Never treat an uncertain dispatched child as undispatched.

Call identity is exact:

```python
{
    "version": 1, "scope": original_scope,
    "run_id": original_run_id, "execution_epoch": original_epoch,
    "activity_id": actual_sdk_activity_id,
    "activity_name": registered_sdk_activity_name,
    "attempt": actual_positive_attempt,
    "invocation_id": unique_actual_owner_id,
    "request_digest": digest(original_carrier),
    "manifest_digest": digest(original_manifest),
}
```

The original History records begin before business I/O. Exact Update retry is idempotent; conflicting original activity/attempt owner refuses. Another invocation must not execute the same granted call. `end_activity` accepts the exact recorded identity only and marks it stopped, without adopting business effects, verdicts or budget evidence. Bounded ledger capacity refuses new dispatch safely.

`temporal_deployment_release.py` wraps protocol-2 registered business Activities after original deployment validation. Use the Runtime's exact fixed `ContextExecutionOwner`; its actual async operation, registered delegated threads and foreign futures remain owned. `on_end` calls original epoch-pinned `deployment_call_ended`; it returns completed None only after the durable ACK. ACK failure remains an owned retry obligation. Caller/SDK cancellation or body response alone cannot produce stop evidence. No-start owner refusal may retire only the exact newly recorded call when `handler_not_started=True`; ambiguous refusal stays held. Assembly close drains this owner before resource teardown. Whole-loop cancellation never claims ended work.

Closure requires terminal business state, original admitted metadata and bound root, every reservation status settled including amount zero, all actual-call records stopped, no original action/ACK/deferred ACK/reconciliation or uncertain remote work, no unfinished context/Session/tool/auxiliary stages, and every child settled with immutable original execution epoch and seal. Existing quiescent/credit sums alone are insufficient. Cancelled validation proposals that are undispatched can be retired according to their original stage evidence; no late result is adopted to force completion.

The separate closure view provides detached original deployment proof, terminal/obligation summary, recorded calls and `seal` (initially None). A seal is irreversible: exact original identity, obligation digest, terminal state and child seals are fixed. All mutable dispatch/selection/child pin and new control paths refuse after seal; original recorded duplicate controls and read-only submission/status/events remain usable. Sealing does not adopt results or stop physical processes.

## Bottom-up release transport

A fixed registered `RELEASE_ACTIVITY = "ralf.temporal.deployment-release.v2"` performs original SDK proof checks and bottom-up closure in `temporal_deployment_release.py`. It has its own exact marker; only this function and original admission Activity avoid business call-ledger registration. Mechanical owner wrapping remains outermost. It performs no tool/model/data I/O.

Verify root and every original descendant against epoch-pinned SDK description, original parent child intent, metadata and namespace. Query closure, require all obligations stopped, and seal descendants before their parent. Never trust a caller-provided child certificate without reading the original child History. Undispatched settled child intents require original no-start evidence; uncertain starts retain quota. Recheck identities after awaits. Seal races against new dispatch are resolved in the original History Update: dispatch before seal leaves a live obligation; seal before dispatch refuses it.

`release_deployment_root` is an idempotent original Registry Update taking the original bind identity plus the sealed root certificate. Its SDK-owned handler validates the original reservation, then schedules the fixed RELEASE_ACTIVITY in verification mode on the first recorded business task queue. That Activity verifies actual Registry SDK identity/namespace and reads the original root/tree seals directly; a caller-supplied hash or closed boolean never authorizes retirement. The Registry adopts the validated Activity result, rechecks its original claim and certificate after await, and atomically retires occupancy. Preserve the retired record and original command/receipt; only remove it from active-root counting. Concurrent/lost responses return the same original retirement, never a second decrement. A lost release response retries the same original certificate; changed certificates refuse. No TTL, force eviction, negative daemon inference or budget-only release.

Original Run/Parent loop attempts this transport after terminal closure and on original wake/recovery. The transport entry points are `execute(runtime, client, value, info)`, `registered_activity(runtime, client)`, `wrap_activity(runtime, client, function)`, `check_owner(runtime)` and `async close_owner(runtime, *, wait_timeout=30)`. The root mode value is `{mode:"release", scope, run_id, execution_epoch}`; Registry verification mode is `{mode:"verify", scope, root, certificate, manifest, registry_execution_epoch}` and returns `{root, certificate}` only after original SDK/tree verification. The pure state entry `closure(state)` returns `(ready, reasons)`; `seal(state, {scope, children})` returns the immutable certificate. A failed release emits sanitized diagnostics and retains the claim; no business retries. Admission and call-end Updates wake original progression. Expose read-only Engine deployment diagnostics. Registry/API close never cancels or releases accepted business merely because an observer disconnects.

A sealed root can remain held after repeated retirement RPC failure while its original History waits without further events. Public `Engine.drive(run_id)` must recover through that original History: verify Scope, actual namespace UUID, original Registry v2 policy and full accepted envelope, recorded SDK epoch, original closure and certificate. An existing matching Registry retirement returns by reads alone. Otherwise issue a fresh root-only SDK `deployment_seal` Update with the exact original `{scope, children}` payload and a new mechanical SDK Update ID; require its returned certificate to remain equal and recheck identity after awaits. An old Update ID could replay a reply without executing the wake. The seal handler wakes original retirement; it does not reopen business, relax irreversible guards, add a business command or release Registry directly. Alias changes retain the original envelope. `recover_retirement` is an internal transport helper, not a public API. A returned terminal snapshot is separate from confirmed quota retirement.

Parent cancellation receipts may report `remote_stop_confirmed=False` until original descendants actually stop; callers must inspect current original diagnostics rather than infer closure from receipt acceptance. Completed-Action deferred effect acknowledgements resume through original `drive` once the journal route recovers. `reconcile(query=True)` queries uncertain effect evidence; it is not an acknowledgement retry or another business attempt.

## Required evidence

RED→GREEN state tests: malformed envelope, racing aliases/queues, missing original acceptance, scope and namespace mismatch, capacity turnover and retired duplicates; zero-value reserved/unknown entries, live/failed-end calls, pending ACK/reconciliation/stages, child epoch/seal mismatch, seal/dispatch races, irreversible guard and duplicate receipts.

Transport tests execute real wrapped handlers: SDK uncertainty after actual reserve/start acceptance; original epoch pin and changed config recovery; actual ContextExecutionOwner cancellation plus tracked sync thread; failed durable end ACK retaining ownership; forged release marker/certificate and SDK descendant mismatch. No optional SDK import required for pure state tests.

Actual source and independently installed Temporal service: public SDK/Profile/JSON/TOML and factory replacement; selected Agent/sequence/graph/Team/dynamic/nested subtree turnover; approval restart; dropped reserve/start response followed by changed queue/alias retry; cancellation with live async Provider and committed zero-cost sync write; real manual effect evidence before handler end cannot release; end/ACK then exactly-one next-root acceptance; release response loss and retired duplicate without original business poller; Registry/Worker restart and History replay. Freeze source/wheel/installed identity; verify ordinary default manifests and old original History. Separate source, installation, service, model and full-stage evidence; local commit only.

## dev119 acceptance boundary

The frozen bounded ordinary subset has source and independent-install evidence recorded in [the acceptance review](../reviews/2026-10-15-temporal-deployment-public.md): each passes 953 checks from 46 affected modules, 27 public v2 and 17 private v1 actual Service cases, with zero failures, errors or skips; default dev118 publication and original History compatibility pass. These are affected checks, not a full-stage regression. Real zero-cost write／ACK recovery windows use a test-only SQLite effect-evidence adapter; other deterministic cases use default components; this batch makes no PostgreSQL, Docker or model calls. The selected phase-three Temporal＋PG Service gate, Coding physical close and SDK Session-coordinator admission remain required separate work. Batch 2 and full R01–R26 stay open; delivered with a local commit, no push.
