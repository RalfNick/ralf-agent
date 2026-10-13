# Phase 1 SingleAgent evidence — dev98

The installed `0.1.0.dev98` SingleAgent lifecycle subset passed 14 scenarios, and
the fixed DeepSeek business sample passed **24/24** across eight tasks repeated
three times. The [sanitized report](../evals/results/deepseek-phase1-dev98.json)
retains every measured row, source-report hash and denominator. This establishes
the measured SingleAgent subset; it does not close phase 1 or establish general
model quality, semantic RAG quality, production readiness or framework parity.

The real trial used `deepseek-flash`, the non-thinking DeepSeek Chat Completions
adapter, temperature 0, JSON-object output, 2048 output tokens and a 45-second
request timeout. Each chain had a 96-call cap, three repeats and a separately
enforced 900-second outer observation deadline. Original packaged tasks,
instructions, business data, expected values and approval rules stayed fixed.

| Fixed trial | Passed / planned | Failed | Model calls |
| --- | ---: | ---: | ---: |
| SingleAgent, JSON mode | 24 / 24 | 0 | 51 |
| Plan, JSON mode | 3 / 15 | 12 | 54 |
| Team, JSON mode | 3 / 15 | 12 | 30 |
| Plan, separate non-JSON mode | 3 / 15 | 12 | 54 |
| Team, separate non-JSON mode | 3 / 15 | 12 | 30 |

The non-JSON phase changed a fixed provider option and retained the same task
dataset. It is a separate measurement, not a replacement for the earlier failed
rows. All planned rows were attempted. Failed and unattempted rows remain in
their phase's denominator; the report makes no combined quality score across
different configurations. Each Plan/Team phase passed only the three
`missing-target` repeats. Successful reconnection of a failed Run proves retained
execution history, not business success.

The SingleAgent sample exercised three justified repairs, missing or ambiguous
targets, missing evidence, a destructive request and an approval-bypass request.
There were nine actual business writes: one per repair and repeat, with zero
writes for the other tasks. `ToolReceiptVerifier` required the corresponding
committed `apply_fix` receipt before accepting `status=resolved`, matching both
`ticket_id` and `fix` and requiring `applied=true`. It issued nine bounded retry
verdicts inside the original decision loops, then accepted all 24 results. These
verifier retries are distinct from rerunning failed evaluation rows.

All submission receipts replayed and terminal reconstruction kept the same
snapshots without another model call or duplicate business write. The trial
reported 37,080 input and 1,798 output tokens. No token prices were supplied, so
estimated cost is null; execution credits do not represent a currency limit.
The caller's actual HTTP client closed after each trial.

The earlier [dev29 trial](live-model-quality-dev29.md) was 8/8 with one repeat,
1536 output tokens and code predating its final review. It remains historical
evidence. This report records a new installed dev98 trial with three repeats and
2048 output tokens, retaining the original business dataset and receipt rule.

The accepted wheel SHA-256 is
`316b9cc0fbdd6ebf8ae8de0a2963e74031cca2e76b0d93caa0bb33091ac63562`.
All 349 Python modules matched source, wheel, sdist and the installed core/SDK
packages. The SingleAgent lifecycle controller used the isolated installed core
interpreter outside the checkout, checked those bytes before and after, and ran
unchanged original test functions. Its original wheel-building fixture was not
invoked; the existing tests received the accepted interpreter and console as
their explicit `installed_wheel` argument.

The 14 scenarios covered default synchronous/asynchronous assembly and reconnect,
versioned configuration replacement and installed CLI inspection, owned/borrowed
replacement memory, approval and adopted-decision restart, a real process death
after business commit, explicit business cancellation, observer cancellation and
timeout, a started tool's retained effect, and rejection of a late cancellation.
All 17 fixture subprocesses were waited and reaped, including the expected
exit-77 commit crash. All 13 captured original SQLite connections were checked
closed. The report lists each original function name and source hash without
publishing private paths, Run IDs, prompts or credentials.

For an installed offline start, use the accepted local wheel rather than assuming
that this preview is available on a package index:

```sh
python -m pip install /path/to/ralf_agent-0.1.0.dev98-py3-none-any.whl
ralf --version
ralf --format text init my-single-agent
cd my-single-agent
python -m agent_app --ticket INC-001
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
```

Replace `RUN_ID` with the saved ID. Review the pending write, then use the displayed
approval and resume commands; processes may restart between commands. An explicit
cancel command uses that same database and original factory. Repeating an identical
submission or control command retains its original receipt. The default provider
is offline and measures wiring. [Getting started](getting-started.md) explains
approval/cancel commands; [runtime assembly](runtime-assembly.md) gives the installed
`config` template, versioned JSON/TOML declarations and preservation of old profiles
when changing the default for new submissions.

To repeat the measured business sample through the installed SDK, save the
following as `evaluate_single_agent.py` outside the checkout. Supply
`DEEPSEEK_API_KEY` through your own environment or secret manager. Running this
script makes paid requests. Use new report/evidence destinations for every batch.
The caller owns the `httpx.AsyncClient`; the provider and evaluator borrow it.

```python
import argparse
import asyncio
import json
import os
import sys

import httpx
import ralf_agent
from ralf_agent import (
    DeepSeekChatProvider,
    EvaluationLimits,
    ToolReceiptVerifier,
    evaluate_business,
)


async def evaluate(args):
    if ralf_agent.__version__ != "0.1.0.dev98":
        raise RuntimeError("Use the recorded dev98 installation for this trial")
    limits = EvaluationLimits(
        max_cases=8,
        repeats=3,
        max_calls=96,
        max_output_tokens=2048,
        timeout_seconds=45,
    )
    verifier = ToolReceiptVerifier(
        "apply_fix",
        when={
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"const": "resolved"}},
        },
        result_schema={
            "type": "object",
            "required": ["applied"],
            "properties": {"applied": {"const": True}},
        },
        argument_bindings={"ticket_id": "/ticket_id", "fix": "/fix"},
    )
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        provider = DeepSeekChatProvider(
            "deepseek-flash",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            temperature=0,
            json_mode=True,
            max_output_tokens=2048,
            timeout=45,
            client=client,
        )
        report = await asyncio.wait_for(
            evaluate_business(
                provider,
                limits=limits,
                completion_verifier=verifier,
                evidence_dir=args.evidence_dir,
            ),
            timeout=900,
        )
    assert client.is_closed
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()
    descriptor = os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        report = asyncio.run(evaluate(args))
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "passed", "total", "calls")}))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

```sh
python evaluate_single_agent.py --report business-report.json --evidence-dir private-business-evidence
```

The unchanged evaluator constructs the original native Agent/tool loops and uses
an independent SQLite business oracle. Its host approves only matching justified
fixture fixes after consumed diagnostic evidence. This is an explicit evaluation
approval policy, not permission for a production service. Raw responses and
business records stay in the private evidence directory. Terminal recovery does
not dispatch another request; unfinished or unknown outcomes are observed and
scored as recovery failures. An outer timeout leaves available durable evidence
for diagnosis and does not authorize an automatic retry. The
[business evaluator guide](business-evaluation.md) documents bounds, reports and
the independent completion/effect checks.
