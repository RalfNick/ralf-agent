# Facts adapter contracts design

## Intent and standing authorization

Continue the user's R01–R26 goal: usable defaults and replaceable components,
configuration, lifecycle and original recovery. The user explicitly authorized
continuous implementation, parallel development and local commits without push.
This is an architectural extension of the existing R25 suite, not a new execution
authority. Full framework, service/model quality and independent adoption remain
separate goals. This written design and its implementation plan precede code.

## Selection and compatibility

`AdapterContractSuite(role="facts-store", contract_version="1", profile="core")`
selects F01–F10; explicit `profile="managed"` selects all F01–F16. Every selected
case is required. No fixture is zero testing I/O / `not_run`. Missing required
hooks stay `not_verified`. Fixture self-reported verdicts never certify a case.
Keep Knowledge and Session v1 IDs, labels, suite digests and canonical reports
exact. Add only fixed Facts observation keys and role dispatch to the existing
immutable catalog/report/runner. `_run_case(case_id, fixture, workspace)` keeps
three arguments. Quality fields remain null; private evidence excludes secrets.

Core is the existing `LongTermMemoryStore`/async port: stable `backend_id`,
`facts(scope, namespace) -> list[dict]`, `put_fact(scope, namespace, key, value,
*, expected_version, expires_at=None) -> int`. Valid callers use trusted Scope,
bounded nonempty Unicode namespace/key, finite JSON values (including null and
scalars), exact nonnegative integer version, and None/finite nonboolean expiry.
Exercise small 0/1/2 versions rather than inventing universal numeric ranges.
Records have key/value/version/expires_at; optional finite provenance is retained.
Compare by unique key, not an undocumented base order. Expired facts are hidden
from current reads, yet correct versioned updates can revive them. Raw CAS has
no idempotency key: repeating an accepted expected_version=0 conflicts.

Managed adds `recall`/`validate_facts` and literal integer
`fact_inspection_version=1`/`inspect_fact`. Exact inspection is current state,
including expired records, not a historical write receipt. FactsView protects
provenance/value digests; native raw validators differ on value comparison.
Do not silently strengthen or republish native Memory/Redis/PostgreSQL method
identities. Scanner/index/Embedding/Vector/metadata are distinct later roles.

## Fixed required cases

| ID | Label | Actual evidence |
| --- | --- | --- |
| F01 | identity-and-port | Stable ID and completed sync/async port results |
| F02 | current-read-and-version | Empty, first/update CAS and canonical current values |
| F03 | scope-and-namespace | Full 2 workspace × 2 principal × 2 namespace product, eight addresses |
| F04 | compare-and-swap | Stale/future/repeated CAS refusal, no mutation |
| F05 | expiry-and-currentness | Current/future/expired reads and versioned revival |
| F06 | detached-finite-values | Detached nested input/read values and finite records |
| F07 | backend-errors | Actual memory_call mapping and domain-error preservation |
| F08 | backend-drift | Adapter refuses actual backend change despite unchanged public ID |
| F09 | lifecycle-and-suspension | Actual suspended put drains before owned close; borrowed stays borrowed |
| F10 | local-consumer | Original Agent sees current seeded facts, excludes expired/foreign facts |
| F11 | bounded-recall-and-cursors | Real metering/progress, bound cursors and changed snapshot refusal |
| F12 | validation-and-scoped-binding | Current/stale/deleted/expired references; view tamper/provenance and expiry after await |
| F13 | exact-inspection-and-reopen | Missing/current/expired inspection and fresh same-dataset connection |
| F14 | pipeline-partial-replay | Original MemoryPipeline source/command, partial writes and duplicate reuse |
| F15 | accepted-write-lost-ack | Original managed stage unknown, exact inspection, one accepted fact/model |
| F16 | receipt-and-settlement-recovery | Original committed receipt before settlement, same reservation/budget |

## Concrete fixture and observation contract

