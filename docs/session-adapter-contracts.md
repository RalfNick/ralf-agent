# Session adapter contract checks

The installed `session-store` contract version `1` checks replacements through
the original public Session ports and Local Agent. Choose `core` for the ten
read/append cases, or `receipts` for all fourteen cases including exact write
evidence and original managed Session save recovery.

```python
from relf_agent import AdapterContractSuite, offline_session_fixture

suite = AdapterContractSuite(role="session-store", contract_version="1", profile="receipts")
try:
    report = await suite.run(
        offline_session_fixture(),
        evidence_dir="/absolute/private/new-evidence-directory",
    )
finally:
    await suite.aclose()  # Retain this owner and retry on the creation loop if needed.
print(report.to_dict())
```

Fixture and suite construction do no storage or service I/O. Preparation is
explicit. With no fixture, the runner reports `not_run`; it does not discover
credentials or contact a service. The evidence directory must be new. Cases
report `passed`, `failed` or `not_verified`; every selected case must pass for an
aggregate pass. Missing management hooks remain `not_verified`. Public results
contain bounded observations and identity digests, excluding raw messages,
configuration secrets and exception details. Quality fields remain null.

```shell
relf-check-adapter --role session-store
relf-check-adapter --role session-store --offline
relf-check-adapter --role session-store --profile receipts --offline
relf init my-session-adapter --template session-contracts
cd my-session-adapter
python -m agent_app check
python -m agent_app check --profile receipts
```

The default `core` profile does not require pagination, a SQL connection, path,
dataset-inspection port, Session admission, or receipts. The existing
`knowledge-retriever` version 1 suite retains its original core catalog. See
[knowledge adapter checks](adapter-contracts.md) for that role.

| Case | Observed contract |
| --- | --- |
| S01 | Stable nonempty backend ID and completed sync/async ports |
| S02 | Empty and ordered reads, actual append, exact revisions |
| S03 | Eight actual addresses: two workspaces × two principals × two storage addresses |
| S04 | Stale and future CAS refusal without stored-message mutation |
| S05 | Canonical same-ID retry returns original revision; conflict refused |
| S06 | Detached finite dictionary messages across input/read mutation |
| S07 | Original `memory_call` preserves domain errors and maps backend errors |
| S08 | Adapter detects its own actual backend switch with public ID unchanged |
| S09 | Actual suspended append drains before owned cleanup; borrowed stays borrowed |
| S10 | Original Local Agent consumes seeded history and saves final output |
| S11 | Exact scoped missing/existing receipt retains its original revision |
| S12 | Actual reopened storage retains original messages and receipts |
| S13 | Accepted append with lost ACK is inspectable without duplicate save |
| S14 | Original Run/Turn holds an unknown save and recovers without another model request |

## Implement the core port

Implement a stable nonempty string `backend_id`,
`read(scope, session_id) -> tuple[int, list[dict]]`, and
`append(scope, session_id, message, *, expected_revision, message_id) -> int`.
The ports may be synchronous or asynchronous. This suite certifies valid typed
callers: trusted `Scope`, nonempty text IDs, finite dictionary messages and a
nonnegative integer expected revision. It does not standardize every malformed
raw-input behavior of historical native backends.

Read returns the actual nonnegative integer revision and detached ordered finite
dictionary messages. Append compares a new message ID against the current
revision atomically. A successful new write advances the revision once. A
canonical identical message with an existing ID returns that message's original
revision, even when the caller's expected revision is stale. A changed payload
under the same ID raises `IdempotencyConflict`. A stale or future new-ID write is
refused without changing the stored messages. Original Local adoption refuses
malformed completed read and append values.

Storage keys include the trusted workspace and principal as well as the Session
address. For host-authorized namespaces, register the original backend inside
`SessionBindingResource`; its selected view maps namespace and Session ID into
the existing storage address. See [binding configuration](data-bindings.md).

```python
from relf_agent import ComponentRegistry, RuntimeBuilder

registry = ComponentRegistry()


def sessions(config, context):
    return context.own(MySessionStore(context.path(config["path"])))


registry.register("session_store", "my-session", sessions, validator=validate_config)
builder = RuntimeBuilder(registry)
```

Factory registration and configuration validation should not create clients.
Construct the owned source inside original `BuildContext` assembly. Use
`register_async`, `await builder.abuild(...)` and `context.own_async(client)` for
async creation/cleanup. Directly injected clients stay borrowed unless their
factory declares ownership. Runtime shutdown drains original calls before
closing owned resources. The host closes borrowed sources after that drain.

## Opt in to exact write receipts

The `receipts` profile additionally requires exact integer
`session_receipt_version = 1` and callable
`inspect_message(scope, session_id, message_id)`. The inspection completes with
this exact finite dictionary shape:

