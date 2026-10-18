# Original public Action proof after Registry Update exhaustion

2026-10-18 · Existing P3-3 recovery only. Basic SDK/dev99/dev113 remain frozen.
P3-2/S2 stays deferred/open; P3-4/5/A are not unlocked.

## Reproduced blocker

The immutable 436-file `6af901f` wheel, SHA256
`7a2dc32ab734956b5998bb9cb48d36e575fd60025e6aee9f605560d36cc06cd6`,
failed the actual public manual proof case: **1 failed / 124.292s**. The original
Registry held 4,096 logical command identities and exactly 2,000 accepted/completed
SDK Updates. Repeating an existing drive reservation filled only the SDK Update
counter; it did not create new logical identities or business effects.

After ordinary capacity refusal, the SDK's existing strong-manual branch submitted
a fresh `reserve` Update. Temporal refused it with the cumulative distinct-Update
limit. The original business write occurred once and its handler was still live
before manual recovery. Owned History cleanup and service shutdown completed;
cleanup termination is not proof of recovery or quota retirement.

RED evidence: `/private/tmp/ralf-agent-p3-public-manual-probe-20261018/` and
`/private/tmp/ralf-agent-p3-public-manual-service-red-20261018/`. The existing
Temporal CLI ran against a fresh owned database with original service defaults,
without time skipping, Docker, PG, models or changes to old databases.

## Minimal repair

Only the existing public strong-manual branch, entered after definitive ordinary
capacity refusal, uses `temporal_public_manual_transport`. Its fixed
`reserve_public_manual` Signal calls the **complete asynchronous Registry.reserve**
handler. Original preparation, SDK `manual_control` verification, post-await
Registry epoch/capacity checks and the original Action slot commit remain intact.
The SDK retains its final `_recheck` and complete `_control_result` validation.

Scope, namespace name/UUID, policy, original standalone Registry epoch, target/root
and exact manual payload digest bind the observation. Handle/query/signal/describe
ports are pinned. The cache has 64 entries and a 2 MiB envelope limit; pending
proofs cannot be evicted. Observer cancellation, the 30-second wait, lost replies,
cache saturation or malformed receipts never authorize an Update fallback. The
original verifier remains independent of the observer's cancellation.

Ordinary admission and fresh descendant controls are unchanged. No new Action,
grant, capacity exemption, protocol family or execution authority is introduced.
Public source and Worker callable inventories pin the module and Signal. The
original Update handler remains; historical selected publications require their
matching immutable SDK/Worker. Default compatibility is verified separately.

## Boundary and installed evidence

The initial 15 boundary tests failed because the new module was absent, then
passed after implementation. A first integration batch had **91 passed / 2 failed**:
the old fake RecoveryHandle lacked the original SDK `run_id` and observation API.
The doubles were updated without weakening production identity checks. Final
targeted integration: **118 passed / 3.160s**. Original failure records remain.

Source 127-module affected regression: **2,429 passed / 6 skipped / 89.645s**,
zero failures/errors. The six optional/configuration-dependent cases are not
accepted. The isolated wheel runs the same 127 modules outside the checkout:
**2,429 passed / 6 skipped / 90.712s**, zero failures/errors. All 437 product and
911 test inputs remain fixed; source, wheel and installed product bytes agree.
Default Card and ordinary Temporal publication equal the frozen basic SDK;
original and continued saved default Histories replay successfully.

Independent read-only review found no actionable P1/P2. It checked the full
handler boundary, normal admission, proof identities, pending cache, cancellation,
protocol pins and unchanged service acceptance assertions; it did not run services.

Candidate: `dist/p3-public-manual-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`,
SHA256 `6dad78871e44f579109838e45a6f8b7cc98ebc1938cc80570532e0a108748e23`.
Evidence prefix `/private/tmp/ralf-agent-p3-public-manual`:
`-source-20261018/`, `-install-20261018/` and `-live-20261018/`.

## Actual service acceptance

The same installed wheel passed the actual combined-capacity case:
**1 passed / 127.745s**, zero failures/errors/skips. Exactly 4,096 logical
identities and 2,000 accepted/completed SDK Updates were present before the first
manual proof. One genuine business write occurred while its handler was still
live. The original receipt applied; a different command for the same Action was
refused. Manual proof did not release quota while the thread was live. After
physical exit, the blocked effect ACK still prevented sealing/retirement. Only
after the original ACK succeeded did held roots reach zero.

Restarting the Worker returned the same original manual receipt, with one business
write, zero held roots and still exactly 2,000 accepted Registry Updates. The
History contains the new manual Signal; root and Registry Histories replayed.
Two owned Workers shut down and the owned root/Registry Histories were closed.
The fresh service stopped successfully; it used the same CLI hash as RED and
left old databases untouched. Original 180-second case, 170-second held thread and
5-second Activity limits were preserved. Only this public original-Action manual
capacity subgate closes; cleanup termination is not used as retirement evidence.

`verification.json` and `SHA256SUMS` freeze the exact artifact and evidence summary.
All seventeen earlier artifact checksum sets remain valid. Source/install/live
inputs stayed fixed through acceptance. Historical selected-Worker compatibility
and fresh PG/HTTP/model validation are not inferred from this case.

This batch cannot close full P3-3, P3-2/S2 or later gates. Selected native Coding
pressure remains a distinct evidence gap. No general model quality, new PG/HTTP
service validation, arbitrary History scale or indefinite operation is claimed.
Local commit only; no push or public release.
