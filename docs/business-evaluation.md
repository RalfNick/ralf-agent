# Business-task evaluation

`ralf-evaluate-business` / `evaluate_business` runs actual native Agent model/tool
loops against an independent SQLite ticket service. Eight versioned cases cover
exhausted connection pool, full disk, bad deployment, missing/ambiguous target,
missing evidence, destructive request and approval bypass. They check the final
outcome, tool parameters, stopping, approval and reconstruction from durable
execution/effect records. Repeated submit and approval must retain the same
receipts and one business write. This complements structural plan-proposal
[evaluation](planning-evaluation.md); it is not a cross-framework benchmark.

```shell
ralf-evaluate-business                     # not_run, no external model request
ralf-evaluate-business --offline --max-calls 16
ralf-evaluate-business --provider openai --model-env RALF_EVAL_MODEL \
  --base-url-env RALF_EVAL_BASE_URL --key-env RALF_EVAL_KEY \
  --max-cases 8 --max-calls 32 --timeout 60 --max-output-tokens 2048 \
  --report business-report.json --evidence-dir private-business-evidence
```

The OpenAI-compatible adapter supports configured domestic/overseas endpoints;
Anthropic and Gemini text protocols are also selectable. No credential discovery
or default paid model is used. Model/key/endpoint environment names are explicit.
Model output is scored as behavior, rather than repeating one scripted happy path.
The default offline Provider applies deterministic rules to diagnostic evidence;
its results are regression evidence, with `model_quality: null`. Fixture/scripted/
offline/test Provider identities also retain this label even if offline is omitted.

EvaluationLimits enforces maximum cases/repeats/model dispatch attempts and per-call
timeout; output-token bounds apply to the configured HTTP adapter. Failed/unknown
calls remain in the denominator. Provider usage is reported only when every
attempt supplies valid token counts. Optional per-million token prices estimate
cost; missing usage remains null. `--max-cost-usd` fails closed before model
requests because input/billing cannot be guaranteed bounded by this preview.
Execution credits do not represent dollars. Choose a call budget explicitly.

Live SDK Providers must declare `max_output_tokens` and `timeout` matching
EvaluationLimits before evidence allocation or dispatch; missing/mismatched
bounds return `not_run` with `provider_bounds_unverified`. Identity declarations
are a trusted adapter contract, not an enforceable supplier billing guarantee.
The restart check only drives terminal Runs. Unfinished/unknown Runs are observed
without dispatch and score `recovery: false`; evaluation does not retry a failed
request merely to measure recovery or change the original task outcome.

Completed reports include `summary`, with per-task repeated pass rates, attempted
rows, call counts, all-repeats-passed and mixed-outcome task counts, and metric
numerators/denominators. Failed and unattempted repeats remain in the denominator.
These descriptive counts do not treat repetitions as independent task samples.
For example, `--offline --repeats 3 --max-calls 48` checks all eight fixtures three
times while retaining `model_quality: null`; live repeats require explicit model
configuration and their own call budget.

Reports include dataset identity, per-case metrics, latency, calls, usage, estimated
cost, durable replay and restart checks. Raw prompts, responses and business
records stay in the private evidence directory; reports omit them. Files are
created exclusively with restricted permissions and existing evidence is never
replaced. A custom case document has version `"1"` and a nonempty cases list;
`load_business_cases()` returns editable detached defaults for SDK callers.

No live model run is evidenced by shipping this evaluator. An explicitly configured
and completed live report is needed before claiming task quality; enterprise
identity/production integrations and AgentScope/LangGraph parity need their own
acceptance measurements.
