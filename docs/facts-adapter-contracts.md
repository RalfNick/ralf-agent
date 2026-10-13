# Facts adapter contracts

Facts checks cover explicit replacements for current scoped memory. Select
`AdapterContractSuite(role="facts-store", contract_version="1", profile="core")`
for F01–F10, or `profile="managed"` for all F01–F16. Every selected case is
required. No fixture means `not_run` and zero testing I/O. A missing required
management hook means `not_verified`. Fixture audit counters never supply a
verdict. Knowledge and Session contract selections retain their existing IDs.

```shell
ralf-check-adapter --role facts-store --profile core
ralf-check-adapter --role facts-store --profile managed --offline
ralf init facts-example --template facts-contracts
cd facts-example
python -m agent_app check
python -m agent_app check --profile managed
python -m agent_app seed
python -m agent_app run --mode core --command-id facts-core-first
python -m agent_app run --mode pipeline --command-id facts-pipeline-first
python -m agent_app run --mode managed --command-id facts-managed-first
python -m agent_app run --format json --async --borrowed --command-id facts-async-first
```

The generated application includes the full editable independent SQLite source
in `agent_app/adapter.py`. It implements Facts storage itself. Native SDK Memory,
Redis, and PostgreSQL methods and default identities remain unchanged. Registry
construction opens no data; the original BuildContext creates owned sources
lazily. Explicit borrowed assembly keeps cleanup with the application host after
Runtime drains. JSON and TOML select the same `memory_store`, `provider`, and
`stage_policy` factories. All three application modes share the same actual Facts
and original Run databases, with distinct command IDs for distinct Runs.

Core requires `backend_id`, `facts(scope, namespace)`, and
`put_fact(scope, namespace, key, value, expected_version=..., expires_at=...)`.
Values are detached finite JSON, including scalars and null. Version comparison
uses the current stored version even for expired records, permitting correct
versioned revival. Current reads hide expired facts. Scope includes workspace and
principal; namespace is an independent address dimension. Repeating an accepted
raw CAS with the same expected version conflicts: raw CAS has no idempotency key.

Managed adds bounded `recall`, `validate_facts`, and literal integer
`fact_inspection_version=1` with `inspect_fact`. Recall counts actual scanned and
skipped records, accounts for canonical JSON characters, and makes progress past
expired, unmatched, and oversized records. Cursors bind query, Scope, namespace,
backend and snapshot; changes to that address’s snapshot invalidate old cursors.
Inspection returns exact current state, including expired records, and is not a
historical receipt. Original FactsView protects current value and provenance
digests. Scanner, indexing, embeddings, vectors and metadata are separate roles.

The post-await expiry check establishes an actual validation pause and retains
the reference's original expiry. Preparation and recall latency do not imply an
adapter defect. If that timing window cannot be established, the case remains
`not_verified` with `case_not_verified`; it cannot certify the managed profile.
Case-derived namespaces stay within the port's accepted bound, including space
for the original pipeline's `:commands` address. Lifecycle checks compare the
prepared session's actual before/after counts; a borrowed dataset's historical
close count does not mean its current source was closed.

| Cases | Evidence |
| --- | --- |
| F01–F06 | Completed core ports, current versions, all eight Scope/namespace addresses, CAS refusal, expiry and detached finite values |
| F07–F10 | Actual backend failures and drift, suspended I/O and ownership, original Local Agent facts adoption |
| F11–F13 | Bounded recall/cursors, scoped current validation and post-await expiry, exact inspection and a fresh same-dataset connection |
| F14–F16 | Original pipeline partial replay, managed accepted-write acknowledgement loss, original receipt and reservation settlement recovery |

Fixture `prepare(case_id, workspace)` returns the concrete
`FactsContractSession` containing trusted addresses, original owned resources,
and optional management hooks. Supported faults are `backend-swap`,
`backend-error`, `authorization-denied`, `put-after-first`, `put-ack-lost`, and
`reset`. Partial pipeline faulting permits the original command binding and first
observation, then interrupts the next observation before mutation. `pause` supports
actual suspended `put_fact` and completed backend `validate_facts` held before its
return. `mutate_fact` actually deletes, expires, or changes the selected fact.
Mutation/reset/reopen/wait/release hooks complete with None. `reopen` opens a fresh
connection against the same prepared facade and persisted dataset; it alone does
not establish independent process recovery.

The reference source pins a persisted dataset UUID and the physical file identity
of the original live dataset. Backend swapping is refused even when the public
facade ID remains unchanged. Close releases its original file descriptor and
never writes lifecycle evidence to a substituted file. Audit reports actual fixed
counts. Native full-read adoption validates completed records without republishing
or strengthening native raw methods.

Seed is an explicit idempotent command. It discloses one current seeded fact plus
expired and foreign Scope facts; only the current authorized fact reaches the
actual Agent context. Execution and recovery never seed. `pipeline` invokes the
original MemoryPipeline. `managed` invokes the original ManagedMemoryPolicy.
Business success remains distinct from an auxiliary unknown memory outcome.

Independent process tests interrupt after an accepted put before acknowledgement
and after the original committed memory receipt before reservation settlement.
Both processes are actually waited for and reaped. Recovery uses
`agent_app.runtime:create_engine`, retains the same Run, Actions, commands,
Profile/Release, fact key and reservation, and performs no extra model call or
accepted write. Owned source handles close after recovery. These tests are
separate evidence from a suite pass.

```shell
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine inspect RUN_ID
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

Keep original application code, catalogs and databases for historical Runs.
Cancellation gates fresh I/O around actual awaits, and cleanup retains the
original owner, handler, event loop and workspace through repeated cancellation
and cleanup failures. A retry drains that same owner; later close success cannot
turn a failed report into a pass.

This offline contract checks wiring and bounded observations. It does not certify
arbitrary remote services, Temporal Worker/History, model/semantic/task quality,
full R25/H3/M1/R01–R26 completion, or independent adoption. Malformed native raw
inputs, index lifecycle, other adapter roles and those broader capability gates
remain open.
