# Original Registry retirement after Update exhaustion

2026-10-18 · Existing P3-3 necessary recovery only. Basic SDK/dev99/dev113 remain
frozen. P3-2/S2 is deferred/open; P3-4/5/A are not unlocked.

## Reproduced blocker

The immutable 435-file `0fedebe` wheel (SHA256
`e71780943d331351aa47192aca83d4278a55ab027b103ba8141c3da564040a67`)
failed the original public2 retirement assertions: **1 failed / 38.385s**.
Exactly 2,000 SDK Updates were accepted/completed by the original Registry,
repeating one logical control. The genuine write happened once, the thread ended,
end ACKs drained and the Run became quiescent. Original release Activities returned
`deployment_release_failed`, while the retirement wait expired. The release
Activity still submitted a fresh Update to that exhausted Registry. Owned History
cleanup passed; cleanup termination is not proof of quota retirement.

Earlier invalid probes remain: a nonexistent fixture property (33.818s) and the
stopped original service's connection refusal (2.512s). Neither proves a product
failure. The valid reproduction used the same already-downloaded Temporal CLI,
original defaults and a fresh owned database. It shut down without touching old
databases, starting Docker/PG or changing service limits.

## Minimal repair and compatibility

`temporal_deployment_retirement_transport.py` uses a fixed Signal/Query observation
on the original Registry2/3/4. It calls the complete existing asynchronous
`release_deployment_root` handler: original preparation, SDK verifier Activity,
post-await epoch check and atomic commit are unchanged. Only that handler frees
quota. No new grant, admission slot or execution authority is introduced.

Full Scope, namespace name/UUID, policy, original Registry address and run/first/
original epoch, exact root/certificate and request digest remain bound. The client
checks the standalone SDK Registry and pins handle/query/signal ports. A successful
reply must return the original held-bound root, exact certificate and boolean
`released=True`. The cache is limited to 64 observations with a 2 MiB envelope;
pending verifiers cannot be evicted. The 30-second observer timeout, cancellation,
lost reply or malformed response never authorizes Update fallback or quota release.
A fresh observation may recheck the original immutable certificate idempotently.

The original Update handler remains. Historical selected publications require
their matching immutable SDK/Worker; no generic compatibility transport is added.
Public source and composition Worker inventories pin the new module, Signal and
original handler. Stable defaults and saved Histories are checked separately.

## Evidence before service acceptance

The first boundary run failed all 11 cases because the module was absent, then
passed after implementation. Additional client/integration checks passed for wrong
Scope/namespace UUID/epoch/reset/policy/certificate, port changes, lost replies,
cancelled observers and 64 pending verifiers. Independent read-only review found
no actionable P1/P2; it did not run services.

Source 125-module batch: **2,396 passed / 8 failed / 6 skipped / 87.836s**. All eight
failures were sandbox Unix socket `PermissionError`. The exact eight rerun
unchanged in the authorized environment: **8 passed / 1.304s**. These remain
separate runs. An earlier 111-pass/3-failure integration run used old test doubles
without the new typed Registry identity/observation; the doubles were corrected
without relaxing production checks. The original records are retained.

Local evidence prefix `/private/tmp/ralf-agent-p3-registry-retirement`:
`-probe-20261016/`, `-probe-20261018/`, `-probe-20261018-v2/`, `-service-20261018/`,
`-source-20261018/`, `-install-20261018/` and `-live-20261018/`.
Installed and actual service outcomes are recorded below after verification.

Only this retirement subset may close on passing evidence. Strong public manual
proof/native Coding pressure, full P3-3, P3-2/S2 and later gates stay open. No model
quality, PG service, arbitrary History size or indefinite operation is claimed.

## Final artifact and installed service acceptance

Final wheel: `dist/p3-registry-retirement-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`,
SHA256 `7a2dc32ab734956b5998bb9cb48d36e575fd60025e6aee9f605560d36cc06cd6`.
The directory includes `verification.json` and `SHA256SUMS`. All 436 product files
match source/wheel/isolated site-packages; all 909 copied test inputs stay fixed.
Installed 125-module regression: **2,404 passed / 6 skipped / 87.805s**, no failures
or errors. The six configuration-dependent cases are not accepted. Default Card
and ordinary publication equal the frozen basic SDK; original/continued saved
History replay succeeds. All sixteen earlier artifact checksum sets remain valid.

The same installed wheel passed the existing three actual Temporal cases:
**3 passed / 28.621s**, zero failures/errors/skips. Each case has exactly 2,000
accepted/completed Updates on its selected original authority and one genuine
business write. Default Tool and public Run pressure keep end/call ACKs, cancellation
and original receipts intact. The new public Registry-pressure case retires the
original root, frees its quota, adopts the effect and retains the closure seal,
without another Registry Update. Worker restart, original end ACK reobservation,
all original Histories' replay, physical handler exit and owned closure pass.
The default non-public Tool case has no public deployment root to retire.

All six owned Histories close; the fresh actual service shuts down successfully.
It uses the same CLI hash as the valid RED reproduction and leaves old databases
untouched. No real model, PG/HTTP service, new historical-selected compatibility or
native Coding acceptance is inferred. Only the original public Registry retirement
subgate closes. Strong public manual proof and selected native Coding pressure
remain the next evidence gaps; P3-3/P3-2 and later gates stay open. Local commit only.
