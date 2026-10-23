# Adapter contract checks

RALF's public adapter contract suite lets an external author check a replacement
using the installed SDK, without importing repository tests or installing pytest.
The first role is `knowledge-retriever`, contract version `1`. It checks the
existing read/source-validation contract through the original `KnowledgeContext`.
It does not add a Store, CAS, pagination or connection attribute to that port.

The separately selected `session-store` core/receipts profiles are described in
[Session adapter checks](session-adapter-contracts.md). Their required cases and
optional production capabilities are independent of this Knowledge contract.

```python
from relf_agent import AdapterContractSuite, offline_knowledge_fixture

suite = AdapterContractSuite(role="knowledge-retriever", contract_version="1")
try:
    report = await suite.run(
        offline_knowledge_fixture(),
        evidence_dir="/absolute/private/new-evidence-directory",
    )
finally:
    await suite.aclose()  # Keep and retry the same owner on the creation loop.
print(report.to_dict())
```

`offline_knowledge_fixture()` is an explicit choice. Constructing the suite or
fixture does no source I/O. Running with no fixture returns `not_run`; it does not
discover credentials or access a service. An evidence directory must be fresh;
without one, the runner removes its temporary evidence after operations finish.

```shell
relf-check-adapter
relf-check-adapter --offline
relf init my-adapter --template adapter-contracts
cd my-adapter
python -m agent_app check
```

The generated `agent_app/adapter.py` contains the complete independently
implemented SQLite source, structural Retriever and management fixture. Copy and
edit it for your own adapter. It does not import the package reference class or
delegate retrieval to an SDK KnowledgeStore/Retriever. Its lexical search and
source-copying Provider are deterministic wiring examples; semantic relevance
and model quality remain unverified.

The reference source pins its own actual SQLite file while the client is alive
and checks its physical identity before and after source operations. Replacing
or deleting/recreating the file at the same path raises `DefinitionMismatch`;
closing a changed source releases the original file handle without writing an
audit to the replacement. This protects that explicitly managed source. It does
not reflect arbitrary clients or certify remote-service/resource isolation.

## Interpret the result

All K01–K12 cases are required for this role. Each reports `passed`, `failed` or
`not_verified` with a stable code. The aggregate is `passed` only if every case
passes; absent management capabilities remain `not_verified`. A fixture cannot
return its own success verdict. Counts are bounded observations, while adapter
and configuration identities are digests. Public reports exclude raw queries,
documents, configuration secrets and exception bodies.

| Case | Observed contract |
| --- | --- |
| K01 | Finite structured identity and callable sync/async ports |
| K02 | Actual typed result and exact canonical character metering |
| K03 | Real sources across two Scopes and two namespaces |
| K04 | Item/character budgets and empty results |
| K05 | Current source validation and stale/deleted source refusal |
| K06 | Changed text, metadata, URI, expiry, version and Scope refusal |
| K07 | Expiry checked after a genuinely suspended validator |
| K08 | Original scoped binding allowlist and cross-Scope refusal |
| K09 | Original component/object/configuration/method drift protection |
| K10 | Adapter detects its own actual backend switch with unchanged identity |
| K11 | Real backend and authorization errors, with redacted public results |
| K12 | Validation completes with None; a Local Agent actually receives source evidence |

Some cases test the adapter itself; others test framework protection around the
adapter. Passing these cases proves that bounded combination, rather than all
database services, arbitrary failure timing, business quality or Temporal
compatibility. Source-process recovery evidence is recorded separately. Both
`semantic_quality` and `model_quality` remain null.

