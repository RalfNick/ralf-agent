# Planning proposal quality — dev15

`evaluate_planning` runs the actual ModelDAGPlanner through a managed native child
Run, with a frozen 20-case suite available in the installed package. Cases cover
different evidence, authorized targets, dependencies, parallel plans, conditions,
parameters, refusal and missing-information stops. Oracles evaluate semantics and
Schema compatibility, without requiring particular node IDs or list ordering.

The evaluator measures proposed plan quality only. It does not execute business
workers, assess answer quality or demonstrate framework superiority. End-to-end
task quality and an equal-model LangGraph/AgentScope comparison still require their
own fixtures and actual business execution.

```shell
# Safe default: reports not_run, performs no model call.
relf-evaluate-planning
# Source-only explicit offline fixture: tests scoring and managed evidence.
python examples/evaluate_planning.py --fixture evals/planning-fixtures.json --evidence-dir /tmp/ralf-offline-new
```

Offline fixture results always have `model_quality: null`, including perfect
scores. A real configured run can use:

```shell
relf-evaluate-planning --provider openai --model-env RALF_PLANNING_MODEL --key-env OPENAI_API_KEY --max-cases 20 --max-calls 20 --max-output-tokens 2048 --timeout 60 --evidence-dir /tmp/ralf-live-new --report /tmp/ralf-live-new.json
```

Set credentials locally; values are not printed. `--provider anthropic|gemini`
and `--base-url-env` select the existing native HTTP protocols. Compatibility with
a particular hosted gateway/model must be tested against that configuration.
There is no silent credential discovery or model selection.

EvaluationLimits bounds case count, total calls, repeats, per-request timeout and
output tokens. Prices can annotate observed token usage; unknown usage/cost stays
null. A strict `--max-cost-usd` request fails closed with not_run because the current
Provider contract cannot guarantee a monetary input/billing ceiling. Integer
execution credits are also not a currency cap. Agree on actual calls or configure
an enforceable provider billing control before paid evaluation.

Failures, malformed proposals, unknown outcomes and unattempted repeats stay in
the denominator. The public report has categories, decisions, latency, usage and
evidence digests; private fresh-directory SQLite evidence retains raw responses
and managed Actions, including rejected proposals. Report paths are checked before
calls. Keep private evidence access controlled; do not publish it as a redacted
benchmark report.

Completed reports additionally include `summary`: per-task repeated pass rates,
attempted rows, call counts, all-repeats-passed and mixed-outcome task counts,
and dimension numerators/denominators. Missing dimensions and unattempted repeats
remain failures. These are descriptive measurements; repeats of the same task
are not independent task samples or evidence of statistical superiority.
Offline identities (including `kind="offline"`) keep `model_quality: null`.
The oracle checks required evidence references and fully static object bindings
against the complete input Schema. Unknown member outputs still need execution
and business validation; a passing proposal cannot prove those runtime values.
Provider preflight must complete synchronously with `None`; lazy/async validation
is rejected before model dispatch rather than silently ignored.

The current increment supplies the runner, frozen cases, protocol fixtures and
offline validation. No real-model quality result is asserted without an actual
configured run. See [dynamic DAG](dynamic-dag.md) and [implementation status](implementation-status.md).