New `facts_adapter_contract.py` exports `FactsAdapterFixture`,
`FactsContractAddress(scope, namespace)`, `FactsContractResource(resource,
asynchronous=False)`, `FactsContractPause(wait_entered, release)` and
`FactsContractSession(store, addresses, resources=(), inject_fault=None,
pause=None, audit=None, reopen=None, mutate_fact=None)`.
`prepare(case_id, workspace)` is sync/async and returns that exact bounded DTO.
Resources close through original BuildContext ownership. Addresses contain
trusted Scope and bounded namespace; F03 requires the full eight partitions.
`inject_fault(kind)` accepts backend-swap/backend-error/authorization-denied/
put-after-first/put-ack-lost/reset; `pause("put_fact")` manages actual suspended
I/O. `pause("validate_facts")` can hold an actual completed validation before its
await returns, allowing an original reference's real expiry to elapse before
adoption. Mutation of a stored expiry is not equivalent to that elapsed deadline.
`mutate_fact(scope, namespace, key, mode)` performs actual delete/expire/change
for management tests. `reopen()` opens an actual new connection to the original
durable dataset without changing the prepared facade/identity. Mutation/reset/
reopen/wait/release hooks finish with None; pause returns the concrete pause DTO.

Fixed boolean observations retain runtime_closed/borrowed_closed/handler_finished/
cancelled/cleanup_complete/ports_valid/identity_valid. Facts counts are
facts_calls/put_calls/recall_calls/validate_calls/inspection_calls/fact_count/
version/close_calls/backend_switches/consumer_runs/model_calls/write_count/
receipt_checks/reopen_calls/rejection_checks/scope_checks/namespace_checks/
used_chars/scanned/skipped/duplicate_checks/settlement_checks.
Audit counters describe actual resources and never supply verdicts.

Cancellation gates fresh case I/O before and after actual awaits. Retain the
original preparing/calling/cleanup owner and loop through repeated cancellation,
failed reset/release/close. Record admitted Runs before later setup awaits; use
their original authority to cancel/drain. Shared suite cleanup transfer retains
the same task/owner/workspace; no substitute task or timeout proves completion.

## Consumer adoption and independent implementation

`facts_store_values.py::facts_read_value` validates/detaches completed finite
list-of-records, exact positive versions, unique nonempty keys and valid expiry,
retaining finite provenance. Apply only in private Local `_load_references` full
read adoption. Native published methods and default manifests remain exact.
Existing pipeline/managed CAS and exact inspection boundaries remain authoritative;
fix only reproduced consumer defects, with compatibility evidence.

`facts_adapter_contract_reference.py` implements independent sqlite3 source,
core/managed sync/async facades, actual UUID/physical-file identity and scoped CAS,
TTL, bounded recall/cursors/validation/inspection. It delegates no storage to SDK
Memory. Public names: ReferenceFactsSource, ReferenceSQLiteFactsStore,
ReferenceSQLiteManagedFactsStore, AsyncReferenceSQLiteFactsStore,
AsyncReferenceSQLiteManagedFactsStore, offline_facts_fixture,
ReferenceFactsReader, register_facts_reference_components(registry, source=None,
*, asynchronous=False, owned=True). Factory creation is lazy inside original
BuildContext; injected sources remain host-owned when `owned=False` is explicitly selected.

`facts_adapter_contract_starter.py::facts_contract_files()` creates the editable
`facts-contracts` / `agent_app` application. Core/pipeline/managed modes, JSON/TOML,
sync/async and owned/borrowed paths consume actual disclosed facts. Seed is
explicit/idempotent and never runs on recovery; original factory reattaches the
retained Profile/Run. Actual independent process windows cover accepted write
with lost ACK and committed receipt before settlement, preserving original
Run/Actions/commands/releases/budgets and one model/accepted write, with reaping.

## Acceptance and open scope

TDD for catalog, cases/adoption, independent source and shared integration; one
fresh final reviewer and same-reviewer repair closure. Freeze source/tests before
full regression. Independently install core/SDK wheel, run generated apps,
verify original dev95 two-way defaults/Run/stage compatibility, and compare
source/wheel/sdist/installations plus documentation/CI. Bindings and current
read paths cannot gain writes or a second coordinator. Local commit only.
Raw malformed native inputs, indexing lifecycle, arbitrary remote certification,
other adapter roles, real model/semantic/task quality, full R25/H3/M1/R01–R26 and
independent adoption remain open; none are deleted from the capability queue.
