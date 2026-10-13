# Configured ModelProvider replacement and business composition

Status: implementation design under the standing R01–R26 goal. The user has
authorized continuous implementation and parallel development, with local
commits only. This extends the already approved Harness/Local/Temporal and
capability contracts; it does not replace the execution or configuration model.

## Outcome and limits

Deliver a configurable ModelProvider replacement, a fixed installed contract
suite, and one editable application across Agent, current-source RAG, existing
rule DAG Plan and Supervisor Team. Use real disclosed sources and tool receipts
for the application's verification. Keep the existing five-scenario model-check
evaluator, its selectable scenarios and online quality meaning unchanged.

Finishing this increment closes a replacement/configuration/recovery subset of
R01/R04/R05/R07/R25. It does not close whole rows, H3/M1/R26, model routing,
streaming/native continuation extensions, semantic quality or independent
adoption. After this increment, prioritize the next concrete default-chain gap
from the full queue, rather than indefinitely implementing only role suites.

The default provider is an independent offline implementation. It must process
actual supplied messages and tool descriptors; it must not delegate to EchoProvider,
OfflineCompatibilityProvider, repository tests or a packaged scripted reader.
Its durable source audit records observations, not a model receipt, deduplication
cache or execution authority. No real model or remote service is automatically
selected. Explicit native provider configuration remains available.

## Preserved contracts

`ModelProvider.identity` and async `complete(messages, tools) -> ModelResponse`
remain the core port. Output is finite generic JSON, not necessarily text.
ToolCall call IDs may be absent. Capabilities, request preflight, streaming and
opaque continuation remain optional existing extensions; do not require them
from core providers or silently remove required selected cases.

Local/Temporal retain their own sole authority. Original Agent, Action, attempt,
release/profile, Turn, approval, effect receipt, reservation, received response
and decision-adoption records determine recovery. The suite does not certify
Temporal History from Local results. It does not patch native provider methods,
republish native identities, change recommended defaults, discover credentials,
add provider-hidden retries or fallback.

An accepted call with a lost response stays `outcome_unknown`, with the original
unknown reservation. The generic port supplies no Action ID, idempotency key or
inspection method, so equal prompts and source audits cannot prove exactly-once
or zero-cost redispatch. Read-only reconnection/inspection does not dispatch.
Preserve the existing explicit `resume`/`drive` behavior: it may start a new
separately reserved Attempt on the same original Action/snapshot, retaining the
old unknown attempt/hold. Configurable unknown-model retry policy remains open;
this increment does not silently change existing default/history contracts. A
committed received response is adopted on the same Run
without calling the provider again. Completed invalid JSON evidence is distinct
from an unreceived response. Deep/nonfinite/lazy completed values must not leak
coroutines or lose known completion merely because evidence encoding fails.
Newly returned response fields have an explicit limit of 128 nested JSON
containers, checked before recursive encoding or copying. Deeper completed
values become received-invalid evidence and settle the original completed
Attempt; they do not become unknown external work. This bounded capture policy
leaves generic scalar/null output, native provider identity and already-recorded
historical responses unchanged. It is a supported evidence limit, not a claim
that deeper JSON is intrinsically invalid.

## Frozen catalogs

Select `AdapterContractSuite(role="model-provider", contract_version="1",
profile="core")` for P01–P10 and explicit `profile="tools"` for all P01–P16.
All selected cases are required. Catalogs are immutable and include profile in
their digest. Existing K/S/Facts catalogs, digests, canonical reports, aliases,
observation keys and status tables remain byte-compatible.

| ID | Label | Required observation |
| --- | --- | --- |
| P01 | identity-and-port | Stable finite identity and actual async complete |
| P02 | response-and-metering | Generic JSON completion, known and unknown usage |
| P03 | detached-request-and-response | Actual original request and received evidence detached from supplier mutation |
| P04 | completed-invalid-evidence | Original known completion, invalid adoption and lazy/deep cleanup |
| P05 | provider-errors | Actual domain errors and public redaction, retained unknown attempt |
| P06 | component-drift | Identity/method changes rejected at original acceptance boundaries |
| P07 | backend-drift | Selected actual source changes cannot silently satisfy pinned identity |
| P08 | lifecycle-and-suspension | Original suspended call drains before owned close; borrowed remains open |
| P09 | local-consumer | Actual default Agent completion and original metering |
| P10 | recorded-response-recovery | Same original Run adopts committed response without redispatch |
| P11 | tool-proposals-and-schema | Registered actual proposals, call IDs, Schema/default arguments |
| P12 | authorization-boundary | Denied business effect remains unwritten |
| P13 | durable-approval | Original signed approval and duplicate command, one actual effect |
| P14 | followup-tool-evidence | Actual tool receipt appears in the original follow-up model request |
| P15 | duplicate-submit-replay | Same original request/command returns original Run without extra calls/effects |
| P16 | accepted-call-lost-response | Original unreceived attempt/hold survive; inspection does not redispatch and explicit new attempts reserve separately |

