# H2c1 — Temporal native Agent facade

Continue the user-approved ideal Harness roadmap inline. Preserve all existing
dev31/dev32 dirty changes, original Local facade/Session behavior and Temporal
History/command/release identities. No automatic commit, remote publication,
new base dependency, paid-model call or unrelated private-workspace access.

## Scope and choice

Deliver `Runtime.from_temporal(engine, owned=False, authority_locator=None,
close_timeout=30, close_policy='detach')` for native AgentSpec and sequential
WorkflowSpec, through the existing Agent/AgentHarness/AgentRun/RunRef/WaitResult.
Reuse existing AsyncExecutionEngine/AsyncRuntimeDiagnostics contracts; do not
create a third execution authority or modify Workflow/History. A small private
Temporal client Runtime specializes hosting while common async observation and
control hooks preserve the Local implementation. Standalone Agent stays Local.

A complete backend refactor is unnecessarily invasive now; a separate public
RemoteAgent would fragment the entry API. Specializing the existing Runtime
and using common hooks keeps application API and recovery identity shared.
Graph/Team/Dynamic/nesting facade, bindings, shared Sessions, FIFO, deadline,
input and handoff refuse before network acceptance. Their existing raw Temporal
APIs remain unchanged. Full H2/Harness and AgentScope parity remain pending.

## Authority and identity

Server Workflow/History owns accepted intent, Actions, approvals, budget and
terminal state. Runtime owns only outbound submit/resume/control RPC tasks.
Capture immutable input/parameters before scheduling; caller cancellation cannot
discard an already-started managed RPC or cause business cancel. Drain those RPCs
before owned facade closure; actual event-loop/process loss still requires the
original command_id for retry/explicit recovery. Never generate a replacement
submission ID after an ambiguous response.

The opaque authority locator is a digest of the actual client service endpoint,
namespace and optional host alias seed, excluding queue/release/secrets. Pin client
object, configured namespace and trusted Scope for this Runtime. Queue/default
release moves cannot change historical receipts. New submissions use current
registered release; historical replay and controls validate original Run digest.
Endpoint aliases require consistent host canonical configuration; no cluster-ID
discovery or live migration is promised.

`await runtime.areference(run_id)` and `await runtime.aattach(ref)` query original
diagnostics and validate Scope/locator/release and native backend before use.
The Local variants are additive wrappers around existing synchronous operations.
Remote synchronous reference/attach explicitly request the async variants. Attach,
status/events/diagnostics/pending/wait send only queries. Accepted submit/control
wake the existing server Workflow; explicit resume requests its existing drive command with zero polling duration;
Workflow execution remains server-owned. Terminal Run observation is separate
from real server Activity stop; client detach does not prove stop or rollback.

## Waiting

Local wait behavior remains unchanged. Remote handles start with a detached,
validated snapshot from submission or async attachment. Each wait queries fresh
diagnostics; timeouts bound the observation, including slow queries, without
drive/cancel. Timeout returns the last successfully observed snapshot and its
actual observed_at, not a fabricated fresh server state. Zero timeout can return
that known observation. Caller cancellation propagates CancelledError and ends
only the query. Failed queries propagate errors; no hidden provider/model retry.
Returned mutable snapshots must not mutate the handle's internal observation.

## Ownership and close

Shared Agent closes only its entry. Remote Runtime defaults to detach; drain/cancel/
handoff policies refuse explicitly. It stops accepting work, awaits actual managed
RPC completion, then closes owned TemporalEngine facade only. Client and Workers
are always borrowed under the existing engine contract. Close timeout/cancellation
retains shielded cleanup; retry follows original H2a state semantics. Remote parked
RunRefs are not a client-owned business history; callers retain their refs/command
IDs. RPC history must not retain completed tasks or every historical Run.

## Acceptance

TDD: same Agent API succeeds with Local/Temporal; native/sequence approval/replay,
wait cancellation/timeout (including blocked query), input detachment, pending RPC
close/caller cancellation, wrong Scope/locator/release/resource/loop, borrowed versus
owned close, retry after close failure, original-release replay and refusal before
network. Use existing pure Temporal state with a protocol-client test double for
offline RPC behavior, and an opt-in actual Temporal Service/Worker acceptance with
History replay. Actual service probe uses local persisted service and explicit
offline Provider; absence is reported, never counted as passed. Build actual dev32/
dev33 wheels, verify Local schema1/schema2 recovery and byte-equal packaging,
optional-free imports, unchanged dependencies/starters and final full regression.
One fresh final reviewer; one TDD Important/Critical fix pass, no re-review.
