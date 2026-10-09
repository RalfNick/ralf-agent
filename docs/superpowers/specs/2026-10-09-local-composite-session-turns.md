# Local composite Session Turns — H2b2

Continue the approved H1/H2 architecture after the explicit local dev34 commit.
Extend the existing durable Session entry to Local Graph, Team, Dynamic and nested
definitions. Users open/submit/rebind the same AgentSession API; execution and
Turn ordering remain owned by the existing LocalEngine/SQLite authority.

## Scope and behavior

- Composite conversation storage is the host's plain colocated SQLiteMemory (or
  a host-authorized SessionView with namespace=None), on the actual execution
  connection. Native/sequence Session namespace selection is unchanged. Composite
  root namespace views, remote conversation stores and FIFO remain unsupported.
- Composite manifests reuse existing compiler/binding/orchestration publication.
  Members retain existing Session/context/bindings: Team/nested children and
  parallel graph nodes use existing isolated addresses; sequential graph nodes
  retain their existing shared address. The root conversation records the
  original whole-turn task and final composite result. No implicit history input
  rewrite or claim of model recall quality. Existing raw definition restrictions
  (including Graph members with disabled Sessions) remain effective.
- Atomically accept Turn/Run/route with existing receipts. Busy and binding
  mismatch remain durable. Original command replay precedes new alias resolution.
  Idle CAS rebind may cross native/composite kinds only on the same actual route.
- Before committing composite success, append one stable final conversation
  message inside the existing SQLite execution transaction and verify its actual
  saved content. No external async I/O, nested authority, new effect replay, or
  SQLiteMemory construction (executescript) inside that transaction. Append failure
  rolls back final message/event/success; existing child/tool evidence remains.
- Session occupancy includes root/descendant nonterminal states, actual handlers,
  unknown/received tool evidence, graph frames and required saved result. Parent
  terminal/cancelled status alone cannot release the lane. Bounded pure discovery
  rejects malformed ownership rather than ignore it. Status/attach remain pure.
  An explicit resume/evidence control may wake the existing authority's terminal
  housekeeping to adopt child evidence and mark quiescence; it cannot reopen a
  cancelled parent, execute a new effect or manufacture a successful root message.
- First successful composite open/rebind atomically activates database Schema3;
  failed/busy/mismatched requests do not upgrade. Native-only Sessions stay
  Schema2 and ordinary raw databases Schema1. New readers support1/2/3, all later
  preparation is monotonic, dev34 and older readers refuse3 before dispatch.
- Base SessionAdmissionStore stays compatible. An optional composite admission
  extension provides synchronous prepare_composites; advertised capabilities and
  actual extension/resource are checked before composite acceptance. Typed None
  results only; lazy or foreign-transaction adapters refuse.

## Acceptance

Use real SQLite authority/memory and actual async/thread handlers: ordered
graph/parallel/team/linear-plan/DAG/nested turns, original member isolation, stable
root-save ID/content, original submit/control receipts, busy/cancel/unknown holds,
source restart, rebind, scope/aliases, append/commit failures and schema rollback.
An actual captured dev34 wheel must recover Schema1/2 approvals and refuse new3;
new installed SDK recovers3 without repeated effects. Full regression, package
bytes/dependency/optional-import checks and one fresh read-only review must pass.
No paid calls, automatic push, sibling private workspace access or next-stage
automatic commit. This closes a Local composite subset, not full H2 or H3.
