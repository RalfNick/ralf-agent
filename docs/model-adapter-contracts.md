# ModelProvider replacement checks and editable business application

The installed `model-provider` contract version `1` checks the core async port
and its use by the original Local authority. Choose `core` for P01–P10 or
`tools` for every P01–P16 case. Every selected case must pass. The existing
five-scenario model-check evaluator remains separate and retains its quality
meaning; these replacement checks do not measure model quality.

```shell
ralf-check-adapter --role model-provider
ralf-check-adapter --role model-provider --offline
ralf-check-adapter --role model-provider --profile tools --offline
ralf init my-model-adapter --template model-contracts
cd my-model-adapter
python -m agent_app check
python -m agent_app check --profile tools
```

Construction and a check without a selected fixture perform no supplier I/O.
No fixture reports `not_run`. The explicit offline fixture uses independent
SQLite supplier code; it does not call an SDK Echo/compatibility provider or
repository tests. Missing management hooks report `not_verified`. Public
results contain the fixed bounded booleans, counts and identity digests, with
null quality fields. They exclude raw messages, outputs, supplier errors and
credentials. Retained evidence requires a fresh private directory.

```python
from ralf_agent import AdapterContractSuite, offline_model_fixture

suite = AdapterContractSuite(role="model-provider", contract_version="1", profile="tools")
try:
    report = await suite.run(offline_model_fixture(), evidence_dir="/private/new-directory")
finally:
    await suite.aclose()
print(report.to_dict())
```

| Cases | Actual observation |
| --- | --- |
| P01–P02 | Stable finite identity, actual async complete, generic finite JSON and known/unknown usage |
| P03–P04 | Detached original request/received evidence; completed invalid, lazy and deep values retain known completion |
| P05–P07 | Actual domain errors, redacted public failures, component/method/source drift |
| P08 | Suspended original call and owned/borrowed resource lifecycle |
| P09–P10 | Original Local Agent metering and same-Run committed-response adoption |
| P11–P12 | Actual descriptors/proposals/call IDs/Schemas/defaults and denied business effects |
| P13–P15 | Original durable approval, follow-up receipt evidence and original duplicate-command replay |
| P16 | Accepted supplier call with lost response retains its original unknown attempt and held reservation |

## Implement and configure the port

Implement a stable finite dictionary `identity` and an actual async
`complete(messages, tools) -> ModelResponse`. Completion output may be any
finite generic JSON, including null, booleans, numbers, arrays and objects.
It need not be text. Usage may be unknown. Tool proposals use registered names
and JSON argument objects; their call IDs may be absent. Capabilities, request
preflight, streaming and opaque continuation remain existing optional extension
ports. Core selection does not require them or add model routing.

Newly returned model evidence has a limit of 128 nested JSON containers per
response field. Excess depth is recorded as completed-invalid received evidence
and settles the original completion cost; it does not turn known completion
into an unknown model call. This evidence limit leaves the finite-JSON port
meaning, already received historical records and native provider identities
unchanged.

Register application code explicitly with existing `ComponentRegistry`. Validate
configuration before allocation. Create owned resources inside `BuildContext`;
use `register_async`, `abuild` and `own_async` for async construction and closure.
With explicit `owned=False`, the host retains its actual original source and
closes it after the original Runtime drains. A configuration file selects an
already registered factory and never imports arbitrary application code.

## Run the same business application

The generated `agent_app/adapter.py` contains the full independent source,
provider and business adapters. The source pins a persistent dataset UUID and
live physical file identity. It records every actual supplier request and
constructed response without deduplicating model calls. Those observations
do not dispatch, adopt or settle Runs. The business effect table implements only
the explicitly declared idempotent `record_resolution` tool effect; it provides
no model receipt or call inspection extension.

```shell
python -m agent_app seed
python -m agent_app run --kind agent --format sdk --command-id agent-first
python -m agent_app run --kind rag --format json --provider alternate --command-id rag-first
python -m agent_app run --kind plan --format toml --async --command-id dag-first
python -m agent_app run --kind plan --plan-mode flat --command-id rule-first
python -m agent_app run --kind team --borrowed --provider alternate --command-id team-first
```

All modes share `.ralf/business.sqlite` and `.ralf/runs.sqlite`. Explicit seed is
idempotent and adds the current cache runbook. Run and recovery never seed;
an unseeded app returns a rejected completed answer. Use distinct command IDs
for distinct runs. The primary/alternate choices change only the provider
declaration within the same mode; business tools, verifiers, retrieval and data
remain the same. SDK, JSON and TOML profiles have equivalent original identities.