K09 covers registered direct method bindings, not arbitrary transitive Python
state. Native Lexical/Vector/Hybrid combinations also pin their declared internal
source/index/embedding ports; see the exact [drift boundary](extending.md#3-身份与不可变发布).
K10 remains the adapter's responsibility: detect its own actual backend change,
even if its public identity was not updated. A cached validator is not evidence
that the current source is still valid. These checks do not sandbox trusted code.

## Implement a replacement

Implement `identity`, `retrieve(scope, namespace, query)` and
`validate(scope, namespace, items)`. Both ports may be synchronous or asynchronous.
Return public `RetrievalResult`/`RetrievedChunk` values bound to the requested
Scope/namespace. `used_chars` is the length of the canonical JSON array of chunk
dataclass dictionaries, or zero for an empty result. Bound the actual returned
values, including metadata. The validator must re-read the current original
source, compare its provenance/content/version/expiry and complete with None.

```python
from relf_agent import ComponentRegistry, KnowledgeContext, RuntimeBuilder

registry = ComponentRegistry()


def knowledge(config, context):
    client = context.own(MySource(config["source"]))
    return KnowledgeContext(MyRetriever(client), namespace=config["namespace"])


registry.register("knowledge", "my-retriever", knowledge, validator=validate_config)
builder = RuntimeBuilder(registry)
```

Use `register_async`, `await builder.abuild(...)` and `context.own_async(client)`
for async creation/close. A directly injected client remains borrowed unless the
factory explicitly registers ownership. Resource management and original Run
execution remain separate. Runtime shutdown must drain actual operations before
closing owned clients; borrowed client cleanup stays with its host.

If owned cleanup fails, retain the same suite and handle `CloseIncomplete`.
Its report describes the unfinished original owner. Call `await suite.aclose()`
on the original event loop to retry cleanup; do not rerun the cases or release
the temporary workspace while real operations/resources remain active.

The generated application fully replaces the knowledge component in
`recommended_profile("semantic-knowledge", version="2", ...)`. Its equivalent
JSON and TOML declarations select explicitly registered factories; configuration
does not import application code. An unused HTTP Embedding declaration is not
required for a complete replacement. Keeping the native semantic adapter still
requires the original explicit embedding configuration.

```shell
python -m agent_app seed
python -m agent_app run --kind agent --command-id agent-first
python -m agent_app run --kind rag --command-id rag-first
python -m agent_app run --kind plan --format json --async --command-id plan-first
python -m agent_app run --kind team --format toml --borrowed --command-id team-first
```

The RAG application is an Agent using the selected knowledge context. Plan/Team
use original managed child Runs and fixed budgets. The application observes
references in the committed final model requests; merely retrieving a candidate
does not count as disclosure. `seed` is explicit and never runs during recovery.

For per-Agent namespace selection, wrap the original native `KnowledgeContext`
with `KnowledgeBindingResource` or the `knowledge-resource` declaration, then
select an allowed namespace through the existing binding descriptor. Arbitrary
custom `KnowledgeContextPort` implementations do not automatically gain scoped
resource-selector support. See [binding configuration](data-bindings.md)
and [recommended combinations](recommended-harness.md).

## Supply a fixture for your real adapter

Implement `KnowledgeAdapterFixture.prepare(case_id, workspace)` and return a
concrete `KnowledgeContractSession`. Preparation is explicit I/O. The session
contains the real structural Retriever and `KnowledgeContractSource` records
describing original seeded queries/chunks. K03 needs two actual Scopes crossed
with two namespaces. Management hooks mutate original sources, switch actual
backends, inject errors, pause original I/O and expose audit counts. They are not
new production Retriever methods and never supply a pass/fail verdict.

`mutate_source(chunk, operation)` supports `replace`, `delete` and `expire`.
`inject_fault(kind)` supports `backend-swap`, `backend-error`,
`authorization-denied`, `invalid-validation-return`, `identity-drift`,
`method-drift` and `reset`. `pause(operation)` returns `KnowledgeContractPause`
with wait/release callbacks completing with None; supported operations are
`retrieve` and `validate`. K07 pauses after an actual successful source read, then
lets the original TTL expire before validation returns. `audit()` returns only
bounded integer/bool observations allowed by the public contract values.

Declare each genuinely owned client with `KnowledgeContractResource`; resources
created for injected faults remain that client's responsibility. Hooks may be
sync/async. Missing required hooks produce `not_verified`; tests cannot infer a
successful failure window from adapter method names or an absent exception.

## Recover original evidence

Keep the original code, profile and databases for a historical Run. The local
reference process tests distinguish the original windows:

- After `model_dispatched` commits, the original request and references are
  durable, while no received response exists. Deleting the source before restart
  must not trigger a replacement retrieval/model call. The original failure and
  unresolved execution credits remain visible.
- After `model_response_recorded` commits, the received response and budget
  settlement are durable. A restart adopts that response without re-querying the
  deleted source or calling the model again. Original Run/Action/attempt/command
  receipt/Session Turn and immutable references remain the same.

These are actual independent-process checks with successful wait/reap, rather
than copying an in-memory engine. They verify the Local reference combination.
Tools/business writes require their own effect-window evidence. Remote-service
and Temporal adapters need their respective actual backend/Worker/History
evidence. A suite pass alone does not complete R25, H3, M1 or the full R01–R26
capability plan.
