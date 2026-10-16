# Python 工具与模型 SDK

普通 Python 函数可直接注册为工具，框架负责参数 Schema、默认参数及受管理执行。
先用下面的 `ToolRegistry.tool` 或 `register_function` 接入业务函数；完整最小 Agent
见[README](../README.md#编写自己的-agent)。模型协议与配置见[模型接入指南](model-adapters.md)。
不需要先接入 MCP、沙箱或分布式执行。

下文同时保留 dev22 引入的原生 Responses 适配器和兼容探针说明。
Responses 推理续接使用独立、显式启用的适配器，见[推理续接指南](responses-reasoning.md)；
不能将基础适配器拒绝 opaque 状态理解为所有适配器都不支持。

## Register ordinary Python functions

```python
from ralf_agent import ToolRegistry

tools = ToolRegistry()


@tools.tool(effect="read_only", description="Find a record by its ID")
def lookup(record_id: str, limit: int = 5):
    return {"record_id": record_id, "limit": limit}


# lookup remains an ordinary callable.
assert lookup("A-1") == {"record_id": "A-1", "limit": 5}
```

Use register_function(function, ...) for programmatic registration. Keyword
functions and bound methods are supported; positional-only/variadic signatures
need the existing explicit ToolSpec/(arguments, context) API. The bridge adapts
keyword arguments to that executor contract, including async function results.
Effect must be declared. Annotation inference never grants approval or permission.
Write tools retain their existing effect, approval, budget and recovery semantics.

Supported inference: str/int/float/bool/None, list[T], dict[str,T], fixed tuple
arrays, unions/Optional, homogeneous Literal values and Annotated's base type.
Annotated metadata is ignored; use explicit input_schema for constraints.
Postponed annotations use a bounded AST whitelist, never eval/get_type_hints.
Named user types, Pydantic/dataclass conversion, aliases and arbitrary expressions
require an explicit input Schema or an explicit custom adapter. Values remain JSON
values; Python tuple annotations describe fixed JSON arrays, not a coercion API.

Generated schemas reject extra fields and distinguish required parameters from
parameters with defaults. Defaults are validated, captured in private JSON
snapshots and copied for each call. Only a digest enters implementation identity;
values never appear as Schema defaults. Changing defaults changes a new
registration's identity. Source-less Python code has a normalized bytecode digest.
Captured owner/global dependencies still require explicit version/config identity.
Changing the original function's `__defaults__` or `__kwdefaults__` after registration
cannot supply an omitted required argument; execution uses the captured defaults.
Parameter completeness also uses the frozen declaration, not a later `__signature__`
or a mutable descriptor copy. Signature metadata cannot hide required inputs or
introduce additional requirements into an already registered tool.
Register a new definition when changing the intended defaults.
Explicit Schemas must be closed object Schemas declaring exactly the callable
parameters, with each default checked against its parameter Schema. Effective
merged arguments are validated again. Local proposals and Temporal model Activities
resolve defaults before the operation digest, approval and host policy, so the
approved arguments match execution. Resolved defaults appear in private Run and
approval records when used; secrets belong in host context/config instead.

When supplying an explicit Schema, declare the Python function's required inputs
in `required` (or equivalent constraints). The shared proposal boundary also
rejects a missing required callable argument, even if the Schema admits it;
it cannot become an approval request or a dispatched tool call. Captured defaults
and the separately injected host context retain their existing behavior. The
framework preserves the supplied Schema and existing tool identities, including
valid `allOf` constraints; it does not rewrite stored approvals or repair old Runs.

To receive the host context, declare context_parameter explicitly:

```python
@tools.tool(
    effect="idempotent_write", requires_approval=True, context_parameter="context", version="1"
)
def apply(value: int, *, context):
    return business_service.apply(value, idempotency_key=context.effect_key)
```

The Context parameter is absent from inferred model Schema. Supplying it in model
arguments is rejected even with an explicit Schema; only the executor injects it.
Existing low-level registration and manifests stay unchanged.

## Native Responses

```python
from ralf_agent import OpenAIResponsesProvider

provider = OpenAIResponsesProvider(
    "YOUR_ACTUAL_MODEL",
    max_output_tokens=1024,
    timeout=30,
    json_mode=True,
)
# Reads OPENAI_API_KEY; the caller controls borrowed HTTP client lifetime.
```

Runtime profiles select adapter="openai-responses". Credentials use api_key_env;
keys do not belong in JSON/TOML. base_url defaults to https://api.openai.com/v1.
Text/functions, complete SSE, temperature/top_p, capability restrictions and
native JSON formatting are supported. seed/stop are unsupported. An optional
reasoning_effort="none" is sent explicitly; model/account support is not inferred.

The adapter sends store=false and complete explicit input history, without
previous_response_id. Function call_id is preserved separately from output item
id. Client tools use strict=false, retaining the host's optional/default/Schema
semantics. Provider only proposes calls; Engine/ToolExecutor own authorization.

json_mode requests text.format=json_object and requires a JSON instruction.
Alternatively output_schema plus schema_name requests native strict structured
output. The supported subset requires a root object, closed objects, all property
names required and local references; unrecognized native keywords fail preflight.
Use nullable fields for optional output values. Schema and name are pinned in
identity; actual final JSON is also validated locally. Every schema-bearing
location is traversed, object constraints require an explicit object type, and
the local validator uses a registry that refuses external retrieval.

Reasoning items/opaque continuation, server tools, refusal, media and nonempty
annotations are explicitly refused. They cannot be faithfully represented by the
current text/function ModelResponse. A successful protocol fixture is not a claim
that every Responses model or endpoint works. SSE requires semantic event ordering,
completed status and final agreement with collected text/argument fragments,
completion metadata, function/call IDs, content parts and response identity. Text
fragments are display-only; decisions are complete responses, not stream chunks.
This does not add durable live Run events or a WebSocket transport.

References: [function calling](https://developers.openai.com/api/docs/guides/function-calling),
[structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
[semantic streaming](https://developers.openai.com/api/reference/resources/responses/streaming-events).

## Bounded compatibility checks

```sh
ralf-check-model                         # not_run; no key reads or network calls
ralf-check-model --offline               # deterministic fixtures; not model quality
ralf init my-model-check --template model-check
cd my-model-check
python -m agent_app
```

A real check is explicit and may incur fees:

```sh
ralf-check-model --adapter openai-responses --model YOUR_ACTUAL_MODEL \
  --api-key-env MY_MODEL_KEY --max-calls 6 --max-output-tokens 1024 \
  --timeout 30 --evidence-dir PRIVATE_FRESH_DIRECTORY
```

SDK: await evaluate_model_compatibility(provider, cases=[...], limits=EvaluationLimits(...),
evidence_dir=...). Providers are borrowed. Choose cases text/structured/tool/stream/
stream_close. Defaults allow five cases and six model attempts; the echo tool is
read-only and checks exact arguments and its durable result. Native capabilities
that disable tools/streams are recorded as unsupported, not silently enabled.

Completed text, structured, tool and stream probes also check the requested final
output `{"ok":true}` separately from runtime success and tool receipts. JSON text
and equivalent object output are accepted; false, numeric 1, extra fields or
duplicate JSON keys fail the output check. The intentional stream_close probe
continues to measure early consumer cleanup rather than a final answer.

Each scenario runs through managed LocalEngine authority with bounded decisions
and credits. Private SQLite evidence is mode0600; use a fresh directory for every
probe. Public reports contain receipt IDs, checks and known/unknown token usage,
not raw answers or exception strings. Provider metadata has a typed projection;
unknown generation keys and error codes never pass through to public reports. max_calls includes attempted invocations;
preflight failures and absent optional stream ports need not cause HTTP calls.
Configure actual Provider output limits within the declared probe allowance. Call
timeout bounds the awaited client, not arbitrary trusted code or supplier work.
Currency caps return not_run because the generic port cannot enforce billing.

stream_close closes the consumer after its first text event and checks completion
of aclose. The original Run correctly remains waiting_reconciliation with unknown
model outcome/usage. It proves neither upstream cancellation nor billing refunds.
Whole usage is null if any call has unknown usage; known_usage is only the subtotal.

Offline and online reports always keep model_quality=null. These are narrow
protocol/scenario checks; use the frozen business/planning evaluation for task
quality. This increment makes no new paid calls or online compatibility claim.
