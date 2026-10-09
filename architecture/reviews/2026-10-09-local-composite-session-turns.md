# dev35 / H2b2 — Local composite Session Turns

The same AgentSession now accepts colocated Graph/parallel/transform, Team,
Dynamic linear-plan/DAG and nested definitions. LocalEngine and its actual SQLite
transaction remain the only execution authority; no Facade scheduler or new
state machine was introduced. This closes a Local subset, not full H2/H3.

## Behavior

- Root conversation uses plain host SQLiteMemory on the execution connection;
  composite root namespaces and remote/shared Temporal Sessions refuse.
- Existing member releases/bindings and Session addresses remain: Team/nested
  children and parallel nodes are isolated; sequential graph nodes share their
  existing address. The whole-turn task/result is recorded without hidden input
  rewriting or model-recall claims.
- Required root result uses `run_id + ':turn:result'`. The actual save, confirmation,
  evidence event and success share the final authority transaction. Failed/cancelled
  Turns create no successful root message; previously committed child facts survive.
- Busy includes actual async/thread handlers, unknown/received tools, descendant
  states, frame quiescence and required root save. Bounded traversal verifies original
  ownership; pure status does not execute. Explicit evidence/resume can wake terminal
  housekeeping without reopening a cancelled parent or reexecuting its business.
- Successful composite open/idle rebind enables monotonic schema3. Failed/busy or
  mismatched requests do not upgrade; native-only Sessions stay schema2. New code
  supports1/2/3; actual dev34 refuses3 before dispatch.
- Base SessionAdmissionStore stays compatible. Its optional composite extension
  requires exact Store marker2 and synchronous prepare_composites()->None in the
  real transaction. Atomic SQLite append returns a completed positive revision,
  verified against actual saved content.

## Verification

Final source **2393 passed,56 skipped** with warnings-as-errors;
installed contracts **259 passed** outside checkout. Actual dev34↔dev35 wheel approval
recovery passed4 native/sequence schema1/schema2 cases in each direction. Six
schema3 graph/parallel/team/plan/DAG/nested cases retain original refs, manifests,
Turns and command/control receipts; effects occur once per accepted Action. Actual
old read-only and writable readers refuse3 before dispatch.

Captured old wheel147 SDK modules equal baseline; new source/wheel/sdist/installed148
modules byte-equal,294 optional-free exports and20 identical starter file maps.
Dependencies/extras/scripts unchanged; private evidence and database data excluded.
No paid model calls, automatic dev35 commit/push or publication. Full H2, remote
conversation authority, composite root namespaces, FIFO, Temporal bindings,
automatic H3 chains and task-quality acceptance remain pending.

## Review and one fix pass

One fresh gpt-6-astra/high read-only reviewer ran39 pre-fix focused tests and seven
additional authorized SessionView(namespace=None) composition probes. It found one
Important/P1, no Critical/Minor: actual SQLite COMMIT failure left an open
transaction, exposing uncommitted success/root message and releasing the Session.
The original synthetic _commit exception test did not exercise database COMMIT.

A real deferred foreign-key/root-save trigger reproduced false succeeded; a real
Connection subclass reproduced rollback failure replacing the original error.
Both regressions observed RED. COMMIT now runs inside the rollback-protected
block. Failed rollback preserves the original exception, disables further Store
connection use and attempts close; close remains retryable. After the one fix
pass69 focused tests, full2393/56 and installed259 passed. No re-review. Packages
and all14 actual-wheel cases were rebuilt/rerun after this shared authority fix.

Ruff/format506 files and Git whitespace checks pass;11 changed public Markdown
files have valid local targets. Wheel/sdist contain no private artifacts, database
files or credential-shaped content. Configured-service skips remain explicit;
this stage made no fresh Temporal/remote-service or real-model quality claim.

## Rulings and costs (complete list)

1. Continue approved architecture inline after the requested baseline commit;
   retain local dev35 work/evidence. Cost: new increment remains uncommitted.
2. Explicit evidence/resume can wake original terminal housekeeping. Cost: extra
   terminal accounting must conform; actual cancelled-child reconciliation is tested.
3. Preserve original member addresses, including sequential graph shared history.
   Cost: intermediate and final whole-turn messages can coexist there.
4. Review the captured uncommitted delta because the commit range is empty.
   Cost: manual packet completeness; new paths and git status were cross-checked.
5. Reviewer set aside remote/shared Temporal Sessions, FIFO/deadline/handoff/H3;
   keep the approved Local subset. Cost: those applications need later contracts.
6. Reviewer set aside automatic recall and graph message coexistence; keep explicit
   context semantics. Cost: application history usage requires explicit configuration.
7. Hostile Python/transaction-violating adapters stay outside trusted conformance.
   Cost: validated ports are not an arbitrary-code sandbox.
8. Parent runs full/installed/package gates independently of fresh review.
   Cost: verification breadth depends on maintained tests and configured-service scope.
9. Fix the shared SQLite transaction boundary, not only composite consumers.
   Cost: unrecoverable rollback faults require close/reopen before further use.

Deferred minors: none. Full H2/H3 and enterprise maturity are not marked complete.
