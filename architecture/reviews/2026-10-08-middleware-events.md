# Invocation middleware and durable event review — dev23

2026-10-08. Local development following the accepted
[alignment order](../../docs/agentscope-alignment.md). This first A2 increment
adds opt-in invocation middleware and resumable observation of committed Run
events. Input continuation, workspace tools and Sandbox remain later increments.

## Delivered boundaries

- Immutable invocation records and structural Provider/ToolExecutor wrappers,
  with synchronous before/after hooks, strict completed-None returns, no-op and
  metadata logging defaults. Profiles can assemble registered adapters explicitly.
- Current Python entry code and declared configuration participate in identity,
  including optional model stream/preflight presence and mode. Middleware never
  rewrites the approved operation or takes execution authority.
- After hooks and their dispatcher are best effort. Failures do not erase known
  model/tool receipts; identity drift remains visible for the existing Engine
  to reject the original release after persisting received evidence.
- Scope-bound cursor/envelope ports, bounded pull subscriptions over sync or async
  readers, terminal tail draining and an SSE wire encoder. Observation does not
  drive, cancel or close an Engine. A cancelled read is joined before cleanup;
  interrupted close remains retryable.
- Read-only ralf-watch-events CLI and twentieth packaged observable starter.
  Existing nineteen starter dictionaries and default runtime identities remain
  compatible. No new base dependencies or optional SDK requirements.

See the [guide](../../docs/middleware-and-events.md) for custom hooks, default
profiles, resource ownership, cursor persistence and installed usage.

## One independent review and one fix pass

One fresh reviewer ran all65 initial feature tests and verified the actual dev22
baseline. Three Important findings were accepted, with no Critical or Minor:

1. Optional stream/preflight implementations were absent from delegate identity.
   Code changes or new optional methods could dispatch under an old identity.
   Their presence, mode and normalized entry code are now pinned and verified.
2. Replacing the after dispatcher during an awaited call could discard an already
   received model/tool result. A safe outer after boundary now preserves receipts,
   including streaming completion, while release drift still causes refusal.
3. Timeout cancellation followed by another cancellation could lose the private
   read task during cleanup. Reads now use a non-propagating timed wait and one
   cancellation request; shielded cleanup keeps the task until it actually finishes.

Eight permanent regression tests failed before the fix pass; all73 focused tests
pass afterward. One covers actual Engine persistence of the received response
before refusing a changed release. No re-review or implementation delegation.

An initial full actual-service run had1834 passes and one existing Temporal test
failure: it queried a child Run during the durable-intent-to-StartChild acceptance
window. Production authority code is unchanged. The test now retries only typed
NotFound within its original deadline and still requires the actual child credit
reservation before cancellation. Strict quiescence, spent/reserved/unknown and
History replay assertions are retained. The affected test and new subscription
recovery case pass against the actual service.

## Scope decisions and their costs

- Existing user authorization permits inline implementation and preserving the
  dirty workspace. No commit, push or publication; cost: no published release.
- Middleware/events precede input/Workspace/Sandbox contracts; cost: A2 and full
  AgentScope parity remain incomplete.
- Synchronous observer hooks preserve the receipt adoption boundary; cost:
  async telemetry consumes separate events, and before failures can leave
  conservative unknown intents/credits under existing execution semantics.
- Actual service/install/History gates are completed locally by the author;
  cost: evidence covers tested combinations, not arbitrary production deployments.
- No new live credential or model calls; cost: online endpoint interoperability
  and real task quality remain unverified by this increment.
- Reader code is trusted, bounded and cancellation-cooperative; cost: no forced
  preemption of blocking Python or proof of remote server-side cancellation.
- Captured/global host dependencies require explicit identities/configuration;
  cost: undeclared dependency drift is outside these guarantees.
- Prior increment code is byte-preserved and compatibility-tested, without a new
  whole-project independent audit; cost: this review does not certify all older
  features for production. No deferred Minor findings.

## Final verification

- Full actual-service suite: **1843 passed in389.47s**, warnings treated as errors.
  The initial failure and its narrowly corrected test precondition remain recorded.
- Outside-checkout installed wheel: **625 passed in125.38s**. Optional SDKs blocked:
  **556 passed,7 expected skips in21.44s**. The focused review regressions and actual
  Temporal middleware/events recovery case are included in these final gates.
- Actual dev22 wheel native/parallel Graph/Team/flat/DAG/nested receipts recover
  under dev23, retaining exact pre-resume records, duplicate controls, scoped
  Sessions and one business write per parent. Native Temporal Run/registry History
  replay/continuation and installed Temporal starter across Worker restart pass.
- Original nineteen starter dictionaries remain unchanged; twenty are available.
  260 public exports import without optional SDKs. All120 SDK modules match source,
  tested wheel and installed package; final artifacts refresh only documentation
  and retain those tested SDK bytes. Base requirements and six extras are unchanged.
- Ruff, format, Git whitespace,31 relative-document link sets, CI YAML/Python support
  matrix and requirements checks pass locally. Build/source/wheel/sdist/installed
  identities and credential-like literal exclusion are checked on final artifacts.
  Task-owned PostgreSQL/Qdrant/Temporal services stop after verification.

All checks are local; remote CI and paid protocol/quality evaluation are outside
this increment. Changes remain in the existing workspace without commit or push.