SingleAgent proposes the actual current lookup and answers from its committed
receipt. RAG additionally retrieves and validates the current source, with
references observed in the original persisted model snapshot. Plan uses existing
RulePlanner or RuleDAGPlanner with bounded original child Runs, rather than
demonstrating intelligent planning. Supervisor Team supplies original worker
results to its supervisor. The provider processes actual incident input, tool
descriptors, returned tool results, disclosed source references and member input.

The bounded business completion verifier correlates the original requested
incident with the actual receipt arguments, result and final answer. It applies
the same intent check to resolution receipts and recognizes object, JSON-string
and wrapped child tasks; absent incident input selects the documented cache
default. Plan/Team additionally correlate each original child input with the
parent incident, original tool receipts and final-model consumption proofs.
Diagnostics follow only the original Run's child links; supplier counts or
retrieval candidates do not become member or disclosure evidence. These checks
demonstrate this offline business wiring, with task/model/semantic quality null.

## Supply actual supplier controls

`ModelAdapterFixture.prepare(case_id, workspace)` may be sync or async. It returns
`ModelContractSession` containing the actual provider, up to sixteen declared
`ModelContractResource(resource, asynchronous=False)` owners and optional
`configure`, `inject_fault`, `pause`, `audit`, `reopen` hooks. Hooks prepare actual
supplier conditions beneath the adapter; they never supply a pass/fail verdict
or replace an original received response with a completed DTO.

- `configure("output", {"output": generic_json, "usage": optional_usage})`
  selects actual supplier output. Usage token counts are nonnegative integers.
- `configure("invalid-output", {"invalid": "nan" | "lazy" | "deep"})`
  generates invalid values at the actual supplier response boundary.
- `configure("tools", {"name": registered_name, "arguments": object,
  "call_id": optional_id})` emits the proposal against real descriptors and
  answers the follow-up from its actual tool-result messages.
- Faults are `provider-error`, `authorization-denied`, `identity-drift`,
  `method-drift`, `backend-swap`, `response-lost` and `reset`.
- `pause("complete")` returns `ModelContractPause(wait_entered, release)` for
  an actual suspended call. Both callbacks complete with None.
- `audit()` returns a primitive fixed-key snapshot; each case uses baseline
  deltas. `reopen()` reconnects to the original durable supplier source and
  returns None, without creating execution authority.

A native HTTP fixture maps these specifications to its real supplier transport.
Prompting a paid model to emit an exact fixture answer is not a substitute for
the control. Cancellation releases/drains original calls and engines before
owned supplier/workspace cleanup. If cleanup fails, retain the original suite,
handle `CloseIncomplete`, and retry `await suite.aclose()` on its creation loop.
Cancellation alone cannot prove that remote supplier work stopped.

If application shutdown is incomplete or cancelled, the escaping error retains
`application_cleanup`, a concrete owner with the original `runtime`, `instance`
and `source`. Keep it on the original loop and retry
`await error.application_cleanup.aclose(close_timeout=30)` after the supplier
can finish. The application preserves the original cancellation/close error;
it does not repeatedly time out internally. Owned supplier closure stays with
the original RuntimeInstance. The host closes a borrowed supplier only after
that original runtime drains. An actual source-close error retains the same
owner for retry and remains observable.

## Recover the original records

Keep the original application code, profiles and databases. The lazy original
factory resolves the accepted persisted profile; construction and read-only
status/events/diagnostics do not open or seed the supplier source.

```shell
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine inspect RUN_ID
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

Actual waited/reaped process checks exercise three boundaries in the editable
app: committed final model response before decision adoption, accepted supplier
response lost before local recording, and approved effect receipt before effect
adoption. The committed response resumes the same original Run with no extra
provider call. The effect receipt is adopted without repeating the accepted
write; one subsequent model call consumes its actual original result. In the
editable application's lost-response probe, the original Local engine first
catches the supplier error and records its unknown attempt; the process then
exits. Reconnect/read-only inspection preserves that unknown attempt and held
reservation with no automatic extra call. A process that exits immediately at
the supplier boundary instead leaves the original executing attempt abandoned,
unreceived and reserved until original recovery normalizes it. Supplier audits
cannot prove safe redispatch because the core port has no Action ID, model
idempotency key or inspection method.

An explicit resume preserves the existing recovery contract: it may create a new
model Attempt on the same Action/snapshot, another call and another reservation,
while retaining the previous unknown evidence and held cost. Inspection is not
an instruction to retry. See [original recovery guide](recovery-guide.md).

This is a candidate bounded replacement/configuration/recovery subset, pending
final source/wheel/installed acceptance receipts. It leaves
arbitrary remote services, Temporal Worker/History, real model/task quality,
routing, index lifecycle, ToolSource/Runner, deployment, native continuation
certification, external adoption and whole R01–R26/H3/M1 gates open. Existing
native continuation and full-history recovery remain compatibility checks.
