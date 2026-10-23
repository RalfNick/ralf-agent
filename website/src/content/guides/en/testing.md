---
title: Testing & evaluation
description: Run an offline application regression, check model protocols, and separate fixture results from live task quality.
locale: en
slug: testing
sources: [docs/sdk-model-tools.md, docs/business-evaluation.md, docs/task-evaluation.md, docs/planning-evaluation.md, docs/agent-api.md, docs/completion-verification.md]
---

Install SDK `0.1.0a6` using [quickstart](/en/docs/quickstart/) and activate that Python environment first. The offline examples below need no model key, network service or pytest. They were checked against the pinned a6 source baseline.

## Choose the evidence you need

| Check | Question answered | What a pass cannot establish |
| --- | --- | --- |
| Application regression | Did our tools, output assertions, identity and recovery rules behave as expected under controlled responses? | Real model reasoning or task quality. |
| Model protocol compatibility | Did this Provider/endpoint handle the tested text, schema, tools and stream contracts? | General intelligence or success on your business tasks. |
| Task evaluation | Did actual configured model/tool execution satisfy independent task oracles? | Quality outside the frozen tasks, or production acceptance of unrelated integrations. |

Keep deterministic regression in your regular checks. Run compatibility when changing an adapter/endpoint; run live task evaluation against versioned application cases when judging model behavior. Offline evaluators intentionally report `model_quality: null`, even at a perfect score. Compatibility reports keep it null for both offline and live probes.

## A complete offline application test

Create a fresh working directory:

```bash
mkdir relf-offline-tests
cd relf-offline-tests
```

Save the following as `test_app.py`. This is a real managed Agent/tool loop with your own structural `ModelProvider`, not a call to an external model. `complete` returns a tool proposal first, then returns the actual tool result. The test checks the business output, durable tool completion and identical-command replay.

```python
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from relf_agent import Agent, ModelResponse, ToolCall, ToolRegistry


class OfflineProvider:
    identity = {"kind": "offline-application-test", "version": "1"}

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        receipts = [m for m in messages if m["role"] == "tool"]
        if not receipts:
            return ModelResponse(
                tool_calls=(ToolCall("lookup", {"ticket": "INC-001"}, "lookup-1"),)
            )
        return ModelResponse(output=json.loads(receipts[-1]["content"]))


async def main():
    provider = OfflineProvider()
    tools = ToolRegistry()
    lookups = []

    @tools.tool(effect="read_only", description="Read a test ticket")
    def lookup(ticket: str):
        lookups.append(ticket)
        return {"ticket": ticket, "status": "open"}

    with TemporaryDirectory() as directory:
        async with Agent(
            model=provider,
            tools=tools,
            instructions="Read the ticket and return its status.",
            db_path=Path(directory) / "runs.sqlite",
        ) as agent:
            run = await agent.submit("Check INC-001", command_id="test-001")
            observed = await run.wait(wait_timeout=5)
            assert observed.snapshot.state == "succeeded", observed.snapshot.error
            assert observed.snapshot.result == {"ticket": "INC-001", "status": "open"}
            actions = [a for a in observed.snapshot.actions if a["kind"] == "tool"]
            assert len(actions) == 1 and actions[0]["status"] == "completed"
            replay = await agent.submit("Check INC-001", command_id="test-001")
            repeated = await replay.wait(wait_timeout=5)
            assert replay.ref == run.ref and replay.receipt == run.receipt
            assert repeated.snapshot.result == observed.snapshot.result
            assert provider.calls == 2 and lookups == ["INC-001"]
    print("PASS: tool result, durable completion, command replay; model calls=2")


asyncio.run(main())
```

Run it in the activated environment:

```bash
python test_app.py
```

Expected output, with exit code 0:

```text
PASS: tool result, durable completion, command replay; model calls=2
```