```python
{
    "scope": {"workspace": "project", "principal": "person"},
    "session_id": "original-storage-address",
    "message_id": "original-message-id",
    "revision": 2,
    "receipt": {"revision": 1, "message": {"role": "assistant", "content": "saved"}},
}
```

A missing message has `receipt=None`; current `revision` remains the actual
stream revision. An existing receipt includes that message's original positive
revision, even after later writes. Inspection is scoped to the exact requested
workspace, principal, address and message ID. Alternate method names or a
different receipt-version marker do not select this extension.

An independent external backend needs receipts to participate in managed
`Runtime.create_agent(...).open_session(...)` Turns. A core-only replacement can
still serve the original Local Agent directly. Receipt data adds no execution
authority: original Local Session admission accepts commands, owns Turns and
journals final-save intent and confirmation in the original Run transaction.

## Use the editable reference

The starter's `agent_app/adapter.py` contains the complete independent sqlite3
implementation, rather than importing a package reference or delegating Session
data to a native SDK backend. Its scoped transactions, CAS, dedupe, receipts and
persistent dataset UUID are editable. The live client also pins the actual file
identity and refuses deletion/recreation or replacement at the same path.
Closing a changed source releases its original handle without writing lifecycle
evidence to the replacement. These checks protect this explicit known source;
they do not certify arbitrary remote-service isolation.

```shell
python -m agent_app seed
python -m agent_app run --mode core --command-id core-first
python -m agent_app run --mode receipts --command-id managed-first
python -m agent_app run --format json --async --borrowed --command-id async-first
```

JSON and TOML choose equivalent registered factories. Default sources are owned
and created lazily inside BuildContext. `--async` uses the original async assembly
and resource-close mode. `--borrowed` leaves cleanup with the application host.
Core Runs use logical address `example-core`, while managed Turns use `example`
in the same original data source. Explicit `seed` initializes both empty streams;
the modes can then alternate in one application without sharing a reserved
Session address. Each new run command uses its own command ID.
The deterministic offline Provider reports actual disclosed history from its
model request; it is a wiring example, with model quality unverified. Seeding is
explicit and never runs as part of execution or recovery.

Keep original application code, catalogs and databases for historical Runs.
The lazy `agent_app.runtime:create_engine` factory uses `ProfiledEngine` to
resolve the original persisted profile. Creating the factory or using its
status/events/diagnostics and exact command receipt observations does not open
the Session source.

```shell
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine inspect RUN_ID
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

## Supply management evidence

Implement `SessionAdapterFixture.prepare(case_id, workspace)` and return exact
`SessionContractSession`. It contains the real structural `store`, isolated
`SessionContractAddress(scope, session_id)` values, declared
`SessionContractResource(resource, asynchronous=False)` owners, and optional
`inject_fault`, `pause`, `audit`, and `reopen` hooks. At least one address must be
empty; S03 needs exactly the full two-workspace × two-principal × two-address
Cartesian product: eight actual addresses. Workspace and principal must each
vary independently, including different principals in the same workspace and
different workspaces for the same principal. A fixture missing either independent
Scope dimension cannot verify isolation.

Fault kinds are `backend-swap`, `backend-error`, `authorization-denied`,
`append-ack-lost` and `reset`. `pause("append")` returns
`SessionContractPause(wait_entered, release)` for a real suspended original
append. `reopen()` opens an actual fresh storage connection to the same durable
dataset. That management hook alone does not certify persistence in a new process;
the two real process tests provide separate evidence. Mutation, release and reopen callbacks complete with None. Hooks may
be sync/async and never return success verdicts. Audit contains only the frozen
bounded Session observation keys. The suite writes its own messages and checks
actual port readbacks.

If cleanup fails, keep the original suite and handle `CloseIncomplete`. Retry
`await suite.aclose()` on its creation loop. Do not rerun cases or release the
workspace while original operations/resources remain active. Cancellation is
not evidence that a real append has stopped.

## Recover original process evidence

The independent reference process tests cover two actual save windows:

- The original Session append commits, then its process exits before returning
  the ACK. Original Run save-dispatch intent remains durable without confirmed
  receipt. A second process inspects that exact message ID and adopts the save.
- The original Run commits the matching Session receipt, then its process exits
  before Run success commits. A second process adopts that confirmed receipt
  and completes the same Run.

Both processes are actually exited, waited and reaped. Recovery retains the
same Run, Turn, Session resource, release digest, model Action/request/response/
attempt, command receipts and budget. The original data contains one final
message, and model/append/save counts remain one. Recovery neither reseeds nor
creates replacement Run authority. Suite passes and these bounded Local process
checks do not certify arbitrary business effect windows, remote services,
Temporal Worker/History, model quality, external adoption, or complete
R25/H3/M1/R01–R26 capability acceptance.
