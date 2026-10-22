---
title: Core concepts
description: Understand agent definitions, durable execution facts and external business effects as separate concerns.
locale: en
slug: concepts
sources: [docs/concepts.md, docs/recovery-guide.md, docs/agent-api.md, docs/completion-verification.md]
---

## How a task executes

`AgentSpec` declares instructions, allowed tools, model selection and output constraints. A provider receives messages and tool descriptions and returns a response or proposal. The engine validates proposals, records facts and controls actual execution.

```text
AgentSpec + input
      ↓ submit(command_id)
     Run
      ↓ drive
Model → Decision → Tool / Approval → Result
      ↳ execution facts saved in the store
```

| Concept | Responsibility |
| --- | --- |
| `AgentSpec` | Declarative agent definition |
| Provider | Model requests, responses and tool proposals |
| Tool | Business capability with a schema, version and effect category |
| Run | Durable task identity, state, budget and events |
| Action | A specific operation linked to approval, receipts and reconciliation |
| Engine / Runtime | Managed execution, storage, observation and control |

`LocalEngine.submit` returns a run reference. `drive` advances that run; `status` and `events` observe it. An observation timeout does not cancel the business task.

## Choose an SDK entry point

| Entry point | When to use it |
| --- | --- |
| `Agent` | Start with a configured model and tools, submit/wait and durable conversations |
| `Runtime` | Share execution hosting, observation and resource lifetimes across agents or composite definitions |
| `LocalEngine` | Directly control local submission, drive, approval, reconciliation and component assembly |
| Runtime profile | Select registered components through JSON/TOML with versioned recovery identities |

These entry points reuse the original execution authority rather than creating separate approval or budget logs. `Agent.run` submits and waits. Its `WaitResult.snapshot` contains the actual business state; a successful wait can still mean the task is awaiting approval.

## Commands and execution identity

`command_id` identifies one caller intent. Within the same scope, the same ID and request return the original receipt. Changed content with the same ID produces `idempotency_conflict`. Approval and cancellation commands also have their own IDs.

Recovery requires the original database or history, matching component identities and original business evidence. Use changed definitions for new tasks, rather than forcing a new default configuration onto an old run.

| Identity | What it links |
| --- | --- |
| `command_id` | One submission or control intent and its original receipt |
| Run ID | An accepted task, retrievable by repeating the same intent |
| Action ID / operation digest | One operation, its original arguments, approval and evidence |
| `effect_key` | The original business effect's idempotency/query identity, supplied by host execution context |
| Session / Turn | A conversation and its individual turns, distinct from one run |

A ticket may have multiple turns, tool actions and control commands. Do not use its ticket number interchangeably for these identities or assume approval applies to another operation merely because the tool name matches.

## Approval and unknown effects

A task requiring human confirmation pauses at `waiting_approval`. Approval is bound to a specific action and operation digest. The actual business result is known only after execution continues.

An uncertain dispatched write can lead to `waiting_reconciliation`. Check its business effect and adopt the confirmed result. A timeout alone is not a reason to issue the write again.

> Recorded model responses and tool observations can be adopted during recovery. External operations without received evidence follow their effect-specific rules. The framework does not promise exactly-once effects across third-party systems.

## Sessions, memory and knowledge

Session / Turn captures conversational identity. Facts retain scoped, versioned information with provenance. Knowledge / RAG holds documents, retrieval candidates and citations. Context is what a particular model request actually consumes.

These components can be selected and replaced independently. A scope comes from the trusted host and is not, by itself, authentication. See [sessions, memory and RAG](/en/docs/sessions-memory/).

## Valid output and business completion

An output schema checks JSON structure and fields; it does not prove the business task is complete. A completion verifier can check adopted tool receipts and result constraints for the current agent node.

The model saying “fixed,” a historical success message or another member's receipt cannot automatically replace evidence for the current operation. Business verification calls run through managed tools; a pure verifier only examines the supplied facts. Continue to [models and tools](/en/docs/models-tools/).

## From local execution to orchestration

Start locally with SQLite. Workflows, static graphs and Plan / Team coordinate steps or agents. Child runs retain the same tool, approval and recovery protocols. The Temporal backend requires explicit configuration and takes authority from its original workflow history.

`budget` is an integer allowance of **execution credits**, reserved and settled for execution attempts. It is not a currency budget or a hard provider token limit. Continue to [workflows and teams](/en/docs/workflows/).