Every invocation uses a fresh temporary database and closes its Agent before deleting it. A changed input or definition must use a new command ID; do not delete a production database to bypass an identity conflict. A failed assertion exits nonzero: inspect `snapshot.state`, `.error`, `.actions` and `await run.pending()` before changing the expected result. This test never instantiates an HTTP Provider. Add your application's refusal, approval, input, cancellation and restart cases next; the [input guide](/en/docs/user-input/) and [recovery guide](/en/docs/recovery/) give operational sequences.

## Check a model adapter without business claims

From `relf-offline-tests`, run:

```bash
relf-check-model
relf-check-model --offline > compatibility.json
python - <<'PY'
import json
with open("compatibility.json") as file:
    r = json.load(file)
print(r["status"], r["passed"], r["total"], r["calls"], r["model_quality"])
PY
```

The first command reports `status: "not_run"`, `reason: "provider_not_configured"`, `calls: 0` without reading a model key or making a request. The summary from the second is:

```text
completed 5 5 6 None
```

The five cases are `text`, `structured`, `tool`, `stream`, `stream_close`; `--cases text,tool` selects a subset. The tool case checks exact arguments and a durable read-only echo result. The early stream-close case intentionally leaves a Run in `waiting_reconciliation` with unknown model outcome/usage. A passed cleanup probe proves that the consumer closed, not that a supplier stopped work or refunded usage.

For editable installed scaffolding:

```bash
relf init my-model-check --template model-check
cd my-model-check
python -m agent_app
cd ..
```

The starter runs the same five offline cases and stores private evidence in `my-model-check/.ralf/model-check`. A repeated run requires a fresh evidence location, for example `python -m agent_app --evidence-dir .ralf/model-check-2` while inside that starter. It is a compatibility runner and does not expose an application Engine factory.

A live compatibility probe is a separate, explicit opt-in and may incur provider fees. Set `MY_MODEL_KEY` privately and replace the model placeholder with a model available to your account:

```bash
relf-check-model --adapter openai-responses --model YOUR_ACTUAL_MODEL \
  --api-key-env MY_MODEL_KEY --max-calls 6 --max-output-tokens 1024 \
  --timeout 30 --evidence-dir .ralf/private-live-compatibility-1
```

