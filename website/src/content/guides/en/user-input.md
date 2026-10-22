---
title: Durable user input
description: Pause an original run for a question, submit a targeted JSON answer and resume across processes.
locale: en
slug: user-input
sources: [docs/user-input.md, docs/agent-api.md, docs/session-api.md, docs/recovery-guide.md]
---

Use durable input when an application needs a missing parameter or clarification. An explicitly registered `request_input` tool pauses its original Run at `waiting_input`. The question survives shutdown and restart. Business approval, a new conversation Turn and a reply to this question are different operations. Ordinary output such as `{"status":"needs_input"}` does not create a durable question.

The following path uses the installed **0.1.0a1** Local SDK and an offline provider. It needs no model key or network service. First complete [installation](/en/docs/installation/) or the [quickstart](/en/docs/quickstart/).

## 1. Create the installed input starter

From a working directory, choose a project directory that does not yet exist:

```bash
ralf --format text init input-app --template user-input
cd input-app
python -m agent_app run --command-id first-question
```

Use the `run` subcommand above and the generated README for this template. The generic hint printed by `init` can mention the other starter's `--ticket` option.

The result includes `state: waiting_input`, a `run_id` and an input entry in `pending`. Its prompt is `Which environment should I use?`. Save the original `run_id`, `pending_id` and `target_digest`; the values are generated for your task. Repeating this exact submission retrieves the same Run and open question.

## 2. Inspect the question and reply Schema

Replace `RUN_ID` with the saved value. Global CLI options go before the subcommand:

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  --format text inspect RUN_ID
```

Expect `State: waiting_input`, the question, its reply Schema and a suggested `send-input` command. The default policy accepts a nonblank JSON string. Take the pending identity and digest from this original question; an approval action's digest is a different target.

`inspect` reads SQLite without loading the factory or acquiring an execution lease. Passing the factory here lets its suggested continuation command name the correct application.

## 3. Answer the original question

Substitute the three saved placeholders. The outer single quotes below are shell quoting; the inner double quotes make `production` a JSON string:

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine \
  send-input RUN_ID PENDING_ID \
  --digest TARGET_DIGEST --value-json '"production"' \
  --command-id environment-answer
```

The receipt should include `kind: send_input`, `record_state: durably_recorded` and `apply_state: applied`. It records acceptance of this answer. The raw CLI does **not** drive the Run, and the receipt does not establish business success.

## 4. Resume and inspect the result

```bash
ralf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine resume RUN_ID
ralf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

Expect `State: succeeded` and `Result: {"environment": "production"}`. Each command can run in a separate process. Keep the same database, original factory, release and policy configuration when restarting.

Repeat the exact `send-input` command from step 3, including `environment-answer`. It returns the original applied receipt, even after completion. It does not ask another question, allocate a Session Turn or reset execution credits. The offline fixture demonstrates durable execution, rather than model reasoning quality.

## Command identity, Schema and rejected answers

The host fixes the policy and reply Schema before the Run is accepted. `request_input` takes exactly `{"prompt": "Which environment?"}` and must be the only tool call in that model decision. Registering the intrinsic marker does not add it to an Agent's tool allowlist automatically. A regular Python tool merely named `request_input` does not gain this authority.

| Situation | Result and next step |
| --- | --- |
| Same reply command ID, target, value and conditions | Original receipt; safe to retrieve after an uncertain response |
| Same command ID with a changed value or target | `idempotency_conflict`; retain the old command and use a new ID for a new intent |
| Value fails the fixed Schema | Rejected receipt with `invalid_input`; inspect the still-open question, then send a valid value using a new command ID |
| New command targets an already consumed or stale question | `stale_pending_target`; inspect current pending controls |
| Owner is cancelling, cancelled or terminal | `target_closed`; a late new answer cannot reopen it |
| Optional `--expected-state-revision` no longer matches | `version_conflict`; reread the owner and decide whether to issue a new command |
| Malformed JSON, missing required fields or unauthorized target | Command fails before acceptance; correct the command or target |

When a terminal owner also has a consumed question, a new command can report `target_closed`; replaying the original accepted command still returns its original receipt. Inspect `apply_state` and `outcome`, rather than assuming that valid JSON or an exit code means an answer was applied.

Policy defaults are eight questions, 4096 prompt characters and 65536 reply UTF-8 bytes. Configurable ranges are `max_requests` 1–32, `max_prompt_chars` 1–16384 and `max_reply_bytes` 1–1048576. Replies must be finite ordinary JSON, at most 32 levels deep, and satisfy the fixed Schema. Schemas allow local fragment references; remote and dynamic references are rejected without fetching them.

## A complete offline SDK example

Save this as `input_sdk.py` in a separate directory with the SDK installed, then run `python input_sdk.py`. It uses a fresh `.ralf/sdk-input.sqlite` store, an explicit enum Schema and an owned Runtime. Repeating the unchanged file retrieves the original completed Run.

```python
import asyncio
import json

