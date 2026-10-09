# SDK model/tools foundation review — dev22

2026-10-08. Local development only, following the accepted order in the
[alignment roadmap](../../docs/agentscope-alignment.md). This increment improves
model/tool developer defaults; it does not complete AgentScope parity or M1.

## Delivered contracts

- Native stateless Responses text/client functions, JSON-object/strict Schema
  formatting, complete SSE and capability refusal, using existing Provider,
  Harness and execution authority. Reasoning/media/server tools remain refused.
- Typed Python tool registration with pure annotation inference, keyword bridge,
  explicit host Context, captured defaults and new implementation identity.
  Existing low-level registrations retain their identity and behavior.
- Managed five-scenario compatibility SDK/CLI and nineteenth offline starter.
  Explicit limits, private receipts and safe public reports; no provider means
  not_run. Consumer stream close retains unknown outcome/usage.

See the [SDK guide](../../docs/sdk-model-tools.md) for supported shapes and limits.

## Independent review and one fix pass

One fresh independent reviewer ran all 62 initial dev22 tests and local
reproductions. Four Important findings were accepted:

1. **P1: nested untyped Schema escaped remote-reference traversal.** All Schema
   locations are now traversed, native object constraints require an explicit type,
   and local validation uses a registry that refuses external retrieval.
2. **P2: contradictory SSE done metadata was ignored.** Received items, parts,
   text/argument completions, output identities and response IDs are checked against
   the complete snapshot. Fragments after completion are refused.
3. **P2: explicit typed Schema did not validate captured defaults.** Registration
   checks each default and dispatch checks effective merged arguments. A related
   Local policy bypass was reproduced: omitted target defaulted to production only
   after authorization. Both Local proposals and Temporal model observations now
   resolve defaults before operation identity/approval/policy. Actual operation
   values appear in private approval records; secrets use host Context/config.
4. **P2: provider-controlled nested identity and exception codes leaked into
   public probe reports.** Public identity uses a bounded typed field projection;
   unknown generation keys and error codes never pass through.

Regression evidence: 17 failures before fixes plus four passing controls. The
Temporal default fixture initially used a write without the required journal;
corrected read-only observation independently reproduced raw arguments before
fixes. All 127 focused/related tests pass after the one fix pass. No re-review,
additional implementer or deferred Minor findings.

## Verification scope

The initial full actual-service suite passed 1748 tests before the fix pass; it is
not the final acceptance evidence. Final suite, installed-wheel and package gates
are recorded below once complete. Local test services include PostgreSQL, Redis,
Qdrant and persisted Temporal with actual process/replay tests.

The reviewer did not judge live endpoint compatibility, general model quality,
supplier cancellation/billing, service/History/installed-wheel gates or Python3.14
lazy annotations. Author decisions: run actual local service/History/wheel gates;
leave new live interoperability and quality unverified; stream close proves only
consumer cleanup with unknown supplier outcome; supported Python remains3.11–3.13.
These limits apply even when offline checks pass. No new paid calls or credentials
are used; previous real trial evidence is unchanged. No commit, push or release.

## Final evidence

- Full actual-service suite: **1769 passed in365.20s**, warnings as errors.
- Outside-checkout installed wheel: **551 passed in125.22s**.
- Optional SDKs blocked: **483 passed,7 expected skips in34.49s**.
- Actual dev21 wheel native/parallel Graph/Team/flat/DAG/nested receipts, duplicate
  controls, scoped Sessions and one business write per parent recover with dev22.
  One-shot upgrade fixtures require a fresh queued snapshot and their original
  sequential prerequisites; failed fixture reruns are retained in the local ledger.
- Actual dev21 native Temporal Run/registry History replay and command continuation,
  plus installed Temporal starter DAG/Team/RAG and approval across Worker restart,
  pass. Original eighteen starter dictionaries are unchanged; nineteen are available.
- 249 unique public exports import with optional SDKs blocked. Base requirements and
  six extras are unchanged; all111 SDK modules match source/wheel/sdist/installed.
- Ruff, formatting, Git whitespace,27 relative-document link sets, CI YAML/support
  matrix and requirements checks pass. CI configuration is local; remote CI was
  not run. Final artifacts contain current guides/review, no private evidence or
  credential-like literals. Task-owned services are stopped after all gates.

No new live protocol or real-model quality claim follows from these gates.
