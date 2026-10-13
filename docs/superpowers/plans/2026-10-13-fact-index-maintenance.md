# Facts index maintenance implementation plan

**Goal:** An opt-in, bounded automatic Facts-index refresh and usable native
default Agent/Session chain under original execution authority.

**Spec:** [design](../specs/2026-10-13-fact-index-maintenance-design.md).

**Baseline:** `3ecc7e9cf047c79751d82b4aaa62cf05d9842a23` (dev97, locally
committed; no push). Private prototypes are engineering evidence, not acceptance.

## Parallel ownership and preflight

The user explicitly requested parallel development. Three exclusive author lanes
share fixed interfaces; root owns shared registration/exports/version, integration,
capability documentation and acceptance. No worker commits or edits another lane.
Each author preserves a meaningful RED then GREEN, commands and cleanup evidence.

- Generation lane produces fixed source-snapshot API and unchanged rebuild DTO.
  Tool lane consumes it; source_changed is typed, generic CAS remains pending.
- Tool lane produces an owned Source borrowing its index/catalog; assembly lane
  creates Source last and closes native resources only after actual owner drain.
- Assembly pairs exact index/resource identity and uses existing Graph/Runtime;
  reader namespace and explicit MemoryRecallPolicy must match fixed selection.
- Ruling: async tools use original abuild and recorded-profile app recovery.
  Original synchronous ProfiledEngine remains a read-only factory for this app;
  do not add hidden async dispatch or advertise unsupported CLI continuation.
- Ruling: metadata is data evidence, not Run authority; only exact historical
  effect receipts reconcile an original maintenance Action.

## Task 1 — generation lane

Files: `src/ralf_agent/fact_index_generation.py`,
`tests/test_fact_index_generation.py` and an exclusive process fixture if needed.

- [x] Promote additive private prototype; use relative package imports and public
  documentation. Keep original fact_index.py bytes/identity unchanged.
- [x] RED/GREEN native partial, source replacement, current recall, expired/deleted
  source, reopen, late old publication, competing CAS and mutation/equality checks.
- [x] Actual ownership/thread/process closure evidence; freeze final interfaces.

## Task 2 — managed tool lane

Files: `src/ralf_agent/fact_index_maintenance_tools.py`,
`tests/test_fact_index_maintenance_tools.py`,
`tests/test_fact_index_maintenance_recovery.py`,
`tests/fact_index_maintenance_recovery_worker.py`.

- [x] Promote exact effect journal/ToolSource; original ToolPolicy admission,
  InvocationContext, reconciliation and handler owner remain authoritative.
- [x] RED/GREEN original Graph ToolAction and budget/receipt/ready-only gating,
  key reuse, source change, generic CAS/budget pending, cancellation/close retry.
- [x] Actual waited/reaped original Run/Session crash-window recovery; observation
  never dispatches; exact completed receipts adopt without extra index effects.

## Task 3 — default composition lane

Files: `src/ralf_agent/fact_index_maintenance_factories.py`,
`src/ralf_agent/fact_index_maintenance_starter.py`, corresponding test modules,
and `docs/fact-index-maintenance.md`.

- [x] Add native async factories, canonical pairing helper and borrowed owner;
  preflight before allocation, weak cache lifecycle and reverse drain order.
- [x] Editable Graph/Agent/Session app, explicit seed, status and async recorded
  profile recovery; SDK/JSON/TOML and owned/borrowed modes.
- [x] RED/GREEN two actual Session turns: grounded Fact commit, automatic refresh,
  current Fact evidence reaches reader; incomplete shutdown retains original owner.
- [x] Installed wheels exercise the same generated app without source fallback.

## Task 4 — root integration and acceptance

- [x] Shared exports/starter registration and dev98 candidate version, public guide
  and capability checklist consistent with delivered scope.
- [x] Integrate authored tests; one fresh whole-batch review, reproduce important
  findings and repair with RED/GREEN; preserve rulings and limitations.
- [x] Full source regression/static checks, installed core+SDK acceptance and
  immutable dev97/native index compatibility with source/wheel/sdist byte proof.
- [x] Record actual acceptance and remaining capabilities, exact local commit,
  clean working tree and no push; whole continuous goal remains active.

## Review focus

Journal truth vs current-generation truth; source change at every await;
same-generation CAS and old generation late publication; fixed Scope/namespace
and original effect identity; close failures and real delegated threads;
weak-context leaks; original recorded profile vs changed defaults;
ready-only gating before a reader; hidden async/remote I/O or fake semantic claims.

## Review repair ledger

One fresh whole-batch review found two P1 and two P2 defects. The coordinated
repair pass has meaningful REDs for outer/nested execution-owner replacement,
SDK source replacement, the exact guide mode switch and missing CLI Session ID.
Generation/catalog source-race REDs and native equality refusal are repaired and independently replayed.

- Ruling: correct `_FixedPorts.check` once with identity-safe binding comparison
  instead of duplicating native-catalog guards. Original fact_index.py and native
  identity/method records stay unchanged. Invalid receiver replacement that
  supplier equality previously concealed now refuses; installed old/new native
  and original Run/Turn compatibility must verify legitimate behavior.
- Ruling: cleanup checks actual original ownership before and after awaiting it;
  ownership drift fails closed, keeping native resources for restore/retry.
  Data-binding failure alone does not prevent draining an intact execution owner.
- Ruling: explicit CLI Session IDs separate ownership profiles; preserve stable
  default Session and original binding refusal. Changing a command prefix cannot
  change an existing Session's accepted profile.
- Ruling: generation-only source-read adoption checks classify an actual changed
  source. Generic catalog CAS/budget/refusal does not become a terminal receipt.

P3 descriptor-description drift and boolean journal schema-version hardening are
recorded as deferred strict-validation work, without claiming forged effects or
complete R25 validation coverage. Wheel installation instructions are corrected
without making a public package-index release claim.

## Final acceptance

The final product/test bytes are frozen. Full distinct-case source gate is 8298 passed/617 configured skips, with only sandbox-socket failures retried and XML identities deduplicated. Isolated installed core/SDK each 163 pass; actual 12 config combinations, 32 Turns and six process-crash windows pass. The same reviewer closed all four original findings, including an additional exact source-close-method replay and three RED→GREEN cases. Original dev97 compatibility and 349-module artifact provenance are checked; remaining semantic/service/GC/strict-input scope stays open. Final metadata is built and checked before the authorized local commit; no push. See [acceptance](../../../architecture/reviews/2026-10-13-fact-index-maintenance.md).
