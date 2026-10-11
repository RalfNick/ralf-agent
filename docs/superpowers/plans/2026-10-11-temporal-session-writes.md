# Temporal external Session writes and persistent native Turns

Existing full specification: architecture/specs/temporal-session-data-contract.md. Continuous user authorization; local commits only, no push. Goal remains full R01–R26.

## Global constraints

Original Run History owns accepted write intents, received receipts, save adoption and business success. Session coordinator owns Turns/occupancy, not business saves. Data CAS is not a third execution authority. Existing dev65 read-only private addresses and old default histories remain valid; full writes are an explicit new protocol. Exact data receipt is distinct from actual handler completion; cancellation/timeout must retain uncertainty until real execution end is proved. SessionKey includes original Namespace UUID plus physical data resource, scoped namespace and stable session ID; sequential persistent members must agree. Parent/members remain disabled until their stable addresses/root-save gates exist.

### Task 1: original save intents and managed data I/O

Implement opt-in Runtime registration and pure native/sequence save stages: original model/result/context revision -> inspect -> admitted CAS append -> exact receipt receive -> independent adoption -> node success. Stable message ID, bounded JSON, fixed original methods/client/physical source, credits and errors. Actual execution-end evidence separate from record existence; unknown saves retain Run/Turn ownership and never repeat model/tools. Test original write-before/after-commit ACK loss, received-before-adoption, corrupt receipt, cancel/late effects and component drift with sync/async default ports. Reuse shared receipt validation and original dispatch guard.

### Task 2: persistent native/sequence Session identity and recovery

Extend actual SessionKey/physical resource and root address, binding compatibility, mixed/disabled sequence refusal and idle rebind/no implicit migration. Original Context uses external data once with independent protected History projection. Default History-only sessions unchanged. Add actual handler completion tracking and independent original History stop proofs, actual Worker kill/restart and Redis/PostgreSQL windows; Parent selected external data still explicitly refuses until later full member/root capability. No claim of full external Session until this task is actually delivered.

### Task 3: acceptance and local commit

One fresh-context read-only review required by requesting-code-review skill; fix important findings with RED→GREEN. Full/source/installed/core/build/old-new/actual service checks, capability docs and M1 remaining gates. Final local commit only after concrete proof, no push. If turn ends mid-task, preserve ledger/current work and continue full task; do not replace the goal with a private-write subset.