Boolean observations are the existing common seven keys. Model count keys are
`model_calls`, `request_count`, `response_count`, `close_calls`, `backend_switches`,
`identity_checks`, `method_checks`, `consumer_runs`, `rejection_checks`,
`received_count`, `adopted_count`, `tool_calls`, `write_count`, `approval_count`,
`duplicate_checks`, `reservation_checks`, `settlement_checks`, `reopen_calls`.
Reports contain only fixed booleans/counts/digests and existing null quality fields.
Raw prompts, outputs, supplier errors and credentials are not public observations.

## Concrete fixture boundary

Add `ModelAdapterFixture.prepare(case_id: str, workspace: Path) ->
ModelContractSession`, accepting sync or async preparation. It prepares concrete
resources and supplier controls, never a verdict or substituted completed DTO.
The session contains `provider`, up to 16 `ModelContractResource(resource,
asynchronous=False)` owners, and optional callable `configure`, `inject_fault`,
`pause`, `audit`, `reopen` hooks. Missing required hooks mean `not_verified`.

`configure(kind: str, value: dict) -> None` configures the actual supplier below
the selected adapter. Kinds `output`, `invalid-output`, `tools` have detached JSON
specifications. Output supports generic `output` and optional `usage`. Invalid
output selects `nan`, `lazy` or `deep` through the `invalid` key; it is generated
at the actual supplier response boundary, not serialized as a pretend response.
Tools specifies `name`, `arguments`, optional `call_id`; the supplier emits the
proposal against actual descriptors, then answers from the actual returned tool
receipt. A native HTTP fixture maps specifications to its real transport shape.
Exact fixture responses are not demanded of a paid model merely through prompts.

`inject_fault(kind: str) -> None` supports `provider-error`, `authorization-denied`,
`identity-drift`, `method-drift`, `backend-swap`, `response-lost`, `reset`.
Each fault changes the actual selected resource/port. `pause("complete")` returns
`ModelContractPause(wait_entered, release)` for an actual suspended call; callbacks
finish with None. `audit()` returns a validated primitive snapshot of fixed keys,
including actual close counts. Use per-session baseline deltas; do not count
historical closes as current borrowed closure. `reopen()` reconnects the original
durable supplier audit/source, without returning a new execution authority.

Preparation, calls, resets and close retain the actual owner, loop and tasks.
Observation cancellation releases/drains original calls and engines before
owned sources or suite workspaces close. Failed cleanup remains owned by the
existing AdapterContractSuite and retried through its original `aclose()`.
Cleanup cannot infer that remote supplier work stopped from consumer cancellation.

## Independent application

Add `model_adapter_contract_reference.py` with an application-owned sqlite3
supplier audit and independent async provider. Add lazy sync/async factories
through existing ComponentRegistry/BuildContext. Validate configuration before
allocation. Explicit `owned=False` borrowing retains host ownership. The source
may record request/response counts and supplier settings, but never dispatch or
settle Runs. Source records survive process exits solely for actual observation.

Add `model-contracts` starter with a full editable `agent_app/adapter.py`, actual
business tools and bounded verifier, SDK/JSON/TOML replacement, explicit seed,
read-only diagnostics and original `agent_app.runtime:create_engine` factory.
Runtime execution and recovery never seed. Show Agent, current-source RAG,
RulePlanner/DAG Plan and Supervisor Team in the same app/data set with distinct
command IDs. Provider-only replacement preserves the other business components.
Reference Plan demonstrates existing deterministic orchestration, not intelligent
model planning. Verifiers check actual source/effect evidence rather than echo
success or output Schema alone.

Actual independent process windows cover committed model response before adoption
and accepted supplier response lost before local recording. The former recovers
without another call; the latter preserves unknown outcome/held reservation on
reconnection and read-only inspection. Explicit resume follows the existing
new-attempt contract, preserving original evidence and separately reserving cost.
An approved effect and its original receipt must not be repeated after restart.
Preserve native continuation and complete-history process recovery as compatibility
gates rather than adding mandatory continuation to this core suite.

## Acceptance

Meaningful RED→GREEN tests, one fresh whole-batch reviewer, same-author repairs,
final frozen regression and Ruff/format/whitespace checks. Build and install local
wheel outside checkout in core and SDK environments without source fallback.
Verify editable application modes, replacement, both configuration formats,
sync/async construction and owned/borrowed closure, plus actual waited/reaped
process windows and previous dev96 same-Run/default compatibility. Compare source,
wheel/sdist/installed bytes and documentation. Commit only accepted scope locally;
do not push or mark unverified quality/services/adoption or full R01–R26 complete.

## Self-review

Root ruling: the original [recovery guide](../../recovery-guide.md) and
[Action contract](../../../architecture/specs/action-recovery-contract.md) permit
explicit new model Attempts while retaining unknown costs. Preserve that behavior;
do not add a blanket unknown-model guard through adapter certification. The cost
of a wrong interpretation is a silent recovery compatibility change.

The suite observes the selected provider beneath existing authority. Its source
hooks prepare conditions, not outcomes. Generic JSON, optional ports, unknown
usage, real effects and lost-response uncertainty remain explicit. Configuration,
lifecycle and application usability are part of this deliverable. Routing,
index lifecycle, ToolSource/Runner, deployment and actual quality remain separate
open capabilities in the authoritative queue.