This allows at most six attempted model invocations, with declared per-call output/await bounds. It is not a monetary cap or proof of upstream cancellation. Other adapters are listed by `relf-check-model --help`; a passing result applies only to the selected endpoint, model, adapter and cases. No live result is implied by the offline checks on this page. SDK callers can `await evaluate_model_compatibility(provider, cases=[...], limits=EvaluationLimits(...), evidence_dir=...)`; injected Providers are borrowed. More details: [SDK compatibility checks (mixed Chinese/English)](repo:docs/sdk-model-tools.md#bounded-compatibility-checks).

## Exercise business, RAG, Plan and Team behavior

From `relf-offline-tests`, these installed commands execute actual managed loops with deterministic offline Providers and independent task oracles:

```bash
relf-evaluate-business --offline --max-calls 16 \
  --evidence-dir .ralf/business-1 --report business.json
relf-evaluate-rag --offline \
  --evidence-dir .ralf/rag-1 --report rag.json
relf-evaluate-orchestration --offline --kind plan-and-execute --max-calls 32 \
  --evidence-dir .ralf/plan-1 --report plan.json
relf-evaluate-orchestration --offline --kind team --max-calls 32 \
  --evidence-dir .ralf/team-1 --report team.json
python - <<'PY'
import json
for name in ("business", "rag", "plan", "team"):
    with open(name + ".json") as file:
        r = json.load(file)
    print(f"{name}: {r['status']} {r['passed']}/{r['total']} "
          f"calls={r['calls']} model_quality={r['model_quality']}")
PY
```

The commands print JSON reports; their summary is:

```text
business: completed 8/8 calls=15 model_quality=None
rag: completed 8/8 calls=8 model_quality=None
plan: completed 5/5 calls=17 model_quality=None
team: completed 5/5 calls=17 model_quality=None
```

| Suite | Evidence and limits |
| --- | --- |
| Business | Eight ticket-service cases check independent business state, tool parameters, approval/refusal, stopping, replay and terminal reconstruction. Offline rules are regression evidence. |
| RAG | Eight cases check answers, displayed source/version/text support, stopping and terminal reconnection. Offline hash embeddings are a lexical baseline; `semantic_quality` remains null. |
| Plan / Team | Five cases each execute managed researcher/writer children and check inventory/calculator tool receipts, parameters, totals, ordering and stopping. Offline Plan uses the rule DAG; Team uses the fixed supervisor. This does not measure autonomous planning quality. |

Each `--report` must be a new file; each evidence location must be fresh for that batch. Use new paths for reruns. Public JSON omits raw prompts/answers; private SQLite evidence contains them and uses restricted permissions. A failed offline suite is an application/protocol/oracle regression to investigate, not a reason to enable a paid model. Inspect per-case checks/metrics and the retained original Run evidence.

Without `--offline` or an explicitly selected Provider, these evaluators report `not_run` and make no model calls. Task evaluator exit codes are 0 for a complete pass (or the unconfigured default display), 1 for failed cases and 2 for missing/invalid configured input. Check `status` as well as the exit code: `not_run` is not a pass.

## Evaluate plan proposals separately

`relf-evaluate-planning` scores proposals through a managed `ModelDAGPlanner` child; it does not execute the proposed business workers. Its default frozen suite has 20 cases, but the supplied offline response fixture covers only three.

The safe installed default is:

```bash
relf-evaluate-planning
```

It reports `not_run`, 20 total cases, zero calls and `model_quality: null`. To run the source fixture, return to the published repository checkout root used for installation (the file is not created in your test directory):

```bash
relf-evaluate-planning --fixture evals/planning-fixtures.json \
  --max-cases 3 --max-calls 3 \
  --evidence-dir .ralf/planning-1 --report planning.json
```

Expected fields are `status: "completed"`, `passed: 3`, `total: 3`, `calls: 3`, `model_quality: null`, exit code 0. Passing proposal semantics and schema checks cannot prove the proposed workers or final answer will succeed. [Planning evaluation (English)](repo:docs/planning-evaluation.md) explains the oracles and report denominator.

## Opt in to actual task quality

After protocol checks pass, explicitly configure the chosen endpoint/model/key and a separate fresh evidence batch. For example, this bounded business run is a live opt-in; it was not run for this guide:

```bash
relf-evaluate-business --provider openai --model-env RELF_EVAL_MODEL \
  --base-url-env RELF_EVAL_BASE_URL --key-env RELF_EVAL_KEY \
  --max-cases 8 --max-calls 32 --max-output-tokens 2048 --timeout 60 \
  --evidence-dir .ralf/private-live-business-1 --report live-business.json
```

Set those environment variables locally; do not put credentials in source or reports. `--max-calls` counts attempts, including failed/unknown outcomes. `--timeout` bounds the awaited client call; trusted code and supplier work need their own controls. Execution credits are not currency. `--max-cost-usd` fails closed with `not_run` because the generic contract cannot guarantee a hard billing ceiling. Unknown usage/cost remains null.

For repeated business measurements, `--offline --repeats 3 --max-calls 48` runs the same eight fixtures three times; live repeats require their own explicit call allowance. Failed and unattempted repeats stay in the denominator. Repeats are descriptive measurements of the same tasks, not independent task samples. Extend versioned cases and independent business oracles to your application before making a quality claim.

See [business evaluation (English)](repo:docs/business-evaluation.md), [complete task evaluation (Chinese; optional deeper details)](repo:docs/task-evaluation.md) and [completion verification (Chinese; optional)](repo:docs/completion-verification.md). Continue with the [application tutorial](/en/docs/app-tutorial/) or use the [API/CLI reference](/en/docs/api-reference/) to inspect failures.
