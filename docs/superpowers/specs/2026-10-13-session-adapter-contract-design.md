# Session adapter contract design

## Intent and scope

Continue R25 external adapter adoption under the user's standing authorization:
parallel implementation, original Harness/Local/Temporal authorities, local commits
only. dev95 adds an installed SessionStore contract suite and independently editable
SQLite replacement. Facts and other role suites remain separate future increments.

The base production port is unchanged: backend_id, read(scope, session_id) and
append(scope, session_id, message, expected_revision=..., message_id=...). A valid
caller supplies Scope, nonempty text IDs, finite dictionary messages and an integer
revision. This batch certifies that typed domain, not arbitrary malformed raw
inputs. Existing raw Memory defaults accept some bool/float revisions and non-dict
messages; strict raw-input validation is not accepted here. Published append,
read_page and inspection fingerprints remain unchanged for historical recovery.
The original consumer must refuse malformed completed read/append results.

## Selected approach

Extend the existing AdapterContractSuite with keyword-only profile='core'.
knowledge-retriever/version1 only supports core and retains its exact K01–K12
report serialization, aliases and digest. session-store/version1 supports core
(S01–S10) and receipts (S01–S14). A report explicitly selects its catalog; missing,
reordered, duplicate or foreign cases cannot certify a profile. No fixture does
zero I/O and returns not_run. Missing hooks yield not_verified. New catalogs are
immutable, and public observations remain finite bounded counters/booleans,
redacted digests and generated evidence references. Quality fields remain null.

Requiring receipts on every base Store would make structural replacements less
usable; treating receipts as implicit optional cases could falsely certify
recovery. Explicit profiles preserve the actual extension boundary.

## Frozen cases

| ID | Label | Evidence |
| --- | --- | --- |
| S01 | identity-and-port | Stable nonempty backend_id, completed sync/async ports |
| S02 | ordered-read-and-append | Empty read, exact revision, actual ordered messages |
| S03 | scope-and-address | Two workspaces × two principals × two storage addresses |
| S04 | compare-and-swap | Stale/future new writes refused without mutation |
| S05 | message-idempotency | Canonical same-ID retry returns original revision; conflict refused |
| S06 | detached-finite-messages | Input/read mutations cannot alter persisted finite dictionaries |
| S07 | backend-errors | Original memory_call preserves domain errors and maps actual backend errors |
| S08 | backend-drift | Adapter detects actual switched backend while public ID stays fixed |
| S09 | lifecycle-and-suspension | Actual suspended I/O drains before original owned cleanup; borrowed resources stay borrowed |
| S10 | local-consumer | Original Local Agent consumes seeded history and saves final output |
| S11 | exact-message-receipts | Exact scoped missing/existing receipt and original revision after later writes |
| S12 | reopened-receipts | Fresh actual storage connection retains original messages/receipts |
| S13 | accepted-write-lost-ack | Accepted append whose ACK is lost is inspectable without duplicate |
| S14 | managed-save-recovery | Original Local Run/Turn holds unknown save and recovers exact receipt without a second model request |

Core never requires read_page, connection/path attributes, Session admission or
inspect_message. Receipt profile requires session_receipt_version=1 and
inspect_message; it is data evidence, not another execution authority.

## Fixture protocol

New session_adapter_contract.py exposes SessionAdapterFixture.prepare(case_id,
workspace), sync or async, returning exact SessionContractSession. It holds store,
addresses (SessionContractAddress(scope, session_id)), optional resources
(SessionContractResource(resource, asynchronous=False)), and management hooks
inject_fault(kind), pause(operation), audit(), reopen(). At least one isolated
empty address; S03 requires the complete two-workspace × two-principal × two-address matrix (eight actual partitions). Hooks do not give verdicts.

inject_fault supports backend-swap, backend-error, authorization-denied,
append-ack-lost and reset. pause('append') returns SessionContractPause(wait_entered,
release) for actual suspended append. reopen() completes with None after replacing
its actual connection to the same original durable dataset. Every mutation and
pause callback completes with None. Audit uses only the frozen Session observation
keys. Missing management capabilities do not pass. Ownership uses BuildContext;
original operations, failed release/cleanup and workspaces are retained until the
same suite.aclose() completes on its original loop. Partial prepare failure cleanup
is the fixture's responsibility. Cancellation drains the original active operation and stops later case I/O. Newly accepted Runs are registered before subsequent setup awaits and canceled through their original authority; cleanup release/reset must remain possible. Cancellation does not release live operations.

## Independent implementation and use

session_adapter_contract_reference.py contains a standalone SQLite structural
Store and fixture using sqlite3 directly, not a native SDK memory delegate. Dataset
UUID persists in its database and contributes to backend identity; live physical
file replacement is refused. Transactions implement Scope/address isolation,
lookup-before-CAS dedupe, exact scoped inspection and detached finite messages.
Construction is pure, preparation/seed explicit. Internal short connections close
on every path and physical ownership closes even after faults.

The session-contracts starter copies the editable implementation, exposes check,
seed and run, and uses explicitly registered lazy factories in SDK/JSON/TOML,
owned/borrowed sync/async assembly. Base mode may use direct Local Agent; managed
Session/Turn recovery selects receipts. Seed never runs on recovery. Independent
process tests terminate and reap the original process in actual accepted-save
windows, then recover the original Run, Turn, command receipts and budget; they
must not repeat model work, reseed or introduce a new Run authority.

## Integration and acceptance

Root owns shared types/runner/CLI/exports/version/CI and documentation. Exclusive
parallel authors own catalog, Session role/consumer validation, and reference/
starter/recovery files. Freeze interfaces before product edits; each lane records
actual RED/GREEN. One fresh whole-batch reviewer checks the merged implementation.
Run frozen source regression, installed SDK/CLI/generated replacement and original
version compatibility, packaging provenance/static/document links. Preserve all
failed evidence and original process handles. Real services, Temporal Worker/
History, model quality and external adoption need distinct actual evidence; a
Session suite pass does not complete R25/H3/M1/R01–R26.