from ralf_agent import (
    AgentSpec, LocalEngine, ModelResponse, Runtime, SQLiteStore,
    ToolCall, ToolRegistry, UserInputPolicy, register_user_input,
)


class OfflineInputProvider:
    identity = {"kind": "docs-input-sdk", "version": "1"}

    async def complete(self, messages, tools):
        replies = [m for m in messages if m["role"] == "tool"]
        if replies:
            return ModelResponse(output={
                "environment": json.loads(replies[-1]["content"]),
            })
        return ModelResponse(tool_calls=(ToolCall(
            "request_input", {"prompt": "Which environment?"},
            call_id="environment",
        ),))


async def main():
    tools = ToolRegistry()
    ask = register_user_input(tools, policy=UserInputPolicy(
        reply_schema={"type": "string", "enum": ["production", "staging"]},
    ))
    spec = AgentSpec("assistant", "Ask for the environment.", tools=(ask,))
    engine = LocalEngine(
        SQLiteStore(".ralf/sdk-input.sqlite"),
        providers={"default": OfflineInputProvider()}, tools=tools,
    )
    async with Runtime(engine, owned=True) as runtime:
        agent = runtime.create_agent(spec)
        run = await agent.submit("Check deployment", command_id="sdk-request-1")
        observed = await run.wait()
        print(observed.snapshot.state)
        question = next((q for q in await run.pending() if q["kind"] == "input"), None)
        if question is not None:
            receipt = await run.send_input(
                question["pending_id"], question["target_digest"], "production",
                command_id="sdk-answer-1",
            )
            if receipt.apply_state != "applied":
                raise RuntimeError(receipt)
            print(receipt.apply_state)
        result = await run.wait(terminal_only=True)
        print(result.snapshot.state, result.snapshot.result)


asyncio.run(main())
```

On the first execution expect `waiting_input`, `applied`, then `succeeded {'environment': 'production'}`. The Facade's applied `run.send_input()` wakes the original managed root automatically. Raw `engine.send_input(...)` and CLI `send-input` require an explicit drive/resume. The answer becomes the original tool call's result; its remaining decision/tool limits and credits continue unchanged.

To change the model, replace `OfflineInputProvider` with your configured provider as described in [models and tools](/en/docs/models-tools/). To change the reply shape, update `UserInputPolicy` and the provider's output handling together. New definitions and policies need new request identities and an appropriate new store or Session; retain the old configuration to recover old Runs.

## Sessions and child owners

An open question keeps its Session busy. `Session.submit()` and `Session.run()` request a **new Turn** and can raise `SessionBusy`; they cannot answer the previous Turn. Use the original Run's `send_input()`, finish or explicitly cancel that Turn, then wait for the Session to become idle. Rebinding is also idle-only.

For a Team, graph or nested child, `root.pending()` includes each question's original owner RunRef in `ref`. The following is a **usage fragment** inside an already configured Runtime with an existing `root` handle; it is not a standalone program:

```python
from ralf_agent import RunRef

question = next(q for q in await root.pending() if q["kind"] == "input")
owner = await runtime.aattach(RunRef.from_dict(question["ref"]))
receipt = await owner.send_input(
    question["pending_id"], question["target_digest"], "production",
    command_id="child-answer-1",
)
print(receipt.apply_state)
```

Reply to that owner, preserving its target digest. A root `wait()` can return `wait_reason="control_available"` while its authoritative snapshot still says `running` because a sibling is executing. Read `pending()` to find the owner; this observation does not declare all handlers stopped. A sibling's approval or unknown effect remains an independent control. `terminal_only=True` keeps waiting for terminal state and is unsuitable for discovering unanswered questions.

Closing a Local owned Runtime can park a stable input wait after actual sibling handlers finish. Retain the original RunRef, database and release; attach it in the matching Runtime, inspect pending controls and answer its owner. Observation timeout, cancelling `wait()` or disconnecting does not answer or cancel the Run. `CloseIncomplete` requires resolving the original outstanding resources and retrying normal close; do not delete leases to force a restart.

Continue with the [application tutorial](/en/docs/app-tutorial/), [recovery](/en/docs/recovery/) or [API and CLI reference](/en/docs/api-reference/). The optional repository [input protocol guide](repo:docs/user-input.md) covers profile policy declarations, dynamic planning clarification and the opt-in A2A extension.
