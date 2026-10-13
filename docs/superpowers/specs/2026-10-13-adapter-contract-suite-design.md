# Public adapter contract suite

Status: dev94 frozen first-role design; verified behavioral evidence is recorded
in [acceptance](../../../architecture/reviews/2026-10-13-knowledge-adapter-contracts.md). Standing user authorization
requires continued capability development with independent parallel tasks and
central integration; no additional execution authority, remote push or automatic
completion of R01–R26 follows from this increment.

## Intent and decisions

R25 requires external authors to validate replacement components from the
installed SDK. Start with the existing KnowledgeRetriever read/source contract,
supporting both synchronous and asynchronous implementations through the original
KnowledgeContext. Keep the same Runtime/BuildContext/Local authority for consumers.
This is architectural work: the new subsystem is observational and does not
change Run identities, recommended defaults or Temporal history protocols.

Three approaches were considered: exporting repository pytest helpers; accepting
fixture-provided success verdicts; and a dependency-free SDK runner with frozen
black-box cases. The SDK runner is selected because external authors can run it
without repository tests and its verdict follows actual behavior. Management
hooks control sources and faults, never declare that a test passed.

## Public entry and reports

```python
suite = AdapterContractSuite(role="knowledge-retriever", contract_version="1")
try:
    report = await suite.run(fixture=my_fixture, evidence_dir=private_directory)
    report.to_dict()
finally:
    await suite.aclose()
```

Construction and `run(fixture=None)` do no I/O. The latter returns `not_run` with
`adapter_not_configured` and every required case `not_verified`. Unknown roles,
versions and malformed arguments fail explicitly. Case IDs and requirements are
fixed by suite version `1`; totals derive from cases. Cases are `passed`, `failed`
or `not_verified`; aggregate status is `passed` only when all required cases pass,
`failed` if any fails, otherwise `incomplete`. Missing hooks are not passing skips.

AdapterContractCaseResult and AdapterContractReport are immutable/detached finite
JSON views. They include role, contract/suite versions and digest, adapter and
configuration digests, original execution authority/evidence kind, stable error
codes, bounded integer/bool observations and optional relative evidence refs
(path, sha256, bytes). They exclude query/source/identity/exception text and raw
backend configuration. `semantic_quality` and `model_quality` stay null. Results
distinguish adapter behavior, framework boundary protection and Local consumer
evidence; fixtures do not certify real services, Temporal or external adoption.

No fixture callback can supply a case verdict. The runner dispatches the frozen
role implementation. Private evidence is optional: use an exclusively created
directory, generated filenames, bounded records and no raw exception text in the
public report. Without a retained directory, temporary files are cleaned after
actual operations finish and no dangling evidence refs are returned.

## Knowledge fixture and cases

`KnowledgeAdapterFixture.prepare(case_id, workspace)` returns a concrete
`KnowledgeContractSession`; preparation may be sync/async and occurs only during
explicit execution. The session contains a structural retriever, trusted Scope,
namespace/query, expected original Chunk values, a foreign Scope/namespace, and
optional source-management callbacks. Callbacks mutate actual sources, inject a
specified fault, expose bounded audit counts, or pause/release actual I/O.
Explicit owned resources use original BuildContext own/own_async; direct clients
are borrowed unless declared owned. Missing required hooks yield not_verified.
Fixture types do not add CAS, pagination, conn/path or store inheritance to the
production Retriever port.

Source-update checks include a positive control for the new current version
before deletion. An always-rejecting validator cannot satisfy that case. Pause
checks first validate the normal source, then require an actually started,
suspended original call before mutating it. If management release fails, retain
that original call, owner and workspace for same-loop cleanup; do not close the
client or report cleanup complete while the operation is active.

The fixed cases are K01–K12:

1. **K01 identity-and-port**: actual structured identity and callable sync/async ports.
2. **K02 result-and-metering**: actual RetrievalResult and canonical character count.
3. **K03 scope-and-namespace**: separate real sources across two Scopes/namespaces.
4. **K04 bounded-retrieval**: item and canonical metadata/text budgets, empty results.
5. **K05 current-source**: valid original source; stale version/deleted source rejected.
6. **K06 tampered-source**: changed text/source URI/metadata/expiry/version/Scope rejected.
7. **K07 expiry-after-await**: expiry rechecked after actual validator await.
8. **K08 scoped-binding**: original approved namespace selectors and cross-Scope refusal.
9. **K09 component-drift**: original object, identity/config and bound method drift.
10. **K10 backend-drift**: fixture switches a real backend without changing identity;
    the adapter must detect its own physical-resource drift. No automatic reflection claim.
11. **K11 backend-errors**: errors map through the original context; public report redacted.
12. **K12 validation-and-consumer**: validator completes and returns None; an actual
    Local Agent request contains validated source evidence and no fabricated model quality.

Frozen case requirements do not introduce a universal duplicate-result rule:
basic KnowledgeContext currently permits duplicate candidates. Method pinning
is a real uncovered boundary: strengthen KnowledgeContext around its existing
awaits without changing default identity bytes; test both valid synchronous
adapters and method replacement before/after awaited retrieval/validation.
Pin the three original RetrievalQuery parameters in a private transient guard,
without changing its dataclass fields, constructor or serialized request. This
detects parameter/type changes at the original result boundary; it is not an
isolation guarantee against arbitrary trusted Python reflection.

## Defaults, customization and recovery

Provide an explicitly selected offline fixture with a genuinely independent
SQLite source/adapter implementation, directly returning public retrieval DTOs
and re-reading original source values. It cannot delegate to built-in Retriever
or KnowledgeStore. It has its own audit and source mutation controls, fixed path
and resource checks, and honest lexical/offline evidence labels.
Its own source resource pins the original physical SQLite file through an open
descriptor; replacement/deletion at the same path fails before/after reads.
Cleanup releases the original descriptor without writing to the replacement
database. Normal source version updates and process reopening remain supported.

An installed starter demonstrates the suite and complete knowledge factory
replacement in semantic-knowledge version2 using registered JSON/TOML declarations,
sync/async assembly, owned/borrowed lifetimes and Agent/RAG/Plan/Team consumers.
No unrelated Embedding declaration, implicit network/model download or credential
discovery is permitted. CLI uses the same runner: no fixture means not_run;
`--offline` explicitly runs the independent fixture.

Actual independent processes validate original Local model-dispatched and
model-response-recorded recovery windows, source deletion after exit, stable
Run/Action/command/Turn/budget/references and actual wait/reap. The suite report
does not claim arbitrary adapter recovery without required independent evidence.
Temporal/remote backend certification and general adapter roles remain explicit
future cases; offline lexical evidence never closes semantic/model quality.

## Integration gates

Freeze shared signatures first; runner/report, Knowledge cases and independent
reference/recovery use exclusive files. Root owns exports, CLI, version, CI,
default/history compatibility and documentation. One fresh integrated review
checks all changes; preserve valid RED/GREEN and failures. Final source suite,
independent core/SDK installs, original defaults/history compatibility, source/
wheel/sdist provenance, static/docs checks and actual owned-process cleanup are
required before the local commit. Complete R25/H3/M1/R01–R26 remains open.
