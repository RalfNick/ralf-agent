# SDK model and typed-tool foundations — dev22

Approved intent: implement the previously accepted roadmap in order, beginning
with model/tool developer foundations, preserving current dev21 and local-only
work. This increment delivers a native protocol, typed tool convenience and
bounded reusable compatibility checks. Sandbox, live event/UI, automatic in-Run
compression, semantic RAG and enterprise services remain subsequent increments.

## Boundaries and implementation

OpenAIResponsesProvider uses existing HTTP lifetime/preflight/capability ports.
It transforms plain text and function-call histories to stateless input items,
sets store=false, keeps call_id distinct from item id, uses function strict=false
to preserve host JSON Schema behavior, and supports native JSON-object or explicit
strict object Schema output. It accepts completed assistant text/function items,
validates usage and rejects refusal/incomplete/server tools/media/reasoning items
instead of losing required continuation state. SSE requires monotonically ordered
semantic events and a complete final snapshot; received text/argument fragments
and all observed completed items/content must agree with that snapshot.
Response identity and item/call IDs cannot change; local output validation must
never retrieve external Schema references. Fragments cannot execute tools or become receipts.
ModelResponse, NativeHarness, engine authority and old native identities stay fixed.

ToolRegistry.register_function / tool decorator adapt keyword Python functions
to existing (arguments, InvocationContext) handlers. infer_tool_schema supports
bounded JSON-shaped primitives, lists, string-key dicts, fixed tuples, unions,
Literal and Annotated base types. Postponed annotations use a pure whitelisted
AST parser, never eval/get_type_hints. Missing/unsupported types require explicit
Schema; positional-only/variadic signatures fail preflight. Optional explicit
context_parameter injects host context and never accepts it from model args.
Defaults are validated and captured as private JSON snapshots; only their digest
is exposed in registration identity. Effective values are validated and materialized
in Local proposals and Temporal observations before digest/approval/policy, and
appear in private operation evidence when used. Explicit Schemas must declare the
callable parameters in a closed object. Secrets use host context/config instead. Hidden captured dependencies still require explicit version/config. New immutable wrapper identities
include original callable and bridge code without altering legacy identities.

Compatibility checks run text, structured and read-only echo-tool scenarios in
managed LocalEngine Runs with fixed definitions, private durable evidence,
max-case/max-call/output/time limits and sanitized public reports. Provider None
returns not_run. Offline fixtures never claim model quality; online checks prove
only the selected protocol/scenario/configuration. Borrowed providers stay owned
by caller; reused evaluation helpers provide invocation timeout, call accounting
and call evidence. Public identities/codes use an explicit typed/known projection. No automatic paid calls, credentials or external business tools.

## Acceptance

TDD covers exact request shapes, function roundtrip under approval/restart, SSE
ordering/final mismatch/refusal, native formatting and config preflight; typed
schema/async/context/default/invalid annotation/registration identity; managed
probe budget/error/usage/private evidence and no-provider default. Real HTTP
transport fixtures, SDK installation, actual dev21 wheel/native History recovery,
all old18 starter contents, base imports/dependencies and full service regression
must pass. One fresh final review, one Important/Critical fix pass, no remote writes.

Protocol references: [function calling](https://developers.openai.com/api/docs/guides/function-calling),
[structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
[streaming](https://developers.openai.com/api/reference/resources/responses/streaming-events).
