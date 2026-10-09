# dev38 — H2b4a remote native/sequence Session Turns

Baseline: 1f27300/dev37. Implements the [approved plan](../../docs/superpowers/plans/2026-10-09-remote-session-turns.md)
and [bounded delivery spec](../../docs/superpowers/specs/2026-10-09-remote-session-turns.md).
This is remote data under the existing Local execution authority, not distributed
admission or cross-database atomicity. Composite remote roots remain next work.

## Delivered behavior

Existing SessionBindingResource and Profile session-resource factories select
Redis/PostgreSQL (or explicit receipt-v1 custom backends). Each native/sequence
Turn fixes one backend/namespace and independently records the original binding
in the Run. Scope/address reservation conservatively refuses direct backend
aliases. Same authority transaction enables schema5 only for accepted remote
open/rebind; previous schema1/2/3/4 paths retain their release and receipt identity.

Session adapters atomically inspect current revision and exact message-ID receipt
without full-history reads. The original Run records required save intent,
independent adopted-model Action marker, dispatch attempts and matching scoped
receipt. Missing confirmation pauses; explicit resume inspects first and reuses
output/message ID without model or business-tool replay. Terminal recovery only
queries and preserves failed/cancelled state. Unknown saves retain the Turn;
actual running tasks/threads retain Coordinator ownership. Observation derives
eligibility from durable evidence, not current remote availability/retention.

## Independent review and one fix pass

Fresh read-only reviewer dev38_final_review confirmed one Important finding, no
Critical or Minor findings: absent/empty/partial terminal save journals were
interpreted as no outstanding write. With a remotely committed append whose
response was lost, cancellation followed by journal loss released the Turn.

Six RED reproductions cover cancelled/failed sequence Runs with missing whole
journal, empty journal and missing second-node intent. The fix makes the journal
mandatory at admission and atomically records each intent's model-Action marker;
entries and independent source identities must correspond. Metadata loss now
refuses status/pending/recovery before capacity release or new effects. Final
focused fault/receipt gate: 39 passed. No re-review was performed.

Reviewer offline gate: 33 passed with warnings as errors. Its sandbox blocked
Redis Unix-socket fixture setup; implementer ran the isolated service gate with
allowed local-listener permissions. PostgreSQL remained unconfigured.

## Verification

- Final full regression: 2498 passed,58 configured-service skips, warnings as errors.
- Installed wheel contracts: 240 passed; actual package import path asserted.
- Actual old37/new38 distributions: 24 bidirectional schema1 native/bound/sequence/
  graph/parallel/team/plan/DAG/nested and schema2/3/4 Session approval recoveries,
  plus new schema5 unknown-save recovery with old37 read refusal: 25 cases passed.
  Original RunRefs/releases, duplicate approval receipts and real SQLite business
  effect counts are checked. Parallel fixtures use distinct business targets.
- Source service gate: 35 passed,2 PostgreSQL-service skips; installed real-service gate2 passed/2 PostgreSQL skips, including actual
  isolated Redis native/sequence lost-acknowledgement and restart recovery.
- Packaging: all153 SDK modules byte-equal to source;294 root exports and21
  rendered starter trees unchanged from actual dev37. No new dependencies.
- Ruff/format and Git whitespace checks passed; no credential/config/private
  workspaces/tests are packaged. No paid-model calls or remote push.

## Rulings and remaining cost

1. Native/sequence first: their adopted outputs provide a complete small recovery
   path. Cost: remote composite roots remain unsupported until the next increment.
2. Keep data/admission authorities separate. Conservative Scope-wide address
   reservation prevents opaque backend aliases. Cost: genuinely distinct backends
   need different namespace/Session IDs within that Scope; no cross-authority lease.
3. User requested continuous implementation and verified local commits. Decisions
   and fixes proceed inline. Cost: no routine design/commit approval stop.
4. Retain cancelled/failed unknown saves; missing remote receipt is not proof of
   non-execution. Cost: terminal absent evidence can keep a lane occupied; a trusted
   not-executed/abandonment protocol belongs to later recovery governance.
5. No remote/local atomicity claim. A cancelled or locally uncommitted Run may
   have a saved observation message; it is not proof of business success.
6. Actual Redis passed; absent PostgreSQL, Temporal bindings/shared Sessions and
   true model quality remain explicit unverified scope. Tests do not establish
   general framework parity or enterprise readiness.

Deferred Minor findings: none. Remaining capabilities continue in
[remaining-work](../../docs/remaining-work.md), rather than becoming a new authority.
